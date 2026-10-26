"""把每个模块下面所有内容（功能点 / 子功能 / 规则 / 页面）合并重写成一份模块文档。

用于「目录只到二级」改造后的一次性整理，也可以以后手动补文档。

用法：
    python manage.py rebuild_module_docs --project 1 --dry-run    # 先看会处理哪些模块
    python manage.py rebuild_module_docs --project 1              # 只处理还没文档的模块
    python manage.py rebuild_module_docs --project 1 --force      # 全部重写
    python manage.py rebuild_module_docs --project 1 --only 甜言蜜语
"""
from django.core.management.base import BaseCommand

from apps.knowledge_base.models import KnowledgeNode


class Command(BaseCommand):
    help = '把模块下的全部内容合并重写成模块文档（供「目录只到二级」使用）'

    def add_arguments(self, parser):
        parser.add_argument('--project', type=int, required=True, help='项目 ID')
        parser.add_argument('--only', type=str, default='', help='只处理名字包含该关键词的模块')
        parser.add_argument('--force', action='store_true', help='已有文档的也重写')
        parser.add_argument('--dry-run', action='store_true', help='只打印将要处理什么')

    def handle(self, *args, **options):
        from apps.knowledge_base.extract import generate_summary
        from apps.knowledge_base.extract_views import _collect_subtree_pages

        qs = KnowledgeNode.objects.filter(
            project_id=options['project'], kind='module', status='confirmed'
        )
        if options['only']:
            qs = qs.filter(name__contains=options['only'])
        qs = qs.order_by('order', 'id')

        done = skipped = failed = 0
        for m in qs:
            if (m.summary or '').strip() and not options['force']:
                self.stdout.write(f'跳过（已有文档）：{m.name}')
                skipped += 1
                continue

            pages = _collect_subtree_pages(m)
            if not pages:
                self.stdout.write(f'跳过（下面没内容）：{m.name}')
                skipped += 1
                continue

            if options['dry_run']:
                self.stdout.write(f"[dry-run] {m.name}：将用 {len(pages)} 条内容生成文档")
                continue

            try:
                doc = generate_summary(m, pages)
            except Exception as e:
                self.stderr.write(f"生成失败 {m.name}：{str(e)[:160]}")
                failed += 1
                continue

            if not doc:
                self.stderr.write(f"生成失败（空文档）{m.name}")
                failed += 1
                continue

            m.summary = doc
            m.save(update_fields=['summary'])
            self.stdout.write(self.style.SUCCESS(
                f"已生成 {m.name}（{len(doc)} 字 · 来源 {len(pages)} 条）"
            ))
            done += 1

        self.stdout.write(self.style.SUCCESS(
            f"处理完成：成功 {done} · 跳过 {skipped} · 失败 {failed}"
            + ('（试运行，未写入）' if options['dry_run'] else '')
        ))
