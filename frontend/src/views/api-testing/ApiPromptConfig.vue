<template>
  <div class="api-prompt-config">
    <div class="page-header">
      <div>
        <h2>接口测试提示词配置</h2>
        <p>配置 AI 生成接口测试用例的提示词，支持 [[变量]] 占位符；未配置时使用内置默认提示词</p>
      </div>
      <div class="header-actions">
        <el-button @click="restoreDefault" :loading="restoring">恢复默认</el-button>
        <el-button type="primary" @click="openCreate">新建配置</el-button>
      </div>
    </div>

    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="configs.length === 0" class="empty">
      <p>暂无提示词配置，当前使用内置默认提示词。</p>
      <el-button type="primary" @click="openCreate">新建配置</el-button>
    </div>

    <div v-else class="config-list">
      <div v-for="c in configs" :key="c.id" class="config-card">
        <div class="config-head">
          <div class="config-title">
            <span class="type-badge">{{ c.prompt_type_display }}</span>
            <span class="name">{{ c.name }}</span>
            <el-tag :type="c.is_active ? 'success' : 'info'" size="small">{{ c.is_active ? '启用中' : '已停用' }}</el-tag>
          </div>
          <div class="config-actions">
            <el-button size="small" @click="openEdit(c)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeConfig(c)">删除</el-button>
          </div>
        </div>
        <pre class="content-preview">{{ c.content }}</pre>
        <div class="config-meta">更新于 {{ c.updated_at }} · 创建人 {{ c.created_by_name || '-' }}</div>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑提示词' : '新建提示词'" width="720px" top="6vh">
      <el-form :model="form" label-width="90px">
        <el-form-item label="配置名称" required>
          <el-input v-model="form.name" placeholder="如：DeepSeek 用例生成" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.prompt_type" style="width:100%" :disabled="!!form.id">
            <el-option label="用例生成提示词" value="api_testcase_writer" />
            <el-option label="接口测试执行提示词" value="api_test_execution" />
          </el-select>
        </el-form-item>
        <el-form-item label="提示词内容" required>
          <el-input v-model="form.content" type="textarea" :rows="18" class="prompt-area" />
          <div class="var-hint">可用占位符：{{ varHint }}</div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
          <span class="active-tip">同类型同时只有一个生效</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/utils/api'

const configs = ref([])
const loading = ref(false)
const saving = ref(false)
const restoring = ref(false)
const dialogVisible = ref(false)
const varHint = computed(() => form.prompt_type === 'api_test_execution'
  ? '[[method]] [[url]] [[name]] [[execution_summary]]'
  : '[[method]] [[url]] [[name]] [[param_info]] [[response_info]] [[clarification]]')

const form = reactive({ id: null, name: '', prompt_type: 'api_testcase_writer', content: '', is_active: true })

const load = async () => {
  loading.value = true
  try {
    const r = await api.get('/api-testing/prompt-configs/')
    configs.value = r.data.configs || []
  } catch (_) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const resetForm = () => {
  form.id = null
  form.name = ''
  form.prompt_type = 'api_testcase_writer'
  form.content = ''
  form.is_active = true
}

const openCreate = () => { resetForm(); dialogVisible.value = true }
const openEdit = (c) => {
  form.id = c.id
  form.name = c.name
  form.prompt_type = c.prompt_type
  form.content = c.content
  form.is_active = !!c.is_active
  dialogVisible.value = true
}

const save = async () => {
  if (!form.name.trim() || !form.content.trim()) { ElMessage.warning('请填写名称和内容'); return }
  saving.value = true
  try {
    const payload = { name: form.name.trim(), prompt_type: form.prompt_type, content: form.content, is_active: form.is_active }
    if (form.id) {
      await api.put(`/api-testing/prompt-configs/${form.id}/`, payload)
      ElMessage.success('已保存')
    } else {
      await api.post('/api-testing/prompt-configs/', payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message)) }
  finally { saving.value = false }
}

const removeConfig = async (c) => {
  try {
    await ElMessageBox.confirm(`删除提示词「${c.name}」？`, '确认', { type: 'warning' })
    await api.delete(`/api-testing/prompt-configs/${c.id}/delete/`)
    ElMessage.success('已删除')
    await load()
  } catch (_) {}
}

const restoreDefault = async () => {
  try {
    await ElMessageBox.confirm('将当前类型提示词恢复为内置默认内容？', '恢复默认', { type: 'warning' })
  } catch (_) { return }
  restoring.value = true
  try {
    const types = [
      { type: 'api_testcase_writer', label: '用例生成提示词' },
      { type: 'api_test_execution', label: '接口测试执行提示词' },
    ]
    for (const t of types) {
      const r = await api.get('/api-testing/prompt-configs/default/', { params: { prompt_type: t.type } })
      const existing = configs.value.find(c => c.prompt_type === t.type)
      if (existing) {
        await api.put(`/api-testing/prompt-configs/${existing.id}/`, { content: r.data.content, is_active: true })
      } else {
        await api.post('/api-testing/prompt-configs/', {
          name: '默认' + t.label, prompt_type: t.type, content: r.data.content, is_active: true,
        })
      }
    }
    ElMessage.success('已恢复默认')
    await load()
  } catch (e) { ElMessage.error('恢复失败: ' + (e.response?.data?.error || e.message)) }
  finally { restoring.value = false }
}

onMounted(load)
</script>

<style scoped>
.api-prompt-config { padding: 24px; max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { margin: 0; }
.page-header p { color: #909399; margin-top: 6px; font-size: 13px; }
.header-actions { display: flex; gap: 8px; }
.empty { text-align: center; color: #909399; padding: 60px 0; }
.config-list { display: flex; flex-direction: column; gap: 14px; }
.config-card { border: 1px solid #e8eaed; border-radius: 10px; padding: 14px 16px; background: #fff; }
.config-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.config-title { display: flex; align-items: center; gap: 8px; }
.type-badge { font-size: 12px; background: #e8f0fe; color: #1967d2; padding: 3px 10px; border-radius: 999px; font-weight: 600; }
.name { font-weight: 600; font-size: 15px; }
.content-preview { margin: 0; white-space: pre-wrap; word-break: break-all; background: #f8f9fa; border: 1px solid #eef0f2; border-radius: 8px; padding: 10px 12px; font-size: 12px; color: #3c4043; max-height: 200px; overflow: auto; }
.config-meta { margin-top: 8px; font-size: 12px; color: #9aa0a6; }
.prompt-area :deep(textarea) { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 13px; line-height: 1.6; }
.var-hint { font-size: 12px; color: #909399; margin-top: 4px; }
.active-tip { font-size: 12px; color: #909399; margin-left: 8px; }
</style>
