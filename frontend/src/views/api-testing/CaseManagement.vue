<template>
  <div class="case-page">
    <div class="page-topbar">
      <div class="topbar-left">
        <h2 class="page-title">测试用例管理</h2>
        <span class="page-desc">AI 分析 → 人工确认 → 需求澄清 → 生成用例 → 执行报告</span>
      </div>
      <div class="topbar-right">
        <el-select v-model="filterRequestId" placeholder="按接口筛选" clearable size="small" style="width:260px" filterable @change="loadCases">
          <el-option v-for="r in requests" :key="r.id" :label="r.name" :value="r.id">
            <div class="req-option">
              <span class="req-option-name">{{ r.name }}</span>
              <span v-if="r.confirmed" class="req-confirmed">✓ 已确认</span>
            </div>
          </el-option>
        </el-select>
        <el-button size="small" @click="loadRequests">刷新</el-button>
        <el-button size="small" type="warning" @click="batchConfirm" :disabled="!filterRequestId">批量确认</el-button>
        <el-button size="small" type="success" @click="executeAll" :disabled="!filterRequestId" :loading="executing">执行</el-button>
        <el-button size="small" type="info" @click="analyzeResults" :disabled="!filterRequestId || !hasExecuted" :loading="analyzing">AI 分析</el-button>
        <el-button size="small" type="primary" @click="generateForRequest" :disabled="!filterRequestId" :loading="generating">生成用例</el-button>
      </div>
    </div>

    <!-- 流程引导 -->
    <div class="flow-bar">
      <div class="flow-step done"><span class="flow-idx">1</span>AI 参数分析</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step done"><span class="flow-idx">2</span>人工确认</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step done"><span class="flow-idx">3</span>需求澄清</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step" :class="{ active: flowStep === 1, done: flowStep >= 2 }"><span class="flow-idx">4</span>生成用例</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step" :class="{ active: flowStep === 2, done: flowStep >= 3 }"><span class="flow-idx">5</span>执行报告</div>
      <span v-if="flowStep > 0" class="flow-current">当前：{{ flowLabels[flowStep] }}</span>
    </div>

    <div class="case-body">
      <!-- 下一步引导横幅 -->
      <div v-if="filterRequestId" class="next-step-banner" :class="bannerType">
        <div class="next-step-left"><span class="next-step-icon">{{ bannerIcon }}</span><span>{{ bannerText }}</span></div>
        <div class="next-step-right"><span class="next-step-tip">{{ bannerTip }}</span></div>
      </div>

      <div v-if="report" class="case-report">
        <div class="report-row">
          <span class="report-stat ok">通过 {{ report.summary.passed }}</span>
          <span class="report-stat fail">失败 {{ report.summary.failed }}</span>
          <span class="report-stat err">错误 {{ report.summary.errors }}</span>
          <span class="report-stat">通过率 {{ report.summary.pass_rate }}</span>
          <span class="report-stat">平均 {{ report.summary.avg_response_time }}ms</span>
        </div>
      </div>
      <div class="case-stats" v-if="cases.length>0">
        <div class="stat">总计 <b>{{ cases.length }}</b></div>
        <div class="stat ok">已确认 <b>{{ cases.filter(c=>c.confirmed).length }}</b></div>
        <div class="stat s-normal">正常 <b>{{ cases.filter(c=>c.scenario==='normal').length }}</b></div>
        <div class="stat s-boundary">边界 <b>{{ cases.filter(c=>c.scenario==='boundary').length }}</b></div>
        <div class="stat s-exception">异常 <b>{{ cases.filter(c=>c.scenario==='exception').length }}</b></div>
      </div>

      <div v-if="!filterRequestId" class="empty-hint">请先选择一个接口</div>
      <div v-else-if="cases.length===0" class="empty-hint">暂无用例，点击「生成用例」</div>

      <div v-else class="case-list">
        <div v-for="c in cases" :key="c.id" class="case-card" :class="{ confirmed: c.confirmed, disabled: !c.enabled }">
          <!-- 头部：场景 / 优先级 / 名称 + 操作 -->
          <div class="card-head">
            <div class="head-left">
              <span class="scenario-badge" :class="'sc-'+c.scenario">{{ c.scenario_label }}</span>
              <span class="priority-badge" :class="'pri-'+c.priority">{{ c.priority }}</span>
              <span class="case-name">{{ c.name }}</span>
              <span v-if="c.confirmed" class="confirmed-badge">✓ 已确认</span>
            </div>
            <div class="head-right">
              <el-switch v-model="c.enabled" size="small" inline-prompt active-text="启" inactive-text="停" @change="toggleEnable(c)" />
              <el-button v-if="!c.confirmed" size="small" type="success" plain @click="confirmOne(c)">确认</el-button>
              <el-button size="small" plain @click="editCase(c)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="deleteOne(c)">删除</el-button>
            </div>
          </div>

          <!-- 请求行 -->
          <div class="req-line">
            <span class="method-tag" :class="'m-'+c.method.toLowerCase()">{{ c.method }}</span>
            <code class="case-url">{{ c.url }}</code>
            <span class="expect-chip"><i>预期</i><b>{{ c.expected_status||'?' }}</b></span>
            <span v-if="c.executed&&c.response_time" class="time-chip">⏱ {{ c.response_time }}ms</span>
          </div>

          <!-- 主体：请求数据 | 断言 -->
          <div class="card-body">
            <div class="block">
              <div class="block-title">请求数据</div>
              <template v-if="Object.keys(c.params||{}).length||(c.body&&Object.keys(c.body).length)">
                <div v-for="(v,k) in (c.params||{})" :key="'p'+k" class="kv-row">
                  <span class="kv-key">{{ k }}</span>
                  <span class="kv-val">{{ typeof v==='object'?formatJson(v):v }}</span>
                </div>
                <div v-if="c.body&&Object.keys(c.body).length" class="kv-row body-row">
                  <span class="kv-key">body</span>
                  <pre class="kv-pre">{{ formatJson(c.body) }}</pre>
                </div>
              </template>
              <div v-else class="block-empty">无请求参数</div>
            </div>

            <div class="block">
              <div class="block-title">断言 <span class="block-count">{{ (c.assertions||[]).length }}</span></div>
              <div v-for="(a,i) in c.assertions" :key="i" class="assert-line">
                <span class="assert-icon" :class="'at-'+a.type">{{ assertionIcon(a.type) }}</span>
                <span class="assert-text">{{ formatAssertion(a) }}</span>
              </div>
              <div v-if="!c.assertions?.length" class="block-empty">无断言</div>
            </div>
          </div>

          <!-- 执行结果 -->
          <div v-if="c.executed" class="result-row">
            <span class="result-pill" :class="'rp-'+c.last_status">
              <span class="pill-icon">{{ resultStatusIcon(c.last_status) }}</span>
              {{ resultStatusText(c.last_status) }}
            </span>
            <span v-if="c.response_time" class="time-chip">{{ c.response_time }}ms</span>
            <span v-if="c.last_status==='fail'" class="fail-toggle" @click="c._showFail=!c._showFail">{{ c._showFail?'收起':'查看失败详情' }}</span>
          </div>
          <div v-if="c.executed && c.last_status==='skip' && c.error_message" class="skip-note">{{ c.error_message }}</div>
          <div v-if="c.executed&&c.last_status==='fail'&&c._showFail" class="fail-detail-box">
            <div v-for="(a,i) in parseAssertResults(c.error_message)" :key="i" class="assert-item" :class="{pass:a.pass,fail:!a.pass}">
              <span class="assert-type">{{ a.type }}</span>
              <span v-if="a.type==='status_code'">预期 {{ a.expected }} / 实际 {{ a.actual }}</span>
              <span v-else-if="a.type==='json_path'">{{ a.path }}：预期 {{ a.expected }} / 实际 {{ a.actual }}</span>
              <span v-else-if="a.type==='contains'">包含"{{ a.expected }}"</span>
              <span class="assert-check">{{ a.pass ? '✓' : '✗' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="showEdit" title="编辑用例" width="600px" append-to-body>
      <el-form :model="editForm" label-width="80px" size="small" v-if="editForm.id">
        <el-form-item label="名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="场景"><el-select v-model="editForm.scenario"><el-option v-for="s in scenarios" :key="s.value" :label="s.label" :value="s.value" /></el-select></el-form-item>
        <el-form-item label="优先级"><el-select v-model="editForm.priority"><el-option v-for="p in priorities" :key="p" :label="p" :value="p" /></el-select></el-form-item>
        <el-form-item label="预期状态码"><el-input-number v-model="editForm.expected_status" :min="100" :max="599" /></el-form-item>
        <el-form-item label="Params"><el-input v-model="editForm.paramsText" type="textarea" :rows="3" placeholder="JSON格式" /></el-form-item>
        <el-form-item label="Body"><el-input v-model="editForm.bodyText" type="textarea" :rows="3" placeholder="JSON格式" /></el-form-item>
        <el-form-item label="Headers"><el-input v-model="editForm.headersText" type="textarea" :rows="3" placeholder="JSON格式" /></el-form-item>
        <el-form-item label="断言"><el-input v-model="editForm.assertionsText" type="textarea" :rows="5" placeholder="JSON数组格式" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="showEdit=false">取消</el-button><el-button type="primary" @click="saveEdit">保存</el-button></template>
    </el-dialog>

    <!-- AI 执行结果分析弹窗 -->
    <el-dialog v-model="analysisDialog" title="AI 执行结果分析" width="720px" top="6vh">
      <pre class="analysis-text">{{ analysisText || '分析中...' }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/utils/api'
import { useRoute } from 'vue-router'

const requests = ref([])
const cases = ref([])
const filterRequestId = ref(null)

const flowLabels = ['', '生成用例', '执行报告', '查看报告']
// 0=未选接口 1=无用例(下一步生成) 2=有用例未执行(下一步执行) 3=已执行(查看报告)
const flowStep = computed(() => {
  if (!filterRequestId.value) return 0
  if (cases.value.length === 0) return 1
  const executedCount = cases.value.filter(c => c.executed).length
  return executedCount === 0 ? 2 : 3
})

const bannerType = computed(() => {
  if (cases.value.length === 0) return 'banner-warn'
  return cases.value.some(c => c.executed) ? 'banner-ok' : 'banner-info'
})
const bannerIcon = computed(() => ({ 'banner-ok':'✅', 'banner-info':'ℹ️', 'banner-warn':'📋' }[bannerType.value]))
const bannerText = computed(() => {
  if (cases.value.length === 0) return '尚未生成用例'
  const executedCount = cases.value.filter(c => c.executed).length
  if (executedCount === 0) return `已生成 ${cases.value.length} 条用例，尚未执行`
  const passed = cases.value.filter(c => c.last_status === 'pass').length
  const failed = cases.value.filter(c => c.last_status === 'fail').length
  const errors = cases.value.filter(c => c.last_status === 'error').length
  return `已执行：通过 ${passed} / 失败 ${failed} / 错误 ${errors}`
})
const bannerTip = computed(() => {
  if (cases.value.length === 0) return '点击右上角「生成用例」'
  if (!cases.value.some(c => c.executed)) return '点击右上角「执行」运行全部启用用例'
  return '顶部已展示测试报告，可继续执行、编辑或用例管理'
})
const generating = ref(false)
const showEdit = ref(false)
const executing = ref(false)
const analyzing = ref(false)
const analysisDialog = ref(false)
const analysisText = ref('')
const hasExecuted = computed(() => cases.value.some(c => c.executed))
const report = ref(null)
const editForm = reactive({ id:null,name:'',scenario:'',priority:'',expected_status:null,paramsText:'',bodyText:'',headersText:'',assertionsText:'' })
const scenarios = [{value:'normal',label:'正常'},{value:'boundary',label:'边界'},{value:'exception',label:'异常'}]
const priorities = ['P0','P1','P2','P3']

// 分页接口全量加载（后端 PAGE_SIZE=20，需循环拉取所有页）
const fetchAllPages = async (url, params = {}) => {
  let all = []
  let page = 1
  while (true) {
    const response = await api.get(url, { params: { ...params, page } })
    const data = response.data || {}
    const items = data.results || (Array.isArray(data) ? data : [])
    all = all.concat(items)
    if (!data.next) break
    page += 1
  }
  return all
}

const loadRequests = async () => {
  try {
    const all = await fetchAllPages('/api-testing/requests/')
    // 最新确认的接口排最前（按确认时间倒序），未确认的按创建时间倒序排后面
    requests.value = all.sort((a, b) => {
      const aTime = a.confirmed_at || ''
      const bTime = b.confirmed_at || ''
      if (aTime && bTime) return bTime.localeCompare(aTime)
      if (aTime) return -1
      if (bTime) return 1
      return (b.created_at || '').localeCompare(a.created_at || '')
    })
  } catch(_) {}
}

const loadCases = async () => {
  if(!filterRequestId.value){ cases.value=[]; report.value=null; return }
  try {
    const r = await api.get(`/api-testing/cases/?request_id=${filterRequestId.value}`)
    cases.value = r.data.cases||[]
    await loadReport()
  } catch(_) {}
}

const generateForRequest = async () => {
  generating.value = true
  try {
    const r = await api.post('/api-testing/cases/generate/', { request_ids: [filterRequestId.value] })
    if (r.data.errors && r.data.errors.length) {
      ElMessage.warning(`生成 ${r.data.generated} 条用例；${r.data.errors.join('; ')}`)
    } else {
      ElMessage.success(`生成 ${r.data.generated} 条用例`)
    }
    await loadCases()
  } catch(e) { ElMessage.error('生成失败: '+(e.response?.data?.error||e.message)) }
  finally { generating.value = false }
}

const batchConfirm = async () => {
  try {
    await api.post('/api-testing/cases/batch-confirm/', { request_id: filterRequestId.value })
    ElMessage.success('已全部确认')
    await loadCases()
  } catch(e) { ElMessage.error('确认失败') }
}

const confirmOne = async (c) => {
  await api.put(`/api-testing/cases/${c.id}/`, { ...c, confirmed: true })
  c.confirmed = true
  ElMessage.success('已确认')
}

const editCase = (c) => {
  editForm.id = c.id; editForm.name = c.name; editForm.scenario = c.scenario
  editForm.priority = c.priority; editForm.expected_status = c.expected_status
  editForm.paramsText = JSON.stringify(c.params||{}, null, 2)
  editForm.bodyText = JSON.stringify(c.body||{}, null, 2)
  editForm.headersText = JSON.stringify(c.headers||{}, null, 2)
  editForm.assertionsText = JSON.stringify(c.assertions||[], null, 2)
  showEdit.value = true
}

const saveEdit = async () => {
  try {
    const data = {
      name: editForm.name, scenario: editForm.scenario, priority: editForm.priority,
      expected_status: editForm.expected_status,
      params: JSON.parse(editForm.paramsText||'{}'),
      body: JSON.parse(editForm.bodyText||'{}'),
      headers: JSON.parse(editForm.headersText||'{}'),
      assertions: JSON.parse(editForm.assertionsText||'[]'),
    }
    await api.put(`/api-testing/cases/${editForm.id}/`, data)
    showEdit.value = false
    await loadCases()
    ElMessage.success('已保存')
  } catch(e) { ElMessage.error('保存失败: '+e.message) }
}

const deleteOne = async (c) => {
  try {
    await ElMessageBox.confirm('删除该用例？','确认',{type:'warning'})
    await api.delete(`/api-testing/cases/${c.id}/delete/`)
    await loadCases()
  } catch(_) {}
}

const analyzeResults = async () => {
  if (!filterRequestId.value) return
  analyzing.value = true
  analysisText.value = ''
  analysisDialog.value = true
  try {
    const r = await api.post('/api-testing/cases/analyze/', { request_id: filterRequestId.value })
    analysisText.value = r.data.analysis || '（无分析结果）'
  } catch (e) {
    analysisText.value = '分析失败: ' + (e.response?.data?.error || e.message)
  } finally { analyzing.value = false }
}

const executeAll = async () => {
  executing.value = true
  try {
    const r = await api.post('/api-testing/cases/execute/', { request_id: filterRequestId.value })
    ElMessage.success(`执行完成: 通过${r.data.passed} 失败${r.data.failed} 错误${r.data.errors} 跳过${r.data.skipped || 0}`)
    if (r.data.regenerated) {
      ElMessage.warning(`检测到参数分析/澄清已更新，已自动重新生成 ${r.data.regenerated} 条用例后执行`)
    }
    await loadCases()
    await loadReport()
  } catch(e) { ElMessage.error('执行失败: '+(e.response?.data?.error||e.message)) }
  finally { executing.value = false }
}

const loadReport = async () => {
  if(!filterRequestId.value) return
  try {
    const r = await api.get(`/api-testing/cases/report/?request_id=${filterRequestId.value}`)
    report.value = r.data
  } catch(_) {}
}

const formatJson = (obj) => {
  try { return JSON.stringify(obj, null, 2) } catch(_) { return String(obj) }
}
const assertionIcon = (type) => ({ status_code:'⌁', json_path:'$.', json_path_exists:'∃', json_path_neq:'≠', contains:'≈', response_time:'⏱' }[type] || '•')
const formatAssertion = (a) => {
  if (a.type==='status_code') return `状态码 = ${a.expected}`
  if (a.type==='json_path') return `${a.path} = ${a.expected}`
  if (a.type==='json_path_exists') return `字段存在: ${a.path}`
  if (a.type==='json_path_neq') return `${a.path} ≠ ${a.expected}`
  if (a.type==='contains') return `包含 "${a.expected}"`
  if (a.type==='response_time') return `响应时间 < ${a.expected}ms`
  return a.type || ''
}
const resultStatusIcon = (s) => ({ pass:'✓', fail:'✕', error:'!', skip:'–' }[s] || '•')
const resultStatusText = (s) => ({ pass:'执行通过', fail:'执行失败', error:'执行错误', skip:'已跳过' }[s] || s)
const toggleEnable = async (c) => {
  try {
    await api.put(`/api-testing/cases/${c.id}/`, { enabled: c.enabled })
  } catch(_) { c.enabled = !c.enabled; ElMessage.error('更新失败') }
}

const parseAssertResults = (msg) => {
  if(!msg) return []
  try { const d=JSON.parse(msg); return d.assertions||[] } catch(_) { return [] }
}

const route = useRoute()

onMounted(async () => {
  await loadRequests()
  // 从参数分析页跳转过来时，直接选中对应接口并加载用例
  const rid = route.query.request_id
  if (rid) {
    filterRequestId.value = Number(rid)
    await loadCases()
  }
})
</script>

<style scoped>
.case-page { height: calc(100vh - 60px); background: #f5f6f8; display: flex; flex-direction: column; }
.page-topbar { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; background: #fff; border-bottom: 1px solid #e8eaed; }
.topbar-left { display: flex; align-items: baseline; gap: 12px; }
.page-title { margin: 0; font-size: 18px; font-weight: 600; }
.page-desc { font-size: 13px; color: #8b8fa3; }
.topbar-right { display: flex; gap: 8px; align-items: center; }
.case-body { flex: 1; overflow-y: auto; padding: 16px 24px; }
.empty-hint { text-align: center; padding: 60px; color: #9aa0a6; font-size: 15px; }

.case-stats { display: flex; gap: 16px; margin-bottom: 16px; }
.case-report { background: #fff; border: 1px solid #e8eaed; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
.report-row { display: flex; gap: 20px; flex-wrap: wrap; }
.report-stat { font-size: 14px; font-weight: 500; }
.report-stat.ok { color: #137333; }
.report-stat.fail { color: #c5221f; }
.report-stat.err { color: #e37400; }
.stat { font-size: 13px; color: #5f6368; }
.stat b { color: #202124; margin-left: 4px; }
.stat.ok { color: #137333; }
.stat.s-normal { color: #1a73e8; }
.stat.s-boundary { color: #e37400; }
.stat.s-exception { color: #d93025; }

.case-list { display: flex; flex-direction: column; gap: 12px; }

.case-card {
  border: 1px solid #e8eaed; border-radius: 12px; background: #fff; overflow: hidden;
  box-shadow: 0 1px 3px rgba(16,24,40,.04); transition: box-shadow .2s, border-color .2s;
}
.case-card:hover { box-shadow: 0 4px 16px rgba(16,24,40,.08); }
.case-card.confirmed { border-color: #b7e1c3; }
.case-card.disabled { opacity: .55; }

.card-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 16px; background: linear-gradient(180deg,#fafbfc,#f6f8fa); border-bottom: 1px solid #eef0f2;
}
.head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.head-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

.scenario-badge { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px; color: #fff; flex-shrink: 0; }
.sc-normal { background: #1a73e8; }
.sc-boundary { background: #e37400; }
.sc-exception { background: #d93025; }
.priority-badge { font-size: 12px; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: #202124; color: #fff; flex-shrink: 0; }
.pri-P0 { background: #c5221f; } .pri-P1 { background: #e37400; } .pri-P2 { background: #1a73e8; } .pri-P3 { background: #5f6368; }
.case-name { font-weight: 600; font-size: 14px; color: #202124; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.confirmed-badge { font-size: 11px; color: #137333; background: #e6f4ea; padding: 2px 8px; border-radius: 999px; flex-shrink: 0; }

.req-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 16px; border-bottom: 1px solid #f0f1f3; }
.method-tag { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 5px; color: #fff; letter-spacing: .3px; }
.m-get { background: #1a73e8; } .m-post { background: #188038; } .m-put { background: #e37400; } .m-delete { background: #d93025; } .m-patch { background: #9334e6; } .m-options { background: #5f6368; } .m-head { background: #5f6368; }
.case-url { font-size: 12.5px; color: #3c4043; background: #f1f3f4; padding: 3px 8px; border-radius: 6px; font-family: 'SFMono-Regular', Consolas, monospace; word-break: break-all; }
.expect-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #5f6368; }
.expect-chip b { color: #188038; }
.time-chip { font-size: 12px; color: #5f6368; }

.card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 14px 16px; }
@media (max-width: 1100px) { .card-body { grid-template-columns: 1fr; } }
.block-title { font-size: 12px; font-weight: 600; color: #9aa0a6; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.block-count { background: #e8eaed; color: #5f6368; border-radius: 999px; padding: 0 7px; font-size: 11px; }
.kv-row { display: flex; gap: 8px; align-items: baseline; font-size: 13px; padding: 3px 0; }
.kv-key { color: #1967d2; font-family: monospace; flex-shrink: 0; min-width: 60px; font-weight: 600; }
.kv-val { color: #3c4043; word-break: break-all; }
.kv-pre { margin: 0; font-size: 12px; line-height: 1.5; background: #f8f9fa; border: 1px solid #eef0f2; border-radius: 6px; padding: 8px 10px; max-height: 160px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
.block-empty { font-size: 12px; color: #dadce0; }

.assert-line { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
.assert-icon { width: 24px; height: 22px; border-radius: 6px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #fff; }
.at-status_code { background: #188038; } .at-json_path { background: #1a73e8; } .at-json_path_exists { background: #5f6368; } .at-json_path_neq { background: #b25e00; } .at-contains { background: #e37400; } .at-response_time { background: #9334e6; }
.assert-text { color: #3c4043; }

.result-row { display: flex; align-items: center; gap: 10px; padding: 6px 16px 12px; font-size: 13px; }
.result-pill { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 999px; font-size: 13px; font-weight: 600; }
.pill-icon { font-size: 12px; font-weight: 700; }
.rp-pass { background: #e6f4ea; color: #137333; } .rp-fail { background: #fce8e6; color: #c5221f; } .rp-error { background: #fef7e0; color: #b25e00; } .rp-skip { background: #f1f3f4; color: #5f6368; }
.fail-toggle { margin-left: auto; font-size: 12px; font-weight: 500; color: #c5221f; cursor: pointer; text-decoration: underline; }
.fail-toggle:hover { color: #8f1d1a; }
.fail-detail-box { padding: 10px 16px 12px; border-top: 1px solid #fce8e6; background: #fff5f5; }
.skip-note { font-size: 12px; color: #b25e00; padding: 2px 16px 12px; line-height: 1.6; }

.assert-item { font-size: 12px; padding: 3px 10px; border-radius: 6px; display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.assert-item.pass { background: #e6f4ea; color: #137333; }
.assert-item.fail { background: #fce8e6; color: #c5221f; }
.assert-type { font-size: 11px; background: rgba(0,0,0,.08); padding: 0 4px; border-radius: 3px; }
.assert-check { margin-left: auto; font-weight: bold; }
.no-data { font-size: 12px; color: #dadce0; }
.req-option { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.req-option-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.req-confirmed { color: #67c23a; font-size: 12px; font-weight: 600; flex-shrink: 0; }
.analysis-text { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.7; color: #202124; max-height: 60vh; overflow: auto; font-family: inherit; }

/* 流程引导条 */
.flow-bar { display: flex; align-items: center; gap: 8px; padding: 10px 24px; background: #fff; border-bottom: 1px solid #e8eaed; flex-wrap: wrap; }
.flow-step { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: #9aa0a6; }
.flow-step .flow-idx { width: 20px; height: 20px; border-radius: 50%; background: #e8eaed; color: #5f6368; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.flow-step.active { color: #1a73e8; font-weight: 600; }
.flow-step.active .flow-idx { background: #1a73e8; color: #fff; }
.flow-step.done { color: #137333; }
.flow-step.done .flow-idx { background: #34a853; color: #fff; }
.flow-arrow { color: #dadce0; font-size: 14px; }
.flow-current { margin-left: auto; font-size: 12px; color: #5f6368; background: #f1f3f4; padding: 3px 10px; border-radius: 999px; }

/* 下一步引导横幅 */
.next-step-banner { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; padding: 12px 16px; border-radius: 10px; }
.banner-ok { background: linear-gradient(90deg,#e6f4ea,#f6fef9); border: 1px solid #b7e1c3; }
.banner-info { background: linear-gradient(90deg,#e8f0fe,#f5f9ff); border: 1px solid #c5d8f7; }
.banner-warn { background: linear-gradient(90deg,#fef7e0,#fffdf5); border: 1px solid #f2dfae; }
.next-step-left { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: #202124; }
.next-step-icon { font-size: 18px; }
.next-step-right { display: flex; align-items: center; gap: 10px; }
.next-step-tip { font-size: 12px; color: #5f6368; }
</style>
