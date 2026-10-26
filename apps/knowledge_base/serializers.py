from rest_framework import serializers
from .models import KnowledgeNode, KnowledgeChangeLog


class KnowledgeNodeSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)
    children = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeNode
        fields = [
            'id', 'project', 'parent', 'kind', 'kind_display', 'name', 'content', 'summary',
            'rule_type', 'rule_type_display', 'status', 'is_locked', 'order',
            'children', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_children(self, obj):
        children = obj.children.all().order_by('order', 'id')
        return KnowledgeNodeSerializer(children, many=True, context=self.context).data


class KnowledgeNodeFlatSerializer(serializers.ModelSerializer):
    """不含 children 的扁平序列化器，用于列表/创建/更新返回"""
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)

    class Meta:
        model = KnowledgeNode
        fields = [
            'id', 'project', 'parent', 'kind', 'kind_display', 'name', 'content', 'summary',
            'rule_type', 'rule_type_display', 'status', 'is_locked', 'order',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class KnowledgeChangeLogSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = KnowledgeChangeLog
        fields = ['id', 'project', 'target_type', 'target_id', 'target_name', 'action',
                  'action_display', 'operator', 'operator_name', 'detail', 'created_at']
