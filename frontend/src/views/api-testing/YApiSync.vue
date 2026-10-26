<template>
  <div class="yapi-sync-page">
    <div class="page-header">
      <h2>YApi 同步</h2>
      <p>按版本勾选，展开可预览接口</p>
    </div>

    <el-empty v-if="!connection && !loadingConnections" description="还没有 YApi 连接">
      <el-button type="primary" @click="openCreateDialog">新建连接</el-button>
    </el-empty>

    <el-alert
      v-if="tokenInvalid"
      class="token-alert"
      type="error"
      title="YApi Token 已失效，版本列表与同步都会失败"
      :closable="false"
      show-icon
    >
      <div class="alert-body">
        <div class="alert-text">{{ tokenCheck.message || 'YApi 拒绝了当前 Token（40011 请登录），请更新后重试。' }}</div>
        <div class="alert-actions">
          <el-button size="small" type="primary" @click="openEditDialog">去更新 Token</el-button>
          <el-button size="small" @click="verifyToken">重新校验</el-button>
        </div>
      </div>
    </el-alert>

    <el-card v-if="connection" class="config-card">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong>{{ connection.name }}</strong>
          <div>
            <el-button size="small" @click="openEditDialog">编辑</el-button>
            <el-button size="small" type="warning" plain @click="openEditDialog">更新 Token</el-button>
            <el-button size="small" type="danger" @click="deleteConnection">断开</el-button>
          </div>
        </div>
      </template>
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
        <el-select v-model="currentId" size="small" style="width:240px" @change="loadConnection">
          <el-option v-for="c in connections" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button size="small" type="primary" @click="openCreateDialog">新建连接</el-button>
        <el-button size="small" type="warning" @click="fixBaseUrl" :loading="fixing">统一路径格式</el-button>
        <el-button size="small" @click="verifyToken" :loading="checkingToken">校验 Token</el-button>
      </div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="YApi">{{ connection.yapi_url }}</el-descriptions-item>
        <el-descriptions-item label="项目 ID">{{ connection.yapi_project_id }}</el-descriptions-item>
        <el-descriptions-item label="关联">{{ connection.project_name }}</el-descriptions-item>
        <el-descriptions-item label="上次同步">{{ fmtTime(connection.last_synced_at) }}</el-descriptions-item>
        <el-descriptions-item label="Token 状态" :span="2">
          <span :class="tokenStatusClass">{{ tokenStatusText }}</span>
          <span v-if="tokenCheck.at" class="check-time">（实测于 {{ fmtTime(tokenCheck.at) }}）</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>


    <el-card v-if="connection" style="margin-top:16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong>版本列表（{{ categories.length }} 个，已选 {{ selectedCats.length }}）</strong>
          <div>
            <el-button size="small" @click="loadCategories" :loading="loadingCats">刷新</el-button>
            <el-button size="small" @click="selectedCats=categories.filter(c=>/^v?\d/.test(c.name)).map(c=>c.catid)">只选版本号</el-button>
            <el-button size="small" @click="selectedCats=[]">清空</el-button>
            <el-button
              size="small" type="primary" @click="startSync" :loading="syncing"
              :disabled="selectedCats.length===0 || tokenInvalid"
            >
              {{ syncing ? '同步中...' : `同步 ${selectedCats.length} 个版本` }}
            </el-button>
          </div>
        </div>
      </template>

      <div v-loading="loadingCats" class="ver-list">
        <el-empty
          v-if="!sortedCats.length && !loadingCats"
          :description="tokenInvalid ? 'Token 失效，读不到版本列表' : '没有读到分类，可点上方「刷新」重试'"
          :image-size="70"
        />
        <div v-for="c in sortedCats" :key="c.catid" class="ver-row">
          <div class="ver-main" @click="toggleExpand(c.catid)">
            <el-icon class="expand-icon" :class="{ expanded: expandedCats.has(c.catid) }">
              <component :is="expandedCats.has(c.catid) ? 'ArrowDown' : 'ArrowRight'" />
            </el-icon>
            <el-checkbox
              :model-value="selectedCats.includes(c.catid)"
              @change="toggleCat(c.catid)"
              @click.stop
              class="ver-check"
            />
            <span class="ver-name" :class="{ isVer: /^v?\d/.test(c.name) }">{{ c.name }}</span>
            <span class="ver-count">{{ c.count }} 个接口</span>
          </div>
          <div v-if="expandedCats.has(c.catid)" class="ver-detail">
            <div v-for="iface in c.interfaces" :key="iface.id" class="ver-iface">
              <el-tag :type="methodColor(iface.method)" size="small" class="method-tag">{{ iface.method }}</el-tag>
              <span class="iface-title">{{ iface.title }}</span>
              <span class="iface-path">{{ iface.path }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <div v-if="lastSyncResult" style="margin-top:12px;color:#67c23a;font-size:13px">
      上次: {{ lastSyncResult.status }} | 新增 {{ lastSyncResult.new }} | 更新 {{ lastSyncResult.updated }}
    </div>

    <el-card v-if="logs.length > 0" style="margin-top:16px">
      <template #header><strong>同步日志</strong> <span class="log-count">最近 {{ logs.length }} 条</span></template>
      <el-table :data="logs" size="small">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{row}">
            <el-tag :type="row.status==='success'?'success':row.status==='failed'?'danger':'warning'" size="small">
              {{ row.status==='success'?'成功':'失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_interfaces" label="总数" width="60" />
        <el-table-column prop="new_count" label="新增" width="60" />
        <el-table-column prop="updated_count" label="更新" width="60" />
      </el-table>
    </el-card>
  </div>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑连接' : '新建连接'" width="560px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="连接名称" required>
          <el-input v-model="form.name" placeholder="如：XX系统-YApi" />
        </el-form-item>
        <el-form-item label="关联项目" required>
          <el-select v-model="form.project" filterable style="width:100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="YApi 地址" required>
          <el-input v-model="form.yapi_url" placeholder="http://yapi.example.com" />
        </el-form-item>
        <el-form-item label="YApi Token" :required="!form.id">
          <el-input v-model="form.yapi_token" placeholder="_yapi_token 的值（编辑时留空则不修改）" show-password />
        </el-form-item>
        <el-form-item label="YApi UID">
          <el-input-number v-model="form.yapi_uid" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="YApi 项目ID" required>
          <el-input-number v-model="form.yapi_project_id" :min="1" style="width:100%" />
        </el-form-item>
        <el-form-item label="自动同步">
          <el-switch v-model="form.auto_sync" />
        </el-form-item>
        <el-form-item label="Token 有效天数">
          <el-input-number v-model="form.token_valid_days" :min="1" :max="90" :controls="false" style="width:160px" />
          <span class="form-tip">换 Token 后从当天重新计时</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="saveConnection" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, ArrowDown } from '@element-plus/icons-vue'
import api from '@/utils/api'

const connection = ref(null)
const connections = ref([])
const currentId = ref(null)
const loadingConnections = ref(false)
const categories = ref([])
const dialogVisible = ref(false)
const saving = ref(false)
const fixing = ref(false)
const projects = ref([])
const form = reactive({
  id: null, name: '', project: null, yapi_url: '', yapi_token: '',
  yapi_uid: 0, yapi_project_id: null, auto_sync: false,
})
const selectedCats = ref([])
const expandedCats = reactive(new Set())
const logs = ref([])
const syncing = ref(false)
const loadingCats = ref(false)
const lastSyncResult = ref(null)

const sortedCats = computed(() =>
  [...categories.value].sort((a, b) => b.name.localeCompare(a.name, 'zh'))
)

const toggleExpand = (catid) => {
  expandedCats.has(catid) ? expandedCats.delete(catid) : expandedCats.add(catid)
}

const toggleCat = (catid) => {
  const idx = selectedCats.value.indexOf(catid)
  idx >= 0 ? selectedCats.value.splice(idx, 1) : selectedCats.value.push(catid)
}

const methodColor = (m) => ({ GET: 'success', POST: 'primary', PUT: 'warning', DELETE: 'danger', PATCH: 'info' }[m] || '')

const fmtDays = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1))

// 「剩余天数」只是按 token_updated_at + token_valid_days 推算的日期，
// 与 YApi 侧真实登录态无关（YApi 可能提前失效），所以进页面用一次真实请求校验。
const tokenCheck = ref({ state: 'idle', message: '', at: null })
const checkingToken = ref(false)
const tokenInvalid = computed(() => tokenCheck.value.state === 'invalid')

const tokenStatusText = computed(() => {
  const c = connection.value
  const st = tokenCheck.value.state
  const days = c?.token_remaining_days
  const daysText = days === null || days === undefined
    ? ''
    : (c.token_status === 'expired' ? `日期推算已过期 ${fmtDays(Math.abs(days))} 天` : `日期推算剩余 ${fmtDays(days)} 天`)

  if (st === 'checking') return '校验中…'
  if (st === 'invalid') return '已失效（YApi 拒绝当前 Token）'
  if (st === 'error') return `校验失败：${tokenCheck.value.message || '连不上 YApi'}`
  if (st === 'ok') {
    return daysText ? `可用（已实测）· ${daysText}` : '可用（已实测）'
  }
  return daysText || '未知（保存连接后生效）'
})

const verifyToken = async () => {
  if (!connection.value) return
  checkingToken.value = true
  tokenCheck.value = { state: 'checking', message: '', at: null }
  try {
    const r = await api.get(
      `/api-testing/yapi-connections/${connection.value.id}/verify-token/`,
      { timeout: 25000 }
    )
    const d = r.data || {}
    if (d.ok) {
      tokenCheck.value = { state: 'ok', message: '', at: d.checked_at || new Date() }
    } else {
      tokenCheck.value = {
        state: d.code === 'YAPI_TOKEN_INVALID' ? 'invalid' : 'error',
        message: d.error || 'YApi 拒绝访问',
        at: d.checked_at || new Date(),
      }
    }
  } catch (e) {
    tokenCheck.value = {
      state: 'error',
      message: e.response?.data?.error || e.message,
      at: new Date(),
    }
  } finally { checkingToken.value = false }
}

/** YApi 相关错误统一出口：Token 失效 → 直接给「去更新 Token」，不再只弹一句红字 */
const handleYapiError = async (e, prefix = '操作失败') => {
  const data = e.response?.data || {}
  if (data.code === 'YAPI_TOKEN_INVALID') {
    tokenCheck.value = { state: 'invalid', message: data.error, at: new Date() }
    ElMessage.warning('YApi Token 已失效，需要更新后重试')
    try {
      await ElMessageBox.confirm(
        '当前 Token 已被 YApi 拒绝（40011 请登录）。请登录 YApi → 浏览器开发者工具 → Cookies 复制 _yapi_token 的值，粘贴到这里。',
        '需要更新 Token',
        { type: 'warning', confirmButtonText: '立即更新', cancelButtonText: '稍后' }
      )
      openEditDialog()
    } catch (_) {}
    return
  }
  ElMessage.error(`${prefix}: ${data.error || e.message}`)
}

const fmtTime = (iso) => {
  if (!iso) return '从未'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const tokenStatusClass = computed(() => {
  const st = tokenCheck.value.state
  if (st === 'invalid' || st === 'error') return 'tok-expired'
  if (st === 'ok') {
    const d = connection.value?.token_remaining_days
    return d !== null && d !== undefined && d <= 2 ? 'tok-warn' : 'tok-ok'
  }
  const c = connection.value
  if (!c || c.token_status === 'unknown') return ''
  if (c.token_status === 'expired') return 'tok-expired'
  if (c.token_remaining_days <= 2) return 'tok-warn'
  return 'tok-ok'
})

const loadConnections = async () => {
  loadingConnections.value = true
  try {
    const r = await api.get('/api-testing/yapi-connections/')
    connections.value = r.data.results || r.data || []
    if (!currentId.value || !connections.value.some(c => c.id === currentId.value)) {
      currentId.value = connections.value[0]?.id || null
    }
    await loadConnection()
  } catch (_) {
  } finally { loadingConnections.value = false }
}

const loadConnection = async () => {
  connection.value = connections.value.find(c => c.id === currentId.value) || null
  categories.value = []
  selectedCats.value = []
  expandedCats.clear()
  logs.value = []
  lastSyncResult.value = null
  tokenCheck.value = { state: 'idle', message: '', at: null }
  if (connection.value) {
    // 先实测 Token：失效时 categories 预期会 400，不用再弹一次错
    verifyToken()
    loadLogs()
    loadCategories()
  }
}

const loadLogs = async () => {
  try {
    const r = await api.get(`/api-testing/yapi-connections/${connection.value.id}/logs/`)
    logs.value = r.data || []
  } catch (_) {}
}

const loadCategories = async () => {
  loadingCats.value = true
  try {
    const r = await api.get(`/api-testing/yapi-connections/${connection.value.id}/categories/`)
    categories.value = r.data.categories || []
  } catch (e) {
    const data = e.response?.data || {}
    if (data.code === 'YAPI_TOKEN_INVALID') {
      // 顶部红色告警条已足够显眼，这里不再叠 toast
      tokenCheck.value = { state: 'invalid', message: data.error, at: new Date() }
    } else {
      ElMessage.error('加载失败: ' + (data.error || e.message))
    }
  } finally { loadingCats.value = false }
}

const deleteConnection = async () => {
  try {
    await ElMessageBox.confirm('确定断开？', '确认', { type: 'warning' })
    await api.delete(`/api-testing/yapi-connections/${connection.value.id}/`)
    ElMessage.success('连接已断开')
    currentId.value = null
    await loadConnections()
  } catch (_) {}
}

const loadProjects = async () => {
  try {
    const r = await api.get('/api-testing/projects/')
    projects.value = r.data.results || r.data || []
  } catch (_) {}
}

const resetForm = () => {
  form.id = null
  form.name = ''
  form.project = null
  form.yapi_url = ''
  form.yapi_token = ''
  form.yapi_uid = 0
  form.yapi_project_id = null
  form.auto_sync = false
  form.token_valid_days = 7
}

const openCreateDialog = async () => {
  resetForm()
  await loadProjects()
  dialogVisible.value = true
}

const openEditDialog = async () => {
  if (!connection.value) return
  await loadProjects()
  form.id = connection.value.id
  form.name = connection.value.name
  form.project = connection.value.project
  form.yapi_url = connection.value.yapi_url
  form.yapi_token = ''
  form.yapi_uid = connection.value.yapi_uid || 0
  form.yapi_project_id = connection.value.yapi_project_id
  form.auto_sync = !!connection.value.auto_sync
  form.token_valid_days = connection.value.token_valid_days || 7
  dialogVisible.value = true
}

const saveConnection = async () => {
  if (!form.name || !form.project || !form.yapi_url || !form.yapi_project_id) {
    ElMessage.warning('请填写必填项：连接名称、关联项目、YApi 地址、项目ID')
    return
  }
  if (!form.id && !form.yapi_token) {
    ElMessage.warning('新建连接时 YApi Token 为必填项')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name,
      project: form.project,
      yapi_url: form.yapi_url,
      yapi_uid: form.yapi_uid || 0,
      yapi_project_id: form.yapi_project_id,
      auto_sync: form.auto_sync,
      token_valid_days: form.token_valid_days || 7,
    }
    if (form.yapi_token) payload.yapi_token = form.yapi_token
    const tokenChanged = !!form.yapi_token
    if (form.id) {
      await api.put(`/api-testing/yapi-connections/${form.id}/`, payload)
      ElMessage.success('连接已更新')
    } else {
      await api.post('/api-testing/yapi-connections/', payload)
      ElMessage.success('连接已创建')
    }
    dialogVisible.value = false
    await loadConnections()
    // 换 Token 后立刻实测一次，让用户当场知道新 Token 到底能不能用
    if (tokenChanged) await verifyToken()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message))
  } finally { saving.value = false }
}

const fixBaseUrl = async () => {
  if (!connection.value) return
  try {
    await ElMessageBox.confirm('将把当前环境下同域名的绝对地址和相对路径统一为 {{base_url}}/路径；其他域名和自定义变量保持不变。确定执行？', '统一路径格式', { type: 'warning' })
  } catch (_) { return }
  fixing.value = true
  try {
    const r = await api.post(`/api-testing/yapi-connections/${connection.value.id}/fix_base_url/`)
    ElMessage.success(`完成：补全 ${r.data.updated} 个，跳过 ${r.data.skipped} 个`)
  } catch (e) {
    await handleYapiError(e, '执行失败')
  } finally { fixing.value = false }
}

const startSync = async () => {
  syncing.value = true
  try {
    const r = await api.post(`/api-testing/yapi-connections/${connection.value.id}/sync/`, {
      cat_ids: selectedCats.value
    }, { timeout: 600000 })
    lastSyncResult.value = r.data
    ElMessage.success(`完成: 新增${r.data.new} 更新${r.data.updated}`)
    await loadLogs()
  } catch (e) {
    await handleYapiError(e, '同步失败')
  } finally { syncing.value = false }
}

onMounted(() => { loadConnections() })
</script>

<style scoped>
.yapi-sync-page { padding: 24px; max-width: 1100px; margin: 0 auto; }
.page-header { margin-bottom: 24px; }
.page-header h2 { margin: 0; }
.page-header p { color: #909399; margin-top: 4px; }
.config-card { margin-bottom: 16px; }
.ver-list { max-height: 70vh; overflow-y: auto; }
.ver-row { border-bottom: 1px solid #f0f0f0; }
.ver-main { display: flex; align-items: center; gap: 8px; padding: 8px 4px; cursor: pointer; }
.ver-main:hover { background: #f5f7fa; }
.expand-icon { transition: transform .2s; font-size: 12px; color: #909399; }
.expand-icon.expanded { transform: rotate(0); }
.ver-check { margin-right: 0; }
.ver-name { font-weight: 500; }
.ver-name.isVer { color: #2953b3; font-family: monospace; font-size: 14px; }
.ver-count { color: #909399; font-size: 12px; margin-left: auto; }
.ver-detail { padding: 4px 0 8px 40px; }
.ver-iface { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 13px; }
.method-tag { min-width: 56px; text-align: center; }
.iface-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.iface-path { color: #909399; font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tok-ok { color: #137333; }
.tok-warn { color: #e37400; font-weight: 600; }
.tok-expired { color: #c5221f; font-weight: 700; }
.token-alert { margin-bottom: 16px; }
.alert-body { display: flex; align-items: center; gap: 16px; }
.alert-text { flex: 1; min-width: 0; }
.alert-detail { font-size: 12px; margin-top: 2px; word-break: break-all; }
.alert-actions { flex: none; display: flex; gap: 8px; }
.check-time { font-size: 12px; color: #909399; margin-left: 6px; }
.form-tip { font-size: 12px; color: #909399; margin-left: 8px; }
.log-count { font-size: 12px; color: #909399; font-weight: 400; margin-left: 6px; }
</style>
