"""
接口测试 AI 提示词配置 API
"""
import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import ApiPromptConfig
from .serializers import ApiPromptConfigSerializer
from .case_generator import DEFAULT_TESTCASE_WRITER_PROMPT, DEFAULT_TEST_EXECUTION_PROMPT

logger = logging.getLogger(__name__)

# 各提示词类型的内置默认内容（未配置时回退 / 恢复默认用）
DEFAULT_PROMPTS = {
    'api_testcase_writer': DEFAULT_TESTCASE_WRITER_PROMPT,
    'api_test_execution': DEFAULT_TEST_EXECUTION_PROMPT,
}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def prompt_configs(request):
    """提示词配置列表 / 新建"""
    if request.method == 'GET':
        prompt_type = request.query_params.get('prompt_type')
        qs = ApiPromptConfig.objects.all()
        if prompt_type:
            qs = qs.filter(prompt_type=prompt_type)
        data = ApiPromptConfigSerializer(qs, many=True).data
        return Response({'configs': data, 'total': len(data)})

    # POST 新建
    data = dict(request.data)
    if data.get('is_active'):
        pt = data.get('prompt_type')
        if pt:
            ApiPromptConfig.objects.filter(prompt_type=pt, is_active=True).update(is_active=False)
    serializer = ApiPromptConfigSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    serializer.save(created_by=request.user)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_prompt_config(request, config_id):
    """更新提示词配置"""
    try:
        cfg = ApiPromptConfig.objects.get(id=config_id)
    except ApiPromptConfig.DoesNotExist:
        return Response({'error': '配置不存在'}, status=404)

    data = dict(request.data)
    # 同类型同时只能有一个激活
    if data.get('is_active') is True:
        ApiPromptConfig.objects.filter(
            prompt_type=cfg.prompt_type, is_active=True
        ).exclude(id=cfg.id).update(is_active=False)

    serializer = ApiPromptConfigSerializer(cfg, data=data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_prompt_config(request, config_id):
    """删除提示词配置"""
    ApiPromptConfig.objects.filter(id=config_id).delete()
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_default_prompt(request):
    """获取某类型的内置默认提示词（用于恢复默认）"""
    prompt_type = request.query_params.get('prompt_type', 'api_testcase_writer')
    content = DEFAULT_PROMPTS.get(prompt_type)
    if content is None:
        return Response({'error': '未知提示词类型'}, status=400)
    return Response({'prompt_type': prompt_type, 'content': content})
