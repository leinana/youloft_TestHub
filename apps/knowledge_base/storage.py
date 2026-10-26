"""采集快照的存储与过期清理。

采集到的画布截图/原图只用于「识别」和「审核阶段对照」，
审核完就没用了，所以默认保留 15 天。
"""
import os
import shutil
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

SNAPSHOT_ROOT = 'knowledge_collect'
SNAPSHOT_TTL_DAYS = 15


def cleanup_expired_snapshots(days=SNAPSHOT_TTL_DAYS, dry_run=False):
    """删除过期的采集快照目录。只删文件，保留采集批次记录。

    返回 {'dirs': n, 'files': m, 'dry_run': bool}
    """
    from .models import KnowledgeCollection

    cutoff = timezone.now() - timedelta(days=days)
    base = os.path.abspath(os.path.join(settings.MEDIA_ROOT, SNAPSHOT_ROOT))

    dirs = files = 0
    qs = (KnowledgeCollection.objects
          .filter(created_at__lt=cutoff)
          .exclude(snapshot_dir='')
          .order_by('id'))

    for col in qs:
        rel = (col.snapshot_dir or '').strip().strip('/')
        if not rel.startswith(SNAPSHOT_ROOT + '/'):
            continue
        target = os.path.abspath(os.path.join(settings.MEDIA_ROOT, rel))
        # 安全检查：只允许删 media/knowledge_collect 下面的目录
        if not (target == base or target.startswith(base + os.sep)):
            continue
        if not os.path.isdir(target):
            continue

        n = sum(len(fs) for _, _, fs in os.walk(target))
        dirs += 1
        files += n
        if not dry_run:
            shutil.rmtree(target, ignore_errors=True)

    return {'dirs': dirs, 'files': files, 'dry_run': dry_run}
