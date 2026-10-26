"""把需求知识库（已确认节点）格式化成可注入 AI 提示词的语境文本。

支持两种注入模式（backend/settings.py 的 KNOWLEDGE_INJECTION_MODE）：
- precise（默认）：用 AI 语义匹配挑出与本次需求相关的功能点，只注入这部分知识
- full：全量注入项目下所有已确认知识节点
"""
import hashlib
import json
import logging
import re

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max

from .models import KnowledgeNode

logger = logging.getLogger(__name__)

# 匹配结果缓存 24 小时（key 里带知识库版本，KB 变动会自动失效）
MATCH_CACHE_TTL = 24 * 3600
# 精准注入的字数预算
PRECISE_MAX_CHARS = 6000
# 传给匹配 AI 的需求文本上限
MATCH_TEXT_LIMIT = 6000
# 兜底骨架的字数上限
SKELETON_MAX_CHARS = 2500


# ---------------- 全量模式 ----------------

def get_project_knowledge_text(project_id, max_chars=8000):
    """（全量模式）返回项目已确认知识节点的缩进文本（功能域节点不输出自身）"""
    roots = KnowledgeNode.objects.filter(
        project_id=project_id, status='confirmed', parent__isnull=True
    ).order_by('order', 'id')
    if not roots.exists():
        return ''

    lines = []
    total = [0]

    def walk(node, depth):
        if total[0] >= max_chars:
            return
        indent = chr(12288) * depth
        if node.kind == 'rule':
            prefix = f'{indent}- [{node.get_kind_display()}] {node.name}'
            if node.rule_type:
                prefix += f'（{node.get_rule_type_display()}）'
            s = prefix
            if node.content:
                s += f'：{node.content}'
        else:
            s = f'{indent}- [{node.get_kind_display()}] {node.name}'
            if node.content:
                s += f'：{node.content}'
        lines.append(s)
        total[0] += len(s)
        for child in node.children.filter(status='confirmed').order_by('order', 'id'):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)

    return chr(10).join(lines)


# ---------------- 模式 / 版本 ----------------

def _get_injection_mode():
    """知识库注入模式：precise（精准，默认）/ full（全量）"""
    return str(getattr(settings, 'KNOWLEDGE_INJECTION_MODE', 'precise')).strip().lower()


def get_knowledge_version(project_id):
    """知识库版本标识：节点数 + 最大更新时间（新增/修改/删除都会变更）"""
    agg = KnowledgeNode.objects.filter(project_id=project_id, status='confirmed').aggregate(
        cnt=Count('id'), mx=Max('updated_at')
    )
    mx = agg.get('mx')
    ts = int(mx.timestamp()) if mx else 0
    return f"{agg.get('cnt') or 0}_{ts}"


# ---------------- AI 语义匹配 ----------------

def _get_match_cfg():
    """匹配用配置：优先纯文本模型（比视觉模型便宜）"""
    from apps.requirement_analysis.models import AIModelConfig
    cfg = AIModelConfig.objects.filter(is_active=True, supports_vision=False).first()
    if not cfg:
        cfg = AIModelConfig.objects.filter(is_active=True).first()
    return cfg


def _call_match_ai(cfg, prompt):
    """调用匹配模型。推理模型偶发把 token 全花在思考上，正文会是空的，所以给足上限并重试一次。"""
    from apps.requirement_analysis.models import AIModelService
    url = AIModelService.build_openai_compatible_url(cfg.base_url, '/chat/completions')
    headers = AIModelService.get_openai_compatible_headers(cfg.api_key)

    def _do(max_tokens):
        body = {
            'model': cfg.model_name,
            'messages': [
                {'role': 'system', 'content': '你是需求与功能点的匹配专家，只输出 JSON。'},
                {'role': 'user', 'content': prompt},
            ],
            'max_tokens': max_tokens,
            'temperature': 0.1,
        }
        with httpx.Client(timeout=180) as client:
            r = client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        choice = (data.get('choices') or [{}])[0]
        return ((choice.get('message') or {}).get('content') or ''), choice.get('finish_reason')

    text, finish = _do(4096)
    if not text.strip():
        logger.warning('[knowledge] 匹配正文为空（finish=%s），提高上限重试', finish)
        text, _ = _do(16384)
    return text


def _parse_match_json(content):
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
        raise ValueError('AI 匹配输出解析失败')


def _ai_match_feature_ids(text, features):
    """AI 语义匹配，返回命中功能点 id 列表；调用/解析失败返回 None（触发兜底）"""
    cfg = _get_match_cfg()
    if not cfg:
        return None
    lines = [f"{i + 1}. {f['name']}" for i, f in enumerate(features)]
    prompt = (
        '下面是一份 App 功能点清单和一份需求文档。请从清单中选出与需求文档真正相关的功能点，只输出 JSON。'
        + chr(10) + chr(10)
        + '【功能点清单】' + chr(10) + chr(10).join(lines) + chr(10) + chr(10)
        + '【需求文档】' + chr(10) + (text or '')[:MATCH_TEXT_LIMIT] + chr(10) + chr(10)
        + '输出格式：{"indexes": [1, 3, 5]}' + chr(10)
        + '规则：只选确实相关的；不确定的不要选；一个都没选中就输出 {"indexes": []}'
    )
    try:
        content = _call_match_ai(cfg, prompt)
        data = _parse_match_json(content)
    except Exception as e:
        logger.warning('[knowledge] AI 匹配失败: %s', str(e)[:200])
        return None

    idxs = data.get('indexes') if isinstance(data, dict) else None
    if not isinstance(idxs, list):
        return None
    picked = []
    for i in idxs:
        try:
            n = int(i)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= len(features):
            fid = features[n - 1]['id']
            if fid not in picked:
                picked.append(fid)
    return picked


# ---------------- 组装 ----------------

def _skeleton_knowledge(project_id, max_chars=SKELETON_MAX_CHARS):
    """兜底骨架：只输出 功能域 / 功能模块 / 功能点 的名字（不含规则内容）"""
    nodes = list(KnowledgeNode.objects.filter(
        project_id=project_id, status='confirmed'
    ).order_by('order', 'id'))
    if not nodes:
        return ''
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    lines = []
    total = [0]

    def walk(pid, depth):
        if depth > 2 or total[0] >= max_chars:
            return
        for n in by_parent.get(pid, []):
            if total[0] >= max_chars:
                return
            if n.kind not in ('domain', 'module', 'feature'):
                continue
            line = '  ' * depth + '- ' + n.name
            lines.append(line)
            total[0] += len(line) + 1
            walk(n.id, depth + 1)

    walk(None, 0)
    return chr(10).join(lines)


def _render_subtree(node, depth, add_line):
    """递归渲染功能点子树（业务规则 / 子功能点 / 页面描述）"""
    for child in node.children.filter(status='confirmed').order_by('order', 'id'):
        indent = '  ' * depth
        if child.kind == 'rule':
            label = child.get_rule_type_display() or child.get_kind_display()
            s = f'{indent}· [{label}] {child.name}'
            if child.content:
                s += f'：{child.content}'
            if not add_line(s):
                return
        elif child.kind == 'page':
            s = f'{indent}· [页面] {child.name}'
            if child.content:
                s += f'：{child.content}'
            if not add_line(s):
                return
        else:
            s = f'{indent}- {child.name}'
            if child.content:
                s += f'：{child.content}'
            if not add_line(s):
                return
        _render_subtree(child, depth + 1, add_line)


def _assemble_knowledge(project_id, feature_ids, max_chars=PRECISE_MAX_CHARS):
    """把命中的功能点（祖先链 + 规则子树）组装成注入文本"""
    features = list(KnowledgeNode.objects.filter(
        project_id=project_id, id__in=feature_ids, status='confirmed'
    ).order_by('order', 'id'))
    if not features:
        return ''

    lines = []
    total = [0]

    def add_line(s):
        if total[0] + len(s) + 1 > max_chars:
            return False
        lines.append(s)
        total[0] += len(s) + 1
        return True

    for feat in features:
        chain = []
        p = feat.parent
        while p:
            chain.append(p.name)
            p = p.parent
        chain.reverse()
        add_line('■ ' + ' / '.join(chain + [feat.name]))
        doc = (feat.summary or '').strip()
        if doc:
            # 优先注入审核过的需求文档（新流程产出的口径）；文档可能挂在祖先上，已在匹配阶段处理
            for ln in doc.splitlines():
                if not ln.strip():
                    continue
                if not add_line('  ' + ln):
                    break
        else:
            # 历史节点没有文档 → 退回子节点列表
            _render_subtree(feat, 1, add_line)

    return chr(10).join(lines)


# ---------------- 对外主函数 ----------------

def match_feature_ids(project_id, requirement_text):
    """AI 语义匹配命中的功能点 id 列表（带缓存）。

    返回 None 表示 AI 调用失败（调用方自行兜底）。
    """
    text = (requirement_text or '').strip()
    if not text:
        return []

    # 归类/对比/注入统一以「模块」为单元（二级）
    features = list(KnowledgeNode.objects.filter(
        project_id=project_id, kind='module', status='confirmed'
    ).order_by('order', 'id').values('id', 'name'))
    if not features:
        return []

    kv = get_knowledge_version(project_id)
    th = hashlib.md5(text.encode('utf-8')).hexdigest()
    # 前缀 kb_match2：匹配单元从「功能点」改成「模块」，旧缓存作废
    ckey = f'kb_match2:{project_id}:{kv}:{th}'

    picked = cache.get(ckey)
    if picked is None:
        picked = _ai_match_feature_ids(text, features)
        if picked is None:
            return None
        cache.set(ckey, picked, MATCH_CACHE_TTL)
    return picked


def check_coverage(project_id, requirement_text):
    """检查这份需求在知识库里的覆盖情况（复用匹配缓存，不额外调 AI）。

    返回匹配到的功能点，以及哪些「还没文档」、哪些「有待审核的变更」。
    """
    from .models import KnowledgeProposalItem

    picked = match_feature_ids(project_id, requirement_text)
    if picked is None:
        return {'ok': False, 'error': 'AI 匹配失败，暂时无法判断知识库覆盖情况'}
    if not picked:
        return {'ok': True, 'matched': [], 'matched_count': 0,
                'without_doc': [], 'with_pending': []}

    nodes = list(KnowledgeNode.objects.filter(id__in=picked))
    order = {fid: i for i, fid in enumerate(picked)}
    nodes.sort(key=lambda n: order.get(n.id, 999))

    def _has_doc(node):
        """文档可能挂在祖先功能点上（比如文档在「心动功能」，匹配到的是子项「便利贴」）"""
        cur, depth = node, 0
        while cur and depth < 6:
            if (cur.summary or '').strip():
                return True
            cur = cur.parent
            depth += 1
        return False

    rows = []
    for n in nodes:
        pending = KnowledgeProposalItem.objects.filter(
            target_node=n, decision='pending',
            change_type__in=('conflict', 'append', 'new'),
        ).count()
        rows.append({
            'id': n.id,
            'name': n.name,
            'has_doc': _has_doc(n),
            'pending_changes': pending,
        })

    return {
        'ok': True,
        'matched': rows,
        'matched_count': len(rows),
        'without_doc': [r for r in rows if not r['has_doc']],
        'with_pending': [r for r in rows if r['pending_changes']],
    }


def build_relevant_knowledge(project_id, requirement_text, max_chars=PRECISE_MAX_CHARS):
    """精准注入：AI 语义匹配相关功能点 → 组装知识文本。带缓存 + 三级兜底。"""
    text = (requirement_text or '').strip()
    if not text:
        return get_project_knowledge_text(project_id)

    picked = match_feature_ids(project_id, text)
    if picked is None:
        # 匹配调用失败 → 退回全量（保证不比现状差）
        logger.warning('[knowledge] AI 匹配失败，退回全量注入')
        return get_project_knowledge_text(project_id, max_chars=max_chars + 2000)

    if not picked:
        logger.info('[knowledge] AI 匹配为空，注入骨架')
        return _skeleton_knowledge(project_id)

    result = _assemble_knowledge(project_id, picked, max_chars)
    if not result.strip():
        return _skeleton_knowledge(project_id)
    logger.info('[knowledge] 精准注入：命中 %d 个功能点，输出 %d 字', len(picked), len(result))
    return result


def merge_with_structured_knowledge(project, requirement_text=''):
    """把项目知识背景与需求知识库合并，供生成用例时注入。

    传入 requirement_text 且处于 precise 模式时，会做 AI 语义匹配后精准注入。
    """
    base = (project.knowledge_base or '').strip()
    mode = _get_injection_mode()
    if mode == 'precise' and (requirement_text or '').strip():
        structured = build_relevant_knowledge(project.id, requirement_text)
    else:
        structured = get_project_knowledge_text(project.id)

    if not structured:
        return base
    block = '【需求知识库（功能点/规则）】' + chr(10) + structured
    return (base + chr(10) + chr(10) + block) if base else block
