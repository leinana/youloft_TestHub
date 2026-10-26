<template>
  <div class="param-page">
    <div class="page-topbar">
      <div class="topbar-left">
        <h2 class="page-title">参数智能分析</h2>
        <span class="page-desc">AI 分析 → 人工确认 → 需求澄清 → 生成用例 → 执行报告</span>
      </div>
      <div class="topbar-right">
        <el-button @click="loadRequests" :loading="loading">刷新列表</el-button>
        <el-button type="primary" @click="startAnalysis" :loading="analyzing" :disabled="selectedIds.length===0">
          分析选中 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>

    <!-- 流程引导 -->
    <div class="flow-bar">
      <div class="flow-step" :class="{ done: flowStep >= 1 }"><span class="flow-idx">1</span>AI 参数分析</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step" :class="{ active: flowStep === 1, done: flowStep >= 2 }"><span class="flow-idx">2</span>人工确认</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step" :class="{ active: flowStep === 2, done: flowStep >= 3 }"><span class="flow-idx">3</span>需求澄清</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step" :class="{ active: flowStep === 3, done: flowStep >= 4 }"><span class="flow-idx">4</span>生成用例</div>
      <span class="flow-arrow">→</span>
      <div class="flow-step" :class="{ active: flowStep === 4, done: flowStep >= 5 }"><span class="flow-idx">5</span>执行报告</div>
      <span v-if="flowStep > 0" class="flow-current">当前：{{ flowLabels[flowStep] }}</span>
    </div>

    <div class="main-content">
      <!-- 左侧：接口列表 -->
      <div class="left-panel">
        <div class="panel-header">
          <span class="panel-title">接口列表</span>
          <span class="panel-badge">{{ requests.length }}</span>
        </div>

        <div v-if="loading" class="empty-state">加载中...</div>
        <div v-else-if="requests.length===0" class="empty-state">暂无接口</div>

        <div v-else class="list-body">
          <div v-for="group in groupedRequests" :key="group.name" class="ver-group">
            <div class="group-bar" @click="toggleGroup(group.name)">
              <span class="group-arrow">{{ expandedGroups.has(group.name)?'▾':'▸' }}</span>
              <span class="group-folder">📁</span>
              <span class="group-name">{{ group.name }}</span>
              <span class="group-num">{{ group.items.length }}</span>
              <span class="group-actions" @click.stop>
                <a class="act-link" @click="selectGroup(group)">全选</a>
                <a class="act-link" @click="deselectGroup(group)">取消</a>
              </span>
            </div>
            <div v-if="expandedGroups.has(group.name)" class="group-items">
              <div v-for="r in group.items" :key="r.id"
                class="iface-row"
                :class="{ isActive: activeReqId===r.id }"
                @click="onClickIface(r)"
              >
                <el-checkbox v-model="selectedIds" :value="r.id" size="small" />
                <span class="iface-method" :class="'method-'+r.method.toLowerCase()">{{ r.method }}</span>
                <div class="iface-info">
                  <div class="iface-name">{{ r.name }}</div>
                  <div class="iface-path">{{ r.url }}</div>
                </div>
                <span v-if="confirmedIds.has(r.id)" class="status-tag ok">已确认</span>
                <span v-else-if="analyzedIds.has(r.id)" class="status-tag info">已分析</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：分析结果 -->
      <div class="right-panel" v-if="showDetail">
        <div class="panel-header">
          <span class="panel-title">分析详情</span>
          <el-button text @click="showDetail=false">✕</el-button>
        </div>
        <div class="detail-body">
          <div class="detail-req">
            <span class="detail-method" :class="'method-'+detailMethod.toLowerCase()">{{ detailMethod }}</span>
            <span class="detail-name">{{ detailName }}</span>
          </div>
          <div v-if="activeReqId && confirmedIds.has(activeReqId)" class="next-step-banner">
            <div class="next-step-left"><span class="next-step-icon">✅</span>「{{ detailName }}」参数分析已确认，下一步：生成测试用例并执行</div>
          </div>

          <el-alert v-for="(sug,i) in detailAnalysis?.suggestions||[]" :key="i"
            :title="sug" type="info" :closable="false" class="detail-sug" />

          <div class="param-cards">
            <div v-for="(p,i) in detailParams" :key="i" class="param-card">
              <div class="param-head">
                <span class="param-name">{{ p.name }}</span>
                <span class="param-type">{{ p.type||'string' }}</span>
                <span v-if="p.required" class="param-required">必填</span>
                <span v-if="p.needs_real_data" class="param-real">需真实数据</span>
                <span class="param-desc">{{ p.description }}</span>
                <el-button link size="small" @click="editParam(p,i)">编辑</el-button>
              </div>
              <div class="param-body">
                <div class="param-section">
                  <span class="param-label">边界值</span>
                  <span v-for="v in p.boundary_values||[]" :key="v" class="boundary-tag">{{ v }}</span>
                  <span v-if="!(p.boundary_values||[]).length" class="no-data">—</span>
                </div>
                <div class="param-section">
                  <span class="param-label">异常场景</span>
                  <span v-for="v in p.exception_scenarios||[]" :key="v" class="exception-tag">{{ v }}</span>
                  <span v-if="!(p.exception_scenarios||[]).length" class="no-data">—</span>
                </div>
                <div v-if="p.needs_real_data" class="param-section">
                  <span class="param-label">数据来源</span>
                  <el-input v-model="p.data_source" size="small" style="max-width:380px" placeholder="字段名 或 上游接口名.响应路径" />
                  <span class="ds-hint">如 challenge_id 或 发起挑战.data.challenge_id</span>
                </div>
              </div>
            </div>
          </div>

          <div class="clarify-section">
            <div class="clarify-head">
              <span class="clarify-title">需求澄清</span>
              <span v-if="clarify.clarified" class="status-tag ok">已澄清</span>
              <span v-else-if="clarify.questions.length" class="status-tag info">待确认</span>
              <el-button v-if="!clarify.questions.length" size="small" type="primary" plain :loading="clarifying" @click="generateClarify">AI 生成澄清问题</el-button>
              <el-button v-else size="small" type="warning" plain :loading="clarifying" @click="generateClarify">重新生成</el-button>
            </div>
            <div v-if="clarify.questions.length" class="clarify-list">
              <div v-for="(q,i) in clarify.questions" :key="i" class="clarify-item">
                <div class="clarify-q">{{ i+1 }}. {{ q.question }}</div>
                <el-input v-model="q.answer" type="textarea" :rows="2" placeholder="请输入你的确认/补充说明" size="small" />
              </div>
              <div class="clarify-tip">澄清说明可填写可不填写，直接点击下方「确认分析」即会同时保存澄清并确认分析</div>
            </div>
          </div>

          <div class="detail-footer">
            <div v-if="activeReqId && !confirmedIds.has(activeReqId)" class="confirm-tip">👆 请核对上方参数、边界值与异常场景，确认无误后点击「确认分析」</div>
            <div class="footer-row">
              <el-button type="primary" @click="confirmAnalysis">确认分析</el-button>
              <el-button v-if="activeReqId && confirmedIds.has(activeReqId)" type="success" @click="goCaseManagement">去用例管理 →</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 分析中的全屏遮罩 + 进度条（阻止操作页面） -->
    <div v-if="analyzing" class="analyze-overlay">
      <div class="analyze-box">
        <div class="analyze-title">🤖 AI 参数分析中...</div>
        <el-progress :percentage="Math.round(analyzeProgress)" :stroke-width="12" class="analyze-progress" />
        <div class="analyze-tip">正在分析 {{ analyzeTotal }} 个接口，请稍候，期间请勿操作页面</div>
      </div>
    </div>

    <!-- 编辑参数弹窗 -->
    <el-dialog v-model="showEditParam" title="编辑参数" width="500px" append-to-body>
      <el-form :model="editForm" label-width="80px" size="small">
        <el-form-item label="参数名"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="类型"><el-input v-model="editForm.type" /></el-form-item>
        <el-form-item label="必填"><el-switch v-model="editForm.required" /></el-form-item>
        <el-form-item label="边界值"><el-input v-model="editForm.boundaryText" type="textarea" :rows="2" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="异常场景"><el-input v-model="editForm.exceptionText" type="textarea" :rows="4" placeholder="每行一个" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="editForm.description" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="showEditParam=false">取消</el-button><el-button type="primary" @click="saveEditedParam">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'

const requests = ref([])
const loading = ref(false)
const selectedIds = ref([])
const analyzedIds = reactive(new Set())
const confirmedIds = reactive(new Set())
const expandedGroups = reactive(new Set())
const analyzing = ref(false)
const showDetail = ref(false)
const activeReqId = ref(null)
const detailName = ref('')
const detailMethod = ref('')
const detailAnalysis = ref(null)
const showEditParam = ref(false)
const clarify = ref({ questions: [], clarified: false })
const clarifying = ref(false)
const editForm = reactive({ name:'',type:'',required:false,boundaryText:'',exceptionText:'',description:'' })
const editIndex = ref(-1)

const groupedRequests = computed(() => {
  const groups = {}
  for (const r of requests.value) {
    const key = r._colName || '未分组'
    if(!groups[key]) groups[key] = []
    groups[key].push(r)
  }
  return Object.entries(groups).map(([name,items]) => ({name,items}))
})
const detailParams = computed(() => detailAnalysis.value?.parameters || [])

const router = useRouter()
const flowLabels = ['', '人工确认', '需求澄清', '生成用例', '执行报告']
// 当前流程进度（0=未分析 1=已分析 2=已确认 3=澄清完成）
const flowStep = computed(() => {
  const rid = activeReqId.value
  if (!rid || !analyzedIds.has(rid)) return 0
  if (!confirmedIds.has(rid)) return 1
  if (!clarify.value.clarified) return 2
  return 3
})
const goCaseManagement = () => {
  router.push({ path: '/api-testing/case-management', query: { request_id: activeReqId.value } })
}

const toggleGroup = (n) => expandedGroups.has(n) ? expandedGroups.delete(n) : expandedGroups.add(n)
const selectGroup = (g) => {
  const ids = g.items.map(r=>r.id)
  selectedIds.value = [...new Set([...selectedIds.value,...ids])]
}
const deselectGroup = (g) => {
  const ids = new Set(g.items.map(r=>r.id))
  selectedIds.value = selectedIds.value.filter(id=>!ids.has(id))
}

// 分页接口全量加载：后端使用 PageNumberPagination（PAGE_SIZE=20），需循环拉取所有页，避免列表被截断
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
  loading.value = true
  try {
    const [allRequests, allCollections] = await Promise.all([
      fetchAllPages('/api-testing/requests/'),
      fetchAllPages('/api-testing/collections/')
    ])
    const colMap = {}; allCollections.forEach(c=>colMap[c.id]=c.name)
    // 最新同步的接口排在最前面（created_at 倒序）
    requests.value = allRequests
      .map(r=>({...r, _colName: colMap[r.collection]||'未分组'}))
      .sort((a,b)=> (b.created_at||'').localeCompare(a.created_at||''))
    await loadAnalyses()
  } catch(e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const loadAnalyses = async () => {
  try {
    const r = await api.get('/api-testing/param-analysis/')
    const list = r.data.analyses||[]
    analyzedIds.clear(); confirmedIds.clear()
    list.forEach(a=>{ analyzedIds.add(a.request_id); if(a.confirmed) confirmedIds.add(a.request_id) })
  } catch(_) {}
}

const analyzeProgress = ref(0)
const analyzeTotal = ref(0)

const startAnalysis = async () => {
  analyzing.value = true
  analyzeTotal.value = selectedIds.value.length
  analyzeProgress.value = 0
  // 后端批量接口为一次性返回，前端用动画模拟进度（到 90%，完成后跳到 100%）
  const timer = setInterval(() => {
    if (analyzeProgress.value < 90) {
      analyzeProgress.value = Math.min(90, analyzeProgress.value + Math.random() * 8)
    }
  }, 500)
  try {
    const r = await api.post('/api-testing/param-analysis/batch/', {request_ids: selectedIds.value})
    analyzeProgress.value = 100
    ElMessage.success(`完成: ${r.data.analyzed}/${r.data.total}`)
    await loadAnalyses()
    // 分析完成后直接展示详情（优先展示第一个已成功分析的选中接口）
    const target = requests.value.find(x => selectedIds.value.includes(x.id) && analyzedIds.has(x.id))
    if (target) {
      onClickIface(target)
    } else {
      showDetail.value = false
      activeReqId.value = null
    }
  } catch(e) { ElMessage.error('分析失败: '+(e.response?.data?.error||e.message)) }
  finally {
    clearInterval(timer)
    setTimeout(() => { analyzing.value = false }, 400)
  }
}

const onClickIface = async (req) => {
  activeReqId.value = req.id
  if (analyzedIds.has(req.id)) {
    try {
      const r = await api.get(`/api-testing/param-analysis/${req.id}/`)
      detailName.value = req.name
      detailMethod.value = req.method
      detailAnalysis.value = r.data.analysis
      showDetail.value = true
      await loadClarification(req.id)
      // AI 提问澄清自动展示：尚未生成时自动生成
      if (!clarify.value.questions.length && !clarify.value.clarified) {
        await generateClarify()
      }
    } catch(e) { ElMessage.error('加载失败') }
  } else {
    showDetail.value = false
    ElMessage.info('该接口尚未分析，请勾选后点击"分析选中"')
  }
}

const editParam = (row, i) => {
  editIndex.value = i
  editForm.name = row.name||''
  editForm.type = row.type||'string'
  editForm.required = row.required||false
  editForm.boundaryText = (row.boundary_values||[]).join(', ')
  editForm.exceptionText = (row.exception_scenarios||[]).join('\n')
  editForm.description = row.description||''
  showEditParam.value = true
}
const saveEditedParam = () => {
  const i = editIndex.value
  if(i<0||!detailAnalysis.value?.parameters) return
  detailAnalysis.value.parameters[i] = {
    ...detailAnalysis.value.parameters[i],
    name: editForm.name, type: editForm.type, required: editForm.required,
    boundary_values: editForm.boundaryText.split(',').map(s=>s.trim()).filter(Boolean),
    exception_scenarios: editForm.exceptionText.split('\n').map(s=>s.trim()).filter(Boolean),
    description: editForm.description,
  }
  showEditParam.value = false
  ElMessage.success('已修改')
}
const confirmAnalysis = async () => {
  const req = requests.value.find(r=>r.id===activeReqId.value)
  if(!req) return
  try {
    // 先保存澄清（无需全部填写，未回答的保留为空）
    if (clarify.value.questions.length) {
      try {
        await api.put(`/api-testing/clarify/${activeReqId.value}/save/`, {
          questions: clarify.value.questions,
          clarified: true,
        })
        clarify.value.clarified = true
      } catch (e) {
        ElMessage.warning('澄清保存失败: '+(e.response?.data?.error||e.message))
      }
    }
    await api.put(`/api-testing/param-analysis/${activeReqId.value}/save/`, {analysis: detailAnalysis.value, confirmed: true})
    confirmedIds.add(activeReqId.value)
    ElMessage.success('已确认分析')
  } catch(e) { ElMessage.error('确认失败: '+(e.response?.data?.error||e.message)) }
}

const loadClarification = async (reqId) => {
  clarify.value = { questions: [], clarified: false }
  try {
    const r = await api.get(`/api-testing/clarify/${reqId}/`)
    clarify.value = r.data
  } catch (_) {}
}

const generateClarify = async () => {
  clarifying.value = true
  try {
    const r = await api.post(`/api-testing/clarify/${activeReqId.value}/generate/`)
    clarify.value = { questions: r.data.questions, clarified: false }
    ElMessage.success(`已生成 ${r.data.questions.length} 个澄清问题，请逐条确认`)
  } catch (e) {
    ElMessage.error('生成澄清问题失败: ' + (e.response?.data?.error || e.message))
  } finally { clarifying.value = false }
}


onMounted(()=>{ loadRequests() })
</script>

<style scoped>
.param-page { display: flex; flex-direction: column; height: calc(100vh - 60px); background: #f5f6f8; }
.page-topbar { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; background: #fff; border-bottom: 1px solid #e8eaed; }
.topbar-left { display: flex; align-items: baseline; gap: 12px; }
.page-title { margin: 0; font-size: 18px; font-weight: 600; color: #1a1a2e; }
.page-desc { font-size: 13px; color: #8b8fa3; }
.main-content { display: flex; flex: 1; overflow: hidden; }

/* 左侧列表 */
.left-panel { width: 420px; min-width: 340px; background: #fff; border-right: 1px solid #e8eaed; display: flex; flex-direction: column; }
.panel-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid #f0f0f0; }
.panel-title { font-weight: 600; font-size: 14px; }
.panel-badge { background: #e8eaed; color: #5f6368; font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.empty-state { padding: 60px 20px; text-align: center; color: #9aa0a6; font-size: 14px; }
.list-body { flex: 1; overflow-y: auto; }

.ver-group { border-bottom: 1px solid #f0f0f0; }
.group-bar { display: flex; align-items: center; gap: 6px; padding: 8px 12px; cursor: pointer; font-size: 13px; font-weight: 500; color: #3c4043; user-select: none; }
.group-bar:hover { background: #f8f9fa; }
.group-arrow { font-size: 10px; color: #9aa0a6; width: 14px; }
.group-num { background: #e8eaed; color: #5f6368; font-size: 11px; padding: 0 6px; border-radius: 8px; }
.group-actions { margin-left: auto; display: flex; gap: 8px; }
.act-link { font-size: 12px; color: #1a73e8; font-weight: 400; cursor: pointer; }
.act-link:hover { text-decoration: underline; }

.group-items { }
.iface-row { display: flex; align-items: center; gap: 8px; padding: 6px 12px 6px 32px; font-size: 13px; cursor: pointer; border-bottom: 1px solid #fafafa; }
.iface-row:hover { background: #f1f3f4; }
.iface-row.isActive { background: #e3edfd; box-shadow: inset 3px 0 0 #1a73e8; }
.iface-method { font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; color: #fff; min-width: 44px; text-align: center; }
.method-get { background: #e8f0fe; color: #1a73e8; }
.method-post { background: #e6f4ea; color: #188038; }
.method-put { background: #fef7e0; color: #e37400; }
.method-delete { background: #fce8e6; color: #d93025; }
.iface-info { flex: 1; overflow: hidden; }
.iface-name { font-weight: 500; color: #202124; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.iface-path { font-size: 11px; color: #9aa0a6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 1px; }
.status-tag { font-size: 11px; padding: 1px 6px; border-radius: 8px; flex-shrink: 0; }
.status-tag.ok { background: #e6f4ea; color: #137333; }
.status-tag.info { background: #e8f0fe; color: #1967d2; }

/* 右侧详情 */
.right-panel { flex: 1; background: #fff; display: flex; flex-direction: column; overflow: hidden; }
.detail-body { flex: 1; overflow-y: auto; padding: 20px 28px; font-size: 14px; }
.detail-req { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid #f0f1f3; }
.detail-method { font-size: 14px; font-weight: 700; padding: 5px 14px; border-radius: 6px; color: #fff; letter-spacing: .5px; }
.detail-name { font-size: 22px !important; font-weight: 700; color: #1a1a2e; }
.detail-sug { margin-bottom: 12px; }

.param-cards { display: flex; flex-direction: column; gap: 12px; margin-top: 20px; }
.param-card { border: 1px solid #e8eaed; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
.param-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: #f8f9fa; border-bottom: 1px solid #e8eaed; }
.param-name { font-weight: 700; font-size: 16px; color: #202124; }
.param-type { font-size: 13px; background: #e8eaed; color: #5f6368; padding: 3px 10px; border-radius: 6px; font-family: monospace; }
.param-required { font-size: 12px; background: #fce8e6; color: #c5221f; padding: 2px 9px; border-radius: 5px; font-weight: 600; }
.param-real { font-size: 12px; background: #fef7e0; color: #b25e00; padding: 2px 9px; border-radius: 5px; font-weight: 600; }
.param-desc { font-size: 14px; color: #5f6368; flex: 1; }
.param-body { padding: 14px 16px; }
.param-section { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 10px; font-size: 14px; }
.param-label { font-size: 13px; font-weight: 600; color: #9aa0a6; min-width: 56px; padding-top: 3px; flex-shrink: 0; }
.boundary-tag { font-size: 13px; background: #e8f0fe; color: #1967d2; padding: 4px 12px; border-radius: 12px; }
.exception-tag { font-size: 13px; background: #fef7e0; color: #e37400; padding: 4px 12px; border-radius: 6px; display: inline-block; margin-bottom: 4px; margin-right: 6px; }
.no-data { font-size: 13px; color: #dadce0; }
.ds-hint { font-size: 12px; color: #9aa0a6; }

.detail-footer { padding: 18px 0; border-top: 1px solid #e8eaed; margin-top: 20px; }
.clarify-section { margin-top: 20px; border: 1px solid #e8eaed; border-radius: 10px; padding: 14px 16px; background: #fafbfc; }
.clarify-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.clarify-title { font-weight: 700; font-size: 17px; color: #202124; }
.clarify-list { display: flex; flex-direction: column; gap: 12px; }
.clarify-item { border: 1px solid #e8eaed; border-radius: 8px; padding: 10px 12px; background: #fff; }
.clarify-item :deep(.el-textarea__inner) { font-size: 16px; line-height: 1.6; }
.clarify-q { font-size: 16px; color: #202124; margin-bottom: 10px; line-height: 1.6; font-weight: 500; }
.clarify-tip { font-size: 15px; color: #8b8fa3; margin-top: 10px; }

/* 分析中的全屏遮罩 */
.analyze-overlay { position: fixed; inset: 0; background: rgba(15,23,42,.45); display: flex; align-items: center; justify-content: center; z-index: 3000; }
.analyze-box { width: 440px; background: #fff; border-radius: 14px; padding: 36px 40px; text-align: center; box-shadow: 0 12px 40px rgba(0,0,0,.18); }
.analyze-title { font-size: 18px; font-weight: 700; color: #1a1a2e; margin-bottom: 24px; }
.analyze-progress { margin-bottom: 18px; }
.analyze-tip { font-size: 13px; color: #8b8fa3; }

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
.next-step-banner { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; padding: 12px 16px; background: linear-gradient(90deg,#e6f4ea,#f6fef9); border: 1px solid #b7e1c3; border-radius: 10px; }
.next-step-left { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: #137333; }
.next-step-icon { font-size: 18px; }

/* 确认提示 */
.confirm-tip { font-size: 13px; color: #e37400; margin-bottom: 8px; }
.footer-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
</style>
