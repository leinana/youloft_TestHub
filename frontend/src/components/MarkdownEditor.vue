<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="1080px"
    top="4vh"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <div class="mde-wrap">
      <div class="mde-pane">
        <div class="mde-pane-head">Markdown 源码</div>
        <textarea
          v-model="draft"
          class="mde-src"
          spellcheck="false"
          placeholder="在这里编辑需求文档（支持 Markdown：## 标题、- 列表、| 表格 |）"
        />
      </div>
      <div class="mde-pane">
        <div class="mde-pane-head">实时预览</div>
        <div class="mde-preview kb-md" v-html="html"></div>
      </div>
    </div>
    <template #footer>
      <span class="mde-tip">提示：表格要带分隔行（| --- |）才会渲染成表格</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '编辑需求文档' },
  content: { type: String, default: '' },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'save'])

const draft = ref('')

watch(
  () => props.modelValue,
  (open) => { if (open) draft.value = props.content || '' },
)

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const html = computed(() => {
  try {
    return marked(draft.value || '')
      .replace(/<table>/g, '<div class="kb-table-wrap"><table>')
      .replace(/<\/table>/g, '</table></div>')
  } catch (e) {
    return ''
  }
})

const onSave = () => emit('save', draft.value)
</script>

<style scoped>
.mde-wrap { display: flex; gap: 12px; height: 62vh; }
.mde-pane { flex: 1; min-width: 0; display: flex; flex-direction: column; border: 1px solid #e6e8eb; border-radius: 8px; overflow: hidden; }
.mde-pane-head { padding: 7px 12px; background: #f7f8fa; border-bottom: 1px solid #eef0f2; font-size: 12px; color: #646a73; }
.mde-src {
  flex: 1; width: 100%; border: none; outline: none; resize: none;
  padding: 14px 16px; font-size: 13px; line-height: 1.8;
  font-family: ui-monospace, Menlo, Consolas, monospace; color: #1f2329;
}
.mde-preview { flex: 1; overflow-y: auto; padding: 14px 20px; }
.mde-tip { float: left; font-size: 12px; color: #9aa0a6; line-height: 32px; }
</style>
