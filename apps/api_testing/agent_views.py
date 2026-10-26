"""
Agent 接口自动化 — 文字描述 → AI 规划场景 → 自动执行（正向流程 + 依赖处理）
"""
import json
import re
import asyncio
import time
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db.models import Q

from .models import ApiProject, ApiRequest, Environment, TestSuite, TestExecution
from .param_analyzer import _get_ai_config
from .case_views import (
    _get_by_path, _resolve_case_vars, _resolve_case_vars_in_obj,
    _resolve_real_data, _resolve_real_data_in_obj, _run_assertions,
)

logger = logging.getLogger(__name__)

AGENT_PLAN_PROMPT = """你是接口自动化场景规划专家。用户会给出候选接口清单（可能附带一句业务描述），你需要规划调用顺序、填写参数、声明接口之间的数据依赖，并为每一步给出校验规则。

# 候选接口清单（[接口ID] 接口名 (方法 路径) 参数:... 请求体:...）
{interface_list}

# 用户描述
{description}

# 输出要求（只输出 JSON，不要任何解释）
{
  "scenario": "场景名称",
  "steps": [
    {
      "request_id": 123,
      "interface": "接口名称（必须来自上面的清单）",
      "params": { "参数名": "值 或 {{变量}}" },
      "body": { "请求体结构": "值 或 {{变量}}" },
      "capture": [ { "as": "变量名", "path": "响应路径，如 data.challenge_id" } ],
      "assertions": [ { "type": "status_code", "expected": 200 } ]
    }
  ],
  "excluded": [ { "request_id": 123, "reason": "与主流程无关" } ]
}

规则：
1. request_id 必须取自清单方括号里的数字，禁止编造；interface 必须与清单中的名称完全一致
2. 按真实业务调用顺序排列；清单中与目标流程无关的接口不要放进 steps，统一写进 excluded 并给出 20 字内的原因；用户描述若要求「全部保留 / 不要排除」，excluded 必须为空数组
3. 参数和请求体的字段名必须使用清单中列出的字段名（含类型标注，如 is_open:bool），不要自造字段
4. 只填写「接口必需字段」和「用户明确提到的字段」两类；用户没提到、且接口有默认值的可选字段一律不要填写，执行时会自动使用接口默认值
5. 需要真实数据的字段用 {{变量}} 引用，但只能引用「前置步骤 capture 声明的变量」或「环境公参（userid/pairid/av/client 等）」里真实存在的名字，禁止自造变量名
6. 标注为 bool 的字段必须用 true/false，禁止用 1/0
7. 环境公参不需要在 params 里重复填，执行时会自动带上
8. 每一步都必须给出 assertions，至少一条 {"type": "status_code", "expected": 200}；只有在你能确定业务成功时某字段的取值时才追加 json_path 断言，不确定就不要加，宁缺勿错
9. 清单中标注为「动态」的字段（如 date:str(动态${datetime()})）不要填写任何值，执行时会自动用接口默认的动态函数生成
"""


def _field_type(v):
    """推断字段类型，供 AI 规划参考（bool/int/str/array 等）"""
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, int):
        return 'int'
    if isinstance(v, float):
        return 'float'
    if isinstance(v, str):
        if v.startswith('${'):
            return 'str(动态' + v + ')'
        if v.startswith('{{'):
            return 'str(变量)'
        return 'str'
    if isinstance(v, list):
        return 'array'
    if isinstance(v, dict):
        return 'object'
    return '?'


def _summarize_interface(req):
    """接口参数/请求体字段名+类型摘要，供 AI 规划参考"""
    p = req.params
    pkeys = []
    if isinstance(p, dict):
        for k, v in p.items():
            if isinstance(v, dict):
                v = v.get('value')
            pkeys.append(f'{k}:{_field_type(v)}')
    elif isinstance(p, list):
        for x in p:
            if isinstance(x, dict) and x.get('key'):
                pkeys.append(f"{x.get('key')}:{_field_type(x.get('value'))}")
    bkeys = []
    b = req.body
    if isinstance(b, dict):
        d = b.get('data')
        if isinstance(d, dict):
            bkeys = [f'{k}:{_field_type(v)}' for k, v in d.items()]
    return pkeys[:12], bkeys[:12]


def _plan_max_tokens(step_count):
    """按候选接口数量给输出留足 token：每步约 250-300 token，下限 4096、上限 8192"""
    return max(4096, min(8192, 1200 + 300 * max(step_count, 1)))


def _call_ai(ai_config, prompt, system='', max_tokens=4096):
    """调用 OpenAI 兼容接口，返回 (内容, finish_reason)"""
    import httpx
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    url = f'{ai_config["base_url"].rstrip("/")}/v1/chat/completions'
    body = {
        'model': ai_config['model_name'],
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': 0.2,
    }
    headers = {
        'Authorization': f'Bearer {ai_config["api_key"]}',
        'Content-Type': 'application/json',
    }

    async def _call():
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            choice = r.json()['choices'][0]
            return choice['message']['content'], choice.get('finish_reason')

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_call())
    finally:
        loop.close()


def _parse_ai_json(content):
    """解析 AI 输出，兼容 ```json 包裹和前后多余文字"""
    text = content.strip()
    block = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if block:
        text = block.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return json.loads(m.group(0))
        raise ValueError('AI 输出解析失败')


def _find_vars_in_step(step):
    """找出步骤 params/body 里引用的 {{变量}}"""
    refs = []

    def walk(obj):
        if isinstance(obj, str):
            refs.extend(re.findall(r'\{\{([^}]+)\}\}', obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(step.get('params'))
    walk(step.get('body'))
    walk(step.get('headers'))
    return refs


def _resolve_dynamic_in_obj(data, resolver):
    """递归解析对象/数组/字符串中的动态函数（${datetime()} 等）"""
    if isinstance(data, dict):
        return {k: _resolve_dynamic_in_obj(v, resolver) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_dynamic_in_obj(v, resolver) for v in data]
    if isinstance(data, str):
        return resolver.resolve(data)
    return data


def _project_requests(project, user=None):
    """项目内可用接口：属于该项目集合的 + 未归属任何集合的。

    未归属集合的接口（手工新建时没选版本、或早期 YApi 同步留下的记录）没有
    collection 就查不到项目，原来会被漏掉，导致规划里少接口、执行时报「未找到接口」。
    传 user 时按创建者隔离，与 ApiRequestViewSet.get_queryset 的口径保持一致。
    """
    scope = Q(collection__project=project) | Q(collection__isnull=True)
    if user is not None:
        scope = Q(collection__project=project) | Q(collection__isnull=True, created_by=user)
    return ApiRequest.objects.filter(scope)


def _find_request(project, step, user=None):
    """优先按 request_id 精确查找接口，兼容旧的按名称查找。"""
    base = _project_requests(project, user)
    request_id = step.get('request_id')
    if request_id:
        req = base.filter(id=request_id).first()
        if req:
            return req
    name = step.get('interface') or ''
    if not name:
        return None
    return base.filter(name__iexact=name).first() or base.filter(name__icontains=name).first()


def _coerce_like(value, template):
    """按接口定义的类型规范化前端/配置中的值，变量占位符保持原样。"""
    if isinstance(value, str) and '{{' in value:
        return value
    if isinstance(template, bool) and not isinstance(value, bool):
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ('1', 'true', 'yes', 'on'):
                return True
            if lowered in ('0', 'false', 'no', 'off'):
                return False
        elif isinstance(value, (int, float)):
            return bool(value)
        return value
    if isinstance(template, int) and not isinstance(template, bool) and not isinstance(value, bool):
        if isinstance(value, str) and re.fullmatch(r'-?\d+', value.strip()):
            return int(value.strip())
        if isinstance(value, float):
            return int(value)
    if isinstance(template, float) and not isinstance(value, bool):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if isinstance(template, str) and value is not None and not isinstance(value, (dict, list)):
        return str(value)
    return value


def _merge_known_fields(base, override):
    """只覆盖接口定义中已经存在的字段，支持嵌套对象，避免脏字段进入请求体。"""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = json.loads(json.dumps(base))
        for key, value in override.items():
            if key not in merged:
                continue
            # 动态函数字段以接口定义为准
            if isinstance(merged[key], str) and merged[key].startswith('${'):
                continue
            merged[key] = _merge_known_fields(merged[key], value)
        return merged
    if isinstance(base, list) and isinstance(override, list):
        if not base:
            return json.loads(json.dumps(override))
        return [_merge_known_fields(base[0], item) if isinstance(item, (dict, list)) else item for item in override]
    return _coerce_like(override, base)


def _order_steps(steps):
    """按 capture 依赖重排：被引用的变量所在的捕获步骤排到引用步骤之前（稳定拓扑排序）"""
    capture_of = {}
    for idx, s in enumerate(steps):
        for cap in (s.get('capture') or []):
            if cap.get('as'):
                capture_of[cap['as']] = idx
    deps = {}
    for idx, s in enumerate(steps):
        for v in _find_vars_in_step(s):
            cidx = capture_of.get(v)
            if cidx is not None and cidx != idx:
                deps.setdefault(idx, set()).add(cidx)
    order = []
    remaining = set(range(len(steps)))
    while remaining:
        ready = [i for i in remaining if not (deps.get(i, set()) & remaining)]
        if not ready:
            break
        i = min(ready)
        order.append(i)
        remaining.discard(i)
    if len(order) == len(steps):
        return [steps[i] for i in order]
    return steps


def _load_env_vars(project):
    """加载项目生效环境的变量与公参（生成阶段用于判断哪些变量已有值）"""
    env = Environment.objects.filter(project=project, is_active=True).first() \
        or Environment.objects.filter(is_active=True).first()
    env_vars = dict(env.variables or {}) if env else {}
    if env:
        for dp in (env.default_params or []):
            if dp.get('enabled', True) and dp.get('key') and dp['key'] not in env_vars:
                env_vars[dp['key']] = dp.get('value', '')
    return env_vars


def _collect_field_paths(node, prefix='', out=None, depth=0):
    """展开响应结构里的字段路径（兼容 JSON Schema 与普通示例 JSON），供缺数建议使用"""
    if out is None:
        out = []
    if depth > 6 or len(out) >= 200:
        return out
    if isinstance(node, dict):
        if isinstance(node.get('properties'), dict):
            for k, v in node['properties'].items():
                _collect_field_paths(v, f'{prefix}.{k}' if prefix else k, out, depth + 1)
            return out
        if node.get('type') == 'array' and isinstance(node.get('items'), (dict, list)):
            return _collect_field_paths(node['items'], prefix, out, depth + 1)
        traversed = False
        for k, v in node.items():
            if k in ('type', 'description', 'required', 'example', 'default', 'enum', 'title', '$schema'):
                continue
            _collect_field_paths(v, f'{prefix}.{k}' if prefix else k, out, depth + 1)
            traversed = True
        # JSON Schema 的叶子节点通常只剩 type/description，此时 prefix 本身就是字段路径
        if not traversed and prefix:
            out.append(prefix)
        return out
    if isinstance(node, list):
        if node:
            _collect_field_paths(node[0], prefix, out, depth + 1)
        return out
    if prefix:
        out.append(prefix)
    return out


def _response_paths(req):
    """接口的响应字段路径缓存（res_body 可能为空）"""
    body = getattr(req, 'res_body', None)
    if not body:
        return []
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return []
    return _collect_field_paths(body)


def _collect_placeholders(step):
    """收集一个步骤里引用的所有 {{变量}}（params / body / headers / url）"""
    found = []

    def walk(value):
        if isinstance(value, str):
            found.extend(re.findall(r'\{\{([^}]+)\}\}', value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(step.get('params') or {})
    walk(step.get('body') or {})
    walk(step.get('headers') or {})
    walk(step.get('path') or '')
    return list(dict.fromkeys(found))


def _suggest_source(var, steps, req_map, upto_index):
    """在更早的步骤里为缺失变量找一个最可能的来源字段"""
    key = (var.split('.')[-1] or '').lower()
    if not key:
        return None
    loose = None
    for index in range(upto_index):
        req = req_map.get(steps[index].get('request_id'))
        if not req:
            continue
        for path in _response_paths(req):
            name = (path.split('.')[-1] or '').lower()
            if name == key:
                return {'step': index + 1, 'interface': req.name, 'path': path, 'confidence': 'high'}
            if loose is None and (key in name or name in key):
                loose = {'step': index + 1, 'interface': req.name, 'path': path, 'confidence': 'medium'}
    return loose


def _precheck_missing(steps, env_vars, req_map):
    """生成阶段预检缺数：已知环境变量/公参/前序 capture 之外的引用都算缺数，并给出建议来源"""
    env_keys = set(env_vars.keys())
    available = set()
    missing = []
    for index, step in enumerate(steps):
        for var in _collect_placeholders(step):
            if var in env_keys or var in available:
                continue
            if '.' in var and var.split('.')[0] in env_keys:
                continue
            item = {
                'step': index + 1,
                'interface': step.get('interface'),
                'var': var,
            }
            suggestion = _suggest_source(var, steps, req_map, index)
            if suggestion:
                item['suggestion'] = suggestion
            missing.append(item)
        for cap in (step.get('capture') or []):
            if cap.get('as'):
                available.add(cap['as'])
    return missing


def _success_code(req):
    """推断业务成功码：响应结构示例值 → 最近真实历史响应；推断不出返回 (None, None)

    不能硬编码成 0：不同项目约定不同（有的 success=0，有的 status=200），
    猜错会让本来通过的场景变成假失败，比不校验更伤信任。
    """
    body = req.res_body
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = None
    if isinstance(body, dict):
        props = body.get('properties') if isinstance(body.get('properties'), dict) else body
        if isinstance(props, dict):
            for key in ('status', 'code', 'errcode', 'error_code', 'ret'):
                node = props.get(key)
                if not isinstance(node, dict):
                    continue
                for field in ('example', 'default'):
                    if node.get(field) not in (None, ''):
                        return f'$.{key}', node[field]
                enum = node.get('enum')
                if isinstance(enum, list) and len(enum) == 1:
                    return f'$.{key}', enum[0]
    try:
        from .models import RequestHistory
        for h in RequestHistory.objects.filter(request=req).order_by('-executed_at')[:20]:
            # 历史里混着失败记录，HTTP 异常或业务失败（data 为空 / 带 msg）的都不能当成功码参考
            if h.status_code and h.status_code >= 400:
                continue
            data = (h.response_data or {}).get('json')
            if not isinstance(data, dict):
                continue
            payload = data.get('data')
            message = data.get('msg') or data.get('message')
            if payload in (None, '', {}, []) or (isinstance(message, str) and message.strip()):
                continue
            for key in ('status', 'code', 'errcode'):
                if data.get(key) not in (None, ''):
                    return f'$.{key}', data[key]
    except Exception:
        pass
    return None, None


def _fix_business_assertions(step, req):
    """用真实数据校正业务码断言：AI 猜的期望值一律按推断结果重建，推断不出就不做业务码断言"""
    path, expected = _success_code(req)
    result = []
    seen = set()
    for a in (step.get('assertions') or []):
        if not isinstance(a, dict):
            continue
        if a.get('type') == 'json_path' and str(a.get('path') or '').strip() in ('$.status', '$.code', '$.errcode'):
            continue
        key = (a.get('type'), str(a.get('path') or ''), str(a.get('expected')))
        if key in seen:
            continue
        seen.add(key)
        result.append(a)
    if path:
        result.append({'type': 'json_path', 'path': path, 'expected': expected})
    if not any(a.get('type') == 'status_code' for a in result):
        result.insert(0, {'type': 'status_code', 'expected': 200})
    step['assertions'] = result
    return step


_GUESS_IGNORED_NAMES = {'page', 'page_size', 'pagesize', 'limit', 'size', 'offset', 'count', 'type',
                        'version', 'av', 'client', 'timestamp', 't'}
_ABSENT = object()


def _flatten_values(node, prefix='', out=None, depth=0):
    """把 dict 展开成 {路径: 值}，用于和接口默认值比对"""
    if out is None:
        out = {}
    if depth > 6 or not isinstance(node, dict):
        return out
    for key, value in node.items():
        path = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            _flatten_values(value, path, out, depth + 1)
        else:
            out[path] = value
    return out


def _is_suspicious_value(value):
    """只有字面量才可能是 AI 猜的：变量引用、动态函数、布尔、空值、空容器都不算"""
    if isinstance(value, bool) or value in (None, ''):
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, str):
        return '{{' not in value and '${' not in value
    return True


def _request_defaults(req):
    """接口定义里的默认值表，用于区分「照抄默认值」和「AI 自己猜的」"""
    defaults = {}
    body = req.body
    data = body.get('data') if isinstance(body, dict) and 'data' in body else body
    if isinstance(data, dict):
        defaults.update(_flatten_values(data))
    params = req.params
    if isinstance(params, dict):
        for key, value in params.items():
            defaults[key] = value.get('value') if isinstance(value, dict) else value
    elif isinstance(params, list):
        for item in params:
            if isinstance(item, dict) and item.get('key'):
                defaults[item['key']] = item.get('value')
    return defaults


def _collect_guesses(steps, req_map):
    """标出 AI 猜出来的固定值：字面量、与接口默认值不同、且不是常见分页/版本参数

    这类值不会走缺数检测（它不是 {{}} 引用），但猜错会直接导致真实失败，
    必须让用户在发送前确认，否则平台会变成"AI 编数据 → 跑失败 → 用户查不出原因"。
    """
    guesses = []
    for index, step in enumerate(steps):
        req = req_map.get(step.get('request_id'))
        if not req:
            continue
        defaults = _request_defaults(req)
        for location in ('body', 'params'):
            container = step.get(location)
            if not isinstance(container, dict):
                continue
            for path, value in _flatten_values(container).items():
                if not _is_suspicious_value(value):
                    continue
                base = defaults.get(path, _ABSENT)
                if base is not _ABSENT and str(base) == str(value):
                    continue
                if (path.split('.')[-1] or '').lower() in _GUESS_IGNORED_NAMES:
                    continue
                guesses.append({
                    'step': index + 1,
                    'interface': req.name,
                    'location': location,
                    'path': path,
                    'value': value,
                })
    return guesses


def _hydrate_plan_steps(steps, reqs, req_map):
    """把 AI 输出的步骤对齐到真实接口：补 request_id/path/method，兜底断言，过滤不存在的接口"""
    by_name = {}
    for r in reqs:
        by_name.setdefault((r.name or '').strip().lower(), r)
    result = []
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        req = None
        rid = raw.get('request_id')
        if rid is not None:
            try:
                req = req_map.get(int(rid))
            except (TypeError, ValueError):
                req = None
        name = (raw.get('interface') or '').strip()
        if req is None and name:
            req = by_name.get(name.lower())
        if req is None and name:
            req = next((r for r in reqs if name.lower() in (r.name or '').lower()), None)
        if req is None:
            continue
        raw['request_id'] = req.id
        raw['interface'] = req.name
        raw['path'] = req.url or ''
        raw['method'] = (req.method or 'GET').upper()
        _fix_business_assertions(raw, req)
        result.append(raw)
    return result


def _collect_excluded(ai_excluded, reqs, steps):
    """汇总「AI 明确排除」+「AI 压根没纳入」的接口，让前端能把决策摊开给用户看"""
    used = {st.get('request_id') for st in steps}
    reasons = {}
    for item in (ai_excluded or []):
        if not isinstance(item, dict):
            continue
        try:
            rid = int(item.get('request_id'))
        except (TypeError, ValueError):
            continue
        reasons[rid] = str(item.get('reason') or '').strip()[:60]
    out = []
    for r in reqs:
        if r.id in used:
            continue
        out.append({
            'request_id': r.id,
            'name': r.name,
            'method': (r.method or 'GET').upper(),
            'reason': reasons.get(r.id) or 'AI 未纳入本次流程',
        })
    return out


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def plan_scenario(request):
    """场景规划：勾选接口（或一句描述）→ AI 定顺序 + 填参数 + 声明依赖 + 预检缺数"""
    project_id = request.data.get('project_id')
    description = (request.data.get('description') or '').strip()
    request_ids = request.data.get('request_ids') or []
    collection_id = request.data.get('collection_id')

    if not project_id:
        return Response({'error': '需要 project_id'}, status=400)
    if not description and not request_ids:
        return Response({'error': '请先勾选接口，或填写一句场景描述'}, status=400)
    project = ApiProject.objects.filter(id=int(project_id)).first()
    if not project:
        return Response({'error': '项目不存在'}, status=404)

    qs = _project_requests(project, request.user)
    if collection_id:
        try:
            qs = qs.filter(collection_id=int(collection_id))
        except (TypeError, ValueError):
            pass
    if request_ids:
        ids = []
        for rid in request_ids:
            try:
                ids.append(int(rid))
            except (TypeError, ValueError):
                continue
        if ids:
            qs = qs.filter(id__in=ids)

    reqs = list(qs[:300])
    if not reqs:
        return Response({'error': '所选范围内没有可用接口'}, status=400)
    req_map = {r.id: r for r in reqs}

    lines = []
    for r in reqs:
        pkeys, bkeys = _summarize_interface(r)
        parts = [f'[{r.id}] {r.name} ({r.method} {r.url or ""})']
        if pkeys:
            parts.append('参数:' + ','.join(str(k) for k in pkeys))
        if bkeys:
            parts.append('请求体:' + ','.join(str(k) for k in bkeys))
        lines.append(' '.join(parts))
    interface_list = '\n'.join(lines)

    if not description:
        description = '把勾选的接口按真实业务调用顺序排列，构成一个完整流程；与流程无关的接口请排除。'

    prompt = AGENT_PLAN_PROMPT.replace('{interface_list}', interface_list).replace('{description}', description)
    ai_config = _get_ai_config()
    if not ai_config:
        return Response({'error': '未配置 AI 模型，请先在配置里接入'}, status=500)
    try:
        content, finish_reason = _call_ai(ai_config, prompt, system='你是接口自动化场景规划专家，只输出 JSON。',
                                          max_tokens=_plan_max_tokens(len(reqs)))
        # 输出被 token 上限截断（接口太多）时，用紧凑模式重来一次，保证 JSON 完整
        if finish_reason == 'length' or not content.strip().endswith('}'):
            logger.warning(f'AI 输出疑似截断（finish_reason={finish_reason}），改用紧凑模式重试')
            compact = prompt + (
                '\n\n# 补充要求（上一次输出过长被截断）\n'
                '必须输出完整合法的 JSON。为压缩长度：params 与 body 一律给 {}，'
                'capture 只保留确实有下游依赖的字段，assertions 每条只需 {"type": "status_code", "expected": 200}。'
            )
            content, finish_reason = _call_ai(ai_config, compact, system='你是接口自动化场景规划专家，只输出 JSON。',
                                              max_tokens=_plan_max_tokens(len(reqs)))
        plan = _parse_ai_json(content)
    except Exception as e:
        logger.error(f'Agent 规划失败: {e}')
        return Response({'error': f'规划失败: {str(e)[:200]}'}, status=500)

    steps = _hydrate_plan_steps(plan.get('steps') or [], reqs, req_map)
    if not steps:
        return Response({'error': 'AI 没有匹配到任何接口，请检查勾选的接口或换个描述'}, status=400)
    steps = _order_steps(steps)

    env_vars = _load_env_vars(project)
    plan['steps'] = steps
    plan['missing'] = _precheck_missing(steps, env_vars, req_map)
    plan['guesses'] = _collect_guesses(steps, req_map)
    plan['excluded'] = _collect_excluded(plan.get('excluded'), reqs, steps)
    plan['candidate_count'] = len(reqs)
    plan['source'] = 'selection' if request_ids else 'description'
    return Response(plan)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_scenario(request):
    """按规划场景自动执行（正向流程，依赖 capture 自动取数）"""
    project_id = request.data.get('project_id')
    steps = request.data.get('steps') or []
    stop_on_failure = bool(request.data.get('stop_on_failure'))
    if not project_id or not steps:
        return Response({'error': '需要 project_id 和 steps'}, status=400)
    project = ApiProject.objects.filter(id=int(project_id)).first()
    if not project:
        return Response({'error': '项目不存在'}, status=404)

    steps = _order_steps(steps)
    test_suite_id = request.data.get('test_suite_id')
    test_suite = None
    execution = None
    if test_suite_id:
        test_suite = TestSuite.objects.filter(id=test_suite_id, project=project).first()
        if not test_suite:
            return Response({'error': '测试场景不存在或不属于当前项目'}, status=404)
        execution = TestExecution.objects.create(
            test_suite=test_suite,
            status='RUNNING',
            start_time=timezone.now(),
            total_requests=len(steps),
            executed_by=request.user,
        )

    environment_id = request.data.get('environment_id') or (test_suite.environment_id if test_suite else None)
    env = None
    if environment_id:
        env = Environment.objects.filter(id=environment_id, project=project).first()
    if env is None:
        env = Environment.objects.filter(project=project, is_active=True).first()
    if env is None:
        env = Environment.objects.filter(is_active=True).first()
    env_vars = dict(env.variables or {}) if env else {}
    dheaders = [h for h in (env.default_headers or []) if h.get('enabled', True)] if env else []
    dparams = [p for p in (env.default_params or []) if p.get('enabled', True)] if env else []
    for dp in dparams:
        if dp.get('key') and dp.get('key') not in env_vars:
            env_vars[dp['key']] = dp.get('value', '')

    import requests as http_req
    session_vars = {}
    session_cache = {}
    results = []

    for step in steps:
        name = step.get('interface') or ''
        st = time.time()
        item = {'interface': name, 'name': name, 'index': len(results) + 1}
        req = _find_request(project, step, request.user)
        if not req:
            item.update({'status': 'error', 'message': f'未找到接口: {name}',
                         'time_ms': int((time.time() - st) * 1000)})
            results.append(item)
            if stop_on_failure:
                break
            continue
        try:
            url = req.url or ''
            item.update({'request_id': req.id, 'method': (req.method or 'GET').upper(), 'url': url})
            # 先替换 URL 里的变量（如 {{base_url}}），再判断相对路径
            url = _resolve_case_vars(url, env_vars)
            method = (req.method or 'GET').upper()
            base_url = str(env_vars.get('base_url') or '').rstrip('/')
            if not url.startswith('http'):
                url = base_url + (url if url.startswith('/') else '/' + url)

            headers = {}
            for h in dheaders:
                k = h.get('key')
                if k and k not in headers:
                    headers[k] = _resolve_case_vars(h.get('value', ''), env_vars)

            params = {}
            # 接口定义参数兜底（Agent 步骤未提供时自动带上，如 page/limit；兼容 dict / list 两种格式）
            if isinstance(req.params, dict):
                for k, v in req.params.items():
                    if k not in params:
                        params[k] = v if not isinstance(v, dict) else v.get('value', '')
            else:
                for p in (req.params or []):
                    if isinstance(p, dict) and p.get('enabled') is False:
                        continue
                    k = p.get('key') if isinstance(p, dict) else None
                    if k and k not in params:
                        params[k] = _resolve_case_vars(p.get('value', '') or '', env_vars)
            # 环境默认参数：接口定义里的空值视为「未设置」，允许公参补上
            # （YApi 里标了必填但没填示例的参数，同步后是空串，原来会占位把公参挡掉）
            for p in dparams:
                k = p.get('key')
                if not k:
                    continue
                if k not in params or params[k] in ('', None):
                    params[k] = _resolve_case_vars(p.get('value', ''), env_vars)
            # 场景步骤中显式配置的请求头优先
            for k, v in (step.get('headers') or {}).items():
                if k:
                    headers[k] = v
            # 步骤参数覆盖（可视化绑定值优先）
            for k, v in (step.get('params') or {}).items():
                if isinstance(v, dict):
                    v = v.get('value', '')
                params[k] = v

            # body：以接口定义的请求体为基准，叠加 AI 提供的匹配字段（AI 自造字段丢弃）
            body_data = None
            is_json_body = False
            _req_body = req.body if isinstance(req.body, dict) else {}
            _req_data = _req_body.get('data', _req_body) if _req_body else None
            step_body = step.get('body')
            _src = step_body.get('data') if isinstance(step_body, dict) and isinstance(step_body.get('data'), (dict, list)) else step_body
            if isinstance(_req_data, (dict, list)):
                body_data = _merge_known_fields(_req_data, _src) if isinstance(_src, (dict, list)) else json.loads(json.dumps(_req_data))
                is_json_body = True
            elif _req_body.get('type') == 'raw' and isinstance(step_body, str):
                body_data = step_body
            elif isinstance(_src, (dict, list)):
                body_data = json.loads(json.dumps(_src))
                is_json_body = True

            # 变量解析：session_vars 优先 → 环境 → 历史/上游
            # allow_history=False：历史响应可能来自其他场景，容易捞到脏值，场景模式只信显式依赖
            resolve_vars = {**env_vars, **session_vars}
            params = {k: _resolve_case_vars(v, resolve_vars) for k, v in params.items()}
            url = _resolve_case_vars(url, resolve_vars)
            headers = {k: _resolve_case_vars(v, resolve_vars) for k, v in headers.items()}

            # headers / url 同样支持上游取值：鉴权 token 通常在 header，路径参数在 url
            headers, header_missing = _resolve_real_data(
                headers, resolve_vars, project, session_cache, 0, allow_history=False)
            if isinstance(url, str) and '{{' in url:
                _url_resolved, url_missing = _resolve_real_data(
                    {'url': url}, resolve_vars, project, session_cache, 0, allow_history=False)
                url = _url_resolved.get('url', url)
            else:
                url_missing = []
            params, params_missing = _resolve_real_data(
                params, resolve_vars, project, session_cache, 0, allow_history=False)
            missing_all = list(dict.fromkeys(params_missing + header_missing + url_missing))

            if body_data is not None:
                body_missing = []
                # 先做真实数据+类型保留解析（整字段 {{var}} 保留 int/bool 等原始类型，避免 diary_id 变字符串），再解析剩余环境变量
                body_data = _resolve_real_data_in_obj(
                    body_data, resolve_vars, project, session_cache, 0, body_missing, allow_history=False)
                body_data = _resolve_case_vars_in_obj(body_data, resolve_vars)
                missing_all = list(dict.fromkeys(missing_all + body_missing))

            # 缺数不再静默放行：参数/请求头/URL/请求体任一位置缺数都在发送前拦下
            if missing_all:
                item.update({
                    'status': 'error',
                    'missing': missing_all,
                    'message': '数据不足: ' + '、'.join('{{%s}}' % v for v in missing_all),
                    'time_ms': int((time.time() - st) * 1000),
                })
                results.append(item)
                if stop_on_failure:
                    break
                continue

            # 解析动态函数（${datetime()} 等）
            from .variable_resolver import VariableResolver
            _resolver = VariableResolver()
            url = _resolver.resolve(url)
            params = _resolve_dynamic_in_obj(params, _resolver)
            if isinstance(body_data, (dict, list)):
                body_data = _resolve_dynamic_in_obj(body_data, _resolver)

            # 记录请求详情，供失败日志展示（解析后的值）
            item['request_url'] = url
            item['request_params'] = params
            item['request_body'] = body_data

            if is_json_body:
                resp = http_req.request(method=method, url=url, headers=headers, params=params,
                                        json=body_data if body_data is not None else None, timeout=30)
            else:
                resp = http_req.request(method=method, url=url, headers=headers, params=params,
                                        data=body_data if body_data is not None else None, timeout=30)

            try:
                body_json = resp.json()
            except Exception:
                body_json = None

            # 业务结果判定：HTTP<400 且业务成功才算通过（很多接口业务失败也返回 HTTP 200）
            business_ok = True
            fail_msg = ''
            if isinstance(body_json, dict):
                if 'data' in body_json:
                    business_ok = body_json.get('data') not in (None, '', [])
                elif 'status' in body_json or 'code' in body_json:
                    st = body_json.get('status', body_json.get('code'))
                    if isinstance(st, int):
                        business_ok = st == 0 or st == resp.status_code
                    elif isinstance(st, str):
                        business_ok = st.lower() in ('success', 'ok', '0', '200')
                if not business_ok and body_json.get('msg'):
                    fail_msg = str(body_json.get('msg'))

            captured = {}
            for cap in (step.get('capture') or []):
                p = cap.get('path') or ''
                as_name = cap.get('as') or p.split('.')[-1]
                val = _get_by_path(body_json, p) if body_json is not None else None
                if val not in (None, ''):
                    session_vars[as_name] = val
                    captured[as_name] = val

            elapsed_ms = int((time.time() - st) * 1000)
            assertion_results = _run_assertions(resp, step.get('assertions') or [], elapsed_ms)
            assertions_ok = all(assertion.get('pass', False) for assertion in assertion_results)
            step_status = 'pass' if (resp.status_code < 400 and business_ok and assertions_ok) else 'fail'
            failed_assertions = [item for item in assertion_results if not item.get('pass')]
            if failed_assertions and not fail_msg:
                fail_msg = '断言未通过: ' + '; '.join(
                    f"{a.get('type')}(期望 {a.get('expected')}，实际 {a.get('actual')})"
                    for a in failed_assertions[:3]
                )
            item.update({
                'status': step_status,
                'passed': step_status == 'pass',
                'http_status': resp.status_code,
                'message': fail_msg if (not business_ok or failed_assertions) else (item.get('message') or ''),
                'response_body': resp.text[:50000],
                'captured': captured,
                'assertion_results': assertion_results,
                'time_ms': elapsed_ms,
            })
        except Exception as e:
            logger.error(f'Agent 执行步骤失败 [{name}]: {e}')
            item.update({'status': 'error', 'message': str(e)[:200],
                         'time_ms': int((time.time() - st) * 1000)})
        results.append(item)
        if stop_on_failure and item.get('status') != 'pass':
            break

    # 失败即停：剩余步骤标成 skipped，避免前端看到「步数变少」误以为被丢弃
    if stop_on_failure and len(results) < len(steps):
        for rest in steps[len(results):]:
            results.append({
                'interface': rest.get('interface') or '',
                'name': rest.get('interface') or '',
                'request_id': rest.get('request_id'),
                'index': len(results) + 1,
                'status': 'skip',
                'message': '前序步骤失败，已跳过',
                'time_ms': 0,
            })

    execution_id = None
    if execution is not None:
        passed_count = sum(1 for result in results if result.get('status') == 'pass')
        failed_count = sum(1 for result in results if result.get('status') in ('fail', 'error'))
        execution.end_time = timezone.now()
        execution.passed_requests = passed_count
        execution.failed_requests = failed_count
        execution.status = 'COMPLETED' if failed_count == 0 and len(results) == len(steps) else 'FAILED'
        execution.results = results
        execution.save()
        execution_id = execution.id

    return Response({'results': results, 'session_vars': session_vars, 'execution_id': execution_id})
