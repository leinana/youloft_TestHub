"""知识库相关的 Celery 定时任务"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)

# 采集快照保留天数
SNAPSHOT_TTL_DAYS = 15


@shared_task(name='knowledge_base.cleanup_snapshots')
def cleanup_snapshots(days=SNAPSHOT_TTL_DAYS):
    """清理过期的采集快照（画布截图 / 原图）"""
    from .storage import cleanup_expired_snapshots
    try:
        result = cleanup_expired_snapshots(days=days)
        logger.info('[knowledge] 采集快照清理完成: %s', result)
        return result
    except Exception as e:
        logger.warning('[knowledge] 采集快照清理失败: %s', str(e)[:200])
        return {'error': str(e)[:200]}
