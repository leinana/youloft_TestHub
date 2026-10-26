from django.contrib import admin
from .models import KnowledgeNode, KnowledgeChangeLog


@admin.register(KnowledgeNode)
class KnowledgeNodeAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'kind', 'project', 'parent', 'status', 'is_locked', 'order', 'updated_at']
    list_filter = ['kind', 'status', 'is_locked', 'project']
    search_fields = ['name', 'content']
    ordering = ['project', 'order', 'id']


@admin.register(KnowledgeChangeLog)
class KnowledgeChangeLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'target_name', 'target_type', 'action', 'operator', 'created_at']
    list_filter = ['action', 'target_type', 'project']
    search_fields = ['target_name', 'detail']
