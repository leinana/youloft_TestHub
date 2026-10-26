const clone = (value) => {
  if (value === undefined) return undefined
  return JSON.parse(JSON.stringify(value))
}

const GENERIC_FIELDS = new Set(['id', 'code', 'type', 'status', 'name', 'value', 'data'])

export function normalizeName(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]/g, '')
}

export function inferType(value, explicitType = '') {
  if (explicitType) return explicitType
  if (Array.isArray(value)) return 'array'
  if (value === null) return 'null'
  if (typeof value === 'object') return 'object'
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number'
  return typeof value || 'string'
}

export function normalizeParams(params) {
  if (!params) return {}
  if (Array.isArray(params)) {
    return params.reduce((result, item) => {
      if (item && item.key && item.enabled !== false) {
        result[item.key] = item.value ?? item.example ?? ''
      }
      return result
    }, {})
  }
  const result = {}
  Object.entries(params).forEach(([key, value]) => {
    result[key] = value && typeof value === 'object' && !Array.isArray(value)
      ? value.value ?? value.example ?? ''
      : clone(value)
  })
  return result
}

export function normalizeBody(body) {
  if (body === null || body === undefined) return null
  if (typeof body !== 'object') return clone(body)
  const data = Object.prototype.hasOwnProperty.call(body, 'data') ? body.data : body
  if (Array.isArray(data) && data.every((item) => item && (item.key || item.name))) {
    return data.reduce((result, item) => {
      if (item.enabled !== false) result[item.key || item.name] = item.value ?? item.example ?? ''
      return result
    }, {})
  }
  return clone(data)
}

export function normalizeHeaders(headers) {
  if (!headers) return {}
  if (Array.isArray(headers)) {
    return headers.reduce((result, item) => {
      if (item && item.key && item.enabled !== false) {
        result[item.key] = item.value ?? ''
      }
      return result
    }, {})
  }
  return clone(headers)
}

export function getByPath(obj, path) {
  if (!path) return obj
  let current = obj
  for (const segment of String(path).split('.')) {
    if (current === null || current === undefined) return undefined
    if (Array.isArray(current)) {
      current = current[Number(segment)]
    } else if (typeof current === 'object') {
      current = current[segment]
    } else {
      return undefined
    }
  }
  return current
}

export function setByPath(obj, path, value) {
  if (!obj || !path) return obj
  const segments = String(path).split('.')
  let current = obj
  segments.forEach((segment, index) => {
    const isLast = index === segments.length - 1
    if (isLast) {
      if (Array.isArray(current)) current[Number(segment)] = value
      else current[segment] = value
      return
    }
    if (current[segment] === undefined || current[segment] === null) {
      current[segment] = /^\d+$/.test(segments[index + 1]) ? [] : {}
    }
    current = current[segment]
  })
  return obj
}

function flattenSchemaNode(node, prefix, result, required = false) {
  if (!node || typeof node !== 'object') {
    if (prefix) result.push({ path: prefix, name: prefix.split('.').pop(), type: inferType(node), sample: node, required })
    return
  }

  if (node.properties && typeof node.properties === 'object') {
    const requiredFields = new Set(Array.isArray(node.required) ? node.required : [])
    Object.entries(node.properties).forEach(([key, child]) => {
      const path = prefix ? `${prefix}.${key}` : key
      flattenSchemaNode(child, path, result, requiredFields.has(key))
    })
    return
  }

  if (node.type === 'array' || node.items) {
    const itemNode = node.items || {}
    flattenSchemaNode(itemNode, prefix, result, required)
    return
  }

  if (prefix) {
    result.push({
      path: prefix,
      name: prefix.split('.').pop(),
      type: node.type || inferType(node.example ?? node.default),
      sample: node.example ?? node.default ?? node.enum?.[0] ?? '',
      required,
    })
  }
}

function flattenData(value, prefix, result, depth = 0) {
  if (depth > 8 || result.length >= 120) return
  if (Array.isArray(value)) {
    if (value.length === 0) {
      if (prefix) result.push({ path: prefix, name: prefix.split('.').pop(), type: 'array', sample: [], required: false })
      return
    }
    flattenData(value[0], prefix, result, depth + 1)
    return
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, child]) => {
      flattenData(child, prefix ? `${prefix}.${key}` : key, result, depth + 1)
    })
    return
  }
  if (prefix) {
    result.push({ path: prefix, name: prefix.split('.').pop(), type: inferType(value), sample: value, required: false })
  }
}

export function extractResponseFields(request) {
  if (!request?.res_body) return []
  let body = request.res_body
  if (typeof body === 'string') {
    try {
      body = JSON.parse(body)
    } catch (_) {
      return []
    }
  }
  const fields = []
  const looksLikeSchema = request.res_body_is_json_schema || body?.properties || (body?.type && (body?.items || body?.properties))
  if (looksLikeSchema) flattenSchemaNode(body, '', fields)
  else flattenData(body, '', fields)
  return fields
    .filter((field) => field.path)
    .sort((a, b) => a.path.localeCompare(b.path))
}

function flattenInputValue(value, prefix, result, depth = 0) {
  if (depth > 8 || result.length >= 120) return
  if (Array.isArray(value)) {
    if (value.length === 0) {
      if (prefix) result.push({ path: prefix, name: prefix.split('.').pop(), type: 'array', value: [] })
      return
    }
    flattenInputValue(value[0], prefix ? `${prefix}.0` : '0', result, depth + 1)
    return
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, child]) => {
      const path = prefix ? `${prefix}.${key}` : key
      flattenInputValue(child, path, result, depth + 1)
    })
    return
  }
  if (prefix) {
    result.push({ path: prefix, name: prefix.split('.').pop(), type: inferType(value), value })
  }
}

function placeholderName(value) {
  if (typeof value !== 'string') return ''
  const match = value.match(/\{\{\s*([^}]+?)\s*\}\}/)
  return match ? match[1] : ''
}

function replacePlaceholder(value, alias) {
  if (typeof value === 'string' && /\{\{\s*[^}]+?\s*\}\}/.test(value)) {
    return value.replace(/\{\{\s*[^}]+?\s*\}\}/, `{{${alias}}}`)
  }
  return `{{${alias}}}`
}

export function isUnset(value) {
  return value === '' || value === null || value === undefined
}

function requiredParamNames(request) {
  const names = new Set()
  if (Array.isArray(request?.params)) {
    request.params.forEach((item) => {
      if (item?.key && Boolean(item.required)) names.add(item.key)
    })
  }
  return names
}

function requiredBodyNames(request) {
  const names = new Set()
  const raw = request?.body
  const data = raw && typeof raw === 'object' && Object.prototype.hasOwnProperty.call(raw, 'data') ? raw.data : raw
  if (Array.isArray(data)) {
    data.forEach((item) => {
      const name = item?.key || item?.name
      if (name && Boolean(item.required)) names.add(name)
    })
  }
  const schema = data && typeof data === 'object' && !Array.isArray(data) && data.properties ? data : null
  if (schema) {
    Object.entries(schema.properties).forEach(([name, prop]) => {
      if (Boolean(prop?.required)) names.add(name)
    })
    ;(schema.required || []).forEach((name) => names.add(name))
  }
  return names
}

export function stepInputs(step) {
  const request = step.request || {}
  const requiredParams = requiredParamNames(request)
  const requiredBody = requiredBodyNames(request)
  const params = step.params || {}
  const body = step.body
  const headers = step.headers || {}
  const result = []

  Object.entries(params).forEach(([key, value]) => {
    result.push({
      location: 'params',
      path: key,
      name: key,
      type: inferType(value),
      value,
      original_value: normalizeParams(request.params)[key] ?? '',
      required: requiredParams.has(key),
    })
  })

  if (body && typeof body === 'object') {
    const bodyFields = []
    flattenInputValue(body, '', bodyFields)
    bodyFields.forEach((field) => {
      result.push({
        location: 'body',
        path: field.path,
        name: field.name,
        type: field.type,
        value: field.value,
        original_value: getByPath(normalizeBody(request.body), field.path) ?? '',
        required: requiredBody.has(field.name),
      })
    })
  }

  Object.entries(headers).forEach(([key, value]) => {
    result.push({
      location: 'headers',
      path: key,
      name: key,
      type: 'string',
      value,
      original_value: normalizeHeaders(request.headers)[key] ?? '',
      required: false,
    })
  })

  return result
}

export function refreshStep(step) {
  step.outputs = extractResponseFields(step.request)
  step.inputs = stepInputs(step).map((input) => {
    const binding = (step.bindings || []).find(
      (item) => item.target_location === input.location && item.target_path === input.path,
    )
    return {
      ...input,
      binding,
      binding_key: binding ? `${binding.source_step_uid}|${binding.source_path}` : '',
    }
  })
  return step
}

export function createStep(request) {
  const step = {
    uid: `step_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    request,
    params: normalizeParams(request.params),
    body: normalizeBody(request.body),
    headers: normalizeHeaders(request.headers),
    captures: [],
    bindings: [],
    assertions: [{ type: 'status_code', expected: 200 }],
    outputs: [],
    inputs: [],
  }
  return refreshStep(step)
}

export function resetStep(step) {
  step.params = normalizeParams(step.request.params)
  step.body = normalizeBody(step.request.body)
  step.headers = normalizeHeaders(step.request.headers)
  step.captures = []
  step.bindings = []
  return refreshStep(step)
}

function sourceFields(steps, stepIndex) {
  return steps.slice(0, stepIndex).flatMap((sourceStep, sourceIndex) => {
    return (sourceStep.outputs || []).map((field) => ({
      ...field,
      step_uid: sourceStep.uid,
      step_index: sourceIndex,
      step_name: sourceStep.request.name,
      step_method: sourceStep.request.method,
      step_path: sourceStep.request.url,
    }))
  })
}

function scoreCandidate(targetName, output) {
  const target = normalizeName(targetName)
  const source = normalizeName(output.name)
  if (!target || !source) return 0
  let score = 0
  if (target === source) score = 0.96
  else if (target.includes(source) || source.includes(target)) score = 0.84
  else return 0

  if (GENERIC_FIELDS.has(target)) score -= 0.2
  if (['string', 'integer', 'number', 'boolean'].includes(output.type)) score += 0.02
  score += Math.min(output.step_index, 9) / 1000
  return score
}

function chooseCandidate(input, candidates) {
  const targetName = placeholderName(input.value) || input.name
  const ranked = candidates
    .map((candidate) => ({ candidate, score: scoreCandidate(targetName, candidate) }))
    .filter((item) => item.score >= 0.78)
    .sort((a, b) => b.score - a.score)

  if (!ranked.length) return null

  const sameNameCount = ranked.filter((item) => normalizeName(item.candidate.name) === normalizeName(targetName)).length
  if (GENERIC_FIELDS.has(normalizeName(targetName)) && sameNameCount !== 1) return null
  return ranked[0]
}

function uniqueAlias(steps, stepIndex, fieldName) {
  const used = new Set(steps.flatMap((step) => (step.captures || []).map((capture) => capture.as)))
  const base = `step${stepIndex + 1}_${String(fieldName || 'value').replace(/[^a-zA-Z0-9_]/g, '_')}`
  let alias = base
  let index = 2
  while (used.has(alias)) {
    alias = `${base}_${index}`
    index += 1
  }
  return alias
}

export function writeInputValue(step, input, value) {
  if (input.location === 'headers') {
    step.headers[input.path] = value
    return
  }
  if (input.location === 'params') {
    setByPath(step.params, input.path, value)
    return
  }
  setByPath(step.body, input.path, value)
}

export function cleanupCaptures(steps) {
  const referenced = new Set(
    steps.flatMap((step) => (step.bindings || []).map((binding) => `${binding.source_step_uid}|${binding.alias}`)),
  )
  steps.forEach((step) => {
    step.captures = (step.captures || []).filter((capture) => {
      return !capture.auto || referenced.has(`${step.uid}|${capture.as}`)
    })
  })
}

export function autoConnectSteps(steps, options = {}) {
  // 环境变量/公共参数名：引用了这些的字段属于用户已明确指定，不参与自动串联
  const envNames = new Set((options.envNames || []).filter(Boolean).map(normalizeName))
  let matched = 0
  for (let index = 1; index < steps.length; index += 1) {
    const step = steps[index]
    const candidates = sourceFields(steps, index)
    // 只补没连上的字段：AI 或手工已建立的依赖、已填写的固定值一律不动
    const boundKeys = new Set(
      (step.bindings || []).map((item) => `${item.target_location}|${item.target_path}`),
    )
    step.inputs.forEach((input) => {
      if (boundKeys.has(`${input.location}|${input.path}`)) return
      const placeholder = placeholderName(input.value)
      const hasPlaceholder = Boolean(placeholder)
      if (hasPlaceholder && envNames.has(normalizeName(placeholder))) return
      if (!isUnset(input.value) && !hasPlaceholder) return

      const selected = chooseCandidate(input, candidates)
      if (!selected) return

      const sourceStep = steps.find((item) => item.uid === selected.candidate.step_uid)
      if (!sourceStep) return

      let capture = sourceStep.captures.find((item) => item.path === selected.candidate.path)
      if (!capture) {
        capture = {
          as: uniqueAlias(steps, selected.candidate.step_index, selected.candidate.name),
          path: selected.candidate.path,
          label: selected.candidate.path,
          auto: true,
        }
        sourceStep.captures.push(capture)
      }

      step.bindings.push({
        target_location: input.location,
        target_path: input.path,
        source_step_uid: sourceStep.uid,
        source_step_index: selected.candidate.step_index,
        source_path: selected.candidate.path,
        source_label: `步骤 ${selected.candidate.step_index + 1} · ${selected.candidate.step_name} → ${selected.candidate.path}`,
        alias: capture.as,
        confidence: selected.score,
        auto: true,
      })
      writeInputValue(step, input, replacePlaceholder(input.value, capture.as))
      matched += 1
    })
    refreshStep(step)
  }

  cleanupCaptures(steps)
  steps.forEach(refreshStep)
  const unresolved = steps.reduce((count, step) => {
    return count + step.inputs.filter((input) => input.required && !input.binding && isUnset(input.value)).length
  }, 0)
  return { matched, unresolved }
}

export function bindInputToSource(steps, step, input, sourceStepUid, sourcePath) {
  const sourceStep = steps.find((item) => item.uid === sourceStepUid)
  const field = sourceStep?.outputs.find((item) => item.path === sourcePath)
  if (!sourceStep || !field) return null

  const existing = (step.bindings || []).find(
    (item) => item.target_location === input.location && item.target_path === input.path,
  )
  if (existing) {
    step.bindings = step.bindings.filter((item) => item !== existing)
  }

  let capture = sourceStep.captures.find((item) => item.path === sourcePath)
  if (!capture) {
    const sourceIndex = steps.findIndex((item) => item.uid === sourceStep.uid)
    capture = {
      as: uniqueAlias(steps, sourceIndex, field.name),
      path: sourcePath,
      label: sourcePath,
      auto: true,
    }
    sourceStep.captures.push(capture)
  }

  const sourceIndex = steps.findIndex((item) => item.uid === sourceStep.uid)
  step.bindings.push({
    target_location: input.location,
    target_path: input.path,
    source_step_uid: sourceStep.uid,
    source_step_index: sourceIndex,
    source_path: sourcePath,
    source_label: `步骤 ${sourceIndex + 1} · ${sourceStep.request.name} → ${sourcePath}`,
    alias: capture.as,
    confidence: 1,
    auto: false,
  })
  writeInputValue(step, input, replacePlaceholder(input.value, capture.as))
  cleanupCaptures(steps)
  refreshStep(step)
  return capture
}

export function clearInputBinding(steps, step, input) {
  const binding = (step.bindings || []).find(
    (item) => item.target_location === input.location && item.target_path === input.path,
  )
  if (!binding) return
  step.bindings = step.bindings.filter((item) => item !== binding)
  const currentValue = placeholderName(input.value)
  if (currentValue) writeInputValue(step, input, input.original_value ?? '')
  cleanupCaptures(steps)
  refreshStep(step)
}

export function sourceOptions(steps, stepIndex) {
  const groups = []
  steps.slice(0, stepIndex).forEach((step, index) => {
    groups.push({
      uid: step.uid,
      label: `步骤 ${index + 1} · ${step.request.name}`,
      options: step.outputs.map((field) => ({
        value: `${step.uid}|${field.path}`,
        label: field.path,
        type: field.type,
      })),
    })
  })
  return groups
}

export function scenarioPayload(name, projectId, environmentId, steps) {
  return {
    name,
    project: projectId,
    environment: environmentId || null,
    description: '由可视化接口测试设计器创建',
    scenario_config: {
      version: 1,
      steps: steps.map((step) => ({
        uid: step.uid,
        request_id: step.request.id,
        interface: step.request.name,
        method: step.request.method,
        path: step.request.url,
        params: clone(step.params),
        body: clone(step.body),
        headers: clone(step.headers),
        capture: (step.captures || []).map((capture) => ({
          as: capture.as,
          path: capture.path,
          label: capture.label,
        })),
        bindings: clone(step.bindings || []),
        assertions: clone(step.assertions || []),
      })),
    },
  }
}

export function runSteps(steps) {
  return steps.map((step) => {
    const request = step.request || {}
    return {
      request_id: request.id ?? step.request_id,
      interface: request.name ?? step.interface,
      method: request.method ?? step.method,
      path: request.url ?? step.path,
      params: clone(step.params || {}),
      body: clone(step.body),
      headers: clone(step.headers || {}),
      capture: (step.captures || step.capture || []).map((capture) => ({ as: capture.as, path: capture.path })),
      assertions: clone(step.assertions || []),
    }
  })
}

export function hydrateSteps(config, requests) {
  const configSteps = Array.isArray(config?.steps) ? config.steps : []
  return configSteps.map((saved, index) => {
    const request = requests.find((item) => item.id === saved.request_id)
      || requests.find((item) => item.name === saved.interface)
    if (!request) return null
    const step = createStep(request)
    step.uid = saved.uid || `saved_step_${index + 1}`
    step.params = clone(saved.params || normalizeParams(request.params))
    step.body = clone(saved.body ?? normalizeBody(request.body))
    step.headers = clone(saved.headers || normalizeHeaders(request.headers))
    step.captures = (saved.capture || []).map((capture) => ({ ...capture, auto: true }))
    step.bindings = clone(saved.bindings || [])
    step.assertions = clone(saved.assertions?.length ? saved.assertions : [{ type: 'status_code', expected: 200 }])
    return refreshStep(step)
  }).filter(Boolean)
}

export function scenarioStats(steps) {
  const inputs = steps.flatMap((step) => step.inputs || [])
  const bound = inputs.filter((input) => input.binding).length
  const missing = inputs.filter((input) => input.required && !input.binding && isUnset(input.value)).length
  return {
    inputs: inputs.length,
    bound,
    missing,
    steps: steps.length,
    assertions: steps.reduce((count, step) => count + (step.assertions?.length || 0), 0),
  }
}

/**
 * 把 AI 规划结果转成可视化步骤：复用 createStep/refreshStep，保持与手动编排完全一致的数据结构。
 * AI 只提供「顺序 + 参数 + 依赖声明」，接口定义仍是基准，因此参数做合并而不是整体覆盖。
 */
export function buildStepsFromPlan(plan, requests) {
  const planSteps = Array.isArray(plan?.steps) ? plan.steps : []
  const byId = new Map((requests || []).map((item) => [item.id, item]))
  const steps = []

  planSteps.forEach((saved) => {
    const request = byId.get(saved.request_id)
      || (requests || []).find((item) => item.name === saved.interface)
    if (!request) return

    const step = createStep(request)

    if (saved.params && typeof saved.params === 'object' && !Array.isArray(saved.params)) {
      step.params = { ...normalizeParams(request.params), ...saved.params }
    }
    if (saved.body && typeof saved.body === 'object' && !Array.isArray(saved.body)) {
      const base = normalizeBody(request.body)
      step.body = base && typeof base === 'object' && !Array.isArray(base)
        ? { ...base, ...saved.body }
        : clone(saved.body)
    }
    if (Array.isArray(saved.assertions) && saved.assertions.length) {
      step.assertions = clone(saved.assertions)
    }
    step.captures = (saved.capture || [])
      .filter((capture) => capture && capture.path)
      .map((capture) => ({
        as: capture.as || String(capture.path).split('.').pop(),
        path: capture.path,
        label: capture.path,
        auto: true,
      }))

    refreshStep(step)
    steps.push(step)
  })

  // 依据 {{别名}} 反查来源步骤，把 AI 的依赖声明变成界面上可见的「来自步骤 N」
  const aliasIndex = new Map()
  steps.forEach((step, index) => {
    step.captures.forEach((capture) => {
      if (capture.as && !aliasIndex.has(capture.as)) {
        aliasIndex.set(capture.as, { index, path: capture.path })
      }
    })
  })

  steps.forEach((step, index) => {
    step.inputs.forEach((input) => {
      const alias = placeholderName(input.value)
      if (!alias) return
      const source = aliasIndex.get(alias)
      if (!source || source.index >= index) return
      const sourceStep = steps[source.index]
      step.bindings.push({
        target_location: input.location,
        target_path: input.path,
        source_step_uid: sourceStep.uid,
        source_step_index: source.index,
        source_path: source.path,
        source_label: `步骤 ${source.index + 1} · ${sourceStep.request.name} → ${source.path}`,
        alias,
        confidence: 1,
        auto: true,
      })
    })
    refreshStep(step)
  })

  cleanupCaptures(steps)
  steps.forEach(refreshStep)
  return steps
}

/**
 * 采纳一条缺数建议：把该字段绑定到建议的来源步骤字段上。
 * 返回 null 表示无法自动绑定（例如来源字段在响应结构里已不存在），由用户手工处理。
 */
export function applyMissingSuggestion(steps, missing) {
  if (!missing?.suggestion) return null
  const stepIndex = (missing.step || 1) - 1
  const sourceIndex = (missing.suggestion.step || 1) - 1
  const step = steps[stepIndex]
  const sourceStep = steps[sourceIndex]
  if (!step || !sourceStep) return null

  const token = `{{${missing.var}}}`
  const input = step.inputs.find((item) => String(item.value ?? '').includes(token))
  if (!input) return null

  return bindInputToSource(steps, step, input, sourceStep.uid, missing.suggestion.path)
}
