<template>
  <div class="agent-scenario">
    <div class="page-header">
      <div>
        <h2>Agent 接口自动化</h2>
        <p>用一句话描述业务操作，AI 自动识别接口、排序并执行（正向流程，自动处理依赖取数）</p>
      </div>
    </div>

    <div class="plan-card">
      <div class="plan-row">
        <el-select v-model="projectId" placeholder="选择项目" style="width:240px" filterable>
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-input v-model="description" placeholder="例如：发起挑战，然后查看该挑战的信息" style="flex:1" clearable @keyup.enter="plan" />
        <el-button type="primary" @click="plan" :loading="planning" :disabled="!projectId || !description.trim()">AI 规划</el-button>
      </div>
    </div>

    <div v-if="planResult" class="plan-result">
      <div class="plan-title">场景：{{ planResult.scenario }}</div>
      <div v-for="(s,i) in planResult.steps" :key="i" class="step-card">
        <div class="step-head">
          <span class="step-no">{{ i + 1 }}</span>
          <span class="step-name">{{ s.interface }}</span>
          <span v-if="s.path" class="step-path">{{ s.method || '' }} {{ s.path }}</span>
        </div>
        <div v-if="Object.keys(s.params||{}).length" class="step-line"><b>参数:</b> {{ JSON.stringify(s.params) }}</div>
        <div v-if="s.body && Object.keys(s.body).length" class="step-line"><b>Body:</b> {{ JSON.stringify(s.body) }}</div>
        <div v-if="s.capture && s.capture.length" class="step-line"><b>捕获:</b> {{ s.capture.map(c => c.as + ' ← ' + c.path).join('；') }}</div>
      </div>
      <div class="plan-actions">
        <el-button type="success" @click="run" :loading="running">执行场景</el-button>
        <el-button @click="planResult=null; runResults=[]">清空</el-button>
      </div>
    </div>

    <div v-if="runResults.length" class="run-result">
      <div class="plan-title">执行结果 <span v-if="Object.keys(sessionVars).length" class="vars">会话变量：{{ JSON.stringify(sessionVars) }}</span></div>
      <div v-for="(r,i) in runResults" :key="i" class="result-card" :class="'st-'+r.status">
        <div class="result-head">
          <span class="result-status">{{ {pass:'✅ 通过',fail:'❌ 失败',error:'⚠️ 错误'}[r.status] || r.status }}</span>
          <span class="result-name">{{ r.interface }}</span>
          <span v-if="r.http_status" class="result-http">HTTP {{ r.http_status }}</span>
          <span v-if="r.time_ms" class="result-time">{{ r.time_ms }}ms</span>
          <el-button v-if="r.status==='fail' || r.status==='error'" size="small" type="warning" plain @click="showFailLog(r)">查看失败日志</el-button>
        </div>
        <div v-if="r.message" class="result-msg">{{ r.message }}</div>
        <div v-if="r.captured && Object.keys(r.captured).length" class="result-captured">捕获：{{ JSON.stringify(r.captured) }}</div>
        <pre v-if="r.response_body" class="resp-json">{{ prettyBody(r.response_body) }}</pre>
      </div>
    </div>

    <!-- 失败日志弹窗 -->
    <el-dialog v-model="failLogVisible" title="失败日志" width="760px" top="5vh">
      <template v-if="failLog">
        <div class="log-interface">{{ failLog.interface }}</div>
        <div class="log-meta">状态：{{ statusText(failLog) }}<template v-if="failLog.http_status"> ｜ HTTP {{ failLog.http_status }}</template><template v-if="failLog.time_ms"> ｜ {{ failLog.time_ms }}ms</template></div>
        <div v-if="failLog.message" class="log-block"><div class="log-title">错误信息</div><div class="log-content">{{ failLog.message }}</div></div>
        <div v-if="failLog.request_url" class="log-block"><div class="log-title">请求 URL</div><div class="log-content">{{ failLog.request_url }}</div></div>
        <div v-if="failLog.request_params && Object.keys(failLog.request_params).length" class="log-block"><div class="log-title">请求参数</div><pre class="log-pre">{{ JSON.stringify(failLog.request_params, null, 2) }}</pre></div>
        <div v-if="failLog.request_body" class="log-block"><div class="log-title">请求体</div><pre class="log-pre">{{ JSON.stringify(failLog.request_body, null, 2) }}</pre></div>
        <div v-if="failLog.response_body" class="log-block"><div class="log-title">响应体</div><pre class="log-pre json">{{ prettyBody(failLog.response_body) }}</pre></div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'

const projects = ref([])
const projectId = ref(null)
const description = ref('')
const planning = ref(false)
const running = ref(false)
const planResult = ref(null)
const runResults = ref([])
const sessionVars = ref({})
const failLogVisible = ref(false)
const failLog = ref(null)
const showFailLog = (r) => { failLog.value = r; failLogVisible.value = true }

const prettyBody = (text) => {
  if (!text) return ''
  try { return JSON.stringify(JSON.parse(text), null, 2) } catch (_) { return text }
}
const statusText = (r) => ({ pass:'✅ 通过', fail:'❌ 失败', error:'⚠️ 错误' }[r.status] || r.status || '')

const loadProjects = async () => {
  try {
    const r = await api.get('/api-testing/projects/')
    projects.value = r.data.results || r.data || []
    if (projects.value.length) projectId.value = projects.value[0].id
  } catch (_) { ElMessage.error('加载项目失败') }
}

const plan = async () => {
  if (!projectId.value || !description.value.trim()) return
  planning.value = true
  runResults.value = []
  sessionVars.value = {}
  try {
    const r = await api.post('/api-testing/agent/plan/', {
      project_id: projectId.value,
      description: description.value.trim(),
    }, { timeout: 180000 })
    planResult.value = r.data
    if (!r.data.steps || !r.data.steps.length) ElMessage.warning('AI 未识别到接口，请换一种描述')
  } catch (e) { ElMessage.error('规划失败: ' + (e.response?.data?.error || e.message)) }
  finally { planning.value = false }
}

const run = async () => {
  if (!planResult.value?.steps?.length) return
  running.value = true
  try {
    const r = await api.post('/api-testing/agent/run/', {
      project_id: projectId.value,
      steps: planResult.value.steps,
    }, { timeout: 300000 })
    runResults.value = r.data.results || []
    sessionVars.value = r.data.session_vars || {}
  } catch (e) { ElMessage.error('执行失败: ' + (e.response?.data?.error || e.message)) }
  finally { running.value = false }
}

onMounted(loadProjects)
</script>

<style scoped>
.agent-scenario { padding: 24px; max-width: 1100px; margin: 0 auto; }
.page-header h2 { margin: 0; }
.page-header p { color: #909399; margin-top: 6px; font-size: 13px; }
.plan-card { background: #fff; border: 1px solid #e8eaed; border-radius: 10px; padding: 16px; margin: 16px 0; }
.plan-row { display: flex; gap: 10px; align-items: center; }
.plan-result { margin-top: 16px; }
.plan-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; }
.vars { font-size: 12px; color: #1967d2; font-weight: 400; margin-left: 10px; }
.step-card { border: 1px solid #e8eaed; border-radius: 10px; background: #fff; padding: 12px 16px; margin-bottom: 10px; }
.step-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.step-no { width: 22px; height: 22px; border-radius: 50%; background: #1a73e8; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; }
.step-name { font-weight: 600; font-size: 15px; }
.step-path { font-size: 12px; color: #5f6368; background: #f1f3f4; padding: 2px 8px; border-radius: 4px; font-family: monospace; margin-left: auto; }
.step-line { font-size: 13px; color: #3c4043; margin: 3px 0; }
.plan-actions { margin-top: 12px; }
.run-result { margin-top: 20px; }
.result-card { border: 1px solid #e8eaed; border-radius: 10px; background: #fff; padding: 12px 16px; margin-bottom: 10px; }
.result-card.st-pass { border-color: #b7e1c3; }
.result-card.st-fail { border-color: #f3b8b3; }
.result-card.st-error { border-color: #f2dfae; }
.result-head { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.result-status { font-weight: 700; }
.st-pass .result-status { color: #137333; }
.st-fail .result-status { color: #c5221f; }
.st-error .result-status { color: #b25e00; }
.result-name { font-weight: 600; }
.result-http { font-size: 12px; background: #f1f3f4; padding: 2px 8px; border-radius: 4px; }
.result-time { font-size: 12px; color: #9aa0a6; margin-left: auto; }
.result-msg { font-size: 13px; color: #c5221f; margin-bottom: 4px; }
.result-captured { font-size: 12px; color: #1967d2; margin-bottom: 4px; }
.resp-json { margin: 0; padding: 12px 14px; background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 8px; font-size: 13px; line-height: 1.6; color: #202124; overflow: auto; max-height: 260px; white-space: pre-wrap; word-break: break-all; }
.log-pre.json { margin: 0; padding: 8px 10px; background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 6px; font-size: 13px; line-height: 1.6; color: #202124; overflow: auto; max-height: 240px; white-space: pre-wrap; word-break: break-all; }
.log-interface { font-size: 16px; font-weight: 700; margin-bottom: 6px; }
.log-meta { font-size: 13px; color: #5f6368; margin-bottom: 12px; }
.log-block { margin-bottom: 12px; }
.log-title { font-size: 12px; font-weight: 600; color: #9aa0a6; margin-bottom: 4px; }
.log-content { font-size: 13px; color: #c5221f; background: #fff5f5; border: 1px solid #f3b8b3; border-radius: 6px; padding: 8px 10px; }
.log-pre { margin: 0; background: #f8f9fa; border: 1px solid #eef0f2; border-radius: 6px; padding: 8px 10px; font-size: 12px; color: #3c4043; max-height: 240px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
</style>
