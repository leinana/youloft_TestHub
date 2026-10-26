from django.db import models
from apps.projects.models import Project
from apps.users.models import User


class KnowledgeNode(models.Model):
    """需求知识库节点（自引用树，承载 功能域/模块/功能点/规则/页面描述）"""
    KIND_CHOICES = [
        ('domain', '功能域'),
        ('module', '功能模块'),
        ('feature', '功能点'),
        ('rule', '业务规则'),
        ('page', '页面描述'),
    ]
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('confirmed', '已确认'),
        ('deprecated', '已废弃'),
    ]
    RULE_TYPE_CHOICES = [
        ('normal', '正向流程'),
        ('exception', '异常流程'),
        ('field', '字段约束'),
        ('enum', '枚举值'),
        ('dependency', '依赖'),
        ('frequency', '频率限制'),
        ('member', '会员限制'),
        ('permission', '权限'),
        ('operation', '运营配置'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='knowledge_nodes', verbose_name='关联项目')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='children', verbose_name='父节点')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='feature', verbose_name='节点类型')
    name = models.CharField(max_length=200, verbose_name='标题')
    content = models.TextField(blank=True, verbose_name='内容/描述')
    content_hash = models.CharField(max_length=64, blank=True, db_index=True, verbose_name='内容指纹',
                                    help_text='由 content+summary 归一化后取 md5，用于「一致就跳过」')
    source_type = models.CharField(max_length=20, blank=True, verbose_name='来源类型')
    source_url = models.CharField(max_length=500, blank=True, verbose_name='来源链接')
    source_version = models.CharField(max_length=100, blank=True, verbose_name='来源版本')
    collected_at = models.DateTimeField(null=True, blank=True, verbose_name='采集时间')
    summary = models.TextField(blank=True, verbose_name='需求说明（Markdown）',
                               help_text='AI 按需求文档口径生成的功能说明，页面右侧按文档样式渲染')
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES, null=True, blank=True, verbose_name='规则类型')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed', verbose_name='状态')
    is_locked = models.BooleanField(default=False, verbose_name='人工锁定')
    order = models.IntegerField(default=0, verbose_name='排序')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'kb_nodes'
        verbose_name = '知识节点'
        verbose_name_plural = '知识节点'
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class KnowledgeChangeLog(models.Model):
    """知识库变更记录"""
    ACTION_CHOICES = [
        ('create', '新增'),
        ('update', '修改'),
        ('delete', '删除'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='knowledge_change_logs', verbose_name='关联项目')
    target_type = models.CharField(max_length=20, verbose_name='目标类型')
    target_id = models.IntegerField(verbose_name='目标ID')
    target_name = models.CharField(max_length=200, blank=True, verbose_name='目标名称')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name='操作')
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='操作人')
    detail = models.TextField(blank=True, verbose_name='变更说明')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='时间')

    class Meta:
        db_table = 'kb_change_logs'
        verbose_name = '变更记录'
        verbose_name_plural = '变更记录'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.target_name} - {self.get_action_display()}'


class KnowledgeCollection(models.Model):
    """一次采集批次：采集结果先落在这里，供整理、对比、审核、重放"""
    SOURCE_CHOICES = [
        ('modao', '墨刀'),
        ('axure', 'Axure'),
        ('upload', '上传文档'),
    ]
    STATUS_CHOICES = [
        ('collected', '已采集'),
        ('proposed', '已生成提议'),
        ('applied', '已应用'),
        ('discarded', '已丢弃'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='knowledge_collections',
                                verbose_name='关联项目')
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='modao', verbose_name='来源类型')
    source_url = models.CharField(max_length=500, blank=True, verbose_name='来源链接')
    source_version = models.CharField(max_length=100, blank=True, verbose_name='来源版本')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='collected', verbose_name='状态')
    snapshot_dir = models.CharField(max_length=500, blank=True, verbose_name='截图目录（相对 media）')
    raw_path = models.CharField(max_length=500, blank=True, verbose_name='采集快照 JSON（相对 media）')
    page_count = models.IntegerField(default=0, verbose_name='画布数')
    skipped_backend = models.JSONField(default=list, blank=True, verbose_name='跳过的后台画布')
    collected_pages = models.JSONField(default=list, blank=True, verbose_name='画布清单（含归类与内容）')
    note = models.TextField(blank=True, verbose_name='版本备注',
                            help_text='采集时人工补充的说明，供 AI 整理文档与新旧对比时参考')
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='快照过期时间')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'kb_collections'
        verbose_name = '知识采集批次'
        verbose_name_plural = '知识采集批次'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_source_type_display()} · {self.source_version or self.source_url[:40]}'


class KnowledgeProposal(models.Model):
    """一次整理产出的「知识提议」：等人审核，不直接改知识库"""
    STATUS_CHOICES = [
        ('pending', '待审核'),
        ('applied', '已应用'),
        ('discarded', '已丢弃'),
    ]

    collection = models.OneToOneField(KnowledgeCollection, on_delete=models.CASCADE, related_name='proposal',
                                      verbose_name='采集批次')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='knowledge_proposals',
                                verbose_name='关联项目')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    stats = models.JSONField(default=dict, blank=True, verbose_name='统计')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name='应用时间')

    class Meta:
        db_table = 'kb_proposals'
        verbose_name = '知识提议'
        verbose_name_plural = '知识提议'
        ordering = ['-created_at']

    def __str__(self):
        return f'提议 #{self.pk} · {self.get_status_display()}'


class KnowledgeProposalItem(models.Model):
    """提议里的单条改动（一个功能点一条）"""
    CHANGE_CHOICES = [
        ('new', '新增功能点'),
        ('same', '无变化'),
        ('append', '补充内容'),
        ('conflict', '疑似冲突'),
    ]
    DECISION_CHOICES = [
        ('pending', '待处理'),
        ('accept', '采纳新的'),
        ('keep', '保留旧的'),
        ('merged', '合并'),
        ('ignored', '忽略'),
    ]

    proposal = models.ForeignKey(KnowledgeProposal, on_delete=models.CASCADE, related_name='items',
                                 verbose_name='所属提议')
    target_node = models.ForeignKey(KnowledgeNode, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='proposal_items', verbose_name='目标功能点')
    target_name = models.CharField(max_length=200, verbose_name='功能点名称')
    parent_node = models.ForeignKey(KnowledgeNode, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='建议挂载的父节点')
    change_type = models.CharField(max_length=20, choices=CHANGE_CHOICES, verbose_name='变更类型')
    old_content = models.TextField(blank=True, verbose_name='现有内容')
    new_content = models.TextField(blank=True, verbose_name='新采集内容')
    merged_content = models.TextField(blank=True, verbose_name='人工合并后的内容')
    ai_reason = models.TextField(blank=True, verbose_name='AI 差异说明')
    conflicts = models.JSONField(default=list, blank=True, verbose_name='具体矛盾点')
    new_content_hash = models.CharField(max_length=64, blank=True, db_index=True, verbose_name='新内容指纹')
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default='pending', verbose_name='决策')
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='决策人')
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name='决策时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'kb_proposal_items'
        verbose_name = '知识提议明细'
        verbose_name_plural = '知识提议明细'
        ordering = ['change_type', 'id']

    def __str__(self):
        return f'[{self.get_change_type_display()}] {self.target_name}'
