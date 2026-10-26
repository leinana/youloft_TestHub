"""知识提议：把采集到的需求整理成「提议」，和知识库现值对比，等人审核后再写入。

设计原则：
  · 采集/整理/对比都不写知识库，只产出提议
  · 「一致」的自动跳过，不打扰人
  · 「疑似冲突」只标记，最终由人决定
  · 人上一次选过「保留旧的」，同样的新内容下次不再问（忽略记忆）
"""
import hashlib
import logging
import re
from types import SimpleNamespace

from django.utils import timezone

from .models import (
    KnowledgeNode, KnowledgeCollection, KnowledgeProposal, KnowledgeProposalItem,
)

logger = logging.getLogger(__name__)


# ---------------- 工具 ----------------

def content_hash(*texts):
    """内容指纹：去掉空白差异后取 md5，用于「一致就跳过」"""
    s = chr(10).join((t or '').strip() for t in texts)
    s = re.sub(r'\s+', ' ', s).strip()
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def _get_pending_parent(project_id):
    """未归类的画布挂到这里（不存在则创建）"""
    node = KnowledgeNode.objects.filter(project_id=project_id, name='待归类', parent__isnull=True).first()
    if node:
        return node
    return KnowledgeNode.objects.create(
        project_id=project_id, parent=None, kind='module', name='待归类',
        content='原型导入时未能归类到具体功能点的内容，请人工归位。',
        status='confirmed', order=999,
    )


def _resolve_module_parent(project, parent_id=None):
    """新建模块时确定挂到哪个大类（功能域）。

    指定了 parent_id 就用它；否则优先「核心功能模块」，再退第一个大类；
    一个都没有就建一个「核心功能模块」大类兜底。
    """
    if parent_id:
        node = KnowledgeNode.objects.filter(id=parent_id, project=project, kind='domain').first()
        if node:
            return node
    node = KnowledgeNode.objects.filter(project=project, kind='domain', name='核心功能模块').first()
    if node:
        return node
    node = (KnowledgeNode.objects.filter(project=project, kind='domain', status='confirmed')
            .order_by('order', 'id').first())
    if node:
        return node
    return KnowledgeNode.objects.create(
        project=project, parent=None, kind='domain', name='核心功能模块',
        content='', status='confirmed', order=0,
    )


# ---------------- AI 对比 ----------------

COMPARE_TEMPLATE = """{note}下面是同一个功能的「现有需求」和「新采集需求」。
判断两者关系：same（实质相同）/ append（新增是对现有的补充）/ conflict（两者矛盾）。
只输出 JSON：{"relation":"conflict","reason":"一句话说明差异","conflicts":[{"old":"旧说法","new":"新说法"}]}

【现有需求】
{old}

【新采集需求】
{new}"""


def ai_compare(old, new, note=''):
    """返回 (relation, reason, conflicts)。AI 失败时保守当作 conflict，交给人判断。"""
    from .extract import _get_config, _call_ai, _parse_json

    cfg = _get_config()
    if not cfg:
        return 'conflict', '（未配置 AI 模型，无法自动对比，请人工判断）', []

    note_block = ''
    if (note or '').strip():
        note_block = ('【本次版本的人工备注 —— 可用来判断哪些才算真正变化】\n'
                      + note.strip()[:800] + '\n\n')
    prompt = COMPARE_TEMPLATE.format(note=note_block, old=(old or '')[:4000], new=(new or '')[:4000])
    try:
        out = _call_ai(cfg, prompt, system='你是需求比对专家，只输出 JSON。')
        data = _parse_json(out)
    except Exception as e:
        logger.warning('[proposal] AI 对比失败: %s', str(e)[:160])
        return 'conflict', '（AI 对比失败，保守标记为疑似冲突，请人工判断）', []

    rel = str(data.get('relation') or '').strip().lower()
    if rel not in ('same', 'append', 'conflict'):
        rel = 'conflict'
    reason = str(data.get('reason') or '')[:500]
    conflicts = data.get('conflicts') or []
    if not isinstance(conflicts, list):
        conflicts = []
    return rel, reason, conflicts[:20]


def _was_kept_before(target_node, new_hash):
    """忽略记忆：同一功能点 + 同一份新内容，之前选过「保留旧的」就不再问"""
    if not target_node or not new_hash:
        return False
    return KnowledgeProposalItem.objects.filter(
        target_node=target_node,
        new_content_hash=new_hash,
        decision__in=('keep', 'ignored'),
    ).exists()


# ---------------- 生成提议 ----------------

def build_proposal(collection, selected):
    """按用户勾选/归类的结果生成提议（一行 = 一个顶层分组）。

    selected: [{name, feature_id, parent_id}]
      - name：顶层分组名（没有分组的独立画布用画布名）
      - feature_id：已有模块 id；为空 = 新建模块，模块名就是 name
      - parent_id：新建模块时挂到哪个大类（空则默认「核心功能模块」）
    """
    note = (getattr(collection, 'note', '') or '').strip()
    from .extract import generate_summary
    from .classify import _group_key

    proposal = KnowledgeProposal.objects.create(
        collection=collection, project=collection.project, status='pending',
    )

    # 采集到的画布按顶层分组归档
    page_by_group = {}
    for p in (collection.collected_pages or []):
        g = _group_key(p) or (p.get('name') or '').strip()
        page_by_group.setdefault(g, []).append(p)

    stats = {'new': 0, 'same': 0, 'append': 0, 'conflict': 0, 'ignored': 0}

    def _make_item(target, parent, name, pages, is_new_module=False):
        """target 为 None 表示新增（模块或功能点）"""
        shim = SimpleNamespace(name=name)
        new_doc = generate_summary(shim, pages, note=note)
        if not new_doc:
            new_doc = chr(10).join(f"- {p.get('name')}：{(p.get('content') or '')[:500]}" for p in pages)
        new_hash = content_hash(new_doc)

        old = ((target.summary if target else '') or '').strip()

        if not target:
            change = 'new'
            reason = '知识库里还没有这个模块，建议新建' if is_new_module else '知识库里还没有这个功能点'
            conflicts = []
        elif not old:
            change, reason, conflicts = 'append', '该模块还没有需求文档，建议写入', []
        elif content_hash(old) == new_hash:
            change, reason, conflicts = 'same', '与现有文档一致，无需处理', []
        elif _was_kept_before(target, new_hash):
            change, reason, conflicts = 'same', '你之前选择保留旧内容，本次不再提示', []
            stats['ignored'] += 1
        else:
            rel, reason, conflicts = ai_compare(old, new_doc, note=note)
            change = 'append' if rel == 'append' else ('same' if rel == 'same' else 'conflict')

        KnowledgeProposalItem.objects.create(
            proposal=proposal,
            target_node=target,
            target_name=name,
            parent_node=parent,
            change_type=change,
            old_content=old,
            new_content=new_doc,
            ai_reason=reason,
            conflicts=conflicts,
            new_content_hash=new_hash,
        )
        if change in stats:
            stats[change] += 1

    by_module = {}    # 已有模块 id -> 画布
    new_groups = []   # 待新建模块
    for s in (selected or []):
        gname = (s.get('name') or '').strip()
        pages = page_by_group.get(gname) or []
        if not pages:
            continue
        fid = s.get('feature_id')
        if fid:
            by_module.setdefault(int(fid), []).extend(pages)
        else:
            new_groups.append({'name': gname, 'parent_id': s.get('parent_id'), 'pages': pages})

    # 归到已有模块
    for fid, pages in by_module.items():
        node = KnowledgeNode.objects.filter(id=fid, project=collection.project).first()
        if not node:
            continue
        _make_item(node, node.parent, node.name, pages)

    # 新建模块（挂到指定大类）；如果同名模块已存在就直接归过去，避免建重复
    for ng in new_groups:
        existing = KnowledgeNode.objects.filter(
            project=collection.project, kind='module', name=ng['name'], status='confirmed',
        ).first()
        if existing:
            _make_item(existing, existing.parent, existing.name, ng['pages'])
            continue
        parent = _resolve_module_parent(collection.project, ng.get('parent_id'))
        _make_item(None, parent, ng['name'], ng['pages'], is_new_module=True)

    proposal.stats = stats
    proposal.save(update_fields=['stats'])

    collection.status = 'proposed'
    collection.save(update_fields=['status'])
    return proposal


# ---------------- 应用提议 ----------------

def apply_proposal(proposal, decisions=None, user=None):
    """按决策写入知识库。decisions: [{id, decision, merged_content?}]"""
    decision_map = {}
    for d in (decisions or []):
        try:
            decision_map[int(d.get('id'))] = d
        except (TypeError, ValueError):
            continue

    created = updated = kept = 0
    collection = proposal.collection
    now = timezone.now()

    for item in proposal.items.all():
        d = decision_map.get(item.id) or {}
        decision = d.get('decision') or item.decision
        merged = (d.get('merged_content') or item.merged_content or '').strip()

        if decision in ('keep', 'ignored') or item.change_type == 'same':
            item.decision = 'keep' if item.change_type != 'same' else 'ignored'
            item.decided_by = user
            item.decided_at = now
            item.save(update_fields=['decision', 'decided_by', 'decided_at'])
            kept += 1
            continue

        final_text = merged if (decision == 'merged' and merged) else item.new_content
        if not final_text.strip():
            continue

        if item.target_node_id:
            node = item.target_node
            node.summary = final_text
            node.content_hash = content_hash(final_text)
            node.source_type = collection.source_type
            node.source_url = collection.source_url
            node.source_version = collection.source_version
            node.collected_at = collection.created_at
            node.save(update_fields=['summary', 'content_hash', 'source_type',
                                     'source_url', 'source_version', 'collected_at'])
            updated += 1
        else:
            parent = item.parent_node or _get_pending_parent(collection.project_id)
            # 挂在大类（domain）下面的 = 新模块；挂在模块下面的 = 功能点
            node_kind = 'module' if parent.kind == 'domain' else 'feature'
            KnowledgeNode.objects.create(
                project=collection.project, parent=parent, kind=node_kind,
                name=(item.target_name or '未命名功能')[:200],
                content='', summary=final_text, status='confirmed',
                content_hash=content_hash(final_text),
                source_type=collection.source_type, source_url=collection.source_url,
                source_version=collection.source_version, collected_at=collection.created_at,
            )
            created += 1

        item.decision = 'merged' if (decision == 'merged' and merged) else 'accept'
        item.decided_by = user
        item.decided_at = now
        if merged:
            item.merged_content = merged
        item.save(update_fields=['decision', 'decided_by', 'decided_at', 'merged_content'])

    proposal.status = 'applied'
    proposal.applied_at = now
    proposal.save(update_fields=['status', 'applied_at'])
    collection.status = 'applied'
    collection.save(update_fields=['status'])

    return {'created': created, 'updated': updated, 'kept': kept}
