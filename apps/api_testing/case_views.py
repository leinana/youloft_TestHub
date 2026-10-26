"""
测试用例 API — 生成、查看、确认、删除
"""
import json, asyncio, logging, re
from django.utils import timezone
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import ApiRequest, ParameterAnalysis, ApiGeneratedCase, ApiClarification
from .param_analyzer import _get_ai_config
from .case_generator import generate_test_cases, _get_test_execution_prompt

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_cases(request):
    """为指定接口生成测试用例（基于已确认的参数分析）"""
    request_ids = request.data.get('request_ids', [])
    if not request_ids:
        return Response({'error': '未提供 request_ids'}, status=400)

    ai_config = _get_ai_config()
    if not ai_config:
        return Response({'error': '未配置 AI 模型'}, status=500)

    ids = [int(x) for x in request_ids]
    total_generated = 0
    errors = []

    for rid in ids:
        try:
            req = ApiRequest.objects.get(id=rid)
            pa = ParameterAnalysis.objects.filter(api_request=req).first()
            if not pa:
                errors.append(f'[{rid}] 未找到参数分析')
                continue

            api_data = {
                'name': req.name,
                'method': req.method,
                'url': req.url or '',
                'res_body': req.res_body,
                'res_body_type': req.res_body_type or '',
                'res_body_is_json_schema': req.res_body_is_json_schema,
            }
            param_analysis = pa.analysis

            # 有澄清记录即可生成（不要求已确认）；没有则不带澄清上下文
            cl = ApiClarification.objects.filter(api_request=req).first()
            clarification = None
            if cl:
                clarification = {'questions': cl.questions, 'clarified': cl.clarified}

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cases = loop.run_until_complete(
                generate_test_cases(api_data, param_analysis, ai_config, clarification=clarification)
            )
            loop.close()
            # 确定性修正断言（边界/异常 → 业务码≠0，正常 → 业务码=0）
            cases = _normalize_generated_cases(cases, req)
            # 校正请求体位置（AI 可能把 body 放进了 params）
            cases = _normalize_case_body(cases, req)
            # 需要真实数据的参数 → 改成 {{变量}} 引用
            cases = _apply_data_source_vars(cases, param_analysis)
            logger.info(f'Generated {len(cases)} cases for request {rid}')

            # 重新生成：替换该接口旧用例（仅当新用例非空时删除，避免生成失败导致旧用例丢失）
            if cases:
                ApiGeneratedCase.objects.filter(api_request=req).delete()
            else:
                errors.append(f'[{rid}] AI 未生成有效用例，保留旧用例')

            # 保存用例
            for c in cases:
                ApiGeneratedCase.objects.create(
                    api_request=req,
                    name=c.get('name', f'用例 {total_generated+1}'),
                    scenario=c.get('scenario', 'normal'),
                    priority=c.get('priority', 'P2'),
                    method=c.get('method', req.method),
                    url=c.get('url', req.url or ''),
                    headers=c.get('headers', {}),
                    params=c.get('params', {}),
                    body=c.get('body', {}),
                    assertions=c.get('assertions', []),
                    expected_status=c.get('expected_status'),
                )
                total_generated += 1

        except Exception as e:
            logger.error(f'生成用例失败 [{rid}]: {e}')
            errors.append(f'[{rid}] {str(e)[:100]}')

    return Response({'generated': total_generated, 'errors': errors})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_cases(request):
    """列出测试用例"""
    request_id = request.query_params.get('request_id')
    qs = ApiGeneratedCase.objects.select_related('api_request').all()
    if request_id:
        qs = qs.filter(api_request_id=int(request_id))

    data = [{
        'id': c.id,
        'request_id': c.api_request_id,
        'request_name': c.api_request.name,
        'name': c.name,
        'scenario': c.scenario,
        'scenario_label': c.get_scenario_display(),
        'priority': c.priority,
        'method': c.method,
        'url': c.url,
        'headers': c.headers,
        'params': c.params,
        'body': c.body,
        'assertions': c.assertions,
        'expected_status': c.expected_status,
        'enabled': c.enabled,
        'confirmed': c.confirmed,
        'executed': c.executed,
        'last_status': c.last_status,
        'executed_at': c.executed_at,
        'response_time': c.response_time,
        'error_message': c.error_message,
    } for c in qs.order_by('priority', 'scenario')]  # 优先级从高到低：P0 → P3

    return Response({'cases': data, 'total': len(data)})


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_case(request, case_id):
    """更新单个用例（编辑参数、启用/禁用、确认）"""
    try:
        c = ApiGeneratedCase.objects.get(id=case_id)
    except ApiGeneratedCase.DoesNotExist:
        return Response({'error': '用例不存在'}, status=404)

    for field in ['name', 'scenario', 'priority', 'method', 'url', 'expected_status',
                  'enabled', 'confirmed']:
        if field in request.data:
            setattr(c, field, request.data[field])
    for field in ['headers', 'params', 'body', 'assertions']:
        if field in request.data:
            setattr(c, field, request.data[field])
    c.save()
    return Response({'status': 'ok'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_case(request, case_id):
    """删除单个用例"""
    ApiGeneratedCase.objects.filter(id=case_id).delete()
    return Response({'status': 'ok'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def batch_confirm_cases(request):
    """批量确认用例"""
    request_id = request.data.get('request_id')
    if not request_id:
        return Response({'error': '未提供 request_id'}, status=400)
    count = ApiGeneratedCase.objects.filter(
        api_request_id=int(request_id)
    ).update(confirmed=True)
    return Response({'confirmed': count})


def _resolve_case_vars(value, variables):
    """把 {{key}} 替换为环境变量值"""
    if not isinstance(value, str):
        return value
    result = value
    for k, v in (variables or {}).items():
        if isinstance(v, dict):
            v = v.get('currentValue') or v.get('initialValue') or ''
        result = result.replace('{{%s}}' % k, str(v) if v is not None else '')
    return result


def _resolve_case_vars_in_obj(data, variables):
    """递归解析对象/数组/字符串中的变量"""
    if isinstance(data, dict):
        return {k: _resolve_case_vars_in_obj(v, variables) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_case_vars_in_obj(v, variables) for v in data]
    return _resolve_case_vars(data, variables)


def _normalize_generated_cases(cases, api_request):
    """确定性修正 AI 生成的用例断言：
    - 边界/异常场景：业务码 ≠ 0（非法输入被拒绝），不猜具体错误码
    - 正常场景：HTTP 状态码 + 成功时关键字段存在（不猜具体业务码，各系统成功码不同）
    """
    # 从响应结构推断业务码字段（status/code/errcode/error_code）
    code_field = 'status'
    rb = getattr(api_request, 'res_body', None)
    if isinstance(rb, dict):
        props = rb.get('properties') or {}
        for name in ('status', 'code', 'errcode', 'error_code'):
            if name in props:
                code_field = name
                break
    code_path = f'$.{code_field}'

    normalized = []
    for c in cases:
        c = dict(c)
        scenario = c.get('scenario', 'normal')
        if scenario in ('boundary', 'exception'):
            # 非法输入：只断言业务码非 0（被拒绝），避免猜具体错误码/HTTP状态
            c['assertions'] = [
                {'type': 'json_path_neq', 'path': code_path, 'expected': 0},
            ]
        else:
            # 正常场景：HTTP 状态码 + 成功时关键字段存在（有 data 字段就断言 data 存在，避免猜业务码）
            assertions = [{'type': 'status_code', 'expected': c.get('expected_status') or 200}]
            if isinstance(rb, dict):
                props = rb.get('properties') or {}
                if 'data' in props:
                    assertions.append({'type': 'json_path_exists', 'path': '$.data'})
                elif code_path != '$.status':
                    assertions.append({'type': 'json_path_exists', 'path': code_path})
            c['assertions'] = assertions
        if not c.get('assertions'):
            c['assertions'] = [{'type': 'status_code', 'expected': c.get('expected_status') or 200}]
        normalized.append(c)
    return normalized


def _set_by_path(obj, path, value):
    """按点路径设置值（如 data.starter_user_id）"""
    cur = obj
    parts = (path or '').split('.')
    for i, seg in enumerate(parts):
        if not seg:
            continue
        if not isinstance(cur, dict):
            return False
        if i == len([p for p in parts if p]) - 1:
            cur[seg] = value
            return True
        nxt = cur.get(seg)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[seg] = nxt
        cur = nxt
    return False


def _resolve_var_typed(var_name, env_vars, project, session_cache=None, depth=0, allow_history=True):
    """解析单个变量的真实类型值（环境变量 → 历史响应 → 上游接口），保留数字等原始类型"""
    val = env_vars.get(var_name)
    if val in (None, ''):
        val = _find_from_history(var_name, project, allow_history)
    if val in (None, '') and project is not None and '.' in var_name:
        upstream_name, path = var_name.split('.', 1)
        val = _call_upstream(upstream_name, path, project, session_cache, depth)
    return val


def _resolve_real_data_in_obj(data, env_vars, project, session_cache=None, depth=0, missing_accum=None,
                              allow_history=True):
    """递归解析对象/数组/字符串中的 {{变量}}（真实数据），缺失时收集 missing"""
    if missing_accum is None:
        missing_accum = []
    if isinstance(data, dict):
        return {k: _resolve_real_data_in_obj(v, env_vars, project, session_cache, depth, missing_accum,
                                             allow_history) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_real_data_in_obj(v, env_vars, project, session_cache, depth, missing_accum,
                                          allow_history) for v in data]
    if isinstance(data, str) and '{{' in data:
        # 整个字段就是 {{var}} 时，保留变量的原始类型（如 diary_id 为数字）
        m = re.fullmatch(r'\{\{([^}]+)\}\}', data.strip())
        if m:
            val = _resolve_var_typed(m.group(1), env_vars, project, session_cache, depth, allow_history)
            if val in (None, ''):
                missing_accum.append(m.group(1))
                return data
            return val
        resolved, missing = _resolve_real_data({'v': data}, env_vars, project, session_cache, depth,
                                               allow_history)
        if missing:
            missing_accum.extend(missing)
            return data
        return resolved.get('v', data)
    return data


def _get_by_path(obj, path):
    """按点路径取值：data.challenge_id → obj['data']['challenge_id']（数组取第一个元素）"""
    cur = obj
    for seg in (path or '').split('.'):
        if not seg:
            continue
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, list) and cur:
            cur = cur[0].get(seg) if isinstance(cur[0], dict) else None
        else:
            return None
        if cur is None:
            return None
    return cur if cur not in (None, '') else None


def _deep_get(obj, key):
    """递归在 JSON 中查找第一个 key 匹配的非空值"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and v not in (None, ''):
                return v
            r = _deep_get(v, key)
            if r not in (None, ''):
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_get(item, key)
            if r not in (None, ''):
                return r
    return None


def _call_upstream(upstream_name, path, project, session_cache, depth=0, allow_history=True):
    """自动调用上游接口，从响应中提取指定路径的值（同会话缓存 + 深度限制防循环）"""
    if depth > 5:
        return None
    if session_cache is None:
        session_cache = {}
    if upstream_name in session_cache:
        return session_cache.get(upstream_name)
    from .models import ApiRequest
    # 未归属集合的接口（手工新建没选版本）也要能找到，否则上游取数永远落空
    qs = ApiRequest.objects.filter(Q(collection__project=project) | Q(collection__isnull=True))
    req = qs.filter(name__iexact=upstream_name).first() or qs.filter(name__icontains=upstream_name).first()
    if not req:
        session_cache[upstream_name] = None
        return None

    import requests as http_req
    from .models import Environment
    env = None
    if req.collection and req.collection.project:
        env = Environment.objects.filter(project=req.collection.project, is_active=True).first()
    if env is None:
        env = Environment.objects.filter(is_active=True).first()
    env_vars = dict(env.variables or {}) if env else {}
    dheaders = [h for h in (env.default_headers or []) if h.get('enabled', True)] if env else []
    dparams = [p for p in (env.default_params or []) if p.get('enabled', True)] if env else []
    # 环境公参值并入变量表，便于 {{userid}}/{{pairid}} 等解析
    for _dp in dparams:
        if _dp.get('key') and _dp.get('key') not in env_vars:
            env_vars[_dp['key']] = _dp.get('value', '')

    url = req.url or ''
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
    for p in dparams:
        k = p.get('key')
        if k and k not in params:
            params[k] = _resolve_case_vars(p.get('value', ''), env_vars)
    # 上游接口自身参数（含 {{变量}} 递归解析）
    for p in (req.params or []):
        if isinstance(p, dict) and p.get('enabled') is False:
            continue
        k = p.get('key') if isinstance(p, dict) else None
        if k:
            params[k] = _resolve_case_vars(p.get('value', '') or '', env_vars)
    params, _missing = _resolve_real_data(params, env_vars, project, session_cache, depth + 1, allow_history)
    url = _resolve_case_vars(url, env_vars)
    headers = {k: _resolve_case_vars(v, env_vars) for k, v in headers.items()}

    try:
        if isinstance(req.body, dict) and req.body.get('type') == 'json' and isinstance(req.body.get('data'), dict):
            body_data = _resolve_case_vars_in_obj(req.body['data'], env_vars)
            resp = http_req.request(method=method, url=url, headers=headers, params=params, json=body_data, timeout=30)
        else:
            resp = http_req.request(method=method, url=url, headers=headers, params=params, timeout=30)
        body = resp.json()
        val = _get_by_path(body, path)
    except Exception:
        val = None
    session_cache[upstream_name] = val
    return val


def _find_from_history(var_name, project, allow_history=True):
    """从项目最近的成功请求历史响应里查找字段值（支持 data.challenge_id 取末段）

    allow_history=False 时禁用该兜底：历史数据可能来自其他场景，容易捞到脏值。
    """
    if not allow_history:
        return None
    from .models import RequestHistory
    key = var_name.split('.')[-1]
    qs = RequestHistory.objects.filter(
        Q(request__collection__project=project) | Q(request__collection__isnull=True)
    ).order_by('-executed_at')
    for h in qs[:80]:
        rd = h.response_data or {}
        body = rd.get('json')
        if body is None and rd.get('body'):
            try:
                body = json.loads(rd['body'])
            except Exception:
                body = None
        val = _deep_get(body, key)
        if val not in (None, ''):
            return val
    return None


def _resolve_real_data(params, env_vars, project, session_cache=None, depth=0, allow_history=True):
    """解析用例参数里的 {{变量}}：环境变量 → 历史成功响应 → 自动调用上游接口；返回 (resolved_params, missing_vars)"""
    if not isinstance(params, dict):
        return params, []
    resolved = {}
    missing = []
    for k, v in params.items():
        if isinstance(v, str) and '{{' in v:
            out = v
            var_names = re.findall(r'\{\{([^}]+)\}\}', v)
            ok = True
            for vn in var_names:
                val = env_vars.get(vn)
                if val in (None, ''):
                    val = _find_from_history(vn, project, allow_history)
                if val in (None, '') and project is not None and '.' in vn:
                    # 上游接口依赖：接口名.响应路径
                    upstream_name, path = vn.split('.', 1)
                    val = _call_upstream(upstream_name, path, project, session_cache, depth, allow_history)
                if val in (None, ''):
                    ok = False
                    missing.append(vn)
                    break
                out = out.replace('{{' + vn + '}}', str(val))
            resolved[k] = out if ok else v
        else:
            resolved[k] = v
    return resolved, list(dict.fromkeys(missing))


def _normalize_case_body(cases, api_request):
    """校正 AI 生成时把请求体放错位置：接口有 body 时，若用例 body 为空而 params 里像 body（含 data/type 键），搬移到 body"""
    req_body = getattr(api_request, 'body', None)
    has_body = isinstance(req_body, dict) and req_body.get('type') not in (None, '', 'none')
    if not has_body:
        return cases
    for c in cases:
        if not isinstance(c.get('body'), dict) or not c['body']:
            cp = c.get('params')
            if isinstance(cp, dict) and ('type' in cp or 'data' in cp):
                c['body'] = cp
                c['params'] = {}
    return cases


def _apply_data_source_vars(cases, param_analysis):
    """对参数分析里标注了 needs_real_data 的参数，把用例参数改为 {{变量}} 引用，避免用假值执行"""
    if not param_analysis or not isinstance(param_analysis, dict):
        return cases
    params_def = param_analysis.get('parameters') or []
    mapping = {}
    for p in params_def:
        if isinstance(p, dict) and p.get('needs_real_data'):
            key = p.get('name') or p.get('key')
            src = (p.get('data_source') or key or '').strip()
            if key and src:
                mapping[key] = '{{' + src + '}}'
    if not mapping:
        return cases
    for c in cases:
        # 边界/异常用例故意用非法值测试校验逻辑，不用真实数据；只对正常场景变量化
        if c.get('scenario') not in ('normal', 'biz'):
            continue
        cparams = c.get('params') or {}
        cbody = c.get('body')
        changed = False
        for k, v in mapping.items():
            # URL 参数
            if k in cparams and not (isinstance(cparams[k], str) and cparams[k].startswith('{{')):
                cparams[k] = v
                changed = True
            # 请求体字段（点路径，如 data.starter_user_id）
            if isinstance(cbody, dict) and '.' in k:
                cur_val = _get_by_path(cbody, k)
                if cur_val not in (None, '') and not (isinstance(cur_val, str) and cur_val.startswith('{{')):
                    _set_by_path(cbody, k, v)
                    changed = True
        if changed:
            c['params'] = cparams
    return cases


def _regenerate_cases(req):
    """按最新的参数分析 + 澄清重新生成该接口的用例（替换旧用例），返回生成条数"""
    pa = ParameterAnalysis.objects.filter(api_request=req).first()
    if not pa:
        return 0
    cl = ApiClarification.objects.filter(api_request=req).first()
    clarification = None
    if cl:
        clarification = {'questions': cl.questions, 'clarified': cl.clarified}
    ai_config = _get_ai_config()
    if not ai_config:
        return 0
    api_data = {
        'name': req.name, 'method': req.method, 'url': req.url or '',
        'res_body': req.res_body, 'res_body_type': req.res_body_type or '',
        'res_body_is_json_schema': req.res_body_is_json_schema,
    }
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        cases = loop.run_until_complete(
            generate_test_cases(api_data, pa.analysis, ai_config, clarification=clarification)
        )
    finally:
        loop.close()
    cases = _normalize_generated_cases(cases, req)
    # 校正请求体位置（AI 可能把 body 放进了 params）
    cases = _normalize_case_body(cases, req)
    # 需要真实数据的参数 → 改成 {{变量}} 引用
    cases = _apply_data_source_vars(cases, pa.analysis)
    if not cases:
        return 0
    ApiGeneratedCase.objects.filter(api_request=req).delete()
    for c in cases:
        ApiGeneratedCase.objects.create(
            api_request=req,
            name=c.get('name', '用例'),
            scenario=c.get('scenario', 'normal'),
            priority=c.get('priority', 'P2'),
            method=c.get('method', req.method),
            url=c.get('url', req.url or ''),
            headers=c.get('headers', {}),
            params=c.get('params', {}),
            body=c.get('body', {}),
            assertions=c.get('assertions', []),
            expected_status=c.get('expected_status'),
        )
    return len(cases)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def execute_cases(request):
    """执行指定接口的已确认用例，发送真实HTTP请求并运行断言"""
    request_id = request.data.get('request_id')
    case_ids = request.data.get('case_ids')
    if not request_id and not case_ids:
        return Response({'error': '未提供 request_id 或 case_ids'}, status=400)

    # 重置范围：该接口（或指定 case_ids）的全部用例，包含停用的；执行时只跑启用的
    if case_ids:
        reset_qs = ApiGeneratedCase.objects.filter(id__in=case_ids)
        cases = reset_qs.filter(enabled=True)
    else:
        reset_qs = ApiGeneratedCase.objects.filter(api_request_id=int(request_id))
        cases = reset_qs.filter(enabled=True)

    # 检测用例是否过期：参数分析/澄清在用例生成之后有更新 → 自动重新生成后再执行
    regenerated = 0
    if request_id and not case_ids:
        from .models import ParameterAnalysis, ApiClarification
        _rid = int(request_id)
        _pa = ParameterAnalysis.objects.filter(api_request_id=_rid).first()
        _cl = ApiClarification.objects.filter(api_request_id=_rid).first()
        cfg_times = [x.updated_at for x in (_pa, _cl) if x and x.updated_at]
        # 接口本身（URL/参数/请求体等）有改动也视为用例过期，执行时自动重新生成
        _req_updated = ApiRequest.objects.filter(id=_rid).values_list('updated_at', flat=True).first()
        if _req_updated:
            cfg_times.append(_req_updated)
        latest_cfg = max(cfg_times) if cfg_times else None
        latest_case_created = ApiGeneratedCase.objects.filter(api_request_id=_rid).order_by('-created_at').values_list('created_at', flat=True).first()
        if latest_cfg and latest_case_created and latest_cfg > latest_case_created:
            try:
                _req = ApiRequest.objects.get(id=_rid)
                regenerated = _regenerate_cases(_req)
                if regenerated:
                    logger.info(f'[execute] 参数分析/澄清已更新，自动重新生成 {regenerated} 条用例后执行（request {_rid}）')
                    reset_qs = ApiGeneratedCase.objects.filter(api_request_id=_rid)
                    cases = reset_qs.filter(enabled=True)
            except Exception as e:
                logger.error(f'[execute] 自动重新生成用例失败: {e}')

    # 重复执行同一接口时，先重置上次的执行记录，避免旧结果残留
    reset_qs.update(
        executed=False, last_status=None, response_time=None,
        error_message='', executed_at=None,
    )

    import requests as req, time, json

    upstream_cache = {}
    # 环境公参依赖：参数分析标注了 needs_real_data 的 env 参数（如 userid/pairid），执行前优先用上游/历史真实值覆盖
    env_real_overrides = {}
    if request_id and not case_ids:
        from .models import Environment
        _req0 = ApiRequest.objects.filter(id=int(request_id)).select_related('collection__project').first()
        _proj = _req0.collection.project if (_req0 and _req0.collection) else None
        _env = None
        if _proj:
            _env = Environment.objects.filter(project=_proj, is_active=True).first()
        if _env is None:
            _env = Environment.objects.filter(is_active=True).first()
        _env_vars = dict(_env.variables or {}) if _env else {}
        if _env:
            # 环境公参依赖：default_params 里勾选「需真实」并填了数据来源的参数，执行前优先用真实值覆盖
            for p in (_env.default_params or []):
                if not (isinstance(p, dict) and p.get('enabled', True) is not False and p.get('needs_real_data')):
                    continue
                key = p.get('key')
                src = p.get('data_source') or key
                if not key or not src:
                    continue
                resolved, missing = _resolve_real_data({key: '{{' + src + '}}'}, _env_vars, _proj, upstream_cache)
                if not missing and resolved.get(key) not in (None, ''):
                    env_real_overrides[key] = resolved[key]
    results = []
    passed = 0; failed = 0; errors = 0; skipped = 0

    for c in cases:
        start = time.time()
        result = {'case_id': c.id, 'name': c.name}
        try:
            # 构建请求
            url = c.url or c.api_request.url
            method = (c.method or 'GET').upper()
            if not url:
                raise ValueError('URL is empty')

            # 加载项目环境（默认请求头 / 默认参数 / 环境变量，含 base_url、userid、鉴权头）
            from .models import Environment
            env = None
            api_project = c.api_request.collection.project if c.api_request.collection else None
            if api_project:
                env = Environment.objects.filter(project=api_project, is_active=True).first()
            if env is None:
                env = Environment.objects.filter(is_active=True).first()
            env_vars = dict(env.variables or {}) if env else {}
            default_headers = [h for h in (env.default_headers or []) if h.get('enabled', True)] if env else []
            default_params = [p for p in (env.default_params or []) if p.get('enabled', True)] if env else []
            # 环境公参值并入变量表，便于 {{userid}}/{{pairid}} 等解析
            for _dp in default_params:
                if _dp.get('key') and _dp.get('key') not in env_vars:
                    env_vars[_dp['key']] = _dp.get('value', '')

            # 补全相对路径 / 解析 base_url
            base_url = str(env_vars.get('base_url') or '').rstrip('/')
            if not url.startswith('http'):
                if base_url:
                    url = base_url + (url if url.startswith('/') else '/' + url)
                else:
                    orig_url = c.api_request.url or ''
                    if orig_url.startswith('http'):
                        from urllib.parse import urlparse
                        parsed = urlparse(orig_url)
                        url = f'{parsed.scheme}://{parsed.netloc}{url}'
                    else:
                        raise ValueError(f'Cannot resolve relative URL: {url}')

            headers = c.headers if isinstance(c.headers, dict) else {}
            # 合并环境默认请求头（用例已有的 key 优先）
            for h in default_headers:
                key = h.get('key')
                if key and key not in headers:
                    headers[key] = _resolve_case_vars(h.get('value', ''), env_vars)

            params = c.params if isinstance(c.params, dict) else {}
            # 合并环境默认参数（用例已有的 key 优先）
            for p in default_params:
                key = p.get('key')
                if key and key not in params:
                    params[key] = _resolve_case_vars(p.get('value', ''), env_vars)

            # 解析变量（URL / headers / params / body）
            url = _resolve_case_vars(url, env_vars)
            headers = {k: _resolve_case_vars(v, env_vars) for k, v in headers.items()}
            params = {k: _resolve_case_vars(v, env_vars) for k, v in params.items()}
            # 环境公参真实值覆盖（如 userid/pairid 用上游取到的真实值）
            for k, v in env_real_overrides.items():
                params[k] = v
            # 解析真实数据（环境变量 → 历史成功响应 → 上游接口），缺失则标记数据不足并跳过
            # headers 与 url 也走同一条链路：真实系统的鉴权 token 几乎都在 header，
            # RESTful 路径参数（/order/{{orderId}}）则在 url，二者都必须支持上游取值
            headers, header_missing = _resolve_real_data(headers, env_vars, api_project, upstream_cache)
            if isinstance(url, str) and '{{' in url:
                _url_resolved, url_missing = _resolve_real_data(
                    {'url': url}, env_vars, api_project, upstream_cache)
                url = _url_resolved.get('url', url)
            else:
                url_missing = []
            params, missing_vars = _resolve_real_data(params, env_vars, api_project, upstream_cache)
            missing_vars = missing_vars + header_missing + url_missing
            # 请求体里的 {{变量}} 也走真实数据解析（如 body.data.starter_user_id）
            # 提取请求体 payload（body 是 {type, data} 包装，实际发送 data 部分）
            body_data = None
            is_json_body = False
            if isinstance(c.body, dict):
                _bt = c.body.get('type', 'none')
                _bc = c.body.get('data')
                if _bt == 'json' and isinstance(_bc, (dict, list)):
                    body_data = _bc
                    is_json_body = True
                elif _bt == 'raw':
                    body_data = _bc
                else:
                    body_data = _bc
            if body_data is not None:
                body_data = _resolve_case_vars_in_obj(body_data, env_vars)
                body_missing = []
                body_data = _resolve_real_data_in_obj(body_data, env_vars, api_project, upstream_cache, 0, body_missing)
                missing_vars = missing_vars + body_missing
            if missing_vars:
                msg = '数据不足：缺少真实数据 ' + '、'.join('{{%s}}' % v for v in missing_vars) + '（请先手动调用上游接口，或配置环境变量）'
                result['status'] = 'skip'
                result['error_message'] = msg
                results.append(result)
                skipped += 1
                c.executed = True
                c.last_status = 'skip'
                c.response_time = int((time.time() - start) * 1000)
                c.error_message = msg
                c.executed_at = timezone.now()
                c.save(update_fields=['executed', 'last_status', 'response_time', 'error_message', 'executed_at'])
                continue
            if is_json_body:
                resp = req.request(method=method, url=url, headers=headers,
                                  params=params, json=body_data if body_data is not None else None,
                                  timeout=30)
            else:
                resp = req.request(method=method, url=url, headers=headers,
                                  params=params, data=body_data if body_data is not None else None,
                                  timeout=30)
            elapsed = int((time.time() - start) * 1000)
            result['status_code'] = resp.status_code
            result['response_time'] = elapsed
            result['response_body'] = resp.text[:50000]

            # 运行断言
            assertion_results = _run_assertions(resp, c.assertions or [], elapsed)
            result['assertions'] = assertion_results

            # 判定结果
            all_pass = all(a.get('pass') for a in assertion_results)
            if assertion_results and all_pass:
                result['status'] = 'pass'
                passed += 1
            elif assertion_results:
                result['status'] = 'fail'
                failed += 1
            else:
                result['status'] = 'pass'  # 无断言视为通过
                passed += 1

        except Exception as e:
            result['status'] = 'error'
            result['error_message'] = str(e)[:500]
            result['response_time'] = int((time.time() - start) * 1000)
            errors += 1

        results.append(result)

        # 更新用例执行状态
        c.executed = True
        c.last_status = result.get('status', 'error')
        c.response_time = result.get('response_time')
        # 把断言详情存进 error_message 字段（前端可解析展示）
        c.error_message = json.dumps({
            'assertions': result.get('assertions', []),
            'status_code': result.get('status_code'),
            'response_body': result.get('response_body', '')[:1000],
        }, ensure_ascii=False)
        c.executed_at = timezone.now()
        c.save(update_fields=['executed', 'last_status', 'response_time', 'error_message', 'executed_at'])

    return Response({
        'results': results,
        'total': len(results),
        'passed': passed, 'failed': failed, 'errors': errors, 'skipped': skipped,
        'regenerated': regenerated,
    })


def _run_assertions(resp, assertions: list, elapsed_ms: int) -> list:
    """执行断言列表"""
    results = []
    for a in assertions:
        a_type = a.get('type', '')
        expected = a.get('expected')
        r = {'type': a_type, 'expected': expected}
        try:
            if a_type == 'status_code':
                r['actual'] = resp.status_code
                r['pass'] = resp.status_code == int(expected) if expected else True
            elif a_type == 'response_time':
                r['actual'] = elapsed_ms
                r['pass'] = elapsed_ms <= int(expected) if expected else True
            elif a_type == 'contains':
                r['actual'] = '(text match)'
                r['pass'] = str(expected) in resp.text if expected else True
            elif a_type == 'json_path':
                try:
                    body = resp.json()
                    path = a.get('path', '')
                    val = _json_path_get(body, path)
                    r['actual'] = str(val)[:100]
                    r['pass'] = str(val) == str(expected) if expected is not None else True
                except Exception:
                    r['actual'] = '(parse error)'
                    r['pass'] = False
            elif a_type == 'json_path_neq':
                # 校验 JSON 路径的值不等于 expected（用于不确定具体错误码的拒绝断言）
                try:
                    body = resp.json()
                    path = a.get('path', '')
                    val = _json_path_get(body, path)
                    r['actual'] = str(val)[:100]
                    r['pass'] = str(val) != str(expected)
                except Exception:
                    r['actual'] = '(parse error)'
                    r['pass'] = False
            elif a_type == 'json_path_exists':
                # 只校验字段存在（值非 null），不比较具体值
                try:
                    body = resp.json()
                    path = a.get('path', '')
                    val = _json_path_get(body, path)
                    r['actual'] = str(val)[:100]
                    r['pass'] = val is not None
                except Exception:
                    r['actual'] = '(parse error)'
                    r['pass'] = False
            else:
                r['actual'] = '(unknown type)'
                r['pass'] = True  # 未知断言类型默认通过
        except Exception as e:
            r['pass'] = False
            r['error'] = str(e)[:100]
        results.append(r)
    return results


def _json_path_get(obj, path: str):
    """简单的 JSON path 取值"""
    parts = path.strip().lstrip('$').lstrip('.').split('.')
    cur = obj
    for p in parts:
        if not p: continue
        if '[' in p:
            name, idx = p.split('[', 1)
            idx = int(idx.rstrip(']'))
            cur = cur[name][idx]
        else:
            cur = cur[p] if isinstance(cur, dict) else cur[int(p)] if isinstance(cur, list) else None
    return cur


# ===== 报告 =====

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def case_report(request):
    """获取测试报告"""
    request_id = request.query_params.get('request_id')
    qs = ApiGeneratedCase.objects.select_related('api_request').all()
    if request_id:
        qs = qs.filter(api_request_id=int(request_id))

    executed = [c for c in qs if c.executed]
    total = qs.count()
    passed = sum(1 for c in executed if c.last_status == 'pass')
    failed = sum(1 for c in executed if c.last_status == 'fail')
    error = sum(1 for c in executed if c.last_status == 'error')
    avg_time = int(sum(c.response_time or 0 for c in executed) / max(len(executed), 1))

    details = [{
        'id': c.id,
        'name': c.name,
        'request_name': c.api_request.name,
        'scenario': c.scenario,
        'scenario_label': c.get_scenario_display(),
        'priority': c.priority,
        'method': c.method,
        'url': c.url,
        'expected_status': c.expected_status,
        'last_status': c.last_status,
        'response_time': c.response_time,
        'error_message': c.error_message,
        'executed': c.executed,
        'executed_at': c.executed_at,
    } for c in qs.order_by('priority', 'scenario')]  # 优先级从高到低：P0 → P3

    return Response({
        'summary': {
            'total': total, 'executed': len(executed),
            'passed': passed, 'failed': failed, 'errors': error,
            'avg_response_time': avg_time,
            'pass_rate': f'{int(passed/max(len(executed),1)*100)}%' if executed else 'N/A',
        },
        'cases': details,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_execution(request):
    """AI 分析接口测试执行结果（使用「接口测试执行提示词」配置）"""
    request_id = request.data.get('request_id')
    if not request_id:
        return Response({'error': '未提供 request_id'}, status=400)
    try:
        req = ApiRequest.objects.get(id=int(request_id))
    except ApiRequest.DoesNotExist:
        return Response({'error': '接口不存在'}, status=404)

    cases = ApiGeneratedCase.objects.filter(api_request=req).order_by('priority', 'scenario')
    executed = [c for c in cases if c.executed]
    if not executed:
        return Response({'error': '该接口尚未执行，请先点击「执行」'}, status=400)

    # 汇总执行结果
    lines = []
    for c in executed:
        status_label = {'pass': '通过', 'fail': '失败', 'error': '错误', 'skip': '跳过'}.get(c.last_status, c.last_status or '未执行')
        lines.append(f"### 用例：{c.name}（{c.get_scenario_display()} / {c.priority}）结果：{status_label}")
        lines.append(f"- 方法/地址：{c.method} {c.url}")
        if c.params:
            lines.append(f"- 参数：{json.dumps(c.params, ensure_ascii=False)[:300]}")
        if c.response_time is not None:
            lines.append(f"- 响应时间：{c.response_time}ms")
        try:
            detail = json.loads(c.error_message or '{}')
            if detail.get('status_code') is not None:
                lines.append(f"- HTTP 状态码：{detail.get('status_code')}")
            if detail.get('response_body'):
                lines.append(f"- 响应体：{str(detail.get('response_body'))[:400]}")
            for a in (detail.get('assertions') or [])[:8]:
                mark = '✅' if a.get('pass') else '❌'
                lines.append(f"  {mark} 断言 {a.get('type')} {a.get('path','')} 期望={a.get('expected')} 实际={a.get('actual')}")
        except Exception:
            if c.error_message:
                lines.append(f"- 错误：{c.error_message[:300]}")
        lines.append('')

    summary = '\n'.join(lines)

    template = _get_test_execution_prompt()
    prompt = template
    prompt = prompt.replace('[[method]]', str(req.method))
    prompt = prompt.replace('[[url]]', str(req.url or ''))
    prompt = prompt.replace('[[name]]', str(req.name))
    prompt = prompt.replace('[[execution_summary]]', summary)

    ai_config = _get_ai_config()
    if not ai_config:
        return Response({'error': '未配置 AI 模型'}, status=500)

    import asyncio, httpx
    messages = [
        {"role": "system", "content": "你是 API 测试结果分析专家。"},
        {"role": "user", "content": prompt},
    ]
    api_url = f'{ai_config["base_url"].rstrip("/")}/v1/chat/completions'
    body = {
        'model': ai_config['model_name'],
        'messages': messages,
        'max_tokens': 4096,
        'temperature': 0.3,
    }
    headers = {
        'Authorization': f'Bearer {ai_config["api_key"]}',
        'Content-Type': 'application/json',
    }

    async def _call():
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(api_url, headers=headers, json=body)
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        analysis = loop.run_until_complete(_call())
    finally:
        loop.close()

    return Response({'analysis': analysis})
