"""清理过期的采集快照（画布截图 + 原图）。

只删文件，保留采集批次记录 —— 审计还需要知道「采集过什么、什么时候采的」。
默认保留 15 天。

用法：
    python manage.py cleanup_knowledge_snapshots            # 清理 15 天前的
    python manage.py cleanup_knowledge_snapshots --days 30  # 自定义天数
    python manage.py cleanup_knowledge_snapshots --dry-run  # 只看会删什么
"""
from django.core.management.base import BaseCommand

from apps.knowledge_base.storage import SNAPSHOT_TTL_DAYS, cleanup_expired_snapshots


class Command(BaseCommand):
    help = '清理过期（默认 15 天）的采集快照文件，保留采集批次记录'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=SNAPSHOT_TTL_DAYS, help='保留天数，默认 15')
        parser.add_argument('--dry-run', action='store_true', help='只打印将要删除的内容')

    def handle(self, *args, **options):
        days = options['days']
        dry = options['dry_run']
        result = cleanup_expired_snapshots(days=days, dry_run=dry)
        tail = '（试运行，未实际删除）' if dry else '（已删除）'
        self.stdout.write(self.style.SUCCESS(
            f"清理完成：{result['dirs']} 个批次目录 / {result['files']} 个文件{tail}"
        ))
