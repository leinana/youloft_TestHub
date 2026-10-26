"""
YApi 集成 — API 视图
"""
import asyncio
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.db import models
from urllib.parse import urlsplit
import re

from .models import ApiProject, Environment, YApiConnection, YApiSyncLog
from .yapi_sync import YApiSyncService
from .serializers import YApiConnectionSerializer, YApiSyncLogSerializer


class YApiConnectionViewSet(viewsets.ModelViewSet):
    """YApi 连接管理"""
    queryset = YApiConnection.objects.all()
    serializer_class = YApiConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return YApiConnection.objects.all()
        accessible_projects = ApiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        )
        return YApiConnection.objects.filter(project__in=accessible_projects).distinct()

    def _assert_project_access(self, project):
        user = self.request.user
        if user.is_staff:
            return
        if not ApiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user), id=project.id
        ).exists():
            raise PermissionDenied('无权配置该项目')

    def perform_create(self, serializer):
        self._assert_project_access(serializer.validated_data['project'])
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        project = serializer.validated_data.get('project', serializer.instance.project)
        self._assert_project_access(project)
        serializer.save()

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """执行同步，可传 cat_ids 和 path_prefixes 筛选"""
        conn = self.get_object()
        cat_ids = request.data.get('cat_ids', None)
        path_prefixes = request.data.get('path_prefixes', None)
        service = YApiSyncService(conn)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(service.sync(cat_ids=cat_ids, path_prefixes=path_prefixes))
            loop.close()
            return Response(result)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['get'])
    def categories(self, request, pk=None):
        """获取 YApi 分类 + 接口列表（按版本分组可预览）"""
        conn = self.get_object()
        from .yapi_client import YApiClient
        client = YApiClient(
            base_url=conn.yapi_url, token=conn.yapi_token,
            project_id=conn.yapi_project_id, uid=conn.yapi_uid,
        )
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cats = loop.run_until_complete(client.get_cat_menu())
            interfaces = loop.run_until_complete(client.fetch_all_interfaces())
            loop.close()

            from collections import defaultdict
            cat_map = {c.get('_id'): c.get('name', '') for c in cats}
            grouped = defaultdict(list)

            for i in interfaces:
                cid = i.get('catid', 0)
                grouped[cid].append({
                    'id': i.get('_id'),
                    'title': i.get('title', ''),
                    'method': i.get('method', 'GET'),
                    'path': i.get('path', ''),
                })

            cat_list = []
            for c in cats:
                cid = c.get('_id', 0)
                items = grouped.get(cid, [])
                if items:
                    cat_list.append({
                        'catid': cid,
                        'name': c.get('name', '未分类'),
                        'count': len(items),
                        'interfaces': items,
                    })

            return Response({'categories': cat_list, 'total_interfaces': len(interfaces)})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """获取同步日志"""
        conn = self.get_object()
        logs = conn.sync_logs.all().order_by('-created_at')[:20]
        serializer = YApiSyncLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def fix_base_url(self, request, pk=None):
        """把项目接口统一为 {{base_url}}/相对路径。

        - 相对路径补全 base_url
        - 与当前环境同域名的绝对 URL 转为 base_url 相对路径
        - 其他域名和自定义变量 URL 保持不变
        """
        conn = self.get_object()
        from .models import ApiRequest
        env = Environment.objects.filter(project=conn.project, is_active=True).first()
        base_url = str((env.variables or {}).get('base_url') or '') if env else ''
        base_host = urlsplit(base_url).netloc.lower()
        updated = 0
        skipped = 0
        for req in ApiRequest.objects.filter(collection__project=conn.project):
            raw = (req.url or '').strip()
            if not raw or '{{' in raw:
                skipped += 1
                continue

            query = ''
            if raw.startswith(('http://', 'https://')):
                parsed = urlsplit(raw)
                if base_host and parsed.netloc.lower() != base_host:
                    skipped += 1
                    continue
                path = parsed.path or '/'
                query = f'?{parsed.query}' if parsed.query else ''
            else:
                path = raw

            path = re.sub(r'/{2,}', '/', path)
            if not path.startswith('/'):
                path = '/' + path
            normalized = '{{base_url}}' + path + query
            if normalized != raw:
                req.url = normalized
                req.save(update_fields=['url'])
                updated += 1
            else:
                skipped += 1
        return Response({'updated': updated, 'skipped': skipped, 'base_url': base_url})

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """预览拉取的接口（不导入）"""
        conn = self.get_object()
        from .yapi_client import YApiClient
        client = YApiClient(
            base_url=conn.yapi_url,
            token=conn.yapi_token,
            project_id=conn.yapi_project_id,
            uid=conn.yapi_uid,
        )
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            interfaces = loop.run_until_complete(client.fetch_all_with_details())
            loop.close()
            summary = [{
                'id': i.get('_id'),
                'title': i.get('title', ''),
                'path': i.get('path', ''),
                'method': i.get('method', 'GET'),
                'category': i.get('_cat_name', '未分类'),
            } for i in interfaces]
            return Response({
                'total': len(summary),
                'interfaces': summary,
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# touch-reload-marker
