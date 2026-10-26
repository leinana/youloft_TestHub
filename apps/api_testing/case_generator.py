"""AI test case generator — generates test cases from parameter analysis"""
import json, re, logging, httpx
from typing import List, Dict

logger = logging.getLogger(__name__)


async def generate_test_cases(api_request: dict, param_analysis: dict, ai_config: dict, clarification: dict = None) -> List[dict]:
    name = api_request.get('name','')
    method = api_request.get('method','GET')
    url = api_request.get('url','')
    params = param_analysis.get('parameters',[])

    # 响应结构（来自 YApi 的接口返回定义），用于生成响应断言
    response_info = ''
    try:
        from .param_analyzer import _format_response
        response_info = _format_response(
            api_request.get('res_body'),
            api_request.get('res_body_type', ''),
            api_request.get('res_body_is_json_schema', False),
        )
    except Exception:
        pass

    prompt = _build_prompt(name, method, url, params, clarification, response_info)
    messages = [
        {"role":"system","content":"你是API测试工程师。只返回JSON数组，用```json包裹。"},
        {"role":"user","content": prompt},
    ]

    api_url = f'{ai_config["base_url"].rstrip("/")}/v1/chat/completions'
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(api_url,
            headers={'Authorization':f'Bearer {ai_config["api_key"]}','Content-Type':'application/json'},
            json={'model':ai_config['model_name'],'messages':messages,'max_tokens':16384,'temperature':0.2})
        r.raise_for_status()
        content = r.json()['choices'][0]['message']['content']

    logger.info(f'AI response: {len(content)} chars')

    # Extract ```json block or raw JSON array
    block = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    text = (block.group(1) if block else content).strip()

    # Parse with repair
    try:
        cases = json.loads(text, strict=False)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            cases = json.loads(repair_json(text))
        except Exception:
            arr = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text)
            if arr:
                try:
                    from json_repair import repair_json
                    cases = json.loads(repair_json(arr.group(0)))
                except Exception as e:
                    logger.error(f'JSON repair failed: {e}')
                    return []
            else:
                logger.error(f'No JSON array found')
                return []

    if isinstance(cases, dict):
        cases = cases.get('test_cases') or cases.get('cases') or []
    return cases if isinstance(cases, list) else []


DEFAULT_TESTCASE_WRITER_PROMPT = """为以下API设计测试用例，包含请求参数和断言。

接口: [[method]] [[url]]
名称: [[name]]

【参数定义】
[[param_info]]
[[response_info]]
【要求】
1. 只考虑两类流程：正向流程（正常成功调用）生成 1~2 条；必传参数异常流程（必传参数缺失/为空/类型错误/非法值被拒绝）生成 2~3 条
2. 全部用例总数不超过 5 条
3. 每条用例包含: name, scenario(normal/boundary/exception), params, body, expected_status, assertions, priority(P0-P3)
4. 断言类型: status_code(HTTP状态码), json_path($.xxx 精确等于expected), json_path_exists($.xxx 只校验字段存在,不需要expected), json_path_neq($.xxx 不等于expected), contains(响应包含文本), response_time(毫秒)
5. 断言生成规则（务必遵守）:
   - 【响应结构】里的 description 只是字段含义说明，不是真实期望值，禁止把它当 expected 用
   - 只有确定的值才用 json_path 精确断言（如业务状态码、枚举值、固定code）；不确定的值用 json_path_exists 只校验字段存在
   - 正常场景：业务码字段（如 status/code）用 json_path 断言 = 0；边界/异常场景（非法输入被拒绝）：业务码用 json_path_neq 断言 != 0，不要猜具体错误码，可再用 contains 断言错误信息关键词
   - 错误提示类字段（msg/error）用 contains 断言关键词，不要精确匹配整句
   - 业务错误通常是 HTTP 200 + body 内业务码（如 status/code），此时 status_code 断言用 200，业务码用 json_path 断言
   - 请求参数值必须真实合理：id 类参数用整数（如 1001），禁止用 valid_xxx / xxx_123 之类的占位字符串
   - 超长字符串场景控制在 50~100 个字符即可，不要生成超长文本
   - 每条用例至少包含 1 条断言，禁止空断言
[[clarification]]
```json
[{"name":"正常场景","scenario":"normal","params":{"id":1001},"body":{},"expected_status":200,"assertions":[{"type":"status_code","expected":200},{"type":"json_path","path":"$.status","expected":0},{"type":"json_path_exists","path":"$.data"}],"priority":"P0"}]
```"""


def _get_testcase_writer_prompt() -> str:
    """获取用例生成提示词：优先使用激活的数据库配置，未配置则用内置默认"""
    try:
        from .models import ApiPromptConfig
        cfg = ApiPromptConfig.objects.filter(
            prompt_type='api_testcase_writer', is_active=True
        ).first()
        if cfg and cfg.content and cfg.content.strip():
            return cfg.content
    except Exception:
        pass
    return DEFAULT_TESTCASE_WRITER_PROMPT


def _build_prompt(name, method, url, params, clarification=None, response_info=''):
    template = _get_testcase_writer_prompt()
    pt = json.dumps(params, ensure_ascii=False, indent=2)
    clarity = ''
    if clarification and clarification.get('questions'):
        qa = []
        for q in clarification['questions']:
            qa.append(f"Q: {q.get('question','')}\nA: {q.get('answer','')}")
        clarity = '\n'.join(qa)

    resp = ''
    if response_info and response_info != '无':
        resp = f"\n【响应结构】（接口返回定义，生成断言时必须参考）\n{response_info}\n"

    prompt = template
    prompt = prompt.replace('[[method]]', str(method))
    prompt = prompt.replace('[[url]]', str(url))
    prompt = prompt.replace('[[name]]', str(name))
    prompt = prompt.replace('[[param_info]]', pt)
    prompt = prompt.replace('[[response_info]]', resp)
    prompt = prompt.replace('[[clarification]]', clarity)
    return prompt


DEFAULT_TEST_EXECUTION_PROMPT = """你是资深的 API 测试工程师。以下是一次接口测试执行的结果，请分析执行情况并给出结论与修复建议。

# 接口信息
- 方法/地址：[[method]] [[url]]
- 接口名称：[[name]]

# 执行结果明细
[[execution_summary]]

# 分析要求
1. 用一小段话概括整体执行情况（通过/失败/错误数量、接口是否正常）。
2. 对失败的用例逐条分析失败原因，归类为以下一种或多种：
   - 测试数据问题：如参数缺真实值、用了占位/非法值、缺少环境变量
   - 断言问题：期望值与实际响应不符、期望值本身不合理（如把字段说明当期望值）
   - 环境/接口问题：鉴权失败、服务异常、响应结构变化
3. 对每条失败给出可操作的修复建议（改参数值、改断言、补环境变量等）。
4. 最后给出一条总体结论：该接口当前是否可以信任、下一步建议。

输出 Markdown 格式，不要输出 JSON。"""


def _get_test_execution_prompt() -> str:
    """获取接口测试执行提示词：优先使用激活的数据库配置，未配置则用内置默认"""
    try:
        from .models import ApiPromptConfig
        cfg = ApiPromptConfig.objects.filter(
            prompt_type='api_test_execution', is_active=True
        ).first()
        if cfg and cfg.content and cfg.content.strip():
            return cfg.content
    except Exception:
        pass
    return DEFAULT_TEST_EXECUTION_PROMPT
