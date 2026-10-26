"""知识采集批次 / 提议 相关接口。

流程：采集（落批次）→ 归类 → 生成提议 → 人工审核 → 应用写入知识库
采集和整理阶段都不改知识库。
"""
import json
import logging
import os
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .classify import classify_pages, get_candidates, get_domains, _group_key
from .collector import collect
from .models import KnowledgeCollection, KnowledgeProposal, KnowledgeProposalItem
from .proposal import build_proposal, apply_proposal
from .vision import recognize_pages

logger = logging.getLogger(__name__)

# 采集快照保留天数
SNAPSHOT_TTL_DAYS = 15


def _serialize_item(item):
    if item.change_type == 'new':
        ct_display = '新增模块' if (item.parent_node and item.parent_node.kind == 'domain') else '新增功能点'
    else:
        ct_display = item.get_change_type_display()
    return {
        'id': item.id,
        'change_type': item.change_type,
        'change_type_display': ct_display,
        'target_node': item.target_node_id,
        'target_name': item.target_name,
        'parent_node': item.parent_node_id,
        'parent_name': item.parent_node.name if item.parent_node else '',
        'old_content': item.old_content,
        'new_content': item.new_content,
        'merged_content': item.merged_content,
        'ai_reason': item.ai_reason,
        'conflicts': item.conflicts,
        'decision': item.decision,
        'decision_display': item.get_decision_display(),
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_collection(request):
    """采集 + 视觉识别 + AI 归类。结果落到采集批次，不改知识库。"""
    project_id = request.data.get('project')
    url = (request.data.get('url') or '').strip()
    source_type = request.data.get('source_type') or 'modao'

    if not project_id:
        return Response({'error': '需要 project'}, status=400)
    if not url:
        return Response({'error': '请填写链接地址'}, status=400)
    if source_type not in ('axure', 'modao'):
        return Response({'error': 'source_type 仅支持 axure / modao'}, status=400)

    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return Response({'error': 'project 不合法'}, status=400)

    # 顺带清理过期快照（不依赖 Celery Beat 也能保持磁盘干净）
    try:
        from .storage import cleanup_expired_snapshots
        cleanup_expired_snapshots()
    except Exception as e:
        logger.warning('[collection] 清理过期快照失败: %s', str(e)[:160])

    # 先建批次（采集要用批次目录）
    col = KnowledgeCollection.objects.create(
        project_id=pid,
        source_type=source_type,
        source_url=url,
        note=(request.data.get('note') or '')[:2000],
        status='collected',
        created_by=request.user if request.user.is_authenticated else None,
        expires_at=timezone.now() + timedelta(days=SNAPSHOT_TTL_DAYS),
    )

    try:
        data = collect(
            url,
            source_type=source_type,
            cookie=request.data.get('cookie') or '',
            email=request.data.get('email') or '',
            password=request.data.get('password') or '',
            run_id=col.id,
        )
    except Exception as e:
        col.status = 'discarded'
        col.save(update_fields=['status'])
        return Response({'error': str(e)[:500]}, status=500)

    if data.get('error'):
        col.status = 'discarded'
        col.save(update_fields=['status'])
        return Response({'error': data['error'], 'skipped_backend': data.get('skipped_backend') or []}, status=400)

    pages = data.get('collected') or []
    if not pages:
        col.status = 'discarded'
        col.save(update_fields=['status'])
        return Response({'error': '没有采集到任何画布'}, status=400)

    # 视觉识别
    try:
        recognized = recognize_pages(pages)
    except Exception as e:
        col.status = 'discarded'
        col.save(update_fields=['status'])
        return Response({'error': f'视觉识别失败: {str(e)[:400]}'}, status=500)

    valid_pages = []
    for p, r in zip(pages, recognized):
        content = (r or {}).get('content') or ''
        if content.strip():
            valid_pages.append({
                'name': p.get('name'),
                'content': content,
                'screenshot': p.get('screenshot') or '',
                'parents': p.get('parents') or [],
            })
    if not valid_pages:
        col.status = 'discarded'
        col.save(update_fields=['status'])
        return Response({'error': '识别后没有有效需求内容'}, status=400)

    # AI 归类（按顶层分组，一行 = 一个分组）
    try:
        groups = classify_pages(pid, valid_pages)
        candidates = get_candidates(pid, valid_pages)
        domains = get_domains(pid)
    except Exception as e:
        return Response({'error': f'归类失败: {str(e)[:400]}'}, status=500)

    # 回写批次
    col.source_version = (data.get('source_title') or '')[:100]
    col.page_count = len(valid_pages)
    col.skipped_backend = data.get('skipped_backend') or []
    col.snapshot_dir = f'knowledge_collect/{col.id}'
    col.collected_pages = valid_pages
    col.save(update_fields=['source_version', 'page_count', 'skipped_backend',
                            'snapshot_dir', 'collected_pages'])

    # 平铺画布（带上所属顶层分组，供生成提议时按分组取内容）
    out_pages = []
    for p in valid_pages:
        out_pages.append({'name': p['name'], 'group': _group_key(p)})

    return Response({
        'collection_id': col.id,
        'source_version': col.source_version,
        'note': col.note,
        'groups': groups,          # 归类行：一行 = 一个顶层分组
        'pages': out_pages,        # 平铺画布（带分组）
        'candidates': candidates,  # 全部已有模块
        'domains': domains,        # 全部大类（新建模块时选归属）
        'skipped_backend': col.skipped_backend,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_proposal(request, collection_id):
    """按用户勾选/调整后的归类结果生成提议（仍不写知识库）"""
    col = KnowledgeCollection.objects.filter(id=collection_id).first()
    if not col:
        return Response({'error': '采集批次不存在'}, status=404)

    selected = request.data.get('selected') or []
    if not isinstance(selected, list) or not selected:
        return Response({'error': '需要 selected（勾选的画布与归属）'}, status=400)

    # 已生成过就复用（避免重复点）
    if hasattr(col, 'proposal'):
        col.proposal.delete()

    try:
        proposal = build_proposal(col, selected)
    except Exception as e:
        logger.error('[collection] 生成提议失败: %s', str(e)[:400])
        return Response({'error': f'生成提议失败: {str(e)[:400]}'}, status=500)

    return Response({'proposal_id': proposal.id, 'stats': proposal.stats})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_proposal(request, proposal_id):
    """提议明细：按变更类型分组返回"""
    proposal = KnowledgeProposal.objects.filter(id=proposal_id).first()
    if not proposal:
        return Response({'error': '提议不存在'}, status=404)

    items = [_serialize_item(i) for i in proposal.items.all()]
    col = proposal.collection
    return Response({
        'id': proposal.id,
        'status': proposal.status,
        'stats': proposal.stats,
        'collection_id': col.id,
        'source': {
            'source_type': col.source_type,
            'url': col.source_url,
            'version': col.source_version,
            'collected_at': col.created_at,
            'page_count': col.page_count,
        },
        'items': items,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decide_proposal(request, proposal_id):
    """提交逐条决策（可带人工改写的内容）"""
    proposal = KnowledgeProposal.objects.filter(id=proposal_id).first()
    if not proposal:
        return Response({'error': '提议不存在'}, status=404)

    items = request.data.get('items') or []
    if not isinstance(items, list):
        return Response({'error': 'items 必须是数组'}, status=400)

    now = timezone.now()
    updated = 0
    for d in items:
        try:
            item = proposal.items.get(id=int(d.get('id')))
        except (TypeError, ValueError, KnowledgeProposalItem.DoesNotExist):
            continue
        decision = d.get('decision')
        if decision not in ('accept', 'keep', 'merged', 'ignored', 'pending'):
            continue
        item.decision = decision
        if d.get('merged_content') is not None:
            item.merged_content = d.get('merged_content') or ''
        item.decided_by = request.user if request.user.is_authenticated else None
        item.decided_at = now
        item.save(update_fields=['decision', 'merged_content', 'decided_by', 'decided_at'])
        updated += 1

    return Response({'updated': updated})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_proposal_view(request, proposal_id):
    """把采纳的内容写入知识库"""
    proposal = KnowledgeProposal.objects.filter(id=proposal_id).first()
    if not proposal:
        return Response({'error': '提议不存在'}, status=404)

    decisions = request.data.get('items') or []
    try:
        result = apply_proposal(proposal, decisions=decisions, user=request.user)
    except Exception as e:
        logger.error('[collection] 应用提议失败: %s', str(e)[:400])
        return Response({'error': f'应用失败: {str(e)[:400]}'}, status=500)

    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_collection(request, collection_id):
    """采集批次详情（含原始快照信息，便于追溯与重放）"""
    col = KnowledgeCollection.objects.filter(id=collection_id).first()
    if not col:
        return Response({'error': '采集批次不存在'}, status=404)
    return Response({
        'id': col.id,
        'status': col.status,
        'source_type': col.source_type,
        'url': col.source_url,
        'version': col.source_version,
        'page_count': col.page_count,
        'skipped_backend': col.skipped_backend,
        'snapshot_dir': col.snapshot_dir,
        'expires_at': col.expires_at,
        'created_at': col.created_at,
        'pages': [
            {'name': p.get('name'), 'screenshot': p.get('screenshot')}
            for p in (col.collected_pages or [])
        ],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_coverage_view(request):
    """检查一份需求在知识库里的覆盖情况（哪些功能还没文档、哪些有待确认变更）"""
    from .knowledge_context import check_coverage

    project_id = request.data.get('project')
    text = request.data.get('text') or ''
    if not project_id:
        return Response({'error': '需要 project'}, status=400)
    if not text.strip():
        return Response({'error': '需要 text（需求内容）'}, status=400)

    try:
        result = check_coverage(int(project_id), text)
    except Exception as e:
        logger.warning('[collection] 覆盖检查失败: %s', str(e)[:200])
        return Response({'error': str(e)[:400]}, status=500)
    return Response(result)
