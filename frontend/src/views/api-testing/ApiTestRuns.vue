<template>
  <div class="runs-page">
    <header class="page-head">
      <div>
        <h1>执行与报告</h1>
        <p>运行已保存的场景，查看每一步的真实请求、返回数据和失败原因。</p>
      </div>
      <div class="head-actions">
        <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 190px" @change="onProjectChange">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-button @click="refreshData">刷新</el-button>
        <el-button type="primary" @click="goDesign">新建测试场景</el-button>
        <el-button @click="settingsVisible = true">配置</el-button>
      </div>
    </header>

    <main v-loading="loading" class="runs-workspace">
      <aside class="suite-panel">
        <div class="panel-title">
          <span>测试场景</span>
          <span class="count-badge">{{ projectSuites.length }}</span>
        </div>
        <button
          v-for="suite in projectSuites"
          :key="suite.id"
          class="suite-item"
          :class="{ active: selectedSuiteId === suite.id }"
          @click="selectSuite(suite)"
        >
          <div class="suite-row">
            <span class="suite-name">{{ suite.name }}</span>
            <span class="run-mini" :class="lastStatusClass(suite.id)">{{ lastStatusLabel(suite.id) }}</span>
          </div>
          <div class="suite-meta">
            {{ suite.scenario_config?.steps?.length || 0 }} 个步骤
            <span v-if="suite.environment">· 环境 {{ suite.environment }}</span>
          </div>
        </button>
        <div v-if="!projectSuites.length" class="empty-mini">还没有保存的测试场景</div>
      </aside>

      <section class="history-panel">
        <div class="history-head">
          <div>
            <h3>{{ selectedSuite?.name || '运行记录' }}</h3>
            <p v-if="selectedSuite">最近运行记录，按时间倒序排列</p>
            <p v-else>从左侧选择一个场景，或直接查看全部运行记录</p>
          </div>
          <el-button
            type="primary"
            :loading="running"
            :disabled="!selectedSuite || !selectedSuite.scenario_config?.steps?.length"
            @click="runSelectedSuite"
          >
            运行当前场景
          </el-button>
        </div>

        <div v-if="visibleExecutions.length" class="execution-list">
          <button
            v-for="execution in visibleExecutions"
            :key="execution.id"
            class="execution-row"
            :class="{ active: selectedExecutionId === execution.id }"
            @click="selectExecution(execution)"
          >
            <span class="run-dot" :class="statusClass(execution.status)"></span>
            <span class="execution-main">
              <span class="execution-name">{{ execution.test_suite?.name || execution.test_suite_name }}</span>
              <span class="execution-time">{{ formatTime(execution.created_at) }}</span>
            </span>
            <span class="execution-counts">
              <span class="pass-count">{{ execution.passed_requests }} 通过</span>
              <span v-if="execution.failed_requests" class="fail-count">{{ execution.failed_requests }} 失败</span>
            </span>
            <span class="execution-duration">{{ executionDuration(execution) }}</span>
          </button>
        </div>
        <div v-else class="empty-history">
          <h3>还没有运行记录</h3>
          <p>选择一个测试场景并执行，结果会自动出现在这里。</p>
        </div>
      </section>

      <section v-if="selectedExecution" class="detail-panel">
        <div class="detail-head">
          <div>
            <span class="detail-kicker">执行详情 #{{ selectedExecution.id }}</span>
            <h3>{{ selectedExecution.test_suite?.name || selectedExecution.test_suite_name }}</h3>
            <p>{{ formatTime(selectedExecution.created_at) }}</p>
          </div>
          <el-button @click="goDesign(selectedExecution.test_suite?.id)">编辑这个场景</el-button>
        </div>

        <div class="summary-grid">
          <div class="summary-card total"><b>{{ selectedExecution.total_requests }}</b><span>总步骤</span></div>
          <div class="summary-card pass"><b>{{ selectedExecution.passed_requests }}</b><span>通过</span></div>
          <div class="summary-card fail"><b>{{ selectedExecution.failed_requests }}</b><span>失败</span></div>
          <div class="summary-card"><b>{{ passRate }}%</b><span>通过率</span></div>
        </div>

        <div class="timeline">
          <article v-for="(result, index) in executionResults" :key="index" class="result-card" :class="statusClass(result.status)">
            <div class="result-head">
              <span class="result-index">{{ index + 1 }}</span>
              <span class="result-name">{{ result.interface || result.name }}</span>
              <span class="result-http" v-if="result.http_status">HTTP {{ result.http_status }}</span>
              <span class="result-time" v-if="result.time_ms">{{ result.time_ms }}ms</span>
              <span class="result-status">{{ statusLabel(result.status) }}</span>
            </div>
            <div v-if="result.message" class="result-message">{{ result.message }}</div>
            <div v-if="result.captured && Object.keys(result.captured).length" class="captured-row">
              <span>已传给后续步骤：</span>
              <code v-for="(value, key) in result.captured" :key="key">{{ key }}={{ shortValue(value) }}</code>
            </div>
            <div v-if="result.assertion_results?.length" class="assertion-results">
              <span
                v-for="(assertion, assertionIndex) in result.assertion_results"
                :key="assertionIndex"
                class="assertion-pill"
                :class="assertion.pass ? 'is-pass' : 'is-fail'"
              >
                {{ assertion.pass ? '✓' : '✕' }} {{ assertionLabel(assertion) }}
              </span>
            </div>
            <el-collapse class="result-collapse">
              <el-collapse-item title="查看请求和响应详情">
                <div class="detail-grid">
                  <div>
                    <h5>请求 URL</h5>
                    <pre>{{ result.request_url || result.url }}</pre>
                    <template v-if="hasObject(result.request_params)">
                      <h5>URL / Query 参数</h5>
                      <pre>{{ pretty(result.request_params) }}</pre>
                    </template>
                    <template v-if="hasObject(result.request_body)">
                      <h5>请求 Body</h5>
                      <pre>{{ pretty(result.request_body) }}</pre>
                    </template>
                  </div>
                  <div>
                    <h5>响应</h5>
                    <pre>{{ pretty(result.response_body) }}</pre>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </article>
        </div>
      </section>
    </main>

    <el-drawer v-model="settingsVisible" title="接口自动化配置" size="420px">
      <p class="settings-tip">日常流程只需要“测试设计”和“执行与报告”，其余配置集中在这里。</p>
      <div class="settings-list">
        <button class="settings-item" @click="go('/api-testing/yapi-sync')"><b>YApi 连接</b><span>维护地址、Token 和项目绑定</span></button>
        <button class="settings-item" @click="go('/api-testing/projects')"><b>项目管理</b><span>维护接口测试项目与成员</span></button>
        <button class="settings-item" @click="go('/api-testing/environments')"><b>环境变量</b><span>配置 base_url、Token 和公共参数</span></button>
        <button class="settings-item" @click="go('/api-testing/ai-service-config')"><b>AI 模型</b><span>用于参数分析和智能建议</span></button>
        <button class="settings-item" @click="go('/api-testing/scheduled-tasks')"><b>定时任务</b><span>管理已有定时执行计划</span></button>
        <button class="settings-item" @click="go('/api-testing/notification-logs')"><b>通知记录</b><span>查看任务执行通知</span></button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { runSteps } from '@/utils/apiScenario'

const route = useRoute()
const router = useRouter()

const projects = ref([])
const suites = ref([])
const executions = ref([])
const projectId = ref(null)
const selectedSuiteId = ref(null)
const selectedExecutionId = ref(null)
const loading = ref(false)
const running = ref(false)
const settingsVisible = ref(false)

const projectSuites = computed(() => suites.value.filter((suite) => suite.project === projectId.value))
const selectedSuite = computed(() => projectSuites.value.find((suite) => suite.id === selectedSuiteId.value) || null)
const projectExecutions = computed(() => executions.value.filter((execution) => execution.test_suite?.project === projectId.value))
const visibleExecutions = computed(() => {
  const list = selectedSuiteId.value
    ? projectExecutions.value.filter((execution) => execution.test_suite?.id === selectedSuiteId.value)
    : projectExecutions.value
  return list.slice().sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
})
const selectedExecution = computed(() => executions.value.find((execution) => execution.id === selectedExecutionId.value) || null)
const executionResults = computed(() => Array.isArray(selectedExecution.value?.results) ? selectedExecution.value.results : [])
const passRate = computed(() => {
  const total = selectedExecution.value?.total_requests || 0
  if (!total) return 0
  return Math.round(((selectedExecution.value?.passed_requests || 0) / total) * 100)
})

async function fetchAll(url, params = {}) {
  const result = []
  let page = 1
  while (page <= 50) {
    const response = await api.get(url, { params: { ...params, page } })
    const data = response.data
    if (Array.isArray(data)) return data
    result.push(...(data.results || []))
    if (!data.next) break
    page += 1
  }
  return result
}

async function loadProjects() {
  projects.value = await fetchAll('/api-testing/projects/')
  if (projects.value.length) {
    const requested = Number(route.query.project)
    projectId.value = projects.value.some((project) => project.id === requested) ? requested : projects.value[0].id
    await loadProjectData()
  }
}

async function loadProjectData() {
  if (!projectId.value) return
  loading.value = true
  try {
    const [suiteList, executionList] = await Promise.all([
      fetchAll('/api-testing/test-suites/', { project: projectId.value }),
      fetchAll('/api-testing/test-executions/'),
    ])
    suites.value = suiteList
    executions.value = executionList
    const requestedSuite = Number(route.query.suite)
    const requestedExecution = Number(route.query.execution)
    if (requestedSuite && suiteList.some((suite) => suite.id === requestedSuite)) {
      selectedSuiteId.value = requestedSuite
    } else if (!selectedSuiteId.value || !suiteList.some((suite) => suite.id === selectedSuiteId.value)) {
      selectedSuiteId.value = suiteList[0]?.id || null
    }
    if (requestedExecution && executionList.some((execution) => execution.id === requestedExecution)) {
      selectedExecutionId.value = requestedExecution
    } else if (!selectedExecutionId.value) {
      selectedExecutionId.value = visibleExecutions.value[0]?.id || null
    }
  } catch (error) {
    ElMessage.error(`加载执行记录失败：${error.response?.data?.detail || error.message}`)
  } finally {
    loading.value = false
  }
}

async function onProjectChange() {
  selectedSuiteId.value = null
  selectedExecutionId.value = null
  await loadProjectData()
}

function selectSuite(suite) {
  selectedSuiteId.value = suite.id
  selectedExecutionId.value = visibleExecutions.value[0]?.id || null
}

function selectExecution(execution) {
  selectedExecutionId.value = execution.id
  if (execution.test_suite?.id) selectedSuiteId.value = execution.test_suite.id
}

async function runSelectedSuite() {
  if (!selectedSuite.value?.scenario_config?.steps?.length) {
    ElMessage.warning('这个场景还没有配置步骤')
    return
  }
  running.value = true
  try {
    const response = await api.post('/api-testing/agent/run/', {
      project_id: projectId.value,
      test_suite_id: selectedSuite.value.id,
      environment_id: selectedSuite.value.environment,
      steps: runSteps(selectedSuite.value.scenario_config.steps),
    }, { timeout: 300000 })
    ElMessage.success('场景执行完成')
    await loadProjectData()
    if (response.data.execution_id) selectedExecutionId.value = response.data.execution_id
  } catch (error) {
    ElMessage.error(`执行失败：${error.response?.data?.error || error.message}`)
  } finally {
    running.value = false
  }
}

function refreshData() {
  loadProjectData()
}

function goDesign(suiteId = null) {
  const query = { project: projectId.value }
  if (suiteId || selectedSuiteId.value) query.suite = suiteId || selectedSuiteId.value
  router.push({ path: '/api-testing/design', query })
}

function go(path) {
  settingsVisible.value = false
  router.push(path)
}

function statusClass(status) {
  return `st-${String(status || '').toLowerCase()}`
}

function statusLabel(status) {
  return { pass: '通过', fail: '失败', error: '错误', skip: '跳过', COMPLETED: '已完成', FAILED: '失败', RUNNING: '执行中' }[status] || status || ''
}

function lastExecution(suiteId) {
  return projectExecutions.value
    .filter((execution) => execution.test_suite?.id === suiteId)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0]
}

function lastStatusLabel(suiteId) {
  const execution = lastExecution(suiteId)
  return execution ? statusLabel(execution.status) : '未运行'
}

function lastStatusClass(suiteId) {
  const execution = lastExecution(suiteId)
  return execution ? statusClass(execution.status) : 'st-idle'
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

function executionDuration(execution) {
  if (!execution.start_time || !execution.end_time) return ''
  return `${Math.round((new Date(execution.end_time) - new Date(execution.start_time)) / 1000)}s`
}

function hasObject(value) {
  return value && typeof value === 'object' && Object.keys(value).length > 0
}

function pretty(value) {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch (_) {
      return value
    }
  }
  return JSON.stringify(value, null, 2)
}

function assertionLabel(assertion) {
  if (assertion.type === 'status_code') return `状态码 = ${assertion.expected}`
  if (assertion.type === 'json_path_exists') return `${assertion.path || '字段'} 存在`
  if (assertion.type === 'json_path') return `${assertion.path || '字段'} = ${assertion.expected}`
  if (assertion.type === 'contains') return `响应包含“${assertion.expected}”`
  if (assertion.type === 'response_time') return `响应时间 ≤ ${assertion.expected}ms`
  return assertion.type || '校验'
}

function shortValue(value) {
  if (value && typeof value === 'object') return JSON.stringify(value).slice(0, 60)
  return String(value ?? '').slice(0, 60)
}

onMounted(async () => {
  loading.value = true
  try {
    await loadProjects()
  } catch (error) {
    ElMessage.error(`加载项目失败：${error.response?.data?.detail || error.message}`)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.runs-page {
  --line: #e5e8ef;
  --muted: #7c8497;
  min-height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
  background: #f5f7fb;
}
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 18px 24px; background: #fff; border-bottom: 1px solid var(--line); }
.page-head h1 { margin: 0; font-size: 22px; color: #172033; }
.page-head p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
.head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.runs-workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: 260px minmax(380px, .85fr) minmax(440px, 1.15fr); gap: 12px; padding: 12px; }
.suite-panel, .history-panel, .detail-panel { min-height: 0; background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 3px 14px rgba(20, 31, 56, .04); }
.suite-panel { padding: 14px; overflow-y: auto; }
.history-panel { padding: 16px; overflow-y: auto; }
.detail-panel { padding: 16px; overflow-y: auto; }
.panel-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; font-weight: 650; color: #273047; font-size: 14px; }
.count-badge { min-width: 24px; text-align: center; color: #667085; background: #f2f4f7; border-radius: 10px; font-size: 12px; padding: 2px 7px; }
.suite-item { width: 100%; border: 0; background: transparent; text-align: left; padding: 10px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; }
.suite-item:hover, .suite-item.active { background: #eef4ff; }
.suite-row { display: flex; align-items: center; gap: 8px; }
.suite-name { color: #344054; font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.suite-item.active .suite-name { color: #175cd3; }
.run-mini { margin-left: auto; font-size: 10px; padding: 2px 6px; border-radius: 9px; background: #f2f4f7; color: #667085; }
.suite-meta { margin-top: 5px; color: #98a2b3; font-size: 11px; }
.history-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 13px; border-bottom: 1px solid #eef1f6; }
.history-head h3, .detail-head h3 { margin: 0; color: #273047; font-size: 16px; }
.history-head p, .detail-head p { margin: 5px 0 0; color: var(--muted); font-size: 12px; }
.execution-list { display: flex; flex-direction: column; gap: 5px; padding-top: 10px; }
.execution-row { width: 100%; border: 1px solid transparent; background: #fff; display: flex; align-items: center; gap: 9px; padding: 10px; border-radius: 8px; text-align: left; cursor: pointer; }
.execution-row:hover { background: #f8fafc; }
.execution-row.active { border-color: #b8c6e6; background: #f8faff; }
.run-dot { width: 9px; height: 9px; border-radius: 50%; background: #98a2b3; flex: none; }
.run-dot.st-completed, .run-dot.st-pass { background: #12b76a; }
.run-dot.st-failed, .run-dot.st-fail, .run-dot.st-error { background: #f04438; }
.execution-main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.execution-name { color: #344054; font-size: 12px; font-weight: 600; }
.execution-time { color: #98a2b3; font-size: 11px; }
.execution-counts { margin-left: auto; display: flex; gap: 5px; font-size: 10px; white-space: nowrap; }
.pass-count { color: #067647; }
.fail-count { color: #b42318; }
.execution-duration { color: #667085; font-size: 11px; width: 34px; text-align: right; }
.empty-history { min-height: 320px; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #98a2b3; text-align: center; }
.empty-history h3 { color: #475467; margin: 0 0 5px; }
.empty-history p { margin: 0; font-size: 13px; }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.detail-kicker { color: #98a2b3; font-size: 11px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; margin: 16px 0; }
.summary-card { background: #f8fafc; border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 2px; }
.summary-card b { color: #273047; font-size: 19px; }
.summary-card span { color: #7c8497; font-size: 11px; }
.summary-card.pass b { color: #067647; }
.summary-card.fail b { color: #b42318; }
.timeline { display: flex; flex-direction: column; gap: 9px; }
.result-card { border: 1px solid #e5e8ef; border-radius: 9px; padding: 11px 12px; background: #fff; }
.result-card.st-pass { border-left: 3px solid #12b76a; }
.result-card.st-fail, .result-card.st-error { border-left: 3px solid #f04438; }
.result-head { display: flex; align-items: center; gap: 8px; }
.result-index { width: 21px; height: 21px; border-radius: 50%; background: #f2f4f7; color: #475467; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; }
.result-name { color: #344054; font-size: 13px; font-weight: 600; }
.result-http, .result-time { color: #667085; font-size: 10px; background: #f2f4f7; border-radius: 4px; padding: 2px 5px; }
.result-time { margin-left: auto; }
.result-status { color: #475467; font-size: 11px; }
.result-card.st-pass .result-status { color: #067647; }
.result-card.st-fail .result-status, .result-card.st-error .result-status { color: #b42318; }
.result-message { margin-top: 7px; color: #b42318; background: #fef3f2; border-radius: 5px; padding: 6px 8px; font-size: 12px; }
.captured-row { margin-top: 7px; display: flex; align-items: center; flex-wrap: wrap; gap: 5px; color: #667085; font-size: 11px; }
.captured-row code { background: #eff8ff; color: #175cd3; border-radius: 4px; padding: 2px 5px; }
.result-collapse { margin-top: 7px; }
.result-collapse :deep(.el-collapse-item__header) { height: 28px; color: #667085; font-size: 11px; background: transparent; border-bottom: 0; }
.result-collapse :deep(.el-collapse-item__wrap) { border-bottom: 0; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.detail-grid h5 { margin: 8px 0 4px; color: #667085; font-size: 11px; }
.detail-grid pre { margin: 0; padding: 8px; background: #f8fafc; border-radius: 6px; max-height: 230px; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: 11px; color: #344054; }
.empty-mini { color: #98a2b3; font-size: 12px; padding: 12px 2px; }
.settings-tip { color: #667085; font-size: 13px; line-height: 1.7; }
.settings-list { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; }
.settings-item { display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid #e5e8ef; border-radius: 9px; background: #fff; text-align: left; cursor: pointer; }
.settings-item:hover { border-color: #b8c6e6; background: #f8faff; }
.settings-item b { color: #273047; }
.settings-item span { color: #7c8497; font-size: 12px; }
@media (max-width: 1320px) {
  .runs-workspace { grid-template-columns: 240px minmax(360px, 1fr); }
  .detail-panel { grid-column: 1 / -1; max-height: 520px; }
}


/* 浅色柔和视觉与可读性增强 */
.runs-page {
  --line: #e2e7f2;
  --muted: #758096;
  color: #33405a;
  background:
    radial-gradient(circle at 8% 0%, #edf5ff 0, transparent 34%),
    radial-gradient(circle at 94% 3%, #f5efff 0, transparent 30%),
    linear-gradient(135deg, #f8faff 0%, #fbf9ff 54%, #f6fcfa 100%);
}
.page-head {
  background: linear-gradient(135deg, #fbfdff 0%, #f7f2ff 58%, #f0fbf7 100%);
  border-bottom-color: #dfe5f1;
}
.page-head h1 { font-size: 24px; letter-spacing: .2px; }
.page-head p { font-size: 14px; color: #6f7b91; }
.suite-panel { background: linear-gradient(180deg, #f7fbf7 0%, #fff 56%, #f9fcff 100%); }
.history-panel { background: linear-gradient(180deg, #f7faff 0%, #fff 52%); }
.detail-panel { background: linear-gradient(180deg, #fffaf6 0%, #fff 50%, #faf8ff 100%); }
.suite-panel, .history-panel, .detail-panel { border-color: #e1e6f1; box-shadow: 0 8px 24px rgba(104, 126, 170, .07); }
.panel-title { font-size: 15px; color: #35425c; }
.suite-name { font-size: 14px; }
.suite-meta { font-size: 12px; color: #8b95a9; }
.history-head h3, .detail-head h3 { font-size: 17px; color: #35425c; }
.history-head p, .detail-head p { font-size: 13px; color: #778399; }
.execution-name { font-size: 13px; color: #3c4962; }
.execution-time { font-size: 12px; }
.execution-counts { font-size: 11px; }
.execution-duration { font-size: 12px; }
.summary-grid { gap: 9px; }
.summary-card { padding: 12px; background: #f7f9ff; border: 1px solid #edf0f7; }
.summary-card:nth-child(1) { background: #f1f6ff; }
.summary-card.pass { background: #edf8f2; }
.summary-card.fail { background: #fff1f3; }
.summary-card b { font-size: 21px; }
.summary-card span { font-size: 12px; }
.result-card { border-color: #e2e7f1; box-shadow: 0 4px 14px rgba(105, 125, 170, .04); }
.result-name { font-size: 14px; }
.result-index { font-size: 12px; background: #eef3ff; color: #5d75ad; }
.result-http, .result-time { font-size: 11px; background: #f4f6fb; }
.result-status { font-size: 12px; }
.result-message { font-size: 13px; background: #fff0f2; color: #b25d68; }
.captured-row { font-size: 12px; }
.captured-row code { background: #eaf7f2; color: #4c7f70; }
.assertion-results { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.assertion-pill { border-radius: 12px; padding: 4px 9px; font-size: 12px; }
.assertion-pill.is-pass { color: #4f806e; background: #eaf7f1; }
.assertion-pill.is-fail { color: #b05e69; background: #fff0f2; }
.result-collapse :deep(.el-collapse-item__header) { font-size: 12px; color: #758096; }
.detail-grid h5 { font-size: 12px; color: #758096; }
.detail-grid pre { font-size: 12px; background: #f8faff; }
.runs-page :deep(.el-input__inner),
.runs-page :deep(.el-select__selected-item),
.runs-page :deep(.el-button) { font-size: 13px; }
.runs-page :deep(.el-button--primary) {
  --el-button-bg-color: #7d95d6;
  --el-button-border-color: #7d95d6;
  --el-button-hover-bg-color: #8ea4df;
  --el-button-hover-border-color: #8ea4df;
  --el-button-active-bg-color: #7089cc;
  --el-button-active-border-color: #7089cc;
}
</style>
