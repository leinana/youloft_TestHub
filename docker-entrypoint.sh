#!/bin/bash
# ================================
# TestHub Docker 启动脚本
# ================================

set -e

echo "========================================"
echo "  TestHub Docker Entrypoint"
echo "========================================"

# 等待 MySQL 就绪
echo "[1/4] Waiting for MySQL..."
while ! python -c "
import pymysql
pymysql.connect(host='${DB_HOST:-mysql}', port=int('${DB_PORT:-3306}'), user='${DB_USER:-root}', password='${DB_PASSWORD:-testhub123}', db='${DB_NAME:-testhub}')
" 2>/dev/null; do
    echo "  MySQL not ready yet, retrying in 3s..."
    sleep 3
done
echo "  MySQL is ready!"

# 等待 Redis 就绪
echo "[2/4] Waiting for Redis..."
while ! python -c "
import redis
r = redis.from_url('${REDIS_URL:-redis://redis:6379/0}')
r.ping()
" 2>/dev/null; do
    echo "  Redis not ready yet, retrying in 2s..."
    sleep 2
done
echo "  Redis is ready!"

# 运行数据库迁移
echo "[3/4] Running database migrations..."
python manage.py migrate --noinput

# 创建超级用户（如果不存在）
echo "[4/4] Checking superuser..."
python manage.py shell -c "
from apps.users.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@testhub.local', 'admin123')
    print('  Superuser created: admin / admin123')
else:
    print('  Superuser already exists')
"

echo "========================================"
echo "  Starting Django server..."
echo "========================================"

exec "$@"
