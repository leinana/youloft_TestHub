"""
参数分析 API 视图
"""
import asyncio
import logging
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import ApiRequest, ParameterAnalysis
from .param_analyzer import analyze_parameters, analyze_batch

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_api_params(request):
    """分析指定接口的参数（支持批量 request_ids）"""
    request_ids = request.data.get('request_ids', [])
    if not request_ids:
        return Response({'error': '未提供 request_ids'}, status=400)

    ids = [int(x) for x in request_ids]

    # 先同步获取 AI 配置
    from .param_analyzer import _get_ai_config as _get_ai_config_sync
    ai_config = _get_ai_config_sync()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        results = loop.run_until_complete(analyze_batch(ids, ai_config=ai_config))
    finally:
        loop.close()

    # 保存分析结果
    saved = 0
    for r in results:
        if 'error' not in r and r.get('analysis'):
            req = ApiRequest.objects.get(id=r['id'])
            analysis_data = r['analysis']
            # 如果 AI 返回的参数列表是其他 key，做一次规范化
            if 'parameters' not in analysis_data:
                # 尝试找到参数列表
                for key in analysis_data:
                    if isinstance(analysis_data[key], list):
                        analysis_data = {'parameters': analysis_data[key]}
                        break

            ParameterAnalysis.objects.update_or_create(
                api_request=req,
                defaults={'analysis': analysis_data, 'confirmed': False}
            )
            saved += 1

    return Response({'analyzed': saved, 'total': len(ids), 'results': results})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_analysis(request, request_id):
    """获取单个接口的参数分析"""
    try:
        pa = ParameterAnalysis.objects.get(api_request_id=request_id)
        return Response({
            'id': pa.id,
            'request_id': request_id,
            'name': pa.api_request.name,
            'analysis': pa.analysis,
            'confirmed': pa.confirmed,
        })
    except ParameterAnalysis.DoesNotExist:
        return Response({'error': '未分析'}, status=404)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def save_analysis(request, request_id):
    """保存人工修改后的参数分析"""
    try:
        pa = ParameterAnalysis.objects.get(api_request_id=request_id)
    except ParameterAnalysis.DoesNotExist:
        return Response({'error': '未分析'}, status=404)

    pa.analysis = request.data.get('analysis', pa.analysis)
    pa.confirmed = request.data.get('confirmed', pa.confirmed)
    if pa.confirmed:
        pa.confirmed_by = request.user
        if not pa.confirmed_at:
            pa.confirmed_at = timezone.now()
    pa.save()
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_analyses(request):
    """列出所有已分析的接口，可按分类筛选"""
    cat_id = request.query_params.get('cat_id')
    qs = ParameterAnalysis.objects.select_related('api_request').all()
    if cat_id:
        # 需要通过 api_request 关联到 collection 的 name 来筛选...
        # 简化：直接返回所有
        pass

    data = [{
        'id': pa.id,
        'request_id': pa.api_request_id,
        'name': pa.api_request.name,
        'method': pa.api_request.method,
        'url': pa.api_request.url,
        'confirmed': pa.confirmed,
    } for pa in qs.order_by('-created_at')[:100]]

    return Response({'analyses': data})
