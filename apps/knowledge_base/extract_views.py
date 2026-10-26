from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

import logging

logger = logging.getLogger(__name__)

from .extract import extract_nodes


def _collect_subtree_pages(node):
    """把节点整棵子树里「有内容」的节点收成 summary 的输入。

    三级功能点下面的所有子功能点、业务规则、页面说明都算在内。
    name 用从当前节点往下的路径，保留层级关系。
    """
    pages = []

    def walk(n, path):
        for c in n.children.all().order_by('order', 'id'):
            p = path + [c.name]
            has_text = (c.content or '').strip()
            if has_text:
                pages.append({'name': ' / '.join(p), 'content': c.content})
            elif c.kind in ('feature', 'module', 'page'):
                # 思维导图导入的节点只有名字、没有描述，也要列进来（至少形成功能清单）
                pages.append({'name': ' / '.join(p), 'content': ''})
            walk(c, p)

    walk(node, [])
    return pages


def _refresh_summary(parent_id):
    """抽取完成后，按该功能点「整棵子树」的累积内容生成/刷新需求说明"""
    from .models import KnowledgeNode
    from .extract import generate_summary
    parent = KnowledgeNode.objects.filter(id=parent_id).first()
    if not parent:
        return
    pages = _collect_subtree_pages(parent)
    if not pages:
        return
    try:
        s = generate_summary(parent, pages)
        if s:
            parent.summary = s
            parent.save(update_fields=['summary'])
    except Exception as e:
        logger.warning('生成需求说明失败 [%s]: %s', parent.name, str(e)[:160])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extract_knowledge(request):
    """AI 抽取：把采集到的页面文本抽取成知识节点，挂到目标节点下"""
    project_id = request.data.get('project_id')
    parent_id = request.data.get('parent_id')
    pages = request.data.get('pages') or []

    if not project_id or not parent_id:
        return Response({'error': '需要 project_id 和 parent_id'}, status=400)
    if not isinstance(pages, list) or not pages:
        return Response({'error': '需要 pages（采集到的页面列表）'}, status=400)

    try:
        result = extract_nodes(int(project_id), int(parent_id), pages)
        _refresh_summary(int(parent_id))
        return Response(result)
    except Exception as e:
        return Response({'error': str(e)[:500]}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def classify_link(request):
    """把采集到的画布归类到已有功能点（用于一版原型横跨多功能的场景）"""
    from .classify import classify_pages, get_candidates

    project_id = request.data.get('project_id')
    pages = request.data.get('pages') or []
    if not project_id:
        return Response({'error': '需要 project_id'}, status=400)
    if not isinstance(pages, list) or not pages:
        return Response({'error': '需要 pages（采集到的页面列表）'}, status=400)
    try:
        pid = int(project_id)
        assignments = classify_pages(pid, pages)
        candidates = get_candidates(pid, pages)
        return Response({'assignments': assignments, 'candidates': candidates})
    except Exception as e:
        return Response({'error': str(e)[:500]}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extract_grouped(request):
    """按功能点分组抽取知识节点。

    请求：{ project_id, groups: [{ parent_id: 功能点ID 或 null(待归类), pages: [...] }] }
    """
    from .extract import extract_nodes
    from .classify import get_or_create_pending_node

    project_id = request.data.get('project_id')
    groups = request.data.get('groups') or []
    if not project_id:
        return Response({'error': '需要 project_id'}, status=400)
    if not isinstance(groups, list) or not groups:
        return Response({'error': '需要 groups 分组数据'}, status=400)

    try:
        pid = int(project_id)
        pending_node = None
        total = 0
        details = []
        for g in groups:
            pages = [p for p in (g.get('pages') or []) if (p.get('content') or p.get('text') or '').strip()]
            if not pages:
                continue
            parent_id = g.get('parent_id')
            if not parent_id:
                if pending_node is None:
                    pending_node = get_or_create_pending_node(pid)
                parent_id = pending_node.id
            r = extract_nodes(pid, int(parent_id), pages)
            _refresh_summary(int(parent_id))
            total += r.get('count', 0)
            details.append({'parent_id': parent_id, 'count': r.get('count', 0)})
        return Response({'count': total, 'details': details})
    except Exception as e:
        return Response({'error': str(e)[:500]}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_summary(request):
    """按节点下已有的规则/页面内容，重新生成「需求说明」"""
    from .models import KnowledgeNode
    from .extract import generate_summary

    node_id = request.data.get('node_id')
    node = KnowledgeNode.objects.filter(id=node_id).first()
    if not node:
        return Response({'error': '节点不存在'}, status=404)

    pages = _collect_subtree_pages(node)
    if not pages:
        return Response({'error': '该功能点下面还没有任何内容，无法生成需求说明'}, status=400)

    try:
        s = generate_summary(node, pages)
    except Exception as e:
        return Response({'error': str(e)[:500]}, status=500)
    if not s:
        return Response({'error': '生成失败'}, status=500)

    node.summary = s
    node.save(update_fields=['summary'])
    return Response({'summary': s, 'node_id': node.id})
