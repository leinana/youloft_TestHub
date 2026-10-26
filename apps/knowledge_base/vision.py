"""需求知识库视觉识别：把采集到的画布转成「有效需求内容」。

输入三类素材（缺一不可，互补）：
  1. 整张画布截图      —— 看整体布局、流程图、元素关系
  2. 文字元素 + 坐标    —— 精确文字（DOM 取的，比 OCR 准），坐标用于还原表格行列
  3. 内容型图片的原图   —— 截图贴上去的表格/流程图，原图分辨率远高于画布截图

只读有效需求内容，过滤示例展示型的样板文字（假数据、重复 UI 文案等）。
"""
import base64
import io
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from django.conf import settings

logger = logging.getLogger(__name__)

# 视觉识别并发数
VISION_CONCURRENCY = 4
# 单张图长边上限（比之前提高，保住小字可读性）
MAX_IMAGE_EDGE = 2048
# 竖长图切片阈值与切片高度（手机长截图切段发，避免整体缩小后看不清）
SLICE_THRESHOLD = 2000
SLICE_HEIGHT = 1500
SLICE_OVERLAP = 120
MAX_SLICES_PER_IMAGE = 3
# 每张画布最多附带几张原图（原图多时推理模型容易烧光 token）
MAX_ORIGINAL_IMAGES = 2
JPEG_QUALITY = 82


def _get_vision_config():
    from apps.requirement_analysis.models import AIModelConfig
    cfg = AIModelConfig.objects.filter(role='extractor', supports_vision=True, is_active=True).first()
    if not cfg:
        cfg = AIModelConfig.objects.filter(supports_vision=True, is_active=True).first()
    return cfg


# 送给模型的「精确文字」上限（防止提示词过长把推理模型的 token 烧光）
ELEMENTS_MAX_ITEMS = 500
ELEMENTS_MAX_CHARS = 8000
# 同一行的纵向容忍度（px）
ELEMENTS_ROW_BAND = 14


def _elements_to_text(elements, max_items=ELEMENTS_MAX_ITEMS, max_chars=ELEMENTS_MAX_CHARS):
    """把 DOM 文字元素按坐标还原成分行的纯文本。

    这些文字是直接从 DOM 取的，不受画布缩放影响 —— 比让模型去认缩小的截图准得多。
    同一行（纵向差小于 14px）用 | 连接，行与行之间换行。
    """
    items = []
    for e in (elements or []):
        t = (e.get('t') or '').strip()
        if not t:
            continue
        try:
            y = float(e.get('y') or 0)
            x = float(e.get('x') or 0)
        except (TypeError, ValueError):
            continue
        items.append((y, x, t))
    if not items:
        return ''

    items.sort(key=lambda r: (r[0], r[1]))
    items = items[:max_items]

    rows = {}
    for y, x, t in items:
        band = int(round(y / ELEMENTS_ROW_BAND))
        rows.setdefault(band, []).append((x, t))

    lines = []
    for band in sorted(rows):
        cells = [t for _, t in sorted(rows[band], key=lambda c: c[0])]
        lines.append(' | '.join(cells))

    text = chr(10).join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + chr(10) + '…（文字过多，已截断）'
    return text


def _vision_prompt(name, elements=None):
    """视觉识别提示词。

    注意：这类推理模型对「长指令清单」非常敏感——指令一多就把 token 全花在思考上，
    导致正文为空。所以「指令」部分刻意写得很短，只保留最关键的几条约束。

    另外会把采集时从 DOM 拿到的**精确文字**（带坐标还原成分行）一起给模型，
    让它以原文为准、截图只用来判断版式与箭头关系 —— 画布被墨刀缩小后，截图上的小字不可靠。
    """
    s = (
        '请把这张产品原型画布（标题：' + name + '）里的需求内容完整读出来，'
        '保留原文的数字、条件、枚举值和状态名；'
        '有表格还原成 Markdown 表格，保留表头与行列对应；'
        '有流程就写清先后顺序和分支条件；'
        '忽略示例假数据、按钮文案和纯装饰元素。'
        '只输出内容，不要解释。'
    )
    text = _elements_to_text(elements)
    if text:
        s += (
            chr(10) + chr(10)
            + '【画布里精确提取到的原文（按位置自上而下排列，同一行用 | 分隔）】' + chr(10)
            + text + chr(10)
            + '上面这些文字是原型的真实内容，**以它为准**：'
            + '图片里的字若看不清、被缩小或与上面冲突，一律采用上面的文字。'
            + '截图只用来看版式、流程图走向、箭头关系和表格的行列对应。'
        )
    return s


def _encode_image(im, max_edge=MAX_IMAGE_EDGE):
    w, h = im.size
    if max(w, h) > max_edge:
        s = max_edge / max(w, h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii'), 'image/jpeg'


def _prepare_images(abs_path):
    """读取一张图，必要时竖向切片，返回 [(base64, media_type), ...]"""
    out = []
    with Image.open(abs_path) as im:
        im = im.convert('RGB')
        w, h = im.size
        if h > SLICE_THRESHOLD:
            y = 0
            while y < h and len(out) < MAX_SLICES_PER_IMAGE:
                piece = im.crop((0, y, w, min(h, y + SLICE_HEIGHT)))
                out.append(_encode_image(piece))
                if y + SLICE_HEIGHT >= h:
                    break
                y += SLICE_HEIGHT - SLICE_OVERLAP
        else:
            out.append(_encode_image(im))
    return out


def _call_vision(cfg, images, prompt):
    """images: [(base64, media_type), ...]，多图一起发给视觉模型"""
    from apps.requirement_analysis.models import AIModelService
    url = AIModelService.build_openai_compatible_url(cfg.base_url, '/chat/completions')
    headers = AIModelService.get_openai_compatible_headers(cfg.api_key)
    content = [{'type': 'text', 'text': prompt}]
    for b64, mt in images:
        content.append({'type': 'image_url', 'image_url': {'url': f'data:{mt};base64,' + b64}})
    def _do(max_tokens):
        body = {
            'model': cfg.model_name,
            'messages': [{'role': 'user', 'content': content}],
            'max_tokens': max_tokens,
            'temperature': 0.2,
        }
        with httpx.Client(timeout=300) as client:
            r = client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        choice = (data.get('choices') or [{}])[0]
        return ((choice.get('message') or {}).get('content') or ''), choice.get('finish_reason')

    base_tokens = max(int(cfg.max_tokens or 4096), 16384)
    text, finish = _do(base_tokens)
    # 推理模型偶尔把 token 全花在思考上（finish_reason=length 且正文为空）
    if not text.strip():
        logger.warning('[vision] 正文为空（finish=%s，图片 %d 张），提高 token 上限重试',
                       finish, len(images))
        text, _ = _do(max(base_tokens * 2, 8192))
    return text


def _resolve_screenshot_path(rel):
    """把 /media/... 相对路径解析为磁盘绝对路径"""
    if not rel:
        return None
    rel = rel.lstrip('/')
    if rel.startswith('media/'):
        rel = rel[len('media/'):]
    abs_path = os.path.join(settings.MEDIA_ROOT, rel)
    return abs_path if os.path.isfile(abs_path) else None


def _normalize(text):
    text = (text or '').strip()
    m = re.search(r'```(?:markdown|text)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    if text in ('无有效需求', '无有效需求。', '无有效需求内容'):
        text = ''
    return text


def _recognize_one(cfg, page):
    """识别单个画布：画布截图 + 原图 + 文字坐标 一起送模型"""
    name = (page.get('name') or '未命名').strip()
    images = []

    shot = _resolve_screenshot_path(page.get('screenshot'))
    if shot:
        images.extend(_prepare_images(shot))

    for im in (page.get('images') or [])[:MAX_ORIGINAL_IMAGES]:
        p = _resolve_screenshot_path(im.get('media'))
        if p:
            images.extend(_prepare_images(p))

    if not images:
        return {'name': name, 'content': '', 'error': '无截图，无法识别'}

    try:
        prompt = _vision_prompt(name, page.get('elements'))
        text = _call_vision(cfg, images, prompt)
        return {'name': name, 'content': _normalize(text), 'error': ''}
    except Exception as e:
        logger.warning('视觉识别失败 [%s]: %s', name, str(e)[:200])
        return {'name': name, 'content': '', 'error': str(e)[:200]}


def recognize_pages(pages):
    """并发识别采集到的页面，返回每页的「有效需求内容」（与入参顺序一致）"""
    cfg = _get_vision_config()
    if not cfg:
        raise ValueError('未配置支持多模态（视觉）的 AI 模型，请先在 AI 配置中启用一个 supports_vision 的模型')

    pages = list(pages or [])
    if not pages:
        return []

    results = [None] * len(pages)
    workers = min(VISION_CONCURRENCY, len(pages))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_recognize_one, cfg, p): i for i, p in enumerate(pages)}
        for fut in futures:
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {'name': (pages[idx].get('name') or '').strip(), 'content': '', 'error': str(e)[:200]}

    for i, r in enumerate(results):
        if r is None:
            results[i] = {'name': (pages[i].get('name') or '').strip(), 'content': '', 'error': '识别失败'}
    return results
