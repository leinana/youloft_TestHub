"""独立的浏览器采集 CLI：在子进程中运行，避免 Playwright 与长驻 Django 进程互相影响。

用法：
    python -m apps.knowledge_base.collector_cli <payload_json> <out_json_path>

为什么必须隔离子进程：
    Playwright 的同步 API 在长时间运行的 Django 进程里会卡死
    （报 `PlaywrightContextManager object has no attribute _playwright`），
    放到独立进程里每次都是干净环境，服务本身也不会被拖垮。
"""
import json
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from apps.knowledge_base.collector import collect_modao, collect_axure


def main():
    if len(sys.argv) < 3:
        sys.stderr.write('usage: collector_cli <payload_json> <out_json_path>\n')
        return 2

    payload = json.loads(sys.argv[1])
    out_path = sys.argv[2]

    source_type = payload.get('source_type') or 'axure'
    max_pages = payload.get('max_pages') or None
    run_id = payload.get('run_id') or None

    try:
        if source_type == 'modao':
            data = collect_modao(
                payload.get('url'),
                page_filter=payload.get('page_filter') or None,
                cookie=payload.get('cookie') or None,
                email=payload.get('email') or None,
                password=payload.get('password') or None,
                max_pages=max_pages,
                run_id=run_id,
            )
        else:
            data = collect_axure(
                payload.get('url'),
                page_filter=payload.get('page_filter') or None,
                max_pages=max_pages,
                run_id=run_id,
            )
        result = {'ok': True, 'data': data}
    except Exception as e:
        traceback.print_exc()
        result = {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:600]}'}

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
