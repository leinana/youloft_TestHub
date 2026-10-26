"""需求文档链接采集器：Axure WebShare / 墨刀(modao) 只读原型
通过 Playwright（系统 Edge）渲染原型，采集页面目录、正文文本和截图。
"""
import os
import re
import time
from urllib.parse import quote

from django.conf import settings
from playwright.sync_api import sync_playwright

BROWSER_CHANNEL = None  # 使用 Playwright 自带 Chromium（headless shell，自动化更稳定）
PLAYWRIGHT_BROWSERS_PATH = r'C:\Users\Ln\AppData\Local\ms-playwright'


def _ensure_env():
    """Django 服务可能运行在 SYSTEM 账户下，USERPROFILE 指向 systemprofile，
    这里显式指定 Playwright 浏览器目录和可写临时目录。"""
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = PLAYWRIGHT_BROWSERS_PATH
    tmpdir = os.path.join(settings.MEDIA_ROOT, 'kb_tmp')
    os.makedirs(tmpdir, exist_ok=True)
    os.environ['TEMP'] = tmpdir
    os.environ['TMP'] = tmpdir


# 后台管理端原型的画布关键词：整张画布是后台界面，跟客户端测试无关，采集时直接跳过
BACKEND_KEYWORDS = ('后台', '管理端', 'CMS', '运营平台')


def is_backend_page(name):
    """画布名命中后台关键词 → 视为后台需求，不采集"""
    n = (name or '').strip()
    if not n:
        return False
    return any(k in n for k in BACKEND_KEYWORDS)


def _split_filters(page_filter):
    """过滤词切分：兼容中英文逗号、顿号、分号、换行等分隔符"""
    if not page_filter:
        return []
    return [f.strip() for f in re.split(r'[,，、;；\n]+', page_filter) if f.strip()]


# 墨刀画布树提取：返回叶子画布（名称、父级链、是否 ❌、data-cid）
MODAO_EXTRACT_JS = """() => {
  function iconCls(li) {
    const svg = li.querySelector('.screen-item-icon svg');
    return svg ? (svg.getAttribute('class') || '') : '';
  }
  function collect(ul, ancestors) {
    const leaves = [];
    for (const li of Array.from(ul.children)) {
      if (li.tagName !== 'LI' || !li.classList.contains('rn-content-item')) continue;
      const name = (li.querySelector('.editable-span')?.innerText || '').trim();
      const ic = iconCls(li);
      const childUl = Array.from(li.children).find(c => c.tagName === 'UL');
      if (childUl) {
        leaves.push(...collect(childUl, [...ancestors, name]));
      } else if (name) {
        leaves.push({ name: name, parents: ancestors, isError: ic.includes('symbolError'), cid: li.getAttribute('data-cid') });
      }
    }
    return leaves;
  }
  const root = Array.from(document.querySelectorAll('ul')).find(u => u.querySelector('li.rn-content-item') && !u.closest('li.rn-content-item'));
  return root ? collect(root, []) : [];
}"""


def _sanitize(name):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', (name or '未命名').strip()).strip('_')[:80]


def _shot_path(prefix, idx, name, run_id=None):
    """截图落盘路径。给了 run_id 就用同一个批次目录（避免每次调用生成新目录）。"""
    if run_id:
        rel = f'knowledge_collect/{run_id}'
    else:
        rel = f'knowledge_collect/{prefix}_{time.strftime("%Y%m%d_%H%M%S")}'
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel)
    os.makedirs(abs_dir, exist_ok=True)
    fname = f'{idx:03d}_{_sanitize(name)}.png'
    abs_path = os.path.join(abs_dir, fname)
    media_rel = f'/media/{rel}/{fname}'
    return abs_path, media_rel


# 墨刀画布细节：文字元素（带坐标）+ 图片元素（原图 URL）
MODAO_DETAIL_JS = """() => {
  const box = document.querySelector('[class*="CanvasContainer"]');
  if (!box) return { elements: [], images: [] };
  const elements = [];
  box.querySelectorAll('div,span,p').forEach(el => {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 300) return;
    if (Array.from(el.children).some(c => (c.innerText || '').trim())) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    elements.push({ t: t, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) });
  });
  const images = [];
  box.querySelectorAll('img').forEach(im => {
    const src = im.src || '';
    if (!src || src.indexOf('data:') === 0) return;
    const r = im.getBoundingClientRect();
    images.push({
      src: src,
      nw: im.naturalWidth || 0, nh: im.naturalHeight || 0,
      rw: Math.round(r.width), rh: Math.round(r.height),
      x: Math.round(r.x), y: Math.round(r.y),
    });
  });
  return { elements: elements, images: images };
}"""


def _download_canvas_images(images, idx, limit=4, run_id=None):
    """下载画布里的「内容型图片」原图（比画布截图清晰得多）。

    过滤掉小图标等装饰图；按原图像素面积从大到小取前 limit 张。
    """
    import httpx

    cands = [im for im in (images or [])
             if (im.get('nw') or 0) >= 80 and (im.get('nh') or 0) >= 80]
    cands.sort(key=lambda x: (x.get('nw') or 0) * (x.get('nh') or 0), reverse=True)

    seen, picked = set(), []
    for im in cands:
        u = im.get('src') or ''
        if not u or u in seen:
            continue
        seen.add(u)
        picked.append(im)
        if len(picked) >= limit:
            break
    if not picked:
        return []

    if run_id:
        rel = f'knowledge_collect/{run_id}'
    else:
        rel = f'knowledge_collect/modao_img_{time.strftime("%Y%m%d_%H%M%S")}'
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel)
    os.makedirs(abs_dir, exist_ok=True)

    out = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for i, im in enumerate(picked, 1):
            try:
                r = client.get(im['src'])
                r.raise_for_status()
                ctype = (r.headers.get('content-type') or '').lower()
                ext = '.png' if 'png' in ctype else ('.jpg' if ('jpeg' in ctype or 'jpg' in ctype) else
                                                     (os.path.splitext(im['src'])[1] or '.png'))
                fname = f'{idx:03d}_img{i}{ext}'
                with open(os.path.join(abs_dir, fname), 'wb') as f:
                    f.write(r.content)
                out.append({
                    'media': f'/media/{rel}/{fname}',
                    'w': im.get('nw') or 0,
                    'h': im.get('nh') or 0,
                })
            except Exception as e:
                logger_msg = f'[collect] 图片下载失败 {im.get("src", "")[:80]}: {e}'
                print(logger_msg)
    return out


def _content_clip(elements, images=None, vw=1440, vh=900, pad=40):
    """按画布里的文字/图片坐标，算出「只含内容」的裁剪区域。

    截图默认是整页，会把左侧画布列表、顶部工具栏一起拍进去 —— 既浪费分辨率也干扰模型。
    这里取内容元素的最小外接矩形。算不出来或几乎占满整屏时返回 None（退回整页截图）。
    """
    xs, ys, x2s, y2s = [], [], [], []
    for e in (elements or []):
        try:
            x = float(e.get('x') or 0); y = float(e.get('y') or 0)
            w = float(e.get('w') or 0); h = float(e.get('h') or 0)
        except (TypeError, ValueError):
            continue
        xs.append(x); ys.append(y); x2s.append(x + max(w, 1)); y2s.append(y + max(h, 1))
    for im in (images or []):
        try:
            x = float(im.get('x') or 0); y = float(im.get('y') or 0)
            w = float(im.get('rw') or 0); h = float(im.get('rh') or 0)
        except (TypeError, ValueError):
            continue
        if w < 8 or h < 8:
            continue
        xs.append(x); ys.append(y); x2s.append(x + w); y2s.append(y + h)

    if not xs:
        return None

    left = max(0.0, min(xs) - pad)
    top = max(0.0, min(ys) - pad)
    right = min(float(vw), max(x2s) + pad)
    bottom = min(float(vh), max(y2s) + pad)

    w, h = right - left, bottom - top
    if w < 240 or h < 240:
        return None
    # 本来就占满整屏，裁了也没意义
    if w >= vw - 24 and h >= vh - 24:
        return None
    return {'x': left, 'y': top, 'width': w, 'height': h}


def collect_axure(url, page_filter=None, max_pages=None, run_id=None):
    filters = _split_filters(page_filter)

    base = url.split('#')[0].rstrip('/')

    _ensure_env()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(2500)

        title_hint = page.title()
        metas = page.evaluate(
            "() => Array.from(document.querySelectorAll('.sitemapPageLink')).map(a => ({name: (a.querySelector('.sitemapPageName')?.innerText || '').trim(), nodeurl: a.getAttribute('nodeurl') || ''})).filter(x => x.name && x.nodeurl)"
        )

        total = len(metas)
        if total == 0:
            browser.close()
            return {'source_type': 'axure', 'total_pages': 0, 'collected': [],
                    'error': '未识别到页面目录，请确认链接是 Axure WebShare 只读地址'}
        # 排除：手动过滤词
        if filters:
            metas = [m for m in metas if not any(f in m['name'] for f in filters)]
        # 排除：后台需求画布（不采集、不展示）
        backend_metas = [m for m in metas if is_backend_page(m['name'])]
        metas = [m for m in metas if not is_backend_page(m['name'])]
        collected = []
        if max_pages:
            metas = metas[:max_pages]
        for i, meta in enumerate(metas, 1):
            name = meta['name']
            try:
                page.goto(base + '/' + quote(meta['nodeurl']), wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(1200)
                title = page.title()
                text = page.evaluate('document.body.innerText')
                abs_path, media_rel = _shot_path('axure', i, name, run_id)
                page.screenshot(path=abs_path, full_page=True)
                collected.append({'name': name, 'title': title, 'text': text, 'screenshot': media_rel})
            except Exception as e:
                collected.append({'name': name, 'error': str(e)[:200]})
        browser.close()

    return {'source_type': 'axure', 'source_title': title_hint, 'total_pages': total,
            'skipped_backend': [{'name': m['name'], 'cid': ''} for m in backend_metas],
            'collected': collected}


MODAO_AUTH_URL = 'https://modao.cc/embed/auth_box?type=signin&from=feature&entry_term=guide_sign&redirect_url=/workspace/home'


def _modao_login(page, email, password):
    """登录墨刀（邮箱 + 密码）。默认落地页是微信扫码，需切换到邮箱密码登录。"""
    page.goto(MODAO_AUTH_URL, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(4000)

    # 1. 从微信扫码切到邮箱登录
    mail = page.locator('.login-way-icon.mail').first
    if mail.count() == 0:
        return False
    mail.click()
    page.wait_for_timeout(2000)

    # 2. 从验证码登录切到密码登录
    pwd_tab = page.locator('text=密码登录').first
    if pwd_tab.count() == 0:
        return False
    pwd_tab.click()
    page.wait_for_timeout(2000)

    email_loc = page.locator('input[placeholder="请输入手机号/邮箱"]').first
    pwd_loc = page.locator('input[type="password"]').first
    if email_loc.count() == 0 or pwd_loc.count() == 0:
        return False
    email_loc.fill(email)
    pwd_loc.fill(password)

    login_btn = page.locator('text=立即登录/注册').first
    if login_btn.count() == 0:
        return False
    login_btn.click()
    page.wait_for_timeout(3000)

    # 3. 首次登录会弹“同意协议”确认框
    confirm = page.locator('div.confirm-btn').first
    if confirm.count():
        confirm.click()
        page.wait_for_timeout(8000)
    else:
        page.wait_for_timeout(6000)

    # 登录成功后会跳转到 workspace
    return ('workspace' in page.url
            or page.locator('text=全部团队').count() > 0
            or page.locator('text=退出登录').count() > 0)


def collect_modao(url, page_filter=None, cookie=None, email=None, password=None, max_pages=None, run_id=None):
    _ensure_env()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        # device_scale_factor=2：截图按 2 倍像素渲染，墨刀缩小后的画布小字能保住
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        if cookie:
            cookies = []
            for part in cookie.split(';'):
                part = part.strip()
                if '=' in part:
                    k, v = part.split('=', 1)
                    cookies.append({'name': k.strip(), 'value': v.strip(), 'domain': '.modao.cc', 'path': '/'})
            context.add_cookies(cookies)
        page = context.new_page()

        if not cookie and email and password:
            ok = _modao_login(page, email, password)
            if not ok:
                browser.close()
                return {'source_type': 'modao', 'total_pages': 0, 'collected': [],
                        'error': '墨刀登录失败，请检查邮箱/密码，或改用登录 Cookie'}

        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(8000)

        title_hint = page.title()

        # 提取画布树：叶子画布（名称、父级链、是否 ❌、data-cid）
        leaves = page.evaluate(MODAO_EXTRACT_JS)

        if not leaves:
            browser.close()
            return {'source_type': 'modao', 'total_pages': 0, 'collected': [],
                    'error': '未识别到画布目录，可能链接无访问权限或登录态失效，请检查链接/账号'}

        # 1) 排除带 ❌（symbolError）标记的画布
        error_names = [x['name'] for x in leaves if x['isError']]
        leaves = [x for x in leaves if not x['isError']]

        # 2) 排除页面过滤：命中叶子名或任一父级名都排除（级联排除子画布）
        filters = _split_filters(page_filter)
        if filters:
            leaves = [x for x in leaves
                      if not any(f in x['name'] or any(f in pp for pp in x['parents']) for f in filters)]

        # 3) 排除后台需求画布（命中关键词，不采集、不展示）
        backend_pages = [{'name': x['name'], 'cid': x.get('cid') or ''}
                         for x in leaves if is_backend_page(x['name'])]
        leaves = [x for x in leaves if not is_backend_page(x['name'])]

        if not leaves:
            browser.close()
            if filters:
                return {'source_type': 'modao', 'total_pages': 0, 'collected': [],
                        'error': '排除这些页面后没有剩余可采集的画布，请检查过滤词'}
            if backend_pages:
                return {'source_type': 'modao', 'total_pages': 0, 'collected': [],
                        'skipped_backend': backend_pages,
                        'error': '剩余画布都是后台需求，已全部跳过'}
            return {'source_type': 'modao', 'total_pages': 0, 'collected': [],
                    'error': '所有画布都带 ❌ 标记，无可采集内容'}

        collected = []
        total = len(leaves)
        targets = leaves[:max_pages] if max_pages else leaves
        for i, leaf in enumerate(targets, 1):
            name = leaf['name']
            cid = leaf.get('cid') or ''
            try:
                # 按 data-cid 精确点击画布
                page.locator(f'li[data-cid="{cid}"] .rn-list-item').first.click()
                page.wait_for_timeout(3000)
                # 只取画布内容区（排除左侧画布列表和顶部导航）
                content_loc = page.locator('[class*="CanvasContainer"]').first
                text = content_loc.inner_text() if content_loc.count() else page.evaluate('document.body.innerText')
                # 额外抓：文字元素坐标 + 内容型图片原图
                detail = page.evaluate(MODAO_DETAIL_JS) or {}
                elements = detail.get('elements') or []
                images = _download_canvas_images(detail.get('images') or [], i, run_id=run_id)
                abs_path, media_rel = _shot_path('modao', i, name, run_id)
                # 只截画布内容区（去掉左侧画布列表/顶部工具栏），拿不到内容范围才退回整页
                clip = _content_clip(elements, detail.get('images') or [], 1440, 900)
                if clip:
                    page.screenshot(path=abs_path, clip=clip)
                else:
                    page.screenshot(path=abs_path, full_page=True)
                collected.append({
                    'name': name,
                    'text': text,
                    'screenshot': media_rel,
                    'elements': elements,
                    'images': images,
                    # 父级分组链（顶层 → 直接父级）：产品经理按顶层功能写文档，归类时优先用它
                    'parents': leaf.get('parents') or [],
                })
            except Exception as e:
                collected.append({'name': name, 'error': str(e)[:200]})
        browser.close()

    return {'source_type': 'modao', 'source_title': title_hint, 'total_pages': total, 'excluded_error_pages': error_names,
            'skipped_backend': backend_pages, 'collected': collected}


def collect(url, source_type='axure', page_filter=None, cookie=None, email=None, password=None, max_pages=None, run_id=None):
    """在【独立子进程】里执行采集。

    为什么要隔离：Playwright 的同步 API 在长时间运行的 Django 进程里会卡死
    （报 `PlaywrightContextManager object has no attribute _playwright`），
    服务跑久了就再也采不动。放到子进程里每次都是干净环境，也不会拖垮服务本身。
    """
    import json
    import subprocess
    import sys
    import tempfile

    payload = {
        'url': url,
        'source_type': source_type if source_type in ('axure', 'modao') else 'axure',
        'page_filter': page_filter or '',
        'cookie': cookie or '',
        'email': email or '',
        'password': password or '',
        'max_pages': max_pages or 0,
        'run_id': str(run_id) if run_id else '',
    }
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    fd, out_path = tempfile.mkstemp(suffix='.json', prefix='kb_collect_')
    os.close(fd)
    try:
        try:
            proc = subprocess.run(
                [sys.executable, '-m', 'apps.knowledge_base.collector_cli',
                 json.dumps(payload, ensure_ascii=False), out_path],
                cwd=base_dir,
                capture_output=True,
                text=True,
                timeout=1800,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError('采集超时（超过 30 分钟），已终止')

        result = None
        try:
            with open(out_path, encoding='utf-8') as f:
                result = json.load(f)
        except Exception:
            result = None

        if result is None:
            tail = ((proc.stderr or '') + (proc.stdout or ''))[-600:]
            raise RuntimeError(f'采集子进程未返回结果（exit={proc.returncode}）：{tail}')

        if not result.get('ok'):
            raise RuntimeError(result.get('error') or '采集失败')

        return result.get('data') or {}
    finally:
        try:
            os.unlink(out_path)
        except Exception:
            pass
