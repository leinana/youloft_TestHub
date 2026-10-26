<template>
  <div class="design-page">
    <header class="page-head">
      <div>
        <h1>接口测试设计</h1>
        <p>选择接口，系统自动串联上一步返回数据；确认后一键执行。</p>
      </div>
      <div class="head-actions">
        <el-select v-model="projectId" placeholder="选择项目" filterable style="width: 190px" @change="onProjectChange">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-select v-model="environmentId" placeholder="执行环境" clearable style="width: 160px">
          <el-option v-for="env in environments" :key="env.id" :label="env.name" :value="env.id" />
        </el-select>
        <el-select v-model="collectionId" placeholder="全部版本" clearable style="width: 130px" @change="onCollectionChange">
          <el-option v-for="item in collections" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-button @click="openYapiDrawer">同步 YApi</el-button>
        <el-button @click="settingsVisible = true">配置</el-button>
      </div>
    </header>

    <div class="workflow-strip">
      <div class="flow-item" :class="{ done: steps.length > 0 }"><b>1</b> 选择接口</div>
      <span class="flow-line" />
      <div class="flow-item" :class="{ done: aiGenerated }"><b>2</b> AI 生成场景</div>
      <span class="flow-line" />
      <div class="flow-item" :class="{ done: steps.length > 0 && !missingCount }"><b>3</b> 补齐数据</div>
      <span class="flow-line" />
      <div class="flow-item" :class="{ done: steps.length > 0 && !missingCount }"><b>4</b> 执行</div>
      <span class="flow-tip">已关联 {{ stats.bound }} 个字段 · {{ stats.assertions }} 条校验</span>
      <span v-if="missingCount" class="flow-warning">还有 {{ missingCount }} 个字段待补齐</span>
    </div>

    <div v-if="aiExcluded.length" class="excluded-panel">
      <div class="missing-head">
        <span class="missing-title">
          AI 按业务流程排除了 {{ aiExcluded.length }} 个接口（没进场景）
        </span>
        <span class="excluded-actions">
          <el-button link type="primary" size="small" @click="excludedExpanded = !excludedExpanded">
            {{ excludedExpanded ? '收起' : '查看原因' }}
          </el-button>
          <el-button link type="primary" size="small" @click="addAllExcluded">全部补入</el-button>
          <el-button link size="small" @click="dismissExcluded">知道了</el-button>
        </span>
      </div>
      <div v-if="excludedExpanded" class="excluded-list">
        <div v-for="item in aiExcluded" :key="'x' + item.request_id" class="excluded-row">
          <span class="method" :class="`method-${String(item.method || 'get').toLowerCase()}`">{{ item.method }}</span>
          <span class="excluded-name">{{ item.name }}</span>
          <span class="excluded-reason">{{ item.reason }}</span>
          <el-button link type="primary" size="small" @click="addOneExcluded(item)">加入</el-button>
        </div>
      </div>
    </div>

    <div v-if="aiMissing.length || aiGuesses.length" class="missing-panel">
      <div class="missing-head">
        <span class="missing-title">
          <template v-if="aiMissing.length">还有 {{ aiMissing.length }} 个字段缺少数据</template>
          <template v-if="aiMissing.length && aiGuesses.length">；</template>
          <template v-if="aiGuesses.length">另有 {{ aiGuesses.length }} 个值是 AI 猜的</template>
        </span>
        <el-button link type="primary" size="small" @click="dismissAiHints">忽略</el-button>
      </div>
      <div v-for="(item, index) in aiMissing" :key="'m' + index" class="missing-row">
        <span class="missing-step">步骤 {{ item.step }}</span>
        <span class="missing-iface">{{ item.interface }}</span>
        <span class="missing-var">{{ item.var }}</span>
        <template v-if="item.suggestion">
          <span class="missing-hint">可用 步骤 {{ item.suggestion.step }} · {{ item.suggestion.path }}</span>
          <el-button link type="primary" size="small" @click="useSuggestion(item, index)">采用</el-button>
        </template>
        <span v-else class="missing-hint">没有可用上游，请手工填写或配置环境变量</span>
      </div>
      <div v-for="(item, index) in aiGuesses" :key="'g' + index" class="missing-row">
        <span class="missing-step">步骤 {{ item.step }}</span>
        <span class="missing-iface">{{ item.interface }}</span>
        <span class="guess-field">{{ item.path }}</span>
        <span class="guess-value">= {{ formatGuess(item.value) }}</span>
        <span class="missing-hint">AI 推测的值，可能不准，建议换成真实数据或上游结果</span>
      </div>
    </div>

    <main v-loading="loading" class="workspace">
      <aside class="left-panel">
        <div class="panel-title">
          <span>测试场景</span>
          <el-button link type="primary" @click="newScenario">新建</el-button>
        </div>
        <div class="suite-list">
          <div
            v-for="suite in pagedSuites"
            :key="suite.id"
            class="suite-item"
            :class="{ active: selectedSuiteId === suite.id }"
          >
            <button class="suite-open" @click="openSuite(suite)">
              <span class="suite-name">{{ suite.name }}</span>
              <span class="suite-meta">{{ suite.scenario_config?.steps?.length || 0 }} 个步骤</span>
            </button>
            <el-button link type="danger" class="suite-delete" @click.stop="deleteSuite(suite)">删除</el-button>
          </div>
          <div v-if="!suites.length" class="empty-mini">还没有保存的场景</div>
        </div>
        <div v-if="suites.length > suitePageSize" class="request-pager suite-pager">
          <span class="request-pager-tip">共 {{ suites.length }} 个场景</span>
          <el-pagination
            v-model:current-page="suitePage"
            :page-size="suitePageSize"
            :total="suites.length"
            :pager-count="3"
            layout="prev, pager, next"
            size="small"
            background
          />
        </div>

        <div class="panel-title interface-title">
          <span class="interface-title-left">
            接口库
            <span class="count-badge">{{ filteredRequests.length }}</span>
          </span>
          <span class="interface-title-actions">
            <el-button link type="primary" class="normalize-link" title="手工新建一个接口，不必等 YApi 同步" @click="openInterfaceCreator">
              新建接口
            </el-button>
            <el-button link type="primary" class="normalize-link" :disabled="!activeConnection" @click="normalizeProjectPaths">
              统一路径
            </el-button>
          </span>
        </div>
        <el-input v-model="searchText" placeholder="搜索接口名称或路径" clearable size="small" />
        <div class="request-list">
          <div
            v-for="request in pagedRequests"
            :key="request.id"
            class="request-item"
            :class="{ added: isAdded(request.id) }"
            @contextmenu.prevent.stop="openRequestMenu($event, request)"
          >
            <button class="request-add" @click="addInterface(request)">
              <span class="method" :class="`method-${String(request.method || 'get').toLowerCase()}`">{{ request.method }}</span>
              <span class="request-main">
                <span class="request-name">{{ request.name }}</span>
                <span class="request-path">{{ request.url }}</span>
              </span>
              <span class="add-mark">{{ isAdded(request.id) ? '已加入' : '+' }}</span>
            </button>
          </div>
          <div v-if="!filteredRequests.length" class="empty-mini">当前项目没有可选择的接口</div>
        </div>
        <div v-if="filteredRequests.length > requestPageSize" class="request-pager">
          <span class="request-pager-tip">已加入 {{ steps.length }}</span>
          <el-pagination
            v-model:current-page="requestPage"
            :page-size="requestPageSize"
            :total="filteredRequests.length"
            :pager-count="3"
            layout="prev, pager, next"
            size="small"
            background
          />
        </div>
      </aside>

      <section class="center-panel">
        <div class="scenario-toolbar">
          <el-input v-model="scenarioName" class="scenario-name" placeholder="给这个测试场景起个名字" />
          <div class="toolbar-actions">
            <el-button type="primary" plain :loading="aiPlanning" :disabled="!steps.length" @click="aiGenerate">
              AI 生成场景
            </el-button>
            <el-button :disabled="steps.length < 2" title="只补齐还没连上的字段，不改顺序、不清空已填的值" @click="autoConnect">自动串联</el-button>
            <el-button :loading="saving" :disabled="!steps.length" @click="saveScenario(false)">保存</el-button>
            <el-checkbox v-model="stopOnFailure" class="stop-on-fail" size="small">失败即停</el-checkbox>
            <el-button type="primary" :loading="running" :disabled="!steps.length" @click="saveAndRun">保存并执行</el-button>
          </div>
        </div>

        <div v-if="!steps.length" class="empty-scenario">
          <div class="empty-icon">→</div>
          <h3>从左侧选择接口</h3>
          <p>按真实业务顺序加入接口，例如：登录 → 创建订单 → 查询订单。</p>
          <p>加入后点「AI 生成场景」，系统会自动排出调用顺序、连接上一步的返回值，并列出还缺哪些数据。</p>
        </div>

        <div v-else class="step-list">
          <article
            v-for="(step, index) in steps"
            :key="step.uid"
            class="step-card"
            :class="{ active: selectedStepUid === step.uid }"
            @click="selectedStepUid = step.uid"
          >
            <div class="step-head">
              <span class="step-no">{{ index + 1 }}</span>
              <span class="method" :class="`method-${String(step.request.method || 'get').toLowerCase()}`">{{ step.request.method }}</span>
              <span class="step-name">{{ step.request.name }}</span>
              <span class="step-actions">
                <el-button link size="small" :disabled="index === 0" @click.stop="moveStep(index, -1)">上移</el-button>
                <el-button link size="small" :disabled="index === steps.length - 1" @click.stop="moveStep(index, 1)">下移</el-button>
                <el-button link type="danger" size="small" @click.stop="removeStep(index)">移除</el-button>
              </span>
            </div>
            <div class="step-path">{{ step.request.url }}</div>
            <div class="step-summary">
              <span>{{ step.bindings.length }} 个参数来自前序步骤</span>
              <span v-if="step.captures.length">提供 {{ step.captures.length }} 个返回字段</span>
            </div>
            <div v-if="step.captures.length" class="capture-chips">
              <span v-for="capture in step.captures" :key="capture.as" class="capture-chip">{{ capture.label || capture.path }} → {{ capture.as }}</span>
            </div>
          </article>
        </div>
      </section>

      <aside v-if="selectedStep" class="right-panel">
        <div class="inspector-head">
          <div>
            <span class="inspector-kicker">正在配置</span>
            <h3>{{ selectedStep.request.name }}</h3>
          </div>
          <el-tag size="small">{{ selectedStep.inputs.length }} 个输入</el-tag>
        </div>

        <section class="inspector-section">
          <div class="section-head">
            <h4>请求参数</h4>
            <span>可直接填写固定值，或选择上一步的结果</span>
          </div>
          <div v-if="!selectedStep.inputs.length" class="empty-mini">这个接口没有需要配置的输入字段</div>
          <div v-for="input in selectedStep.inputs" :key="`${input.location}-${input.path}`" class="input-row">
            <div class="input-head">
              <span class="input-name">{{ input.path }}</span>
              <span class="input-location">{{ locationLabel(input.location) }}</span>
              <span v-if="input.required" class="required-dot">必填</span>
              <span v-else class="optional-dot">可选</span>
              <span v-if="guessOf(input)" class="guess-dot" title="这个值是 AI 按语义推测的，可能不准">AI 猜测</span>
            </div>
            <div class="input-controls">
              <el-input
                v-model="input.value"
                size="small"
                placeholder="固定值或选择来源"
                :class="{ 'guess-input': guessOf(input) }"
                @change="onInputValueChange(input)"
              />
              <el-select
                :model-value="input.binding_key"
                size="small"
                clearable
                placeholder="固定值"
                class="source-select"
                @change="onSourceChange(input, $event)"
              >
                <el-option-group v-for="group in sourceGroups" :key="group.uid" :label="group.label">
                  <el-option
                    v-for="option in group.options"
                    :key="option.value"
                    :label="`${option.label} · ${option.type}`"
                    :value="option.value"
                  />
                </el-option-group>
              </el-select>
            </div>
            <div v-if="input.binding" class="binding-note">
              来自 {{ input.binding.source_label }}
            </div>
          </div>
        </section>

        <section class="inspector-section">
          <div class="section-head assertion-head">
            <div>
              <h4>校验规则</h4>
              <span>确认这一步返回什么才算通过</span>
            </div>
            <el-button link type="primary" @click="addAssertion">+ 添加校验</el-button>
          </div>
          <div v-if="!selectedStep.assertions.length" class="empty-mini">还没有校验规则，建议至少确认 HTTP 状态码</div>
          <div v-for="(assertion, assertionIndex) in selectedStep.assertions" :key="assertionIndex" class="assertion-row">
            <el-select v-model="assertion.type" size="small" class="assertion-type" @change="normalizeAssertion(assertion)">
              <el-option v-for="item in assertionTypes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select
              v-if="assertionNeedsPath(assertion.type)"
              v-model="assertion.path"
              size="small"
              class="assertion-path"
              filterable
              allow-create
              default-first-option
              placeholder="选择返回字段"
            >
              <el-option v-for="field in selectedStep.outputs" :key="field.path" :label="`${field.path} · ${field.type}`" :value="field.path" />
            </el-select>
            <el-input
              v-if="assertionNeedsExpected(assertion.type)"
              v-model="assertion.expected"
              size="small"
              class="assertion-expected"
              :placeholder="assertionExpectedPlaceholder(assertion.type)"
            />
            <span v-if="assertion.type === 'response_time'" class="assertion-unit">ms</span>
            <el-button link type="danger" class="assertion-remove" @click="removeAssertion(assertionIndex)">删除</el-button>
          </div>
        </section>

        <section class="inspector-section">
          <div class="section-head">
            <h4>可引用返回数据</h4>
            <span>后续步骤可以直接选择这些字段</span>
          </div>
          <div v-if="!selectedStep.outputs.length" class="empty-mini">YApi 中还没有响应结构，可先试运行后补充</div>
          <div class="output-list">
            <div v-for="field in selectedStep.outputs" :key="field.path" class="output-item">
              <span class="output-path">{{ field.path }}</span>
              <span class="output-type">{{ field.type }}</span>
              <span v-if="capturedAlias(selectedStep, field.path)" class="output-captured">已引用</span>
            </div>
          </div>
        </section>
      </aside>
    </main>

    <teleport to="body">
      <ul
        v-if="requestMenuVisible"
        class="request-menu"
        :style="{ left: requestMenuX + 'px', top: requestMenuY + 'px' }"
      >
        <li @click="editRequestFromMenu">编辑接口</li>
        <li class="danger" @click="deleteRequestFromMenu">删除接口</li>
      </ul>
    </teleport>

    <el-dialog
      v-model="interfaceEditVisible"
      :title="interfaceEditForm.id ? '编辑接口' : '新建接口'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="接口名称">
          <el-input v-model="interfaceEditForm.name" maxlength="200" placeholder="例如：创建订单" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="请求方法">
            <el-select v-model="interfaceEditForm.method" style="width: 100%">
              <el-option v-for="method in httpMethods" :key="method" :label="method" :value="method" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属版本">
            <el-select v-model="interfaceEditForm.collection" clearable placeholder="不归属任何版本" style="width: 100%">
              <el-option v-for="item in collections" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="接口路径">
          <el-input v-model="interfaceEditForm.url" placeholder="推荐：{{base_url}}/模块/接口" />
        </el-form-item>
      </el-form>
      <div class="path-format-tip">
        推荐统一使用 <code v-pre>{{base_url}}/模块/接口</code>。执行时会自动替换为当前环境配置的地址，
        切换测试或预发环境时不需要修改接口。
      </div>
      <el-checkbox v-if="!interfaceEditForm.id" v-model="interfaceJoinScenario" class="interface-join-check">
        创建后直接加入当前场景
      </el-checkbox>
      <template #footer>
        <div class="interface-dialog-footer">
          <el-button v-if="interfaceEditForm.id" link type="primary" @click="openAdvancedEditor">
            高级编辑（参数 / Body / 断言）
          </el-button>
          <span v-else class="footer-hint">创建后可在右侧面板补参数；需要 Body、断言时点「编辑 → 高级编辑」</span>
          <span class="footer-actions">
            <el-button @click="interfaceEditVisible = false">取消</el-button>
            <el-button type="primary" :loading="interfaceSaving" @click="saveInterfaceEdit">
              {{ interfaceEditForm.id ? '保存修改' : '创建接口' }}
            </el-button>
          </span>
        </div>
      </template>
    </el-dialog>

    <el-drawer v-model="yapiDrawer" title="同步 YApi 接口" size="480px">
      <div v-if="!activeConnection" class="drawer-empty">
        <p>当前项目还没有配置 YApi 连接。</p>
        <el-button type="primary" @click="go('/api-testing/yapi-sync')">前往连接管理</el-button>
      </div>
      <template v-else>
        <div class="connection-card">
          <b>{{ activeConnection.name }}</b>
          <span>{{ activeConnection.yapi_url }} · 项目 {{ activeConnection.yapi_project_id }}</span>
        </div>
        <div class="drawer-section-title">选择要同步的版本或分类</div>
        <div v-if="yapiLoading" class="drawer-loading">正在读取 YApi 分类...</div>
        <el-checkbox-group v-else v-model="selectedCats" class="category-list">
          <el-checkbox v-for="category in yapiCategories" :key="category.catid" :value="category.catid" class="category-item">
            <span>{{ category.name }}</span>
            <small>{{ category.count }} 个接口</small>
          </el-checkbox>
        </el-checkbox-group>
        <div class="drawer-actions">
          <el-button @click="yapiDrawer = false">取消</el-button>
          <el-button type="primary" :loading="yapiSyncing" :disabled="!selectedCats.length" @click="syncYapi">
            同步 {{ selectedCats.length }} 个分类
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-drawer v-model="settingsVisible" title="接口自动化配置" size="420px">
      <p class="settings-tip">日常测试只需要“测试设计”和“执行与报告”两个页面，配置项收纳在这里。</p>
      <div class="settings-list">
        <button class="settings-item" @click="go('/api-testing/yapi-sync')">
          <b>YApi 连接</b>
          <span>维护地址、Token 和项目绑定</span>
        </button>
        <button class="settings-item" @click="go('/api-testing/projects')">
          <b>项目管理</b>
          <span>维护接口测试项目与成员</span>
        </button>
        <button class="settings-item" @click="go('/api-testing/environments')">
          <b>环境变量</b>
          <span>配置 base_url、Token 等变量</span>
        </button>
        <button class="settings-item" @click="openSharedDialog">
          <b>公共请求头与参数</b>
          <span>每个请求都会带上的 header 和 userid 等参数</span>
        </button>
        <button class="settings-item" @click="go('/api-testing/ai-service-config')">
          <b>AI 模型</b>
          <span>用于参数分析和智能建议</span>
        </button>
        <button class="settings-item" @click="go('/api-testing/scheduled-tasks')">
          <b>定时任务</b>
          <span>管理已有定时执行计划</span>
        </button>
        <button class="settings-item" @click="go('/api-testing/notification-logs')">
          <b>通知记录</b>
          <span>查看任务执行通知</span>
        </button>
      </div>
    </el-drawer>

    <el-dialog v-model="sharedVisible" title="公共请求头与参数" width="840px" :close-on-click-modal="false">
      <p class="shared-tip">
        这里配置的内容会在该环境的每个请求上自动带上，例如绕过鉴权用的 Signature、标识用户身份的 userid。
        接口自己配了同名且非空的字段时，以接口为准。
      </p>
      <div class="shared-env">
        <span class="shared-env-label">环境</span>
        <el-select v-model="sharedEnvId" size="small" style="width: 260px" @change="loadSharedConfig">
          <el-option v-for="env in environments" :key="env.id" :label="env.name" :value="env.id" />
        </el-select>
        <span class="shared-env-hint">{{ sharedEnvHint }}</span>
      </div>

      <div class="shared-switch">
        <button :class="{ active: sharedTab === 'headers' }" @click="sharedTab = 'headers'">
          公共请求头（{{ sharedHeaders.length }}）
        </button>
        <button :class="{ active: sharedTab === 'params' }" @click="sharedTab = 'params'">
          公共 URL 参数（{{ sharedParams.length }}）
        </button>
      </div>

      <div class="shared-grid shared-grid-head">
        <span>启用</span>
        <span>名称</span>
        <span>值</span>
        <span>说明</span>
        <span />
      </div>
      <div class="shared-body">
        <div v-for="(row, index) in sharedRows" :key="index" class="shared-grid shared-row">
          <el-checkbox v-model="row.enabled" />
          <el-input v-model="row.key" size="small" placeholder="名称，如 Signature" />
          <el-input v-model="row.value" size="small" placeholder="值" />
          <el-input v-model="row.description" size="small" placeholder="说明（可选）" />
          <el-button link type="danger" size="small" @click="removeSharedRow(index)">删除</el-button>
        </div>
        <div v-if="!sharedRows.length" class="empty-mini">还没有配置，点下面的按钮加一行</div>
      </div>
      <el-button class="shared-add" link type="primary" @click="addSharedRow">+ 添加一行</el-button>

      <template #footer>
        <el-button @click="sharedVisible = false">取消</el-button>
        <el-button type="primary" :loading="sharedSaving" :disabled="!sharedEnvId" @click="saveSharedConfig">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/utils/api'
import {
  applyMissingSuggestion,
  autoConnectSteps,
  bindInputToSource,
  buildStepsFromPlan,
  cleanupCaptures,
  clearInputBinding,
  createStep,
  hydrateSteps,
  refreshStep,
  runSteps,
  scenarioPayload,
  scenarioStats,
  sourceOptions,
  writeInputValue,
} from '@/utils/apiScenario'

const route = useRoute()
const router = useRouter()

const projects = ref([])
const requests = ref([])
const environments = ref([])
const suites = ref([])
const collections = ref([])
const yapiConnections = ref([])
const projectId = ref(null)
const environmentId = ref(null)
const collectionId = ref(null)
const aiPlanning = ref(false)
const aiGenerated = ref(false)
const aiMissing = ref([])
const aiGuesses = ref([])
const aiExcluded = ref([])
const excludedExpanded = ref(false)
const stopOnFailure = ref(false)
const selectedSuiteId = ref(null)
const selectedStepUid = ref(null)
const scenarioName = ref('未命名接口场景')
const steps = ref([])
const searchText = ref('')
const loading = ref(false)
const saving = ref(false)
const running = ref(false)
const interfaceEditVisible = ref(false)
const interfaceSaving = ref(false)
const interfaceJoinScenario = ref(true)
const interfaceEditForm = ref({ id: null, name: '', method: 'GET', url: '', collection: null })
const httpMethods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']

const yapiDrawer = ref(false)
const yapiLoading = ref(false)
const yapiSyncing = ref(false)
const yapiCategories = ref([])
const selectedCats = ref([])
const settingsVisible = ref(false)

// 公共请求头与公共 URL 参数（环境级），入口收在「配置」抽屉里
const sharedVisible = ref(false)
const sharedSaving = ref(false)
const sharedEnvId = ref(null)
const sharedTab = ref('headers')
const sharedHeaders = ref([])
const sharedParams = ref([])
const sharedRows = computed(() => (sharedTab.value === 'headers' ? sharedHeaders.value : sharedParams.value))
const sharedEnv = computed(() => environments.value.find((env) => env.id === sharedEnvId.value) || null)
const sharedEnvHint = computed(() => {
  const env = sharedEnv.value
  if (!env) return ''
  return env.is_active ? '当前生效环境' : '未激活，执行时需在顶部选择这个环境'
})

function normalizeSharedRows(rows) {
  return (rows || []).map((row) => ({
    key: row?.key || '',
    value: row?.value ?? '',
    description: row?.description || '',
    // 历史数据里 enabled 可能是字符串 "1"，统一成布尔值
    enabled: row?.enabled !== false && row?.enabled !== 0 && row?.enabled !== '0',
  }))
}

function loadSharedConfig() {
  const env = sharedEnv.value
  sharedHeaders.value = normalizeSharedRows(env?.default_headers)
  sharedParams.value = normalizeSharedRows(env?.default_params)
}

function openSharedDialog() {
  settingsVisible.value = false
  const fallback = environments.value.find((env) => env.is_active) || environments.value[0]
  sharedEnvId.value = environmentId.value || fallback?.id || null
  sharedTab.value = 'headers'
  loadSharedConfig()
  sharedVisible.value = true
}

function addSharedRow() {
  sharedRows.value.push({ key: '', value: '', description: '', enabled: true })
}

function removeSharedRow(index) {
  sharedRows.value.splice(index, 1)
}

function cleanSharedRows(rows) {
  return rows
    .filter((row) => String(row.key || '').trim())
    .map((row) => ({
      key: String(row.key).trim(),
      value: row.value ?? '',
      description: row.description || '',
      enabled: row.enabled !== false,
    }))
}

async function saveSharedConfig() {
  if (!sharedEnvId.value) return
  sharedSaving.value = true
  try {
    const headers = cleanSharedRows(sharedHeaders.value)
    const params = cleanSharedRows(sharedParams.value)
    await api.patch(`/api-testing/environments/${sharedEnvId.value}/`, {
      default_headers: headers,
      default_params: params,
    })
    const env = environments.value.find((item) => item.id === sharedEnvId.value)
    if (env) {
      env.default_headers = headers
      env.default_params = params
    }
    sharedVisible.value = false
    ElMessage.success('公共请求头与参数已保存')
  } catch (error) {
    ElMessage.error(`保存失败: ${error.response?.data?.detail || error.response?.data?.error || error.message}`)
  } finally {
    sharedSaving.value = false
  }
}

const stats = computed(() => scenarioStats(steps.value))
// 环境变量 + 公共参数名：自动串联时跳过这些引用，避免把 {{userid}} 之类改成上游字段
const envVariableNames = computed(() => {
  const names = new Set()
  environments.value.forEach((env) => {
    Object.keys(env.variables || {}).forEach((key) => names.add(key))
    ;(env.default_params || []).forEach((item) => {
      if (item && item.key) names.add(item.key)
    })
  })
  return [...names]
})
const missingCount = computed(() => stats.value.missing + aiMissing.value.length)
const selectedStep = computed(() => steps.value.find((step) => step.uid === selectedStepUid.value) || null)
const selectedStepIndex = computed(() => steps.value.findIndex((step) => step.uid === selectedStepUid.value))
const sourceGroups = computed(() => selectedStepIndex.value > 0 ? sourceOptions(steps.value, selectedStepIndex.value) : [])
const activeConnection = computed(() => yapiConnections.value.find((item) => item.project === projectId.value))
const filteredRequests = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  let list = requests.value
  if (collectionId.value) {
    list = list.filter((request) => request.collection === collectionId.value)
  }
  if (!keyword) return list
  return list.filter((request) => {
    return [request.name, request.url, request.method].some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})

const requestPage = ref(1)
const requestPageSize = ref(20)
const pagedRequests = computed(() => {
  const start = (requestPage.value - 1) * requestPageSize.value
  return filteredRequests.value.slice(start, start + requestPageSize.value)
})

// 搜索或切换版本/项目时回到第一页，避免停在空页
watch([searchText, collectionId, projectId], () => {
  requestPage.value = 1
})

// 过滤后条数变少时，把越界的页码收回来
watch(() => filteredRequests.value.length, (length) => {
  const maxPage = Math.max(1, Math.ceil(length / requestPageSize.value))
  if (requestPage.value > maxPage) requestPage.value = maxPage
})

// 场景列表分页：每页 5 条，场景多了也不用一直往下滑
const suitePage = ref(1)
const suitePageSize = ref(5)
const pagedSuites = computed(() => {
  const start = (suitePage.value - 1) * suitePageSize.value
  return suites.value.slice(start, start + suitePageSize.value)
})

// 场景增删导致条数变化时，把越界的页码收回来
watch(() => suites.value.length, (length) => {
  const maxPage = Math.max(1, Math.ceil(length / suitePageSize.value))
  if (suitePage.value > maxPage) suitePage.value = maxPage
})

// 切换项目时场景列表会整体换掉，回到第一页
watch(projectId, () => {
  suitePage.value = 1
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
    const requestedProject = Number(route.query.project)
    projectId.value = projects.value.some((item) => item.id === requestedProject)
      ? requestedProject
      : projects.value[0].id
    await loadProjectData()
  }
}

async function loadProjectData() {
  if (!projectId.value) return
  loading.value = true
  try {
    const [requestList, envList, suiteList, connections, collectionList] = await Promise.all([
      fetchAll('/api-testing/requests/', { project: projectId.value }),
      fetchAll('/api-testing/environments/', { project: projectId.value }),
      fetchAll('/api-testing/test-suites/', { project: projectId.value }),
      fetchAll('/api-testing/yapi-connections/'),
      fetchAll('/api-testing/collections/', { project: projectId.value }),
    ])
    requests.value = requestList
    environments.value = envList
    suites.value = suiteList
    yapiConnections.value = connections
    collections.value = collectionList
    if (collectionId.value && !collections.value.some((item) => item.id === collectionId.value)) {
      collectionId.value = null
    }
    syncStepRequests()
    if (!environments.value.some((item) => item.id === environmentId.value)) {
      environmentId.value = environments.value.find((item) => item.is_active)?.id || environments.value[0]?.id || null
    }
    const requestedSuite = Number(route.query.suite)
    if (requestedSuite) {
      const suite = suites.value.find((item) => item.id === requestedSuite)
      if (suite) openSuite(suite)
    }
  } catch (error) {
    ElMessage.error(`加载项目数据失败：${error.response?.data?.detail || error.message}`)
  } finally {
    loading.value = false
  }
}

function syncStepRequests() {
  steps.value.forEach((step) => {
    const fresh = requests.value.find((request) => request.id === step.request.id)
    if (fresh && fresh !== step.request) {
      step.request = fresh
      refreshStep(step)
    }
  })
}

async function loadSuites() {
  if (!projectId.value) return
  suites.value = await fetchAll('/api-testing/test-suites/', { project: projectId.value })
}

async function deleteSuite(suite) {
  try {
    await ElMessageBox.confirm(
      `确定删除测试场景“${suite.name}”吗？场景内的编排和参数绑定会一起删除，但不会删除原始接口。`,
      '删除测试场景',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.delete(`/api-testing/test-suites/${suite.id}/`)
    if (selectedSuiteId.value === suite.id) newScenario()
    await loadSuites()
    ElMessage.success('测试场景已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(`删除失败：${error.response?.data?.detail || error.message}`)
    }
  }
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]))
}

// 哪些已保存场景用到了这个接口（场景步骤里存的是 request_id）
function scenarioRefsOf(requestId) {
  return suites.value.filter((suite) => {
    const list = Array.isArray(suite.scenario_config?.steps) ? suite.scenario_config.steps : []
    return list.some((saved) => saved.request_id === requestId)
  })
}

async function deleteInterface(request) {
  const refs = scenarioRefsOf(request.id)
  const usedInCurrent = steps.value.some((step) => step.request.id === request.id)
  const notes = []
  if (refs.length) {
    const names = refs.map((suite) => `「${escapeHtml(suite.name)}」`).join('、')
    notes.push(`已保存场景 ${names} 引用了它，删除后这些场景里对应的这一步会消失`)
  }
  if (usedInCurrent) notes.push('当前正在编辑的场景也包含它，会同时从步骤中移除')
  notes.push('该接口的执行历史记录会一起删除')

  const message = [`确定删除接口「${escapeHtml(request.name)}」吗？`, ...notes.map((note) => `· ${note}`), '此操作不可恢复。'].join('<br>')
  try {
    await ElMessageBox.confirm(message, '删除接口', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      dangerouslyUseHTMLString: true,
    })
    await api.delete(`/api-testing/requests/${request.id}/`)
    requests.value = requests.value.filter((item) => item.id !== request.id)
    if (usedInCurrent) {
      const index = steps.value.findIndex((step) => step.request.id === request.id)
      if (index >= 0) removeStep(index)
    }
    if (interfaceEditVisible.value && interfaceEditForm.value.id === request.id) {
      interfaceEditVisible.value = false
    }
    ElMessage.success('接口已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(`删除失败：${error.response?.data?.detail || error.message}`)
    }
  }
}

const requestMenuVisible = ref(false)
const requestMenuRequest = ref(null)
const requestMenuX = ref(0)
const requestMenuY = ref(0)

const REQUEST_MENU_WIDTH = 132
const REQUEST_MENU_HEIGHT = 82

// 接口右键菜单：定位到鼠标位置，靠边时向内收，避免出屏
function openRequestMenu(event, request) {
  requestMenuRequest.value = request
  const maxX = window.innerWidth - REQUEST_MENU_WIDTH - 8
  const maxY = window.innerHeight - REQUEST_MENU_HEIGHT - 8
  requestMenuX.value = Math.min(event.clientX, Math.max(8, maxX))
  requestMenuY.value = Math.min(event.clientY, Math.max(8, maxY))
  requestMenuVisible.value = true
}

function closeRequestMenu() {
  requestMenuVisible.value = false
  requestMenuRequest.value = null
}

function editRequestFromMenu() {
  const request = requestMenuRequest.value
  closeRequestMenu()
  if (request) openInterfaceEditor(request)
}

async function deleteRequestFromMenu() {
  const request = requestMenuRequest.value
  closeRequestMenu()
  if (request) await deleteInterface(request)
}

function openInterfaceEditor(request) {
  interfaceEditForm.value = {
    id: request.id,
    name: request.name || '',
    method: request.method || 'GET',
    url: request.url || '',
    collection: request.collection || null,
  }
  interfaceEditVisible.value = true
}

// 手工新建接口：默认落到当前版本，避免建完在筛选条件下看不到
function openInterfaceCreator() {
  interfaceJoinScenario.value = true
  interfaceEditForm.value = {
    id: null,
    name: '',
    method: 'GET',
    url: '',
    collection: collectionId.value || null,
  }
  interfaceEditVisible.value = true
}

// 跳到完整编辑器补参数、Body 和断言（该页不进主菜单，只作为深度编辑入口）
function openAdvancedEditor() {
  const form = interfaceEditForm.value
  if (!form.id) return
  interfaceEditVisible.value = false
  router.push({
    path: '/api-testing/interfaces',
    query: { project: projectId.value, request: form.id },
  })
}

async function saveInterfaceEdit() {
  const form = interfaceEditForm.value
  if (!form.name.trim() || !form.url.trim()) {
    ElMessage.warning('接口名称和路径不能为空')
    return
  }
  interfaceSaving.value = true
  try {
    if (!form.id) {
      // 新建：集合可为空（未归类接口对当前用户可见），其余字段走模型默认值
      const response = await api.post('/api-testing/requests/', {
        name: form.name.trim(),
        method: form.method,
        url: form.url.trim(),
        collection: form.collection || null,
        params: {},
        headers: [],
        body: {},
      })
      const created = response.data
      requests.value.unshift(created)
      searchText.value = ''
      requestPage.value = 1
      interfaceEditVisible.value = false
      if (interfaceJoinScenario.value) {
        addInterface(created)
        ElMessage.success(`接口已创建并加入场景：${created.name}`)
      } else {
        ElMessage.success(`接口已创建：${created.name}`)
      }
      return
    }
    const response = await api.patch(`/api-testing/requests/${form.id}/`, {
      name: form.name.trim(),
      method: form.method,
      url: form.url.trim(),
      collection: form.collection || null,
    })
    const current = requests.value.find((request) => request.id === form.id)
    if (current) Object.assign(current, response.data)
    steps.value.forEach((step) => {
      if (step.request.id === form.id) {
        Object.assign(step.request, response.data)
        refreshStep(step)
      }
    })
    interfaceEditVisible.value = false
    ElMessage.success('接口信息已更新')
  } catch (error) {
    ElMessage.error(`保存失败：${error.response?.data?.detail || error.message}`)
  } finally {
    interfaceSaving.value = false
  }
}

async function normalizeProjectPaths() {
  if (!activeConnection.value) {
    ElMessage.warning('当前项目还没有配置 YApi 连接')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将把当前环境下同域名的绝对地址和相对路径统一为 {{base_url}}/路径；其他域名和自定义变量保持不变。',
      '统一接口路径格式',
      { type: 'warning', confirmButtonText: '统一格式', cancelButtonText: '取消' },
    )
    const response = await api.post(`/api-testing/yapi-connections/${activeConnection.value.id}/fix_base_url/`)
    await loadProjectData()
    ElMessage.success(`路径已统一：更新 ${response.data.updated || 0} 个，跳过 ${response.data.skipped || 0} 个`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(`统一路径失败：${error.response?.data?.detail || error.response?.data?.error || error.message}`)
    }
  }
}

async function onProjectChange() {
  newScenario()
  await loadProjectData()
}

function newScenario() {
  selectedSuiteId.value = null
  selectedStepUid.value = null
  steps.value = []
  scenarioName.value = '未命名接口场景'
  aiGenerated.value = false
  aiMissing.value = []
  aiGuesses.value = []
  aiExcluded.value = []
  excludedExpanded.value = false
}

function openSuite(suite) {
  selectedSuiteId.value = suite.id
  scenarioName.value = suite.name
  environmentId.value = suite.environment || environmentId.value
  steps.value = hydrateSteps(suite.scenario_config, requests.value)
  selectedStepUid.value = steps.value[0]?.uid || null
  aiGenerated.value = false
  aiMissing.value = []
  aiGuesses.value = []
}

function isAdded(requestId) {
  return steps.value.some((step) => step.request.id === requestId)
}

function addInterface(request) {
  if (isAdded(request.id)) {
    ElMessage.info('这个接口已经在当前场景中')
    return
  }
  const step = createStep(request)
  steps.value.push(step)
  selectedStepUid.value = step.uid
  if (steps.value.length > 1) {
    const result = autoConnectSteps(steps.value, { envNames: envVariableNames.value })
    if (result.matched) ElMessage.success(`已自动关联 ${result.matched} 个参数`)
  }
}

function removeStep(index) {
  const removedUid = steps.value[index]?.uid
  steps.value.splice(index, 1)
  steps.value.forEach((step) => {
    step.bindings = step.bindings.filter((binding) => binding.source_step_uid !== removedUid)
  })
  cleanupCaptures(steps.value)
  steps.value.forEach(refreshStep)
  if (selectedStepUid.value === removedUid) selectedStepUid.value = steps.value[0]?.uid || null
}

function moveStep(index, offset) {
  const target = index + offset
  if (target < 0 || target >= steps.value.length) return
  const [step] = steps.value.splice(index, 1)
  steps.value.splice(target, 0, step)
  autoConnect()
}

function autoConnect() {
  if (steps.value.length < 2) return
  // 只补齐还没连上的字段，已填的值和已建立的依赖都不会被改动
  const result = autoConnectSteps(steps.value, { envNames: envVariableNames.value })
  selectedStepUid.value = steps.value[Math.min(1, steps.value.length - 1)].uid
  if (result.matched) {
    const tail = result.unresolved ? `，还有 ${result.unresolved} 个必填字段待处理` : ''
    ElMessage.success(`已补齐 ${result.matched} 个关联${tail}`)
    return
  }
  if (result.unresolved) {
    ElMessage.warning('没有识别到可自动关联的同名字段，请手动选择来源')
    return
  }
  ElMessage.success('必填字段都已关联，无需再补')
}

function onInputValueChange(input) {
  if (!selectedStep.value) return
  if (input.binding) {
    selectedStep.value.bindings = selectedStep.value.bindings.filter(
      (binding) => !(binding.target_location === input.location && binding.target_path === input.path),
    )
    cleanupCaptures(steps.value)
  }
  writeInputValue(selectedStep.value, input, input.value)
  refreshStep(selectedStep.value)
}

async function aiGenerate() {
  if (!projectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  const requestIds = [...new Set(steps.value.map((step) => step.request.id))]
  if (!requestIds.length) {
    ElMessage.warning('请先从左侧把要测的接口加入场景')
    return
  }
  aiPlanning.value = true
  aiMissing.value = []
  aiExcluded.value = []
  excludedExpanded.value = false
  try {
    const response = await api.post('/api-testing/agent/plan/', {
      project_id: projectId.value,
      request_ids: requestIds,
      collection_id: collectionId.value || undefined,
    }, { timeout: 240000 })
    const plan = response.data || {}
    const built = buildStepsFromPlan(plan, requests.value)
    if (!built.length) {
      ElMessage.warning('AI 没有排出可用步骤，请确认接口定义是否完整')
      return
    }
    steps.value = built
    selectedStepUid.value = built[0].uid
    aiMissing.value = plan.missing || []
    aiGuesses.value = plan.guesses || []
    aiExcluded.value = plan.excluded || []
    aiGenerated.value = true
    if (plan.scenario && (!scenarioName.value.trim() || scenarioName.value === '未命名接口场景')) {
      scenarioName.value = plan.scenario
    }
    const dropped = requestIds.length - built.length
    const parts = []
    if (dropped > 0) parts.push(`排除 ${dropped} 个无关接口，可在上方查看原因并补入`)
    if (aiMissing.value.length) parts.push(`${aiMissing.value.length} 个字段待补齐`)
    if (aiGuesses.value.length) parts.push(`${aiGuesses.value.length} 个值是 AI 猜的`)
    ElMessage.success(`AI 已生成 ${built.length} 步${parts.length ? `：${parts.join('，')}` : ''}`)
  } catch (error) {
    ElMessage.error(`生成失败：${error.response?.data?.error || error.message}`)
  } finally {
    aiPlanning.value = false
  }
}

function useSuggestion(item, index) {
  const capture = applyMissingSuggestion(steps.value, item)
  if (!capture) {
    ElMessage.warning('这个字段无法自动绑定，请手动选择来源')
    return
  }
  aiMissing.value.splice(index, 1)
  ElMessage.success('已按建议绑定')
}

function formatGuess(value) {
  if (value === null || value === undefined) return '空'
  if (typeof value === 'object') {
    const text = JSON.stringify(value)
    return text.length > 40 ? `${text.slice(0, 40)}…` : text
  }
  return String(value)
}

function guessOf(input) {
  const index = steps.value.findIndex((step) => step.uid === selectedStepUid.value)
  if (index < 0) return null
  return aiGuesses.value.find(
    (item) => item.step === index + 1 && item.location === input.location && item.path === input.path,
  ) || null
}

function dismissAiHints() {
  aiMissing.value = []
  aiGuesses.value = []
}

function dismissExcluded() {
  aiExcluded.value = []
  excludedExpanded.value = false
}

function addOneExcluded(item) {
  const request = requests.value.find((r) => r.id === item.request_id)
  if (!request) {
    ElMessage.warning('该接口已不在接口库中，可能被删除了')
    aiExcluded.value = aiExcluded.value.filter((x) => x.request_id !== item.request_id)
    return
  }
  if (isAdded(request.id)) {
    aiExcluded.value = aiExcluded.value.filter((x) => x.request_id !== item.request_id)
    ElMessage.info('这个接口已经在场景里了')
    return
  }
  addInterface(request)
  aiExcluded.value = aiExcluded.value.filter((x) => x.request_id !== item.request_id)
}

function addAllExcluded() {
  const pending = aiExcluded.value.slice()
  let added = 0
  pending.forEach((item) => {
    const request = requests.value.find((r) => r.id === item.request_id)
    if (request && !isAdded(request.id)) {
      addInterface(request)
      added += 1
    }
  })
  aiExcluded.value = []
  excludedExpanded.value = false
  ElMessage.success(added ? `已补入 ${added} 个接口，排在最后，可拖动或重跑 AI 调整顺序` : '这些接口已经在场景里了')
}

function onCollectionChange() {
  aiMissing.value = []
}

function onSourceChange(input, key) {
  if (!selectedStep.value) return
  if (!key) {
    clearInputBinding(steps.value, selectedStep.value, input)
    return
  }
  const [sourceStepUid, sourcePath] = String(key).split('|')
  const capture = bindInputToSource(steps.value, selectedStep.value, input, sourceStepUid, sourcePath)
  if (capture) ElMessage.success(`已绑定到 ${capture.label || sourcePath}`)
}

const assertionTypes = [
  { value: 'status_code', label: 'HTTP 状态码' },
  { value: 'json_path_exists', label: '字段存在' },
  { value: 'json_path', label: '字段等于' },
  { value: 'contains', label: '响应包含文本' },
  { value: 'response_time', label: '响应时间小于' },
]

function addAssertion() {
  if (!selectedStep.value) return
  selectedStep.value.assertions.push({ type: 'status_code', expected: 200 })
}

function removeAssertion(index) {
  if (!selectedStep.value) return
  selectedStep.value.assertions.splice(index, 1)
}

function normalizeAssertion(assertion) {
  if (assertion.type === 'status_code') {
    assertion.expected = assertion.expected ?? 200
    delete assertion.path
  } else if (assertion.type === 'response_time') {
    assertion.expected = assertion.expected ?? 1000
    delete assertion.path
  } else if (assertion.type === 'contains') {
    assertion.expected = assertion.expected ?? ''
    delete assertion.path
  } else {
    assertion.path = assertion.path || selectedStep.value?.outputs?.[0]?.path || ''
    if (assertion.type === 'json_path') assertion.expected = assertion.expected ?? ''
    else delete assertion.expected
  }
}

function assertionNeedsPath(type) {
  return ['json_path', 'json_path_exists'].includes(type)
}

function assertionNeedsExpected(type) {
  return ['status_code', 'json_path', 'contains', 'response_time'].includes(type)
}

function assertionExpectedPlaceholder(type) {
  return {
    status_code: '例如 200',
    json_path: '期望值',
    contains: '响应中应包含的文字',
    response_time: '例如 1000',
  }[type] || '期望值'
}

function locationLabel(location) {
  return { params: 'URL/Query', body: 'Body', headers: 'Header' }[location] || location
}

function capturedAlias(step, path) {
  return step.captures.find((capture) => capture.path === path)?.as || ''
}

async function saveScenario(showMessage = true) {
  if (!projectId.value || !scenarioName.value.trim() || !steps.value.length) {
    ElMessage.warning('请先选择项目、填写场景名称并加入接口')
    return null
  }
  saving.value = true
  try {
    const payload = scenarioPayload(scenarioName.value.trim(), projectId.value, environmentId.value, steps.value)
    let response
    if (selectedSuiteId.value) {
      response = await api.put(`/api-testing/test-suites/${selectedSuiteId.value}/`, payload)
    } else {
      response = await api.post('/api-testing/test-suites/', payload)
      selectedSuiteId.value = response.data.id
    }
    const savedSuite = response.data
    await loadSuites()
    const current = suites.value.find((item) => item.id === selectedSuiteId.value)
    if (current) {
      scenarioName.value = current.name
      environmentId.value = current.environment || environmentId.value
    }
    if (showMessage) ElMessage.success('场景已保存')
    return current || savedSuite
  } catch (error) {
    ElMessage.error(`保存失败：${error.response?.data?.error || error.response?.data?.detail || error.message}`)
    return null
  } finally {
    saving.value = false
  }
}

async function saveAndRun() {
  if (stats.value.missing) {
    ElMessage.warning(`还有 ${stats.value.missing} 个必填字段未配置`)
    return
  }
  running.value = true
  try {
    const suite = await saveScenario(false)
    if (!suite) return
    const response = await api.post('/api-testing/agent/run/', {
      project_id: projectId.value,
      test_suite_id: suite.id,
      environment_id: environmentId.value,
      steps: runSteps(steps.value),
      stop_on_failure: stopOnFailure.value,
    }, { timeout: 300000 })
    const executionId = response.data.execution_id
    ElMessage.success('场景执行完成')
    router.push({
      path: '/api-testing/runs',
      query: { project: projectId.value, suite: suite.id, execution: executionId },
    })
  } catch (error) {
    ElMessage.error(`执行失败：${error.response?.data?.error || error.message}`)
  } finally {
    running.value = false
  }
}

async function openYapiDrawer() {
  yapiDrawer.value = true
  yapiCategories.value = []
  selectedCats.value = []
  if (!activeConnection.value) return
  yapiLoading.value = true
  try {
    const response = await api.get(`/api-testing/yapi-connections/${activeConnection.value.id}/categories/`)
    yapiCategories.value = response.data.categories || []
    selectedCats.value = yapiCategories.value.length ? [yapiCategories.value[0].catid] : []
  } catch (error) {
    ElMessage.error(`读取 YApi 分类失败：${error.response?.data?.error || error.message}`)
  } finally {
    yapiLoading.value = false
  }
}

async function syncYapi() {
  if (!activeConnection.value || !selectedCats.value.length) return
  yapiSyncing.value = true
  try {
    const response = await api.post(`/api-testing/yapi-connections/${activeConnection.value.id}/sync/`, {
      cat_ids: selectedCats.value,
    }, { timeout: 600000 })
    ElMessage.success(`同步完成：新增 ${response.data.new || 0}，更新 ${response.data.updated || 0}`)
    yapiDrawer.value = false
    await loadProjectData()
  } catch (error) {
    ElMessage.error(`同步失败：${error.response?.data?.error || error.message}`)
  } finally {
    yapiSyncing.value = false
  }
}

function go(path) {
  settingsVisible.value = false
  yapiDrawer.value = false
  router.push(path)
}

onMounted(async () => {
  document.addEventListener('click', closeRequestMenu)
  document.addEventListener('contextmenu', closeRequestMenu)
  document.addEventListener('scroll', closeRequestMenu, true)
  window.addEventListener('resize', closeRequestMenu)
  loading.value = true
  try {
    await loadProjects()
  } catch (error) {
    ElMessage.error(`加载项目失败：${error.response?.data?.detail || error.message}`)
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeRequestMenu)
  document.removeEventListener('contextmenu', closeRequestMenu)
  document.removeEventListener('scroll', closeRequestMenu, true)
  window.removeEventListener('resize', closeRequestMenu)
})
</script>

<style scoped>
.design-page {
  --line: #e5e8ef;
  --muted: #7c8497;
  --primary: #246bfd;
  min-height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
  background: #f5f7fb;
}
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 18px 24px; background: #fff; border-bottom: 1px solid var(--line); }
.page-head h1 { margin: 0; font-size: 22px; color: #172033; }
.page-head p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.workflow-strip { display: flex; align-items: center; gap: 10px; padding: 11px 24px; background: #fbfcff; border-bottom: 1px solid var(--line); font-size: 13px; color: var(--muted); }
.flow-item { display: flex; align-items: center; gap: 7px; white-space: nowrap; }
.flow-item b { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: #e9edf5; color: #667085; font-size: 12px; }
.flow-item.done { color: #175cd3; }
.flow-item.done b { color: #fff; background: var(--primary); }
.flow-line { width: 44px; height: 1px; background: #dfe4ec; }
.flow-tip { margin-left: auto; color: #175cd3; }
.flow-warning { color: #b54708; background: #fffaeb; padding: 3px 9px; border-radius: 12px; }
.workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px minmax(420px, 1fr) 360px; gap: 12px; padding: 12px; }
.left-panel, .center-panel, .right-panel { min-height: 0; background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 3px 14px rgba(20, 31, 56, .04); }
.left-panel { padding: 14px; overflow-y: auto; }
.center-panel { padding: 14px; overflow-y: auto; }
.right-panel { padding: 16px; overflow-y: auto; }
.panel-title { display: flex; align-items: center; justify-content: space-between; font-size: 14px; font-weight: 650; color: #273047; margin-bottom: 10px; }
.interface-title { margin-top: 20px; padding-top: 16px; border-top: 1px solid #eef1f6; }
.count-badge { min-width: 24px; text-align: center; color: #667085; background: #f2f4f7; border-radius: 10px; font-size: 12px; padding: 2px 7px; }
.suite-list { display: flex; flex-direction: column; gap: 6px; max-height: 268px; overflow-y: auto; }
.suite-pager { margin-top: 8px; padding-top: 8px; }
.suite-item, .request-item, .settings-item { border: 0; background: transparent; text-align: left; cursor: pointer; }
.suite-item { flex: none; display: flex; justify-content: space-between; gap: 8px; padding: 9px 10px; border-radius: 8px; color: #344054; }
.suite-item:hover, .suite-item.active { background: #eef4ff; color: #175cd3; }
.suite-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.suite-meta { flex: none; color: #98a2b3; font-size: 12px; }
.request-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; max-height: 44vh; overflow-y: auto; padding-right: 2px; }
.request-pager { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px solid #eef1f6; flex-wrap: wrap; }
.request-pager-tip { font-size: 12px; color: #98a2b3; white-space: nowrap; }
.request-pager :deep(.el-pagination) { --el-pagination-button-width: 26px; --el-pagination-button-height: 26px; padding: 0; }
.request-item { flex: none; display: flex; align-items: flex-start; gap: 8px; padding: 9px 8px; border-radius: 8px; color: #344054; }
.request-item:hover { background: #f7f9fc; }
.request-item.added { opacity: .55; }
.method { flex: none; min-width: 44px; text-align: center; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 3px 5px; background: #eef2f6; color: #475467; }
.method-get { color: #067647; background: #ecfdf3; }
.method-post { color: #175cd3; background: #eff8ff; }
.method-put, .method-patch { color: #b54708; background: #fffaeb; }
.method-delete { color: #b42318; background: #fef3f2; }
.request-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.request-name { font-family: inherit; font-size: 13px; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.request-path { color: #98a2b3; font-family: Consolas, monospace; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.add-mark { margin-left: auto; color: #98a2b3; font-size: 12px; }
.scenario-toolbar { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid #eef1f6; flex-wrap: wrap; }
/* 中间栏较窄时名称框会被按钮组挤到 0 宽，这里给最小宽度并允许按钮组换行 */
.scenario-name { flex: 1 1 180px; min-width: 150px; max-width: 310px; }
.scenario-name :deep(.el-input__wrapper) { box-shadow: none; background: #f7f9fc; }
.toolbar-actions { display: flex; gap: 6px; margin-left: auto; flex: none; flex-wrap: wrap; justify-content: flex-end; }
.empty-scenario { min-height: 360px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: #667085; padding: 30px; }
.empty-scenario h3 { color: #273047; margin: 14px 0 6px; }
.empty-scenario p { margin: 4px 0; font-size: 13px; }
.empty-icon { width: 56px; height: 56px; display: grid; place-items: center; border-radius: 18px; background: #eef4ff; color: var(--primary); font-size: 28px; font-weight: 700; }
.step-list { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; }
.step-card { position: relative; border: 1px solid #e5e8ef; border-radius: 11px; padding: 12px 14px; cursor: pointer; background: #fff; transition: border-color .15s, box-shadow .15s; }
.step-card:hover { border-color: #b8c6e6; }
.step-card.active { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(36, 107, 253, .08); }
.step-head { display: flex; align-items: center; gap: 8px; }
.step-no { width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; background: #172033; color: #fff; font-size: 12px; font-weight: 700; }
.step-name { color: #273047; font-weight: 650; font-size: 14px; }
.step-actions { margin-left: auto; display: flex; }
.step-path { margin-top: 7px; color: #667085; font-family: Consolas, monospace; font-size: 12px; word-break: break-all; }
.step-summary { display: flex; gap: 16px; margin-top: 9px; color: #667085; font-size: 12px; }
.capture-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.capture-chip { background: #eff8ff; color: #175cd3; border-radius: 5px; padding: 3px 7px; font-size: 11px; }
.inspector-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 14px; border-bottom: 1px solid #eef1f6; }
.inspector-kicker { color: var(--muted); font-size: 11px; }
.inspector-head h3 { margin: 4px 0 0; font-size: 16px; color: #273047; }
.inspector-section { padding-top: 16px; }
.section-head { margin-bottom: 9px; }
.section-head h4 { margin: 0; font-size: 13px; color: #344054; }
.section-head span { color: #98a2b3; font-size: 11px; }
.input-row { padding: 10px 0; border-bottom: 1px dashed #e8ebf1; }
.input-head { display: flex; align-items: center; gap: 7px; margin-bottom: 7px; }
.input-name { color: #273047; font-weight: 600; font-size: 12px; word-break: break-all; }
.input-location, .optional-dot { color: #98a2b3; background: #f2f4f7; border-radius: 4px; padding: 2px 5px; font-size: 10px; }
.required-dot { color: #b42318; background: #fef3f2; border-radius: 4px; padding: 2px 5px; font-size: 10px; }
.input-controls { display: grid; grid-template-columns: minmax(0, 1fr) 118px; gap: 7px; }
.source-select :deep(.el-select__placeholder) { font-size: 11px; }
.binding-note { margin-top: 5px; color: #175cd3; font-size: 11px; }
.output-list { display: flex; flex-direction: column; gap: 3px; max-height: 300px; overflow-y: auto; }
.output-item { display: flex; align-items: center; gap: 7px; padding: 6px 7px; border-radius: 6px; background: #f8fafc; font-size: 11px; }
.output-path { min-width: 0; font-family: Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.output-type { margin-left: auto; color: #667085; }
.output-captured { color: #067647; }
.empty-mini { color: #98a2b3; font-size: 12px; padding: 12px 2px; }
.connection-card { padding: 12px; border-radius: 9px; background: #f7f9fc; display: flex; flex-direction: column; gap: 5px; color: #667085; font-size: 12px; }
.connection-card b { color: #273047; }
.drawer-section-title { margin: 18px 0 10px; font-weight: 650; color: #344054; }
.drawer-loading { color: #98a2b3; font-size: 13px; padding: 20px 0; }
.category-list { display: flex; flex-direction: column; gap: 4px; max-height: 480px; overflow-y: auto; }
.category-item { width: 100%; margin: 0; padding: 8px; border-radius: 7px; }
.category-item:hover { background: #f7f9fc; }
.category-item span { margin-right: 8px; }
.category-item small { color: #98a2b3; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.drawer-empty { padding-top: 40px; text-align: center; color: #667085; }
.settings-tip { color: #667085; font-size: 13px; line-height: 1.7; }
.settings-list { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; }
.settings-item { display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid #e5e8ef; border-radius: 9px; }
.settings-item:hover { border-color: #b8c6e6; background: #f8faff; }
.settings-item b { color: #273047; }
.settings-item span { color: #7c8497; font-size: 12px; }

.shared-tip { margin: 0 0 14px; color: #667085; font-size: 13px; line-height: 1.7; }
.shared-env { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.shared-env-label { color: #475467; font-size: 13px; }
.shared-env-hint { color: #98a2b3; font-size: 12px; }
.shared-switch { display: flex; gap: 6px; margin-bottom: 10px; }
.shared-switch button {
  padding: 6px 12px;
  border: 1px solid #e5e8ef;
  border-radius: 8px;
  background: #fff;
  color: #475467;
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
}
.shared-switch button.active { border-color: #b8c6e6; background: #eef4ff; color: #175cd3; }
.shared-grid {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr) minmax(0, 1.4fr) minmax(0, 1fr) 58px;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}
.shared-grid-head { color: #98a2b3; font-size: 12px; border-bottom: 1px solid #eef1f6; }
.shared-body { max-height: 320px; overflow-y: auto; }
.shared-row { border-bottom: 1px solid #f4f6fa; }
.shared-row :deep(.el-button) { white-space: nowrap; }
.shared-add { margin-top: 10px; }
@media (max-width: 1280px) {
  .workspace { grid-template-columns: 250px minmax(380px, 1fr); }
  .right-panel { grid-column: 1 / -1; max-height: 420px; }
}


/* 浅色柔和视觉与可读性增强 */
.design-page {
  --primary: #7891d8;
  --primary-soft: #eef3ff;
  --line: #e2e7f2;
  --muted: #758096;
  color: #33405a;
  background:
    radial-gradient(circle at 7% 0%, #edf5ff 0, transparent 34%),
    radial-gradient(circle at 92% 4%, #f4efff 0, transparent 30%),
    linear-gradient(135deg, #f8faff 0%, #fbf9ff 54%, #f6fcfa 100%);
}
.page-head {
  background: linear-gradient(135deg, #fbfdff 0%, #f7f2ff 58%, #f0fbf7 100%);
  border-bottom-color: #dfe5f1;
}
.page-head h1 { font-size: 24px; letter-spacing: .2px; }
.page-head p { font-size: 14px; color: #6f7b91; }
.workflow-strip { background: rgba(255, 255, 255, .68); backdrop-filter: blur(8px); font-size: 14px; }
.flow-tip { color: #647fcb; }
.flow-warning { color: #a96635; background: #fff3e7; }
.left-panel {
  background: linear-gradient(180deg, #f5f9ff 0%, #fff 52%, #fbfcff 100%);
}
.center-panel { background: linear-gradient(180deg, #ffffff 0%, #fcfdff 100%); }
.right-panel {
  background: linear-gradient(180deg, #fffaf6 0%, #ffffff 46%, #faf7ff 100%);
}
.left-panel, .center-panel, .right-panel { border-color: #e1e6f1; box-shadow: 0 8px 24px rgba(104, 126, 170, .07); }
.panel-title { font-size: 15px; color: #35425c; }
.suite-name, .request-name { font-size: 14px; }
.suite-meta, .add-mark { font-size: 12px; }
.request-path { font-size: 12px; color: #8d97aa; }
.suite-item:hover, .suite-item.active { background: #edf3ff; }
.request-item:hover { background: #f7faff; }
.method { font-size: 11px; }
.method-get { color: #43866f; background: #eaf7f1; }
.method-post { color: #5877bf; background: #edf3ff; }
.method-put, .method-patch { color: #a67040; background: #fff4e8; }
.method-delete { color: #b96a72; background: #fff0f2; }
.scenario-toolbar { border-bottom-color: #edf0f6; }
.scenario-name :deep(.el-input__inner) { font-size: 15px; font-weight: 600; color: #34415b; }
.step-card { border-color: #e2e7f1; background: linear-gradient(180deg, #ffffff, #fcfdff); }
.step-card:hover { border-color: #bdcbef; box-shadow: 0 6px 18px rgba(100, 123, 177, .06); }
.step-card.active { border-color: #8da3df; background: #f8faff; box-shadow: 0 0 0 3px rgba(120, 145, 216, .11); }
.step-no { background: #7f96d2; }
.step-name { font-size: 15px; color: #34415b; }
.step-path { font-size: 12.5px; color: #6f7b91; }
.step-summary { font-size: 12.5px; color: #748096; }
.capture-chip { color: #5277aa; background: #eaf5f2; }
.inspector-kicker { font-size: 12px; color: #8a94a8; }
.inspector-head h3 { font-size: 17px; }
.section-head h4 { font-size: 14px; color: #3d4a63; }
.section-head span { font-size: 12px; color: #8a94a8; }
.input-name { font-size: 13px; }
.input-location, .optional-dot, .required-dot { font-size: 11px; }
.binding-note { font-size: 12px; color: #627fc0; }
.output-item { font-size: 12.5px; background: #f7f9ff; }
.output-path { color: #4a5872; }
.empty-mini, .empty-scenario p { font-size: 13px; }
.assertion-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.assertion-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px;
  margin-bottom: 6px;
  border-radius: 9px;
  background: #fbf8ff;
  border: 1px solid #eee9f8;
}
.assertion-type { width: 112px; flex: none; }
.assertion-path { flex: 1; min-width: 90px; }
.assertion-expected { width: 104px; flex: none; }
.assertion-unit { color: #8791a5; font-size: 12px; flex: none; }
.assertion-remove { flex: none; }
.design-page :deep(.el-input__inner),
.design-page :deep(.el-select__selected-item),
.design-page :deep(.el-button) { font-size: 13px; }
.design-page :deep(.el-input__wrapper),
.design-page :deep(.el-select__wrapper) { background: #fbfcff; box-shadow: 0 0 0 1px #e4e8f2 inset; }
.design-page :deep(.el-button--primary) {
  --el-button-bg-color: #7d95d6;
  --el-button-border-color: #7d95d6;
  --el-button-hover-bg-color: #8ea4df;
  --el-button-hover-border-color: #8ea4df;
  --el-button-active-bg-color: #7089cc;
  --el-button-active-border-color: #7089cc;
}


/* 场景删除与接口编辑操作 */
.suite-item {
  padding: 0;
  gap: 2px;
  overflow: hidden;
}
.suite-open {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 7px 9px 10px;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.suite-delete {
  flex: none;
  margin-right: 4px;
  opacity: 0;
  font-size: 12px;
  transition: opacity .15s;
}
.suite-item:hover .suite-delete,
.suite-item.active .suite-delete,
.suite-item:focus-within .suite-delete { opacity: 1; }
.request-item {
  padding: 0;
  gap: 0;
  align-items: stretch;
  overflow: hidden;
}
.request-add {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 6px 9px 8px;
  border: 0;
  background: transparent;
  color: inherit;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}
/* 接口右键菜单 */
.request-menu {
  position: fixed;
  z-index: 3000;
  min-width: 132px;
  margin: 0;
  padding: 6px 0;
  list-style: none;
  background: #fff;
  border: 1px solid #e9ecf3;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(52, 65, 91, .14);
}
.request-menu li {
  padding: 8px 16px;
  font-size: 13px;
  color: #34415b;
  cursor: pointer;
  transition: background .15s, color .15s;
}
.request-menu li:hover { background: #f5f8ff; color: #536ca5; }
.request-menu li.danger { color: #b96a72; }
.request-menu li.danger:hover { background: #fef3f2; color: #b42318; }
.interface-title-left { display: flex; align-items: center; gap: 7px; }
.interface-title-actions { display: flex; align-items: center; gap: 4px; }
.normalize-link { font-size: 12px; }
.form-row { display: flex; gap: 12px; }
.form-row :deep(.el-form-item) { flex: 1; min-width: 0; }
.interface-join-check { margin-top: 2px; }
.interface-dialog-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.footer-hint { color: #98a2b3; font-size: 12px; }
.footer-actions { display: flex; gap: 8px; margin-left: auto; }
.path-format-tip {
  margin-top: 4px;
  padding: 10px 12px;
  border-radius: 8px;
  color: #64748b;
  background: #f5f8ff;
  font-size: 12px;
  line-height: 1.7;
}
.path-format-tip code {
  color: #536ca5;
  background: #eaf0ff;
  border-radius: 4px;
  padding: 2px 5px;
}
.missing-panel {
  margin: 12px 24px 0;
  padding: 12px 16px;
  background: #fff8ed;
  border: 1px solid #f3dcb6;
  border-radius: 10px;
}
.missing-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.missing-title { color: #9a5b1b; font-size: 13px; font-weight: 600; }
.missing-row { display: flex; align-items: center; gap: 9px; padding: 4px 0; font-size: 12px; color: #6b5a44; flex-wrap: wrap; }
.missing-step { background: #fdf0dc; color: #a96635; border-radius: 4px; padding: 2px 7px; }
.missing-iface { color: #6b5a44; }
.missing-var { font-family: Consolas, monospace; color: #b42318; background: #fef3f2; border-radius: 4px; padding: 2px 7px; }
.missing-hint { color: #8a7a64; }
.guess-dot { color: #a96635; background: #fdf0dc; border-radius: 4px; padding: 1px 6px; font-size: 11px; }
.guess-input :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px #f0c98a inset; background: #fffdf7; }
.guess-field { font-family: Consolas, monospace; color: #a96635; background: #fdf0dc; border-radius: 4px; padding: 2px 7px; }
.guess-value { font-family: Consolas, monospace; color: #b42318; }

/* AI 排除清单：信息性提示，用冷色与「缺数据」的暖色区分 */
.excluded-panel {
  margin: 12px 24px 0;
  padding: 12px 16px;
  background: #f5f8ff;
  border: 1px solid #d8e3f5;
  border-radius: 10px;
}
.excluded-panel .missing-title { color: #3a568c; }
.excluded-actions { display: flex; align-items: center; gap: 2px; }
.excluded-list { margin-top: 4px; display: flex; flex-direction: column; gap: 2px; max-height: 190px; overflow-y: auto; }
.excluded-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 4px 0;
  font-size: 12px;
  color: #55617a;
  flex-wrap: wrap;
}
.excluded-name { color: #34405c; }
.excluded-reason { color: #7a869e; }
.stop-on-fail { margin: 0 2px 0 6px; }
.stop-on-fail :deep(.el-checkbox__label) { font-size: 12px; color: #55617a; }
</style>
