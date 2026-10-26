from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import KnowledgeNode, KnowledgeChangeLog
from .extract import classify_rule_types
from .serializers import (
    KnowledgeNodeSerializer,
    KnowledgeNodeFlatSerializer,
    KnowledgeChangeLogSerializer,
)


def _log(project_id, target_type, target_id, target_name, action, operator, detail=''):
    if not project_id:
        return
    KnowledgeChangeLog.objects.create(
        project_id=project_id,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name[:200],
        action=action,
        operator=operator if operator.is_authenticated else None,
        detail=detail,
    )


class KnowledgeNodeViewSet(viewsets.ModelViewSet):
    """需求知识库节点 CRUD + 树"""
    serializer_class = KnowledgeNodeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = KnowledgeNode.objects.all()
        project_id = self.request.query_params.get('project')
        parent = self.request.query_params.get('parent')
        kind = self.request.query_params.get('kind')
        if project_id:
            qs = qs.filter(project_id=project_id)
        if parent:
            qs = qs.filter(parent_id=parent)
        elif parent == 'root':
            qs = qs.filter(parent__isnull=True)
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def get_serializer_class(self):
        if self.action == 'list' and self.request.query_params.get('flat') == '1':
            return KnowledgeNodeFlatSerializer
        return KnowledgeNodeSerializer

    @action(detail=False, methods=['post'])
    def batch(self, request):
        """批量操作：confirm（草稿转已确认）/ delete（删除）"""
        action = request.data.get('action')
        ids = request.data.get('ids') or []
        project_id = request.data.get('project')
        if not isinstance(ids, list) or not ids:
            return Response({'error': '需要 ids 列表'}, status=400)
        if action not in ('confirm', 'delete'):
            return Response({'error': 'action 仅支持 confirm / delete'}, status=400)

        qs = KnowledgeNode.objects.filter(id__in=ids)
        if project_id:
            qs = qs.filter(project_id=project_id)

        if action == 'confirm':
            updated = qs.update(status='confirmed')
            for node in KnowledgeNode.objects.filter(id__in=ids, project_id=project_id):
                _log(node.project_id, node.kind, node.id, node.name, 'update', self.request.user, '批量确认')
            return Response({'updated': updated})
        deleted, _ = qs.delete()
        for node_id in ids:
            _log(project_id, 'node', node_id, '', 'delete', self.request.user, '批量删除')
        return Response({'deleted': deleted})

    @action(detail=False, methods=['post'])
    def classify_rules(self, request):
        """AI 批量补全规则分类（rule_type 为空的业务规则）"""
        project_id = request.data.get('project')
        if not project_id:
            return Response({'error': '需要 project'}, status=400)
        try:
            result = classify_rule_types(int(project_id))
            return Response(result)
        except Exception as e:
            return Response({'error': str(e)[:500]}, status=500)

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """返回项目完整知识树（根节点列表）"""
        project_id = request.query_params.get('project')
        roots = KnowledgeNode.objects.filter(project_id=project_id, parent__isnull=True).order_by('order', 'id')
        data = KnowledgeNodeSerializer(roots, many=True, context={'request': request}).data
        return Response(data)

    def perform_create(self, serializer):
        # 子节点自动继承父节点的项目
        parent = serializer.validated_data.get('parent')
        if parent and not serializer.validated_data.get('project'):
            serializer.validated_data['project_id'] = parent.project_id
        instance = serializer.save()
        _log(instance.project_id, instance.kind, instance.id, instance.name, 'create', self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        _log(instance.project_id, instance.kind, instance.id, instance.name, 'update', self.request.user)

    def perform_destroy(self, instance):
        _log(instance.project_id, instance.kind, instance.id, instance.name, 'delete', self.request.user)
        instance.delete()


class KnowledgeChangeLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KnowledgeChangeLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = KnowledgeChangeLog.objects.all()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs
