"""
接口参数智能分析 — 用 AI 解析参数类型、边界值、异常场景
"""
import json
import logging
import httpx
from typing import List, Dict

logger = logging.getLogger(__name__)


async def analyze_parameters(api_request: dict, ai_config: dict = None) -> dict:
    config = ai_config
    if not config:
        return {'error': 'AI config not provided'}

    prompt = _build_analysis_prompt(api_request)

    messages = [
        {"role": "system", "content": "你是API测试专家，擅长分析接口参数并给出测试建议。只返回JSON，不要任何解释。"},
        {"role": "user", "content": prompt},
    ]

    headers = {
        'Authorization': f'Bearer {config["api_key"]}',
        'Content-Type': 'application/json',
    }
    url = f'{config["base_url"].rstrip("/")}/v1/chat/completions'

    body = {
        'model': config['model_name'],
        'messages': messages,
        'max_tokens': 4096,
        'temperature': 0.3,
        'response_format': {'type': 'json_object'},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        result = r.json()
        content = result['choices'][0]['message']['content']
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                return json.loads(match.group(0))
            return {'raw': content, 'error': 'JSON解析失败'}


def _get_ai_config() -> dict:
    try:
        from apps.api_testing.models import AIServiceConfig
        cfg = AIServiceConfig.objects.filter(
            service_type='deepseek', role='doc_extractor', is_active=True
        ).first()
        if not cfg:
            cfg = AIServiceConfig.objects.filter(
                service_type='deepseek', is_active=True
            ).first()
        if cfg:
            return {
                'api_key': cfg.api_key,
                'base_url': cfg.base_url,
                'model_name': cfg.model_name,
            }
    except Exception as e:
        logger.error(f'获取AI配置失败: {e}')
    return None


def _build_analysis_prompt(api_request: dict) -> str:
    """构建分析提示词"""
    name = api_request.get('name', '未知接口')
    method = api_request.get('method', 'GET')
    path = api_request.get('path', '')
    url = api_request.get('url', path)
    params = api_request.get('params', [])
    headers = api_request.get('headers', [])
    body = api_request.get('body', {})
    res_body = api_request.get('res_body')
    res_body_type = api_request.get('res_body_type', '')
    res_body_is_schema = api_request.get('res_body_is_json_schema', False)
    env_params = api_request.get('env_params', [])
    env_headers = api_request.get('env_headers', [])
    upstream_interfaces = api_request.get('upstream_interfaces', [])

    # 简化参数列表
    param_info = _format_params(params)
    header_info = _format_params(headers)
    body_info = json.dumps(body, ensure_ascii=False, indent=2) if body and body.get('type') != 'none' else '无'
    response_info = _format_response(res_body, res_body_type, res_body_is_schema)
    env_info = ''
    if env_params or env_headers:
        env_info = f"""
【环境公参】（来自项目环境配置，实际请求会自动带上）
{_format_params(env_params)}

【环境请求头】（来自项目环境配置，实际请求会自动带上）
{_format_params(env_headers)}
"""
    upstream_info = ''
    if upstream_interfaces:
        upstream_info = '\n【同版本其他接口】（用于判断参数的数据来源/上游依赖）\n' + '\n'.join(upstream_interfaces) + '\n'

    return f"""请分析以下API接口的每个参数，给出测试边界值和异常场景。

接口: {method} {url}
名称: {name}

【URL参数】
{param_info}

【Headers】
{header_info}

【请求体】
{body_info}
{env_info}{upstream_info}【响应结构】（来自 YApi 的接口返回定义）
{response_info}

请结合响应结构，推断每个参数对响应字段的影响，并在 suggestions 中补充响应相关的测试建议（如响应字段缺失、类型错误、枚举值校验、状态码等）。

请为每个参数输出：
1. type: 参数类型(string/int/float/bool/array/object)
2. required: 是否必填(true/false)
3. boundary_values: 边界值列表 (最小值、最大值、零、负数、空字符串、超长等)
4. exception_scenarios: 异常场景列表 (不传、传null、错误类型、特殊字符等)
5. description: 参数用途推测
6. needs_real_data: 该参数是否需要真实业务数据才能通过接口校验（如业务主键 challenge_id/order_id/activity_id 等，假值无效），true/false
7. data_source: 当 needs_real_data=true 时，填写数据来源：字段名（从环境变量/历史响应取，如 challenge_id），或 上游接口名.响应路径（当参数来自另一个接口的返回值时，如 发起挑战.data.challenge_id，接口名必须取自【同版本其他接口】列表）；否则为空字符串
8. env_param_dependencies: 对【环境公参】中的参数（如 userid、pairid、av、client 等）也要判断：其中业务标识类参数（如 userid、pairid 这类需要真实有效值才能通过接口校验的）也要输出到 env_param_dependencies 数组，每个元素含 name/needs_real_data/data_source（data_source 格式同第7条）

输出JSON格式:
{{
  "parameters": [
    {{
      "name": "参数名",
      "type": "string",
      "required": true,
      "boundary_values": ["正常值", "空字符串", "超长500字"],
      "exception_scenarios": ["不传此参数", "传null", "传数字类型"],
      "description": "推测的参数作用",
      "needs_real_data": false,
      "data_source": ""
    }}
  ],
  "env_param_dependencies": [
    {{"name": "pairid", "needs_real_data": true, "data_source": "匹配接口.data.pairid"}},
    {{"name": "userid", "needs_real_data": true, "data_source": ""}}
  ],
  "suggestions": ["额外的测试建议..."]
}}"""


def _format_params(params: list) -> str:
    if not params:
        return '无'
    lines = []
    for p in params:
        if isinstance(p, dict):
            k = p.get('key', p.get('name', '?'))
            v = p.get('value', '')
            d = p.get('description', '')
            r = '必填' if p.get('required') else '可选'
            lines.append(f'  {k}: 示例值="{v}", {r}, 说明={d}')
        else:
            lines.append(f'  {p}')
    return '\n'.join(lines) if lines else '无'


def _format_response(res_body, res_body_type='', is_schema=False) -> str:
    """格式化响应体定义，供 AI 分析使用（JSON Schema 同时给出 Schema 与示例）"""
    if res_body in (None, '', [], {}):
        return '无'
    if res_body_type == 'json' and isinstance(res_body, (dict, list)):
        if is_schema and isinstance(res_body, dict):
            try:
                from .yapi_sync import _json_schema_to_example
                example = _json_schema_to_example(res_body)
                return ('JSON Schema:\n' + json.dumps(res_body, ensure_ascii=False, indent=2)
                        + '\n\n示例响应:\n' + json.dumps(example, ensure_ascii=False, indent=2))
            except Exception:
                pass
        return json.dumps(res_body, ensure_ascii=False, indent=2)
    return str(res_body)


async def analyze_batch(request_ids: List[int], ai_config: dict = None) -> List[dict]:
    """批量分析多个接口"""
    from apps.api_testing.models import ApiRequest
    results = []
    for rid in request_ids:
        try:
            req = await ApiRequest.objects.select_related('collection__project').aget(id=rid)

            # 加载项目环境公参/请求头（接口管理-环境配置），让 AI 看到完整请求上下文
            from apps.api_testing.models import Environment
            env = None
            if req.collection and req.collection.project:
                env = await Environment.objects.filter(
                    project=req.collection.project, is_active=True
                ).afirst()
            if env is None:
                env = await Environment.objects.filter(is_active=True).afirst()
            env_params = []
            env_headers = []
            if env:
                env_headers = [h for h in (env.default_headers or []) if h.get('enabled', True)]
                env_params = [p for p in (env.default_params or []) if p.get('enabled', True)]

            # 同版本接口列表（供 AI 判断参数数据来源/上游依赖），最多取 100 个
            upstream_interfaces = []
            if req.collection:
                siblings = [s async for s in ApiRequest.objects.filter(collection=req.collection).exclude(id=req.id)[:100]]
            else:
                siblings = []
            for s in siblings:
                upstream_interfaces.append(f"{s.name} ({s.method} {s.url or ''})")

            data = {
                'name': req.name,
                'method': req.method,
                'path': req.url or '',
                'url': req.url or '',
                'params': req.params or [],
                'headers': req.headers or [],
                'body': req.body or {},
                'res_body': req.res_body,
                'res_body_type': req.res_body_type or '',
                'res_body_is_json_schema': req.res_body_is_json_schema,
                'env_params': env_params,
                'env_headers': env_headers,
                'upstream_interfaces': upstream_interfaces,
            }
            analysis = await analyze_parameters(data, ai_config=ai_config)
            results.append({'id': rid, 'name': req.name, 'analysis': analysis})
        except Exception as e:
            results.append({'id': rid, 'error': str(e)})
    return results
