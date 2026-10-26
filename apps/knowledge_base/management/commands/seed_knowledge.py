"""从 ProcessOn 思维导图(.posm)导入知识库种子数据"""
import json
import zipfile
import tempfile
import os
import sys
import io

from django.core.management.base import BaseCommand
from apps.projects.models import Project
from apps.knowledge_base.models import KnowledgeNode

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_posm_tree(posm_path):
    """解压 .posm 并解析出标题树"""
    with zipfile.ZipFile(posm_path, 'r') as z:
        names = z.namelist()
        pos_name = next((n for n in names if n.endswith('.pos')), None)
        if not pos_name:
            raise ValueError('压缩包中未找到 .pos 文件')
        data = json.loads(z.read(pos_name).decode('utf-8'))
    elements = data['diagram']['elements']
    tree = []
    for n in elements.get('children', []):
        tree.append({'title': n.get('title', ''), 'children': n.get('children', [])})
    return tree


def kind_for_depth(depth, has_children):
    if depth <= 0:
        return 'domain'
    if depth == 1:
        return 'module'
    if depth <= 3:
        # 第2、3层通常是功能点/功能分组
        return 'feature'
    # 第4层及更深：叶子视为规则，有子节点视为功能点
    return 'feature' if has_children else 'rule'


class Command(BaseCommand):
    help = '从 .posm 思维导图导入知识库种子数据'

    def add_arguments(self, parser):
        parser.add_argument('posm_path', type=str, help='.posm 文件路径')
        parser.add_argument('--project-id', type=int, required=True, help='项目ID')
        parser.add_argument('--replace', action='store_true', help='先清空该项目的知识节点再导入')

    def handle(self, *args, **options):
        posm_path = options['posm_path']
        project_id = options['project_id']
        project = Project.objects.filter(id=project_id).first()
        if not project:
            self.stderr.write(f'项目不存在: {project_id}')
            return

        raw_tree = load_posm_tree(posm_path)

        if options['replace']:
            deleted, _ = KnowledgeNode.objects.filter(project_id=project_id).delete()
            self.stdout.write(f'已清空旧节点 {deleted} 个')

        created = 0

        def recurse(nodes, parent, depth):
            nonlocal created
            for n in nodes:
                title = (n.get('title') or '').strip()
                if not title or title in ('自由主题',):
                    if n.get('children'):
                        recurse(n['children'], parent, depth)
                    continue
                children = n.get('children') or []
                has_children = len(children) > 0
                kind = kind_for_depth(depth, has_children)
                node = KnowledgeNode.objects.create(
                    project=project,
                    parent=parent,
                    kind=kind,
                    name=title[:200],
                    content='',
                    status='confirmed',
                    order=0,
                )
                created += 1
                if children:
                    recurse(children, node, depth + 1)

        recurse(raw_tree, None, 0)
        self.stdout.write(self.style.SUCCESS(f'导入完成，共创建节点 {created} 个'))
