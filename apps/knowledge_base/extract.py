"""需求知识库 AI 抽取：把采集到的原型页面文本，抽取成功能点/规则/页面描述，挂到知识树"""
import json
import logging
import re

import httpx

from .models import KnowledgeNode

logger = logging.getLogger(__name__)

RULE_TYPES = ('normal', 'exception', 'field', 'enum', 'dependency', 'frequency', 'member', 'permission', 'operation')
KINDS = ('feature', 'rule', 'page')


def _get_config():
    from apps.requirement_analysis.models import AIModelConfig
    cfg = AIModelConfig.objects.filter(role='extractor', is_active=True).first()
    if not cfg:
        cfg = AIModelConfig.objects.filter(role='writer', is_active=True).first()
    if not cfg:
        cfg = AIModelConfig.objects.filter(is_active=True).first()
    if not cfg:
        return None
    return {
        'api_key': cfg.api_key or '',
        'base_url': cfg.base_url,
        'model_name': cfg.model_name,
        'max_tokens': cfg.max_tokens or 4096,
        'temperature': cfg.temperature,
    }


def _call_ai(cfg, prompt, system=''):
    base = cfg['base_url'].rstrip('/')
    url = f'{base}/chat/completions' if base.endswith('/v1') else f'{base}/v1/chat/completions'
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    headers = {
        'Authorization': f'Bearer {cfg["api_key"]}',
        'Content-Type': 'application/json',
    }

    def _do(max_tokens):
        body = {
            'model': cfg['model_name'],
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': cfg['temperature'],
        }
        with httpx.Client(timeout=240) as client:
            r = client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        choice = (data.get('choices') or [{}])[0]
        return ((choice.get('message') or {}).get('content') or ''), choice.get('finish_reason')

    content, finish = _do(cfg['max_tokens'])
    # 推理模型偶发把 token 全花在思考上（finish_reason=length 且正文为空），提高上限重试一次
    if not content.strip():
        logger.warning('[knowledge] AI 正文为空（finish=%s），用更大 token 上限重试', finish)
        content, _ = _do(max(int(cfg['max_tokens'] or 4096) * 2, 16384))
    return content


def _parse_json(content):
    text = (content or '').strip()
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        m2 = re.search(r'\{[\s\S]*\}', text)
        if m2:
            return json.loads(m2.group(0))
        raise ValueError('AI 输出解析失败')


def _build_prompt(parent, pages):
    children = parent.children.all().order_by('order', 'id')
    child_lines = [f'- [{c.get_kind_display()}] {c.name}' for c in children]
    child_desc = '\n'.join(child_lines) if child_lines else '（暂无子节点）'

    page_blocks = []
    for i, p in enumerate(pages, 1):
        name = (p.get('name') or f'页面{i}').strip()
        text = (p.get('content') or p.get('text') or '').strip()
        if len(text) > 4000:
            text = text[:4000] + '...'
        page_blocks.append(f'## 页面{i}：{name}\n{text}')

    return f"""你是需求知识库抽取专家。请把下面的 App 原型页面内容，抽取成结构化的知识节点，挂载到目标节点下。

# 目标节点（挂载点）
- 名称：{parent.name}
- 类型：{parent.get_kind_display()}

# 目标节点下已有子节点（尽量复用已有，避免重复；确有必要再新增）
{child_desc}

# 原型页面内容
{chr(10).join(page_blocks)}

# 输出要求（只输出 JSON，不要任何解释）
{{
  "nodes": [
    {{"kind": "feature", "name": "功能点名称", "content": "一句话说明这个功能做什么"}},
    {{"kind": "rule", "name": "规则名称", "content": "完整的规则内容", "rule_type": "field"}}
  ]
}}

# kind / rule_type 取值
kind 只能是 feature / rule / page。
rule_type 只能取：normal(正向流程) / exception(异常流程) / field(字段约束) / enum(枚举值)
/ dependency(依赖) / frequency(频率限制) / member(会员限制) / permission(权限) / operation(运营配置)

# 按下面清单逐项检查，不要遗漏
1. 功能点：这个画布/功能是做什么的
2. 业务规则：具体到可验证的程度，如"最多 200 字""每天 3 次""非会员 1 张 / 会员 9 张"
3. 正向流程：正常操作步骤、状态流转
4. 异常/边界：失败、超限、空数据、重复操作、并发、网络异常
5. 字段约束：字段名、必填、长度、格式
6. 枚举值：可选值列表、状态值
7. 依赖/前置条件：需要先完成什么、依赖哪个功能或配置
8. 频率限制 / 会员限制 / 权限 / 运营配置

# 关键要求
- 保留具体细节：数字、条件、枚举值、字段名、状态名必须原样保留，禁止概括成"有字数限制""若干张"这类模糊表述
- 不要漏：同一条需求里有几条规则就抽几条，不要合并、不要限制条数
- 不要编：原文没写的不要自己补充
- 内容写完整、可验证，去掉"页面/前置条件/需求逻辑"这类标题文字

# 不要抽的内容（一律跳过）
纯页面布局/视觉描述、示例展示型假数据、通用按钮文案、装饰性内容。
（page 类型只在确有"页面入口/关键结构"值得记录时才抽，否则不要抽）"""


def extract_nodes(project_id, parent_id, pages):
    """把页面内容抽取成知识节点，创建到 parent 下，状态为 draft（待确认）"""
    parent = KnowledgeNode.objects.filter(id=parent_id, project_id=project_id).first()
    if not parent:
        raise ValueError('目标节点不存在')

    # 只要有名或内容都保留：思维导图导入的节点只有名字、没有描述，也要能进文档
    pages = [p for p in (pages or []) if (p.get('content') or p.get('text') or p.get('name') or '').strip()]
    if not pages:
        raise ValueError('没有可抽取的页面内容')

    cfg = _get_config()
    if not cfg:
        raise ValueError('未配置 AI 模型')

    content = _call_ai(cfg, _build_prompt(parent, pages), system='你是需求知识库抽取专家，只输出 JSON。')
    data = _parse_json(content)

    created = []
    for n in (data.get('nodes') or []):
        name = (n.get('name') or '').strip()[:200]
        if not name:
            continue
        kind = n.get('kind') if n.get('kind') in KINDS else 'rule'
        node_content = (n.get('content') or '').strip()
        rule_type = n.get('rule_type') if n.get('rule_type') in RULE_TYPES else None
        node = KnowledgeNode.objects.create(
            project_id=project_id,
            parent=parent,
            kind=kind,
            name=name,
            content=node_content,
            rule_type=rule_type if kind == 'rule' else None,
            status='draft',
            order=0,
        )
        created.append({
            'id': node.id,
            'kind': node.kind,
            'kind_display': node.get_kind_display(),
            'name': node.name,
            'content': node.content,
            'rule_type': node.rule_type,
            'status': node.status,
        })

    return {'count': len(created), 'nodes': created}



RULE_TYPE_LABELS = {
    'normal': '正向流程', 'exception': '异常流程', 'field': '字段约束', 'enum': '枚举值',
    'dependency': '依赖', 'frequency': '频率限制', 'member': '会员限制',
    'permission': '权限', 'operation': '运营配置',
}


def classify_rule_types(project_id):
    """把 rule_type 为空的规则批量补分类（AI 判断），返回更新数量"""
    from .models import KnowledgeNode
    rules = list(KnowledgeNode.objects.filter(project_id=project_id, kind='rule', rule_type__isnull=True).order_by('id'))
    if not rules:
        return {'updated': 0, 'total': 0}

    cfg = _get_config()
    if not cfg:
        raise ValueError('未配置 AI 模型')

    # 携带父功能点名称，帮助 AI 判断
    infos = []
    for r in rules:
        parent_name = r.parent.name if r.parent else ''
        infos.append({
            'id': r.id,
            'name': r.name,
            'content': (r.content or '')[:300],
            'parent': parent_name,
        })

    updated = 0
    batch_size = 40
    for start in range(0, len(infos), batch_size):
        batch = infos[start:start + batch_size]
        lines = []
        for i, it in enumerate(batch):
            lines.append(f"{i + 1}. 功能：{it['parent']} | 规则：{it['name']} | 内容：{it['content'] or '（无）'}")
        prompt = (
            '请为下面的每条“业务规则”判断其 rule_type 类型。\n'
            'rule_type 可选值（只能选其一）：\n'
            'normal(正向流程)、exception(异常流程)、field(字段约束/输入约束)、enum(枚举值)、'
            'dependency(依赖)、frequency(频率/次数限制)、member(会员限制)、permission(权限)、operation(运营配置)\n\n'
            '判断依据：正向流程=正常操作步骤/展示逻辑；异常流程=错误、拦截、失败、边界处理；'
            '字段约束=字数/长度/格式/必填；枚举值=可选值列表；依赖=前置条件/依赖其他功能；'
            '频率限制=次数/频率/每天/间隔；会员限制=会员/权益；权限=权限/开关；运营配置=后台可配置项。\n\n'
            '只输出 JSON：{"items":[{"index":1,"rule_type":"normal"},...]}\n\n'
            + chr(10).join(lines)
        )
        content = _call_ai(cfg, prompt, system='你是需求规则分类专家，只输出 JSON。')
        data = _parse_json(content)
        items = data.get('items') or []
        mapping = {}
        for item in items:
            try:
                idx = int(item.get('index'))
            except (TypeError, ValueError):
                continue
            rt = item.get('rule_type')
            if rt in RULE_TYPES:
                mapping[idx - 1] = rt

        for i, it in enumerate(batch):
            rt = mapping.get(i)
            if rt:
                KnowledgeNode.objects.filter(id=it['id']).update(rule_type=rt)
                updated += 1

    return {'updated': updated, 'total': len(infos)}


def _build_summary_prompt(parent, pages, note=''):
    page_blocks = []
    for i, p in enumerate(pages, 1):
        name = (p.get('name') or f'画布{i}').strip()
        text = (p.get('content') or p.get('text') or '').strip()
        if len(text) > 6000:
            text = text[:6000] + '...'
        page_blocks.append(f'## 片段{i}：{name}' + chr(10) + text)

    # 模块下面挂着若干功能点：把它们作为小节骨架给出，防止 AI 合并时整块漏掉
    skeleton = ''
    try:
        kids = [c.name for c in parent.children.filter(kind='feature', status='confirmed')
                .order_by('order', 'id')[:40]]
    except Exception:
        kids = []
    if kids:
        skeleton = (
            chr(10) + chr(10) + '【建议的文档结构】请尽量按下面这些功能分小节'
            '（用 ### 小节名），确保每块内容都有归属、不要整块漏掉：'
            + chr(10) + chr(10).join('- ' + k for k in kids)
        )

    note_block = ''
    if (note or '').strip():
        note_block = (
            '\n【本次版本的人工备注 —— 请重点参考】\n'
            + note.strip()[:1000]
            + '\n（以上是产品/测试人员补充的说明，用于帮助你抓重点、判断哪些才是本版真正的内容）\n'
        )

    return f"""下面是从产品原型中提取出来的若干内容，都属于同一个功能：「{parent.name}」。
{note_block}
请把它整理成一份**需求说明文档**，用 Markdown 输出。{skeleton}

# 输出结构（只保留下面这两节；某一节原文确实没内容，整节省略）
## 功能概述
一句话说明这个功能是做什么的。

## 功能逻辑
围绕这个功能自己怎么实现来讲，可以包含：
- 正常流程：用户从哪进入、看到什么、怎么操作、操作后发生什么
- 交互反馈：点击/输入的反馈、提示、跳转去向
- 条件分支：什么条件下显示/隐藏、可用/置灰、走哪条流程
- 状态与规则：状态名、枚举值、数量或次数限制、原文里的具体文案
- 边界表现：失败、超限、空数据、重复操作时**界面**怎么表现（提示什么、留在哪里）

# 硬性要求
1. 只写 App 功能层面的实现描述，全部围绕「功能逻辑」展开 —— 这份文档是给 App 功能测试用例生成用的，不是接口文档
2. 禁止出现接口相关的内容：接口、API、参数、字段名、必填、请求头、前置依赖、测试数据准备、执行顺序
3. 保留原文中的具体数字、条件、枚举值、状态名、文案，禁止概括成"有字数限制""若干张"这类模糊表述
4. 能用表格表达的一律用 Markdown 表格（状态对照、条件分支矩阵、枚举值等）
5. 严格基于上面的内容，不要编造原文没有的东西
6. Markdown 表格**必须带表头分隔行**（如 `| --- | --- |`），否则渲染不出表格
7. 只输出 Markdown 正文，不要任何解释，不要用代码块包裹
8. 某个分区原文里确实没有对应内容时，**整节直接省略**；禁止写「原文未提供」「待补充」「暂无」「未提供」这类占位内容，也不要为了凑格式硬填表格
9. 「功能逻辑」这一节必须保留：即使原文只给了子功能/模块的名称、没有任何细则，也要把它们作为小节（`### 名称`）列在「功能逻辑」下面，让文档保留功能清单的作用；只写名称即可，不要编内容
# 内容
{chr(10).join(page_blocks)}"""


def _fix_md_tables(text):
    """有些模型写 Markdown 表格会漏掉表头分隔行，这里补上（否则前端渲染不出表格）"""
    lines = (text or '').split(chr(10))
    out = []
    sep_re = re.compile(r'^\|[\s\-:|]+\|$')
    in_table = False
    for i, line in enumerate(lines):
        s = line.strip()
        is_row = s.startswith('|') and s.endswith('|') and s.count('|') >= 3
        if not is_row:
            in_table = False
            out.append(line)
            continue
        if sep_re.match(s):
            in_table = True
            out.append(line)
            continue
        if not in_table:
            out.append(line)
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if not sep_re.match(nxt):
                out.append('|' + ' --- |' * (s.count('|') - 1))
            in_table = True
        else:
            out.append(line)
    return chr(10).join(out)


def generate_summary(parent, pages, note=''):
    """为功能点生成一份 Markdown 需求说明（写入 parent.summary 由调用方决定）"""
    # 只要有名或内容都保留：思维导图导入的节点只有名字、没有描述，也要能进文档
    pages = [p for p in (pages or []) if (p.get('content') or p.get('text') or p.get('name') or '').strip()]
    if not pages:
        return ''
    cfg = _get_config()
    if not cfg:
        return ''
    content = _call_ai(cfg, _build_summary_prompt(parent, pages, note=note),
                       system='你是需求文档撰写专家，只输出 Markdown 正文。')
    text = (content or '').strip()
    m = re.search(r'```(?:markdown|md)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    return _fix_md_tables(text)

