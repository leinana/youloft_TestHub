<template>
  <div class="kb-wrap">
    <!-- 顶部：项目选择 -->
    <div class="kb-topbar">
      <div class="kb-title">需求知识库</div>
      <el-select v-model="projectId" placeholder="选择项目" style="width:240px" filterable @change="loadTree">
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-button type="primary" :disabled="!projectId" @click="openCreate(null, 'module')">新增模块</el-button>
      <el-button type="success" plain :disabled="!projectId" @click="openImport">导入文档</el-button>
    </div>

    <div class="kb-body">
      <!-- 左侧：框架目录树 -->
      <aside class="kb-side">
        <div class="kb-side-head">目录</div>
        <div v-if="!tree.length" class="kb-empty">暂无数据，请选择项目</div>
        <el-tree
          v-else
          ref="treeRef"
          :data="displayTree"
          :props="{ label: 'name', children: 'children', isLeaf: 'isLeaf' }"
          node-key="id"
          highlight-current
          :expand-on-click-node="true"
          :default-expanded-keys="domainIds"
          @node-click="onTreeNodeClick"
          @node-contextmenu="onNodeContextMenu"
        >
          <template #default="{ data }">
            <span
              class="kb-side-node"
              :class="{ 'is-leaf': data.isLeaf, 'is-folder': !data.isLeaf }"
              @dblclick.stop="renameNode(data)"
            >
              <span class="kb-side-dot" :class="'kdot-' + data.kind"></span>
              <span class="kb-side-label">{{ data.name }}</span>
              <span v-if="!data.isLeaf && data.children && data.children.length" class="kb-side-count">
                {{ data.children.length }}
              </span>
            </span>
          </template>
        </el-tree>
      </aside>

      <!-- 目录右键菜单 -->
      <div v-if="ctxMenu.visible" class="kb-ctx-mask" @click="closeCtxMenu" @contextmenu.prevent="closeCtxMenu" />
      <div
        v-if="ctxMenu.visible"
        class="kb-ctx-menu"
        :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      >
        <div class="kb-ctx-item" @click="ctxAction('rename')">重命名</div>
        <div class="kb-ctx-item" @click="ctxAction('create')">新建子节点</div>
        <div class="kb-ctx-item" @click="ctxAction('edit')">编辑…</div>
        <div class="kb-ctx-divider" />
        <div class="kb-ctx-item danger" @click="ctxAction('delete')">删除</div>
      </div>

      <!-- 右侧：飞书风格文档区 -->
      <main class="kb-doc">
        <div v-if="!selectedNode" class="kb-doc-empty">
          <el-empty description="请从左侧目录选择功能点，查看它的需求说明" />
        </div>
        <article v-else class="kb-doc-inner">
          <div class="kb-doc-crumb">{{ selectedPathNames }}</div>
          <h1 class="kb-doc-title">{{ selectedNode.name }}</h1>
          <div class="kb-doc-meta">
            <span class="kb-doc-actions">
              <el-button v-if="selectedNode.summary" size="small" type="primary" plain @click="openDocEdit">编辑文档</el-button>
              <el-button size="small" plain :loading="regenLoading" @click="regenSummary(selectedNode)">按内容重写文档</el-button>
            </span>
          </div>

          <!-- AI 生成的需求说明（Markdown，右侧正文） -->
          <div v-if="selectedNode.summary" class="kb-md" v-html="renderMarkdown(selectedNode.summary)"></div>

          <!-- 没有 AI 说明时：给提示，并把子树里已有的内容列出来（避免内容被藏住） -->
          <template v-else>
            <div v-if="selectedSubtreeCount" class="kb-doc-tip">
              该功能点还没有生成需求说明（下面已有 {{ selectedSubtreeCount }} 条内容）。
              点右上角「重新生成说明」即可生成文档。
            </div>
            <div v-else class="kb-doc-tip empty">
              该功能点下面还没有内容。可以通过「导入文档」从墨刀 / Axure 需求链接补充。
            </div>

            <section v-if="subtreeItems.length" class="kb-doc-section">
              <h2 class="kb-doc-h2">已有内容<span class="kb-doc-count">{{ subtreeItems.length }}</span></h2>
              <div v-for="(it, i) in subtreeItems" :key="it.id" class="kb-doc-item">
                <div class="kb-doc-item-head">
                  <span class="kb-doc-no">{{ i + 1 }}</span>
                  <span class="kb-doc-item-name">{{ it.name }}</span>
                  <span class="kb-doc-badge">{{ it.kindLabel }}</span>
                </div>
                <div v-if="it.content" class="kb-doc-item-body">{{ it.content }}</div>
              </div>
            </section>
          </template>
        </article>
      </main>
    </div>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" :title="editMode === 'create' ? '新增节点' : '编辑节点'" width="640px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="节点类型">
          <el-select v-model="form.kind" :disabled="editMode === 'edit'" style="width:100%">
            <el-option v-for="k in kindOptions" :key="k.value" :label="k.label" :value="k.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.name" placeholder="节点标题" />
        </el-form-item>
        <el-form-item v-if="form.kind === 'rule'" label="规则类型">
          <el-select v-model="form.rule_type" clearable placeholder="选择规则类型" style="width:100%">
            <el-option v-for="r in ruleTypes" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容/描述">
          <el-input v-model="form.content" type="textarea" :rows="6" placeholder="功能描述、规则说明或页面描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveNode">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入文档弹窗 -->
    <el-dialog
      v-model="importVisible"
      :title="importTitle"
      :width="importStage === 'config' ? '600px' : '1080px'"
      top="4vh"
    >
      <!-- 阶段一：采集配置 -->
      <template v-if="importStage === 'config'">
        <el-form label-width="90px">
          <el-form-item label="来源类型">
            <el-radio-group v-model="importForm.source_type">
              <el-radio value="axure">Axure（内网）</el-radio>
              <el-radio value="modao">墨刀（官网）</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="链接地址">
            <el-input v-model="importForm.url" placeholder="粘贴 Axure / 墨刀 只读链接" />
          </el-form-item>
          <el-form-item v-if="importForm.source_type === 'modao'" label="账号">
            <el-input v-model="importForm.email" placeholder="墨刀登录邮箱" />
          </el-form-item>
          <el-form-item v-if="importForm.source_type === 'modao'" label="密码">
            <el-input v-model="importForm.password" type="password" placeholder="墨刀登录密码（用于自动登录）" show-password />
          </el-form-item>
          <el-form-item label="版本备注">
            <el-input
              v-model="importForm.note"
              type="textarea"
              :rows="3"
              placeholder="可选：写点这一版的重点，帮 AI 抓准内容。例：v3.9.5 主要优化限免开关逻辑，涉及健康用机和锁屏管控，重点看「对新用户屏蔽」的分支"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="collecting" @click="runCollectAndAnalyze">采集并分析</el-button>
            <div class="kb-form-tip">采集完成后会列出所有画布，可勾选决定哪些要抽取；AI 会自动归类到已有功能点。备注会用于「整理文档」与「新旧对比」。</div>
          </el-form-item>
        </el-form>
        <div v-if="collecting" class="kb-collect-progress">
          <span class="kb-spinner"></span>
          <span class="kb-stage-text">{{ stage }}</span>
        </div>
      </template>

      <!-- 阶段二：归类预览 -->
      <template v-else-if="importStage === 'classify'">
        <div v-if="skippedBackend.length" class="kb-skip-tip">
          已自动跳过 <b>{{ skippedBackend.length }}</b> 个后台需求画布（不采集、不抽取）：
          {{ skippedBackendNames }}
        </div>

        <div class="kb-classify-head">
          共 <b>{{ classifyRows.length }}</b> 个顶层分组（{{ totalCanvasCount }} 个画布），已选 <b>{{ checkedRowCount }}</b> 个，归到
          <b>{{ classifyGroupCount }}</b> 个模块
          <span class="kb-classify-tip">一个分组整理成一篇模块文档；归属模块可逐个调整</span>
        </div>
        <el-table :data="classifyRows" height="420" size="small" border>
          <el-table-column width="46">
            <template #header>
              <el-checkbox :model-value="allRowsChecked" :indeterminate="someRowsChecked && !allRowsChecked" @change="toggleAllRows" />
            </template>
            <template #default="{ row }">
              <el-checkbox v-model="row._checked" />
            </template>
          </el-table-column>
          <el-table-column label="顶层分组" min-width="220">
            <template #default="{ row }">
              <div class="kb-group-name">{{ row.name }}</div>
              <div class="kb-group-sub">
                含 {{ row.page_count }} 个画布<span v-if="row.page_names && row.page_names.length">：{{ row.page_names.slice(0, 8).join('、') }}{{ row.page_names.length > 8 ? ' …' : '' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="归属模块" width="340">
            <template #default="{ row }">
              <el-select v-model="row.feature_id" filterable size="small" placeholder="新建模块" style="width: 100%;" :disabled="!row._checked">
                <el-option value="__new__" :label="'➕ 新建模块：' + row.name" />
                <el-option v-for="f in featureOptions" :key="f.id" :value="f.id" :label="f.name" />
              </el-select>
              <el-select
                v-if="row.feature_id === '__new__'"
                v-model="row.parent_id"
                size="small"
                style="width: 100%; margin-top: 4px;"
                :disabled="!row._checked"
              >
                <el-option v-for="d in classifyDomains" :key="d.id" :value="d.id" :label="'挂到大类：' + d.name" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
        <div class="kb-classify-actions">
          <el-button @click="backToConfig">返回重新采集</el-button>
          <el-button type="primary" :loading="extracting" :disabled="!checkedRowCount" @click="runCreateProposal">
            生成提议（{{ checkedRowCount }}）
          </el-button>
        </div>
      </template>

      <!-- 阶段三：提议审核 -->
      <template v-else>
        <div class="kb-prop-source">
          来源：{{ proposalSourceText }}
          <span v-if="pendingConflictCount" class="kb-prop-warn">还有 {{ pendingConflictCount }} 处疑似冲突未确认</span>
        </div>

        <div v-for="grp in proposalGroups" :key="grp.key" class="kb-prop-group">
          <div class="kb-prop-group-head">
            {{ grp.label }}
            <span class="kb-prop-group-count">{{ grp.items.length }}</span>
            <span
              v-if="grp.key === 'same'"
              class="kb-prop-toggle"
              @click="sameGroupOpen = !sameGroupOpen"
            >{{ sameGroupOpen ? '收起' : '展开' }}</span>
          </div>
          <template v-if="grp.key !== 'same' || sameGroupOpen">
          <div v-for="it in grp.items" :key="it.id" class="kb-prop-item">
            <div class="kb-prop-title">
              <b>{{ it.target_name }}</b>
              <span class="kb-prop-badge" :class="'kb-pb-' + it.change_type">{{ it.change_type_display }}</span>
              <span v-if="it.ai_reason" class="kb-prop-reason">{{ it.ai_reason }}</span>
            </div>

            <div v-if="it.change_type !== 'same'" class="kb-prop-diff">
              <!-- 有 diff：只展示变化行，未变化的折叠成一行 -->
              <template v-if="it._rows">
                <div class="kb-diff-head">
                  <span class="kb-diff-hd">现有</span>
                  <span class="kb-diff-hd">新采集</span>
                </div>
                <div class="kb-diff-body">
                  <template v-for="(row, ri) in it._rows" :key="ri">
                    <div v-if="row.type === 'gap'" class="kb-diff-gap" @click="toggleGap(row)">
                      <template v-if="row._open">
                        <div v-for="(o, oi) in row.rows" :key="oi" class="kb-diff-row is-same">
                          <div class="kb-diff-cell"><span class="kb-diff-txt">{{ o.a }}</span></div>
                          <div class="kb-diff-cell"><span class="kb-diff-txt">{{ o.b }}</span></div>
                        </div>
                      </template>
                      <template v-else>… {{ row.count }} 行未变化，点击展开 …</template>
                    </div>
                    <div v-else class="kb-diff-row" :class="'is-' + row.type">
                      <div class="kb-diff-cell"><span class="kb-diff-txt">{{ row.a }}</span></div>
                      <div class="kb-diff-cell"><span class="kb-diff-txt">{{ row.b }}</span></div>
                    </div>
                  </template>
                </div>
              </template>

              <!-- diff 太大时不硬算，退回整篇并排 -->
              <div v-else class="kb-prop-diff-plain">
                <div class="kb-prop-col">
                  <div class="kb-prop-col-head">现有</div>
                  <pre class="kb-prop-pre">{{ it.old_content || '（暂无文档）' }}</pre>
                </div>
                <div class="kb-prop-col">
                  <div class="kb-prop-col-head">新采集</div>
                  <pre class="kb-prop-pre">{{ it._merged || it.new_content }}</pre>
                </div>
              </div>
            </div>

            <div v-if="it.conflicts && it.conflicts.length" class="kb-prop-conflicts">
              <div v-for="(c, ci) in it.conflicts" :key="ci" class="kb-prop-conflict">
                <span class="old">{{ c.old }}</span>
                <span class="arrow">→</span>
                <span class="new">{{ c.new }}</span>
              </div>
            </div>

            <div class="kb-prop-actions">
              <el-radio-group v-model="it._decision" size="small">
                <el-radio-button v-if="it.change_type !== 'same'" value="accept">用新的</el-radio-button>
                <el-radio-button value="keep">保留旧的</el-radio-button>
                <el-radio-button v-if="it.change_type !== 'same'" value="merged">编辑后合并</el-radio-button>
                <el-radio-button value="ignored">忽略</el-radio-button>
              </el-radio-group>
              <el-button v-if="it._decision === 'merged'" size="small" plain @click="openProposalEditor(it)">打开编辑器</el-button>
            </div>
          </div>
          </template>
        </div>

        <div class="kb-classify-actions">
          <el-button @click="backToClassify">返回归类</el-button>
          <el-button type="primary" :loading="applying" @click="runApplyProposal">
            确认应用（采纳 {{ acceptedCount }} 项）
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 文档编辑器（审核页与文档页共用） -->
    <MarkdownEditor
      v-model="docEditVisible"
      :title="'编辑需求文档 · ' + (selectedNode ? selectedNode.name : '')"
      :content="docEditContent"
      :saving="docEditSaving"
      @save="saveDocEdit"
    />

    <!-- 审核中心弹窗 -->
    <el-dialog v-model="reviewVisible" title="审核中心（草稿节点）" width="720px" top="5vh">
      <div v-if="!draftNodes.length" class="kb-muted" style="text-align:center;padding:30px;">暂无草稿节点</div>
      <template v-else>
        <div class="kb-review-toolbar">
          <el-checkbox :model-value="reviewSelectedIds.length === draftNodes.length" @change="toggleSelectAll">全选</el-checkbox>
          <span class="kb-review-count">已选 {{ reviewSelectedIds.length }} / {{ draftNodes.length }}</span>
          <el-button size="small" type="primary" :disabled="!reviewSelectedIds.length" @click="batchReview('confirm')">批量确认</el-button>
          <el-button size="small" type="danger" plain :disabled="!reviewSelectedIds.length" @click="batchReview('delete')">批量删除</el-button>
        </div>
        <el-checkbox-group v-model="reviewSelectedIds" class="kb-review-list">
          <div v-for="n in draftNodes" :key="n.id" class="kb-review-item">
            <el-checkbox :value="n.id">
              <el-tag :type="kindTagType(n.kind)" size="small">{{ n.kind_display }}</el-tag>
              <span class="kb-review-name">{{ n.name }}</span>
              <span v-if="n.rule_type_display" class="kb-muted">（{{ n.rule_type_display }}）</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import api from '@/utils/api'
import MarkdownEditor from '@/components/MarkdownEditor.vue'

marked.setOptions({ breaks: true, gfm: true })
const renderMarkdown = (text) => {
  if (!text) return ''
  try {
    // 宽表格外面包一层，便于横向滚动、也不撑破版面
    return marked(text)
      .replace(/<table>/g, '<div class="kb-table-wrap"><table>')
      .replace(/<\/table>/g, '</table></div>')
  } catch (e) { return '' }
}

const projects = ref([])
const projectId = ref(null)
const tree = ref([])
const selectedNode = ref(null)
const editVisible = ref(false)
const editMode = ref('create')
const saving = ref(false)
const treeRef = ref(null)
const importVisible = ref(false)
const importForm = ref({ url: '', source_type: 'axure', page_filter: '', cookie: '', email: '', password: '', note: '' })
const reviewVisible = ref(false)
const reviewSelectedIds = ref([])
const classifying = ref(false)
const collecting = ref(false)
const stage = ref('')
const classifyRows = ref(null)
const classifyCandidates = ref([])
const classifyDomains = ref([])
const skippedBackend = ref([])
const importStage = ref('config')
const collectionId = ref(null)
const proposalData = ref(null)
const applying = ref(false)
const proposalEditingItem = ref(null)
const sameGroupOpen = ref(false)
const ctxMenu = ref({ visible: false, x: 0, y: 0, data: null })
const extracting = ref(false)
const regenLoading = ref(false)
const docEditVisible = ref(false)
const docEditSaving = ref(false)
const docEditContent = ref('')

const form = ref({ id: null, project: null, parent: null, kind: 'feature', name: '', content: '', rule_type: null, status: 'confirmed', is_locked: false })

const kindOptions = [
  { value: 'domain', label: '功能域' },
  { value: 'module', label: '功能模块' },
  { value: 'feature', label: '功能点' },
  { value: 'rule', label: '业务规则' },
  { value: 'page', label: '页面描述' },
]
const ruleTypes = [
  { value: 'normal', label: '正向流程' },
  { value: 'exception', label: '异常流程' },
  { value: 'field', label: '字段约束' },
  { value: 'enum', label: '枚举值' },
  { value: 'dependency', label: '依赖' },
  { value: 'frequency', label: '频率限制' },
  { value: 'member', label: '会员限制' },
  { value: 'permission', label: '权限' },
  { value: 'operation', label: '运营配置' },
]

const kindTagType = (kind) => ({ domain: 'danger', module: 'primary', feature: 'success', rule: 'warning', page: 'info' }[kind] || 'info')
const ruleTypeLabel = (t) => (ruleTypes.find(x => x.value === t) || {}).label || '待分类'

// 目录默认展开顶层（功能域）
const domainIds = computed(() => (tree.value || []).map(n => n.id))

// 目录只保留「大类 → 模块」两级；模块作为叶子，
// 它下面的功能点/规则/页面全部收进右侧文档，不在树上展开。
const displayTree = computed(() => {
  // 模块以下（功能点/规则）全部并入模块文档，不在树上展示
  const cut = (nodes) => (nodes || []).map(n => {
    const children = Array.isArray(n.children) ? n.children : []
    if (n.kind === 'module') return { ...n, children: [], isLeaf: true }
    return { ...n, children: cut(children) }
  })
  return cut(tree.value)
})

// id → 完整节点（displayTree 截断过子级，点选后要从原树取全量节点）
const nodeIndexById = computed(() => {
  const map = {}
  const walk = (nodes) => {
    for (const n of nodes) {
      map[n.id] = n
      if (n.children && n.children.length) walk(n.children)
    }
  }
  walk(tree.value || [])
  return map
})

// 节点 → 祖先路径（用于文档区顶部的面包屑）
const nodePathMap = computed(() => {
  const map = {}
  const walk = (nodes, ancestors) => {
    for (const n of nodes) {
      map[n.id] = [...ancestors, n]
      if (n.children && n.children.length) walk(n.children, [...ancestors, n])
    }
  }
  walk(tree.value || [], [])
  return map
})
const selectedPathNames = computed(() => {
  if (!selectedNode.value) return ''
  const path = nodePathMap.value[selectedNode.value.id] || [selectedNode.value]
  return path.map(n => n.name).join('  /  ')
})

// 文档区分区数据
const selectedChildren = computed(() => (selectedNode.value && selectedNode.value.children) || [])
const ruleChildren = computed(() => selectedChildren.value.filter(c => c.kind === 'rule'))
const pageChildren = computed(() => selectedChildren.value.filter(c => c.kind === 'page'))
const childNodes = computed(() => selectedChildren.value.filter(c => c.kind !== 'rule' && c.kind !== 'page'))
const childSectionTitle = computed(() => {
  const k = selectedNode.value && selectedNode.value.kind
  if (k === 'domain') return '功能模块'
  if (k === 'module') return '功能点'
  return '子节点'
})

const draftNodes = computed(() => {
  const out = []
  const walk = (nodes) => {
    for (const n of nodes) {
      if (n.status === 'draft') out.push(n)
      if (n.children) walk(n.children)
    }
  }
  walk(tree.value)
  return out
})
const featureOptions = computed(() => {
  const out = []
  const seen = new Set()
  for (const f of classifyCandidates.value) {
    if (!seen.has(f.id)) { seen.add(f.id); out.push({ id: f.id, name: f.name }) }
  }
  // 兜底：把 AI 已分配但不在候选里的功能点补进来，避免下拉显示为空
  for (const row of (classifyRows.value || [])) {
    if (row.feature_id && row.feature_id !== '__new__' && !seen.has(row.feature_id)) {
      seen.add(row.feature_id)
      out.push({ id: row.feature_id, name: row.feature_name || ('#' + row.feature_id) })
    }
  }
  return out
})
const skippedBackendNames = computed(() => skippedBackend.value.map(x => x.name).join('、'))
const checkedRowCount = computed(() => (classifyRows.value || []).filter(r => r._checked).length)
const allRowsChecked = computed(() => {
  const rows = classifyRows.value || []
  return rows.length > 0 && rows.every(r => r._checked)
})
const someRowsChecked = computed(() => (classifyRows.value || []).some(r => r._checked))
const toggleAllRows = (val) => {
  for (const r of (classifyRows.value || [])) r._checked = !!val
}
// ---- 行级 diff（LCS），用于提议审核里高亮变化 ----
const diffLines = (aText, bText) => {
  const A = String(aText || '').split('\n')
  const B = String(bText || '').split('\n')
  const n = A.length
  const m = B.length
  // 太大就不算 diff（避免卡死），退回整篇并排
  if (n * m > 300000) return null

  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const ops = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (A[i] === B[j]) { ops.push({ type: 'same', a: A[i], b: B[j] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ type: 'del', a: A[i], b: '' }); i++ }
    else { ops.push({ type: 'add', a: '', b: B[j] }); j++ }
  }
  while (i < n) ops.push({ type: 'del', a: A[i++], b: '' })
  while (j < m) ops.push({ type: 'add', a: '', b: B[j++] })
  return ops
}

// 把 diff 结果整理成可渲染的行：变化行 + 前后 2 行上下文，其余折叠
const buildDiffRows = (oldText, newText, ctx = 2) => {
  const ops = diffLines(oldText, newText)
  if (!ops) return null

  const keep = new Array(ops.length).fill(false)
  for (let k = 0; k < ops.length; k++) {
    if (ops[k].type !== 'same') {
      const from = Math.max(0, k - ctx)
      const to = Math.min(ops.length - 1, k + ctx)
      for (let x = from; x <= to; x++) keep[x] = true
    }
  }

  const rows = []
  let gapStart = -1
  for (let k = 0; k <= ops.length; k++) {
    const isKeep = k < ops.length && keep[k]
    if (!isKeep) {
      if (gapStart < 0) gapStart = k
      continue
    }
    if (gapStart >= 0) {
      rows.push({ type: 'gap', count: k - gapStart, rows: ops.slice(gapStart, k), _open: false })
      gapStart = -1
    }
    rows.push(ops[k])
  }
  if (gapStart >= 0) {
    rows.push({ type: 'gap', count: ops.length - gapStart, rows: ops.slice(gapStart), _open: false })
  }
  return rows
}

const toggleGap = (row) => { row._open = !row._open }

const importTitle = computed(() => {
  if (importStage.value === 'classify') return '归类确认（确认后生成知识提议）'
  if (importStage.value === 'review') return '知识提议审核'
  return '采集并分析需求'
})
const PROPOSAL_GROUPS = [
  ['conflict', '疑似冲突（请逐条确认）'],
  ['append', '补充内容'],
  ['new', '新增功能点'],
  ['same', '无变化（已自动跳过）'],
]
const proposalGroups = computed(() => {
  const items = (proposalData.value && proposalData.value.items) || []
  return PROPOSAL_GROUPS
    .map(([key, label]) => ({ key, label, items: items.filter(i => i.change_type === key) }))
    .filter(g => g.items.length)
})
const proposalSourceText = computed(() => {
  const s = (proposalData.value && proposalData.value.source) || {}
  const parts = []
  if (s.version) parts.push(s.version)
  if (s.collected_at) parts.push(new Date(s.collected_at).toLocaleString('zh-CN'))
  if (s.page_count) parts.push(s.page_count + ' 个画布')
  return parts.join(' \u00b7 ') || '-'
})
const pendingConflictCount = computed(() => {
  const items = (proposalData.value && proposalData.value.items) || []
  return items.filter(i => i.change_type === 'conflict' && i._decision === 'keep').length
})
const acceptedCount = computed(() => {
  const items = (proposalData.value && proposalData.value.items) || []
  return items.filter(i => i._decision === 'accept' || i._decision === 'merged').length
})
const totalCanvasCount = computed(() =>
  (classifyRows.value || []).reduce((sum, r) => sum + (r.page_count || 0), 0)
)
const classifyGroupCount = computed(() => {
  const rows = (classifyRows.value || []).filter(r => r._checked)
  const ids = new Set()
  let newCount = 0
  for (const r of rows) {
    if (r.feature_id && r.feature_id !== '__new__') ids.add(r.feature_id)
    else newCount += 1   // 匹配不到 → 各自新建一个模块
  }
  return ids.size + newCount
})
const KIND_LABEL = { domain: '大类', module: '模块', feature: '子功能', rule: '规则', page: '页面' }

// 三级功能点整棵子树里「有内容」的节点（用于没生成说明时的兜底展示）
const subtreeItems = computed(() => {
  if (!selectedNode.value) return []
  const out = []
  const walk = (n, path) => {
    for (const c of (n.children || [])) {
      const p = [...path, c.name]
      if ((c.content || '').trim()) {
        out.push({ id: c.id, name: p.join(' / '), content: c.content, kindLabel: KIND_LABEL[c.kind] || c.kind })
      }
      walk(c, p)
    }
  }
  walk(selectedNode.value, [])
  return out
})
const selectedSubtreeCount = computed(() => subtreeItems.value.length)
const childDefaultKind = (node) => (node.kind === 'feature' ? 'rule' : 'feature')

const loadProjects = async () => {
  try {
    const r = await api.get('/projects/')
    projects.value = r.data.results || r.data || []
    if (projects.value.length) { projectId.value = projects.value[0].id; await loadTree() }
  } catch (e) { ElMessage.error('加载项目失败') }
}
const loadTree = async () => {
  if (!projectId.value) return
  try {
    const r = await api.get('/knowledge/nodes/tree/', { params: { project: projectId.value } })
    tree.value = r.data || []
    selectedNode.value = null
  } catch (e) { ElMessage.error('加载知识库失败') }
}
const onTreeNodeClick = (data) => {
  // 一级（大类）只作目录；二级（模块）才显示右侧文档
  if (!data || data.kind !== 'module') return
  selectedNode.value = nodeIndexById.value[data.id] || data
}
const selectNode = (node) => { selectedNode.value = node }

const openImport = () => { importVisible.value = true; collecting.value = false; stage.value = ''; classifyRows.value = null; classifyCandidates.value = []; classifyDomains.value = []; skippedBackend.value = []; importStage.value = 'config'; collectionId.value = null; proposalData.value = null }
const openReview = () => { reviewVisible.value = true; reviewSelectedIds.value = [] }
const toggleSelectAll = (val) => { reviewSelectedIds.value = val ? draftNodes.value.map(n => n.id) : [] }
const batchReview = async (action) => {
  if (!reviewSelectedIds.value.length) return
  const label = action === 'confirm' ? '确认' : '删除'
  if (action === 'delete') {
    try { await ElMessageBox.confirm(`确定删除选中的 ${reviewSelectedIds.value.length} 个草稿节点吗？`, '删除确认', { type: 'warning' }) }
    catch (_) { return }
  }
  try {
    const r = await api.post('/knowledge/nodes/batch/', { action, ids: reviewSelectedIds.value, project: projectId.value })
    ElMessage.success(`${label}成功`)
    reviewSelectedIds.value = []
    await loadTree()
  } catch (e) { ElMessage.error(`${label}失败: ` + (e.response?.data?.error || e.message)) }
}
const runCollectAndAnalyze = async () => {
  if (!importForm.value.url.trim()) { ElMessage.warning('请填写链接地址'); return }
  collecting.value = true
  skippedBackend.value = []
  stage.value = '正在采集 + 视觉识别 + AI 归类…（画布多时可能要几分钟，请勿关闭）'
  try {
    const r = await api.post('/knowledge/collections/', {
      project: projectId.value,
      source_type: importForm.value.source_type,
      url: importForm.value.url,
      email: importForm.value.email,
      password: importForm.value.password,
      cookie: importForm.value.cookie,
      note: importForm.value.note || '',
    }, { timeout: 1800000 })

    if (r.data.error) {
      skippedBackend.value = r.data.skipped_backend || []
      ElMessage.error('采集失败：' + r.data.error)
      return
    }

    collectionId.value = r.data.collection_id
    skippedBackend.value = r.data.skipped_backend || []
    classifyCandidates.value = r.data.candidates || []
    classifyDomains.value = r.data.domains || []
    const defDomain = (classifyDomains.value.find(d => d.name === '核心功能模块') || classifyDomains.value[0] || {}).id || null
    classifyRows.value = (r.data.groups || []).map(g => ({
      ...g,
      _checked: true,
      feature_id: g.feature_id || '__new__',
      parent_id: g.feature_id ? null : defDomain,
    }))
    importStage.value = 'classify'
    ElMessage.success('采集与归类完成，确认要纳入的画布后生成提议')
  } catch (e) {
    ElMessage.error('采集失败: ' + (e.response?.data?.error || e.message))
  } finally {
    collecting.value = false
    stage.value = ''
  }
}

const backToConfig = () => {
  importStage.value = 'config'
  classifyRows.value = null
  classifyCandidates.value = []
  classifyDomains.value = []
  skippedBackend.value = []
  collectionId.value = null
}
const backToClassify = () => {
  proposalData.value = null
  importStage.value = 'classify'
}

const runCreateProposal = async () => {
  const picked = (classifyRows.value || []).filter(r => r._checked)
  if (!picked.length) { ElMessage.warning('请至少勾选一个画布'); return }
  extracting.value = true
  try {
    const r = await api.post(`/knowledge/collections/${collectionId.value}/proposal/`, {
      selected: picked.map(x => ({
        name: x.name,
        feature_id: x.feature_id === '__new__' ? null : x.feature_id,
        parent_id: x.feature_id === '__new__' ? x.parent_id : null,
      })),
    }, { timeout: 1200000 })
    if (r.data.error) { ElMessage.error('生成提议失败：' + r.data.error); return }

    const resp = await api.get(`/knowledge/proposals/${r.data.proposal_id}/`, { timeout: 120000 })
    const data = resp.data
    ;(data.items || []).forEach(it => {
      it._decision = it.change_type === 'conflict' ? 'keep' : (it.change_type === 'same' ? 'keep' : 'accept')
      it._merged = it.merged_content || ''
      it._rows = buildDiffRows(it.old_content, it.new_content)
    })
    proposalData.value = data
    importStage.value = 'review'
    const st = data.stats || {}
    ElMessage.success(`已生成提议：新增 ${st.new || 0}、补充 ${st.append || 0}、疑似冲突 ${st.conflict || 0}`)
  } catch (e) {
    ElMessage.error('生成提议失败: ' + (e.response?.data?.error || e.message))
  } finally {
    extracting.value = false
  }
}

const runApplyProposal = async () => {
  if (!proposalData.value) return
  applying.value = true
  try {
    const items = (proposalData.value.items || []).map(i => ({
      id: i.id, decision: i._decision, merged_content: i._merged || '',
    }))
    const r = await api.post(`/knowledge/proposals/${proposalData.value.id}/apply/`, { items }, { timeout: 600000 })
    ElMessage.success(`已应用：新建 ${r.data.created} 个功能点，更新 ${r.data.updated} 个功能文档`)
    importVisible.value = false
    proposalData.value = null
    classifyRows.value = null
    skippedBackend.value = []
    importStage.value = 'config'
    collectionId.value = null
    await loadTree()
  } catch (e) {
    ElMessage.error('应用失败: ' + (e.response?.data?.error || e.message))
  } finally {
    applying.value = false
  }
}

const openDocEdit = () => {
  proposalEditingItem.value = null
  if (!selectedNode.value) return
  docEditContent.value = selectedNode.value.summary || ''
  docEditVisible.value = true
}
const openProposalEditor = (it) => {
  proposalEditingItem.value = it
  docEditContent.value = it._merged || it.new_content || ''
  docEditVisible.value = true
}
const saveDocEdit = async (text) => {
  // 提议审核里改的是「待合并内容」，先暂存，等确认应用时才写库
  if (proposalEditingItem.value) {
    proposalEditingItem.value._merged = text
    proposalEditingItem.value._decision = 'merged'
    proposalEditingItem.value._rows = buildDiffRows(proposalEditingItem.value.old_content, text)
    proposalEditingItem.value = null
    docEditVisible.value = false
    ElMessage.success('已暂存，点「确认应用」后才会写入知识库')
    return
  }
  if (!selectedNode.value) return
  docEditSaving.value = true
  try {
    await api.patch(`/knowledge/nodes/${selectedNode.value.id}/`, { summary: text })
    selectedNode.value.summary = text
    docEditVisible.value = false
    ElMessage.success('文档已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    docEditSaving.value = false
  }
}
const regenSummary = async (node) => {
  if (!node) return
  regenLoading.value = true
  try {
    const r = await api.post('/knowledge/regenerate-summary/', { node_id: node.id }, { timeout: 300000 })
    node.summary = r.data.summary
    ElMessage.success('需求说明已重新生成')
  } catch (e) {
    ElMessage.error('生成失败: ' + (e.response?.data?.error || e.message))
  } finally {
    regenLoading.value = false
  }
}
const runClassifyRules = async () => {
  if (!projectId.value) return
  classifying.value = true
  try {
    const r = await api.post('/knowledge/nodes/classify_rules/', { project: projectId.value }, { timeout: 600000 })
    ElMessage.success('已补全 ' + r.data.updated + ' 条规则分类')
    await loadTree()
  } catch (e) { ElMessage.error('补全失败: ' + (e.response?.data?.error || e.message)) }
  finally { classifying.value = false }
}
const onNodeContextMenu = (event, data) => {
  event.preventDefault()
  // 右键「模块」也顺便选中，方便对照右侧文档
  if (data && data.kind === 'module') {
    selectedNode.value = nodeIndexById.value[data.id] || data
  }
  // 菜单尺寸固定（4 项 + 分割线），用固定值做边界判断
  const MENU_W = 150
  const MENU_H = 175
  let x = event.clientX
  let y = event.clientY
  // 右边装不下 → 向左翻
  if (x + MENU_W > window.innerWidth) x = Math.max(8, window.innerWidth - MENU_W - 8)
  // 下面装不下 → 向上翻
  if (y + MENU_H > window.innerHeight) y = y - MENU_H
  // 翻过头 → 贴顶
  if (y < 8) y = 8
  ctxMenu.value = { visible: true, x, y, data }
}
const closeCtxMenu = () => { ctxMenu.value.visible = false }
const ctxAction = (action) => {
  const data = ctxMenu.value.data
  closeCtxMenu()
  if (!data) return
  if (action === 'rename') renameNode(data)
  else if (action === 'create') openCreate(data, data.kind === 'feature' ? 'rule' : 'feature')
  else if (action === 'edit') openEdit(data)
  else if (action === 'delete') removeNode(data)
}
const renameNode = async (node) => {
  if (!node) return
  try {
    const { value } = await ElMessageBox.prompt('输入新的名称', '重命名', {
      inputValue: node.name,
      inputValidator: (v) => (v && v.trim() ? true : '名称不能为空'),
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    await api.patch(`/knowledge/nodes/${node.id}/`, { name: value.trim() })
    ElMessage.success('已重命名')
    await loadTree()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error('重命名失败: ' + (e.response?.data?.detail || e.message || e))
    }
  }
}
const openCreate = (parent, defaultKind) => {
  editMode.value = 'create'
  form.value = { id: null, project: projectId.value, parent: parent ? parent.id : null, kind: defaultKind, name: '', content: '', rule_type: null, status: 'confirmed', is_locked: false }
  editVisible.value = true
}
const openEdit = (node) => {
  editMode.value = 'edit'
  form.value = { id: node.id, project: projectId.value, parent: node.parent, kind: node.kind, name: node.name, content: node.content || '', rule_type: node.rule_type, status: node.status, is_locked: node.is_locked }
  editVisible.value = true
}
const saveNode = async () => {
  if (!form.value.name.trim()) { ElMessage.warning('请输入标题'); return }
  saving.value = true
  try {
    const payload = { ...form.value, parent: form.value.parent || null }
    if (editMode.value === 'create') {
      await api.post('/knowledge/nodes/', payload)
    } else {
      await api.put(`/knowledge/nodes/${form.value.id}/`, payload)
    }
    ElMessage.success('保存成功')
    editVisible.value = false
    await loadTree()
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)) }
  finally { saving.value = false }
}
const removeNode = async (node) => {
  await ElMessageBox.confirm(`确定删除「${node.name}」及其所有子节点吗？`, '删除确认', { type: 'warning' })
  try {
    await api.delete(`/knowledge/nodes/${node.id}/`)
    ElMessage.success('已删除')
    selectedNode.value = null
    await loadTree()
  } catch (e) { ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

onMounted(loadProjects)
</script>

<style scoped>
/* ===== 整体 ===== */
.kb-wrap { height: 100%; display: flex; flex-direction: column; background: #fff; }
.kb-topbar { display: flex; align-items: center; gap: 12px; padding: 12px 20px; background: #fff; border-bottom: 1px solid #eef0f2; }
.kb-title { font-size: 16px; font-weight: 700; color: #1f2329; margin-right: 4px; }
.kb-body { flex: 1; display: flex; min-height: 0; }

/* ===== 左侧框架目录 ===== */
.kb-side { width: 288px; flex-shrink: 0; background: #fbfbfc; border-right: 1px solid #eef0f2; overflow-y: auto; padding: 14px 8px 40px; }
.kb-side-head { padding: 0 12px 10px; font-size: 12px; font-weight: 600; color: #909399; letter-spacing: .5px; }
.kb-side :deep(.el-tree) { background: transparent; }
.kb-side :deep(.el-tree-node__content) { height: 32px; border-radius: 6px; padding-right: 8px; }
.kb-side :deep(.el-tree-node__content:hover) { background: #f0f1f3; }
.kb-side :deep(.el-tree-node.is-current > .el-tree-node__content) { background: #e8f0fe; color: #1a73e8; font-weight: 600; }
.kb-side-node { display: flex; align-items: center; gap: 7px; min-width: 0; width: 100%; }
.kb-side-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.kb-side-count { font-size: 11px; color: #b0b4bb; }
.kb-side-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.kdot-domain { background: #7c4dff; }
.kdot-module { background: #1a73e8; }
.kdot-feature { background: #34a853; }
.kdot-rule { background: #f9ab00; }
.kdot-page { background: #9aa0a6; }

/* ===== 右侧文档区 ===== */
.kb-doc { flex: 1; min-width: 0; overflow-y: auto; background: #fff; }
.kb-doc-empty { padding-top: 120px; }
.kb-doc-inner { max-width: 860px; margin: 0 auto; padding: 40px 48px 120px; }
.kb-doc-crumb { font-size: 12px; color: #9aa0a6; margin-bottom: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-doc-title { font-size: 28px; font-weight: 700; color: #1f2329; line-height: 1.4; margin: 0 0 14px; letter-spacing: -.2px; }
.kb-doc-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-bottom: 18px; border-bottom: 1px solid #f0f1f3; margin-bottom: 8px; }
.kb-doc-actions { margin-left: auto; display: flex; gap: 6px; }

.kb-ktag { font-size: 12px; padding: 2px 8px; border-radius: 4px; background: #f2f3f5; color: #646a73; }
.kkt-domain { background: #f3edff; color: #7c4dff; }
.kkt-module { background: #e8f0fe; color: #1a73e8; }
.kkt-feature { background: #e6f4ea; color: #137333; }
.kkt-rule { background: #fef7e0; color: #b06000; }
.kkt-page { background: #f1f3f4; color: #5f6368; }

.kb-rtag { font-size: 11px; padding: 1px 7px; border-radius: 3px; white-space: nowrap; background: #f2f3f5; color: #646a73; }
.krt-normal { background: #e6f4ea; color: #137333; }
.krt-exception { background: #fce8e6; color: #c5221f; }
.krt-field { background: #fef7e0; color: #b06000; }
.krt-enum { background: #e8f0fe; color: #1a73e8; }
.krt-dependency { background: #f3edff; color: #7c4dff; }
.krt-frequency { background: #fef7e0; color: #b06000; }
.krt-member { background: #fce8e6; color: #c5221f; }
.krt-permission { background: #e8f0fe; color: #1a73e8; }
.krt-operation { background: #e6f4ea; color: #137333; }
.krt-none { background: #f2f3f5; color: #9aa0a6; }

.kb-doc-flag { font-size: 11px; padding: 1px 7px; border-radius: 3px; }
.kb-doc-flag.draft { background: #f2f3f5; color: #646a73; }
.kb-doc-flag.deprecated { background: #fce8e6; color: #c5221f; }
.kb-doc-flag.locked { background: #fef7e0; color: #b06000; }

.kb-doc-section { margin-top: 34px; }
.kb-doc-h2 { font-size: 17px; font-weight: 600; color: #1f2329; margin: 0 0 14px; padding-left: 10px; border-left: 3px solid #1a73e8; line-height: 1.4; }
.kb-doc-count { margin-left: 8px; font-size: 12px; font-weight: 400; color: #9aa0a6; padding: 1px 6px; background: #f2f3f5; border-radius: 3px; }
.kb-doc-p { font-size: 15px; line-height: 1.9; color: #1f2329; margin: 0; white-space: pre-wrap; }

.kb-doc-item { padding: 12px 0 12px 34px; position: relative; border-bottom: 1px solid #f5f6f7; }
.kb-doc-item:last-child { border-bottom: none; }
.kb-doc-no { position: absolute; left: 0; top: 13px; width: 22px; height: 22px; line-height: 22px; text-align: center; background: #f2f3f5; color: #646a73; border-radius: 50%; font-size: 12px; font-weight: 600; }
.kb-doc-item-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.kb-doc-item-name { font-size: 15px; font-weight: 600; color: #1f2329; }
.kb-doc-item-body { margin-top: 6px; font-size: 14px; line-height: 1.9; color: #3f444d; white-space: pre-wrap; }

.kb-doc-list { list-style: none; margin: 0; padding: 0; }
.kb-doc-list li { display: flex; align-items: baseline; gap: 8px; padding: 9px 10px; border-radius: 6px; cursor: pointer; font-size: 14px; }
.kb-doc-list li:hover { background: #f5f6f7; }
.kb-doc-list-name { font-weight: 500; color: #1f2329; flex-shrink: 0; }
.kb-doc-list-brief { color: #9aa0a6; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-doc-blank { margin-top: 30px; font-size: 14px; color: #9aa0a6; }

.kb-muted { color: #9aa0a6; }
.kb-lock-tip { margin-left: 10px; font-size: 12px; color: #909399; }
.kb-empty { padding: 30px 16px; text-align: center; color: #9aa0a6; font-size: 13px; }
.kb-import-result { margin-top: 16px; max-height: 440px; overflow-y: auto; border-top: 1px solid #eef0f2; padding-top: 8px; }
.kb-import-summary { font-size: 13px; color: #409eff; margin-bottom: 10px; }
.kb-import-item { border: 1px solid #eef0f2; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.kb-import-item-head { font-size: 14px; margin-bottom: 8px; }
.kb-import-item-body { display: flex; gap: 12px; align-items: flex-start; }
.kb-import-shot { width: 200px; max-height: 260px; object-fit: contain; border: 1px solid #e8eaed; border-radius: 6px; flex-shrink: 0; }
.kb-import-text { flex: 1; font-size: 12px; line-height: 1.7; color: #606266; white-space: pre-wrap; word-break: break-all; max-height: 260px; overflow-y: auto; }
.kb-extract-section { margin-top: 8px; }
.kb-extract-row { display: flex; gap: 10px; align-items: center; }
.kb-extract-result { margin-top: 10px; color: #67c23a; font-size: 13px; }
.kb-review-toolbar { display: flex; align-items: center; gap: 14px; padding: 10px 0; border-bottom: 1px solid #eef0f2; margin-bottom: 8px; }
.kb-review-count { font-size: 13px; color: #909399; }
.kb-review-list { display: block; max-height: 440px; overflow-y: auto; }
.kb-review-item { padding: 7px 4px; border-bottom: 1px solid #f5f6f8; }
.kb-review-name { margin-left: 8px; font-size: 14px; color: #303133; }

.kb-import-pane { display: flex; gap: 14px; border: 1px solid #eef0f2; border-radius: 8px; overflow: hidden; height: 320px; }
.kb-import-left { width: 250px; flex-shrink: 0; border-right: 1px solid #eef0f2; overflow-y: auto; background: #fafbfc; padding: 6px 0; }
.kb-canvas-item { display: flex; align-items: center; gap: 6px; padding: 7px 12px; cursor: pointer; font-size: 13px; color: #303133; }
.kb-canvas-item:hover { background: #f0f4f8; }
.kb-canvas-item.active { background: #ecf5ff; }
.kb-canvas-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-import-right { flex: 1; min-width: 0; overflow-y: auto; padding: 14px 16px; }
.kb-canvas-content-title { font-size: 15px; font-weight: 700; color: #1f2329; margin-bottom: 10px; }
.kb-canvas-content { font-size: 13px; line-height: 1.8; color: #303133; white-space: pre-wrap; word-break: break-all; }
.kb-recognizing-inline { color: #409eff; font-size: 12px; margin-left: 8px; }
.kb-recognizing-box { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; color: #606266; font-size: 13px; }
.kb-spinner { width: 28px; height: 28px; border: 3px solid #e8eaed; border-top-color: #409eff; border-radius: 50%; animation: kb-spin 0.8s linear infinite; }
@keyframes kb-spin { to { transform: rotate(360deg); } }
.kb-tree-group-label { font-size: 13px; font-weight: 600; color: #606266; }
.kb-tree-group-count { margin-left: 6px; font-size: 12px; color: #909399; }


.kb-collect-progress { margin-top: 16px; display: flex; align-items: center; gap: 10px; padding: 12px 14px; background: #f5f9ff; border: 1px solid #d9ecff; border-radius: 8px; }
.kb-stage-text { font-size: 13px; color: #409eff; }


.kb-form-tip { margin-top: 4px; font-size: 12px; color: #909399; line-height: 1.5; }
.kb-classify-head { margin-bottom: 10px; font-size: 14px; color: #303133; }
.kb-classify-tip { margin-left: 10px; font-size: 12px; color: #909399; }
.kb-classify-actions { margin-top: 14px; display: flex; justify-content: flex-end; gap: 10px; }
.kb-group-name { font-weight: 600; color: #303133; }
.kb-group-sub { margin-top: 2px; font-size: 12px; color: #909399; line-height: 1.5; }


/* ===== 右侧 Markdown 正文（飞书文档风格） ===== */
.kb-md { font-size: 15px; line-height: 1.85; color: #1f2329; word-break: break-word; }

/* 标题层级 */
.kb-md :deep(h1) { font-size: 26px; font-weight: 700; line-height: 1.35; margin: 40px 0 18px; letter-spacing: -.3px; }
.kb-md :deep(h2) { font-size: 20px; font-weight: 650; line-height: 1.4; margin: 40px 0 16px; padding-bottom: 10px; border-bottom: 1px solid #eef0f2; }
.kb-md :deep(h3) { font-size: 17px; font-weight: 600; line-height: 1.5; margin: 28px 0 12px; }
.kb-md :deep(h4) { font-size: 15px; font-weight: 600; line-height: 1.5; margin: 22px 0 10px; color: #3f444d; }
.kb-md :deep(h2:first-child), .kb-md :deep(h3:first-child) { margin-top: 0; }

/* 正文与列表 */
.kb-md :deep(p) { margin: 14px 0; }
.kb-md :deep(strong) { font-weight: 600; }
.kb-md :deep(ul), .kb-md :deep(ol) { margin: 14px 0; padding-left: 26px; }
.kb-md :deep(li) { margin: 8px 0; }
.kb-md :deep(li > p) { margin: 6px 0; }
.kb-md :deep(li > ul), .kb-md :deep(li > ol) { margin: 6px 0; }

/* 代码 / 引用 / 分隔线 */
.kb-md :deep(code) { background: #f2f3f5; border-radius: 4px; padding: 2px 6px; font-size: 13px; font-family: ui-monospace, Menlo, Consolas, monospace; }
.kb-md :deep(pre) { background: #f7f8fa; border: 1px solid #eef0f2; border-radius: 8px; padding: 14px 16px; overflow-x: auto; margin: 18px 0; }
.kb-md :deep(pre code) { background: transparent; padding: 0; }
.kb-md :deep(blockquote) { margin: 18px 0; padding: 12px 16px; border-left: 3px solid #d9dde3; background: #fafbfc; border-radius: 0 6px 6px 0; color: #5f6671; }
.kb-md :deep(blockquote p) { margin: 0; }
.kb-md :deep(hr) { border: none; border-top: 1px solid #eef0f2; margin: 36px 0; }

/* 表格：外面包了 .kb-table-wrap，可横向滚动 */
.kb-md :deep(.kb-table-wrap) { margin: 20px 0; border: 1px solid #e6e8eb; border-radius: 8px; overflow-x: auto; }
.kb-md :deep(table) { width: 100%; border-collapse: collapse; border-spacing: 0; font-size: 14px; line-height: 1.75; }
.kb-md :deep(thead th) { background: #f7f8fa; font-weight: 600; color: #1f2329; white-space: nowrap; }
.kb-md :deep(th), .kb-md :deep(td) { padding: 11px 14px; text-align: left; vertical-align: top; border-bottom: 1px solid #eef0f2; border-right: 1px solid #eef0f2; }
.kb-md :deep(th:last-child), .kb-md :deep(td:last-child) { border-right: none; }
.kb-md :deep(tbody tr:last-child td) { border-bottom: none; }
.kb-md :deep(tbody tr:nth-child(even)) { background: #fcfcfd; }

/* ===== 文档区提示 / 徽标 ===== */
.kb-doc-tip { margin: 22px 0 0; padding: 12px 16px; background: #f5f9ff; border: 1px solid #dcebfd; border-radius: 8px; font-size: 14px; line-height: 1.8; color: #1a5fb4; }
.kb-doc-tip.empty { background: #fafbfc; border-color: #eef0f2; color: #8590a2; }
.kb-doc-badge { font-size: 11px; padding: 1px 7px; border-radius: 3px; background: #f2f3f5; color: #8590a2; }

/* ===== 左侧目录节点状态 ===== */
.kb-side-node.is-leaf { cursor: pointer; }
.kb-side-node.is-folder { color: #3f444d; }


/* ===== 跳过后台需求提示 ===== */
.kb-skip-tip { margin-bottom: 12px; padding: 10px 14px; background: #fafbfc; border: 1px solid #eef0f2; border-radius: 8px; font-size: 13px; line-height: 1.7; color: #8590a2; }


/* ===== 知识提议审核 ===== */
.kb-prop-source { margin-bottom: 12px; font-size: 13px; color: #8590a2; }
.kb-prop-warn { margin-left: 12px; padding: 2px 8px; background: #fff4e5; border: 1px solid #ffd9a8; border-radius: 4px; color: #b06000; font-size: 12px; }
.kb-prop-group { margin-bottom: 18px; }
.kb-prop-group-head { font-size: 14px; font-weight: 600; color: #1f2329; margin-bottom: 8px; padding-left: 8px; border-left: 3px solid #1a73e8; }
.kb-prop-group-count { margin-left: 6px; font-size: 12px; font-weight: 400; color: #9aa0a6; }
.kb-prop-item { border: 1px solid #eef0f2; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; background: #fff; }
.kb-prop-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 14px; }
.kb-prop-badge { font-size: 11px; padding: 1px 7px; border-radius: 3px; background: #f2f3f5; color: #646a73; }
.kb-pb-conflict { background: #fce8e6; color: #c5221f; }
.kb-pb-append { background: #e8f0fe; color: #1a73e8; }
.kb-pb-new { background: #e6f4ea; color: #137333; }
.kb-pb-same { background: #f2f3f5; color: #9aa0a6; }
.kb-prop-reason { font-size: 12px; color: #8590a2; }
.kb-prop-diff { display: flex; gap: 10px; margin-top: 10px; }
.kb-prop-col { flex: 1; min-width: 0; border: 1px solid #eef0f2; border-radius: 6px; overflow: hidden; }
.kb-prop-col-head { padding: 5px 10px; background: #f7f8fa; font-size: 12px; color: #646a73; border-bottom: 1px solid #eef0f2; }
.kb-prop-pre { margin: 0; padding: 10px 12px; max-height: 220px; overflow: auto; font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; color: #3f444d; font-family: inherit; }
.kb-prop-conflicts { margin-top: 10px; padding: 8px 10px; background: #fff8f7; border: 1px solid #fadbd8; border-radius: 6px; }
.kb-prop-conflict { font-size: 12px; line-height: 1.9; color: #3f444d; }
.kb-prop-conflict .old { color: #8590a2; text-decoration: line-through; }
.kb-prop-conflict .arrow { margin: 0 8px; color: #c5221f; }
.kb-prop-conflict .new { color: #c5221f; font-weight: 600; }
.kb-prop-actions { margin-top: 10px; display: flex; align-items: center; gap: 10px; }


/* ===== 差异高亮 ===== */
.kb-diff-head { display: flex; font-size: 12px; color: #646a73; }
.kb-diff-hd { flex: 1; min-width: 0; padding: 5px 10px; background: #f7f8fa; border: 1px solid #eef0f2; border-bottom: none; }
.kb-diff-hd:first-child { border-right: none; border-radius: 6px 0 0 0; }
.kb-diff-hd:last-child { border-radius: 0 6px 0 0; }
.kb-diff-body { border: 1px solid #eef0f2; border-radius: 0 0 6px 6px; max-height: 300px; overflow: auto; }
.kb-diff-row { display: flex; border-bottom: 1px solid #f5f6f7; }
.kb-diff-row:last-child { border-bottom: none; }
.kb-diff-cell { flex: 1; min-width: 0; padding: 3px 10px; font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.kb-diff-cell:first-child { border-right: 1px solid #f0f1f3; }
.kb-diff-txt { display: block; }
.kb-diff-row.is-del .kb-diff-cell:first-child { background: #fdecea; }
.kb-diff-row.is-add .kb-diff-cell:last-child { background: #e8f6ec; }
.kb-diff-row.is-same .kb-diff-cell { color: #9aa0a6; }
.kb-diff-gap { padding: 4px 10px; background: #fafbfc; border-bottom: 1px solid #f5f6f7; font-size: 12px; color: #1a73e8; cursor: pointer; text-align: center; user-select: none; }
.kb-diff-gap:hover { background: #f2f7ff; }
.kb-prop-diff-plain { display: flex; gap: 10px; }
.kb-prop-toggle { margin-left: auto; font-size: 12px; font-weight: 400; color: #1a73e8; cursor: pointer; }


/* ===== 目录右键菜单 ===== */
.kb-ctx-mask { position: fixed; inset: 0; z-index: 2000; }
.kb-ctx-menu { position: fixed; z-index: 2001; min-width: 140px; padding: 4px 0; background: #fff; border: 1px solid #e6e8eb; border-radius: 8px; box-shadow: 0 8px 24px rgba(0, 0, 0, .12); }
.kb-ctx-item { padding: 7px 16px; font-size: 13px; color: #303133; cursor: pointer; }
.kb-ctx-item:hover { background: #f2f6fc; color: #1a73e8; }
.kb-ctx-item.danger { color: #c5221f; }
.kb-ctx-item.danger:hover { background: #fef0f0; color: #c5221f; }
.kb-ctx-divider { height: 1px; margin: 4px 0; background: #f0f1f3; }

</style>
