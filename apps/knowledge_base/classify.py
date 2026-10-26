"""需求知识库：把采集到的画布归类到「模块」。

归类策略（按产品经理写文档的习惯）：
  墨刀画布通常是「顶层分组 → 中间层 → 画布」的结构，
  顶层分组名 ≈ 这个功能模块的名字（产品经理就是按顶层功能写文档的）。
  所以优先用【顶层分组名】匹配知识库模块，分组下的所有画布都归到同一个模块；
  没有分组的独立画布，才用它自己的名字去匹配。

注：接口字段仍沿用 feature_id / feature_name，实际上指向的是「模块」节点。
"""
import logging
import re

from .models import KnowledgeNode

logger = logging.getLogger(__name__)

# 一次最多处理多少个分组名（分组数远小于画布数，一般十几个）
MAX_GROUPS = 60


def _get_modules(project_id):
    """知识库里的全部模块（数量不多，前端可以直接全列）"""
    return list(
        KnowledgeNode.objects.filter(project_id=project_id, kind='module', status='confirmed')
        .order_by('order', 'id').values('id', 'name')
    )


def get_candidates(project_id, pages=None):
    """给前端下拉用的候选：直接给全部模块"""
    return _get_modules(project_id)


def get_domains(project_id):
    """知识库里的全部大类（功能域），供「新建模块」时选择归属大类"""
    return list(
        KnowledgeNode.objects.filter(project_id=project_id, kind='domain', status='confirmed')
        .order_by('order', 'id').values('id', 'name')
    )


def _group_key(page):
    """画布的归类 key：优先顶层分组名，没有分组才用画布自己的名字"""
    parents = [x for x in (page.get('parents') or []) if (x or '').strip()]
    if parents:
        return parents[0].strip()
    return (page.get('name') or '').strip()


def _norm_name(s):
    """归一化名称：去掉空格/全角括号/标点，便于比较"""
    return re.sub(r'[\s\u3000()（）【】\[\]_\-·]+', '', (s or '').strip()).lower()


def _keyword_match(key, modules):
    """字面匹配：先完全相同，再允许包含 —— 但较短的一边至少 4 个字，
    避免「任务」「小组件」这类短词把无关画布吸过去。"""
    k = _norm_name(key)
    if not k:
        return None
    for m in modules:
        if _norm_name(m.get('name')) == k:
            return m['id']
    for m in modules:
        n = _norm_name(m.get('name'))
        if not n:
            continue
        if min(len(n), len(k)) >= 4 and (n in k or k in n):
            return m['id']
    return None


def _ai_match_groups(keys, modules):
    """让 AI 把「分组名」匹配到「模块」，返回 {分组序号: 模块id}；失败返回 None"""
    from .extract import _get_config, _call_ai, _parse_json

    cfg = _get_config()
    if not cfg:
        return None

    mod_lines = [f"{i + 1}. {m['name']}" for i, m in enumerate(modules)]
    key_lines = [f"{i + 1}. {k}" for i, k in enumerate(keys)]

    prompt = (
        '把下面的「原型分组名」匹配到「知识库模块」。\n\n'
        '【知识库模块清单】\n' + chr(10).join(mod_lines) + '\n\n'
        '【原型分组名清单】\n' + chr(10).join(key_lines) + '\n\n'
        '只输出 JSON：{"matches":[{"group":1,"module":3},{"group":2,"module":null}]}\n'
        '严格规则：\n'
        '1. group 是分组序号；module 是模块序号。\n'
        '2. 只有当分组名和某个模块**指的是同一个功能**（名字相同，或明显是同一功能的新旧叫法/别名）时才匹配。\n'
        '3. 只是语义相近、沾边、属于同一大类、功能有关联 —— 一律算匹配不上，module 填 null。\n'
        '4. 拿不准一律填 null。null 会被当成「新建模块」，宁缺勿错。\n'
        '5. 不要编造清单外的序号。'
    )
    try:
        out = _call_ai(cfg, prompt, system='你是需求归类专家，只输出 JSON。')
        data = _parse_json(out)
    except Exception as e:
        logger.warning('[classify] AI 匹配失败: %s', str(e)[:160])
        return None

    result = {}
    for item in (data.get('matches') or []):
        try:
            gi = int(item.get('group'))
        except (TypeError, ValueError):
            continue
        mi = item.get('module')
        if mi is None:
            result[gi] = None
            continue
        try:
            mi = int(mi)
        except (TypeError, ValueError):
            result[gi] = None
            continue
        result[gi] = modules[mi - 1]['id'] if 1 <= mi <= len(modules) else None
    return result


def classify_pages(project_id, pages):
    """按【顶层分组】把画布归类到模块。

    返回（一行 = 一个顶层分组）：
        [{group, name, page_count, page_names, feature_id, feature_name}]
    - group / name：顶层分组名（没有分组的独立画布用它自己的名字）
    - feature_id 为 None 表示没匹配上 → 前端用 name 当模块名新建
    """
    pages = list(pages or [])
    if not pages:
        return []

    # 按顶层分组聚合，保持画布出现顺序
    order = []
    by_group = {}
    for p in pages:
        g = _group_key(p) or (p.get('name') or '').strip()
        if not g:
            continue
        if g not in by_group:
            by_group[g] = []
            order.append(g)
        by_group[g].append(p)

    order = order[:MAX_GROUPS]
    if not order:
        return []

    modules = _get_modules(project_id)
    name_by_id = {m['id']: m['name'] for m in modules}

    # 先做字面匹配（精确/包含），命中的直接采用 —— 字面命中比 AI 可靠
    key_to_module = {}
    need_ai = []
    for k in order:
        mid = _keyword_match(k, modules) if modules else None
        key_to_module[k] = mid
        if mid is None:
            need_ai.append(k)

    # 剩下的才交给 AI，且提示词要求「拿不准就填 null」（= 新建模块）
    if need_ai and modules:
        mapping = _ai_match_groups(need_ai, modules) or {}
        for i, k in enumerate(need_ai, 1):
            mid = mapping.get(i)
            if mid is not None:
                key_to_module[k] = mid

    results = []
    for g in order:
        ps = by_group[g]
        mid = key_to_module.get(g)
        results.append({
            'group': g,
            'name': g,
            'page_count': len(ps),
            'page_names': [(x.get('name') or '').strip() for x in ps],
            'feature_id': mid,
            'feature_name': name_by_id.get(mid, '') if mid else '',
        })
    return results
