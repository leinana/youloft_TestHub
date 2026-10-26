from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .collector import collect
from .vision import recognize_pages


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def collect_link(request):
    """采集 Axure / 墨刀 原型链接，返回页面目录 + 文本 + 截图路径"""
    url = (request.data.get('url') or '').strip()
    source_type = request.data.get('source_type') or 'axure'
    page_filter = request.data.get('page_filter') or ''
    cookie = request.data.get('cookie') or ''
    email = request.data.get('email') or ''
    password = request.data.get('password') or ''
    raw_max = request.data.get('max_pages')
    max_pages = None
    if raw_max:
        try:
            max_pages = int(raw_max)
        except (TypeError, ValueError):
            max_pages = None

    if not url:
        return Response({'error': '请填写链接地址'}, status=400)
    if source_type not in ('axure', 'modao'):
        return Response({'error': 'source_type 仅支持 axure / modao'}, status=400)

    try:
        data = collect(url, source_type=source_type, page_filter=page_filter, cookie=cookie, email=email, password=password, max_pages=max_pages)
        return Response(data)
    except Exception as e:
        return Response({'error': str(e)[:500]}, status=500)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recognize_link(request):
    """对采集到的页面截图做视觉识别，提取有效需求内容"""
    pages = request.data.get('pages') or []
    if not isinstance(pages, list) or not pages:
        return Response({'error': '需要 pages（采集到的页面列表）'}, status=400)
    try:
        result = recognize_pages(pages)
        return Response({'pages': result})
    except Exception as e:
        return Response({'error': str(e)[:500]}, status=500)
