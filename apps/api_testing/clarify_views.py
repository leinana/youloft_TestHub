"""
Interface clarification API - AI asks questions, human confirms, then cases are generated.
"""
import asyncio
import json
import logging
import re
import httpx
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ApiRequest, ApiClarification, ParameterAnalysis
from .param_analyzer import _get_ai_config

logger = logging.getLogger(__name__)


def _build_clarify_prompt(api_request: dict, analysis: dict) -> str:
    name = api_request.get('name', 'unknown')
    method = api_request.get('method', 'GET')
    url = api_request.get('url', '')
    params = analysis.get('parameters', [])
    suggestions = analysis.get('suggestions', [])
    param_text = json.dumps(params, ensure_ascii=False, indent=2) if params else 'none'
    sug_text = '\n'.join(f'- {s}' for s in suggestions) if suggestions else 'none'
    return f"""You are a senior API testing expert. An interface's parameter analysis is below. Raise 1~3 concise clarification questions that a human tester must answer, focusing ONLY on two aspects: the interface's positive (normal) flow and the exception flow for required parameters. Never exceed 3 questions.

Interface: {method} {url}
Name: {name}

[Parameter analysis]
{param_text}

[Analysis suggestions]
{sug_text}

Ask questions around these TWO dimensions only (one sentence each, concrete and answerable):
1. Positive flow (接口正向流程): what parameters/combinations are needed to call the interface successfully? What key data and business status are returned on success?
2. Required-parameter exception flow (必传参数异常流程): when a required parameter is missing, empty, wrong type, or invalid, what does the interface return (business code, error message, HTTP status)?

Do NOT ask about auth/token, idempotency, concurrency, or other dimensions unrelated to these two.
Return questions in Chinese. Output ONLY JSON:
{{"questions": [{{"question": "..."}}, {{"question": "..."}}]}}"""


async def _ask_questions(api_request: dict, analysis: dict, ai_config: dict) -> list:
    prompt = _build_clarify_prompt(api_request, analysis)
    messages = [
        {"role": "system", "content": "You are an API testing expert. Return only JSON, no explanation."},
        {"role": "user", "content": prompt},
    ]
    headers = {
        'Authorization': f'Bearer {ai_config["api_key"]}',
        'Content-Type': 'application/json',
    }
    url = f'{ai_config["base_url"].rstrip("/")}/v1/chat/completions'
    body = {
        'model': ai_config['model_name'],
        'messages': messages,
        'max_tokens': 2048,
        'temperature': 0.3,
        'response_format': {'type': 'json_object'},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        content = r.json()['choices'][0]['message']['content']

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]*\}', content)
        if not m:
            raise ValueError('AI response is not valid JSON')
        data = json.loads(m.group(0))

    questions = []
    for q in (data.get('questions') or []):
        if isinstance(q, str):
            questions.append({'question': q, 'answer': ''})
        elif isinstance(q, dict) and q.get('question'):
            questions.append({'question': q['question'], 'answer': ''})
    return questions


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_clarify_questions(request, request_id):
    try:
        req = ApiRequest.objects.get(id=request_id)
    except ApiRequest.DoesNotExist:
        return Response({'error': '\u63a5\u53e3\u4e0d\u5b58\u5728'}, status=404)

    analysis = {}
    pa = ParameterAnalysis.objects.filter(api_request=req).first()
    if pa:
        analysis = pa.analysis or {}

    ai_config = _get_ai_config()
    if not ai_config:
        return Response({'error': '\u672a\u914d\u7f6e AI \u6a21\u578b\uff0c\u8bf7\u5148\u5728 AI \u670d\u52a1\u914d\u7f6e\u4e2d\u5b8c\u6210\u914d\u7f6e'}, status=500)

    api_data = {'name': req.name, 'method': req.method, 'url': req.url or ''}
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            questions = loop.run_until_complete(_ask_questions(api_data, analysis, ai_config))
        finally:
            loop.close()
    except Exception as e:
        logger.error(f'Generate clarification failed [{request_id}]: {e}')
        return Response({'error': f'\u751f\u6210\u6f84\u6e05\u95ee\u9898\u5931\u8d25: {str(e)[:200]}'}, status=500)

    if not questions:
        return Response({'error': 'AI \u672a\u751f\u6210\u6709\u6548\u95ee\u9898\uff0c\u8bf7\u91cd\u8bd5'}, status=500)

    cl, _ = ApiClarification.objects.update_or_create(
        api_request=req,
        defaults={'questions': questions, 'clarified': False},
    )
    return Response({'request_id': request_id, 'questions': cl.questions})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_clarification(request, request_id):
    try:
        cl = ApiClarification.objects.get(api_request_id=request_id)
    except ApiClarification.DoesNotExist:
        return Response({'error': '\u8be5\u63a5\u53e3\u5c1a\u672a\u751f\u6210\u6f84\u6e05\u95ee\u9898'}, status=404)
    return Response({
        'request_id': request_id,
        'questions': cl.questions,
        'clarified': cl.clarified,
        'clarified_at': cl.clarified_at,
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def save_clarification(request, request_id):
    try:
        cl = ApiClarification.objects.get(api_request_id=request_id)
    except ApiClarification.DoesNotExist:
        return Response({'error': '\u8bf7\u5148\u4e3a\u63a5\u53e3\u751f\u6210\u6f84\u6e05\u95ee\u9898'}, status=404)

    questions = request.data.get('questions')
    clarified = request.data.get('clarified', False)

    if questions is not None:
        if not isinstance(questions, list):
            return Response({'error': 'questions \u5fc5\u987b\u662f\u6570\u7ec4'}, status=400)
        cl.questions = questions

    cl.clarified = bool(clarified)
    if cl.clarified:
        # 不强制要求全部问题填写答案，允许部分回答后直接确认
        cl.clarified_by = request.user
        cl.clarified_at = timezone.now()
    cl.save()
    return Response({'status': 'ok', 'clarified': cl.clarified})
