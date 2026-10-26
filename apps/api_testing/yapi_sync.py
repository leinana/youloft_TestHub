"""
YApi 同步服务 — 将 YApi 接口导入到 TestHub
"""
import json
import logging
import re
from typing import List, Dict, Tuple
from urllib.parse import urlsplit
from django.utils import timezone
from asgiref.sync import sync_to_async

from .models import YApiConnection, YApiSyncLog, ApiRequest, ApiCollection, ApiProject
from .yapi_client import YApiClient

logger = logging.getLogger(__name__)


def _normalize_yapi_path(path: str) -> str:
    """把 YApi 路径统一成单个前导斜杠的相对路径。

    - 绝对 URL 只保留 path，丢弃 host/query
    - 兼容 YApi 自动追加的 _<13 位时间戳>
    - 兼容 //////user/getStatus 这类异常多斜杠路径
    """
    value = str(path or '').strip()
    if not value:
        return '/'
    if value.startswith('{{base_url}}'):
        value = value[len('{{base_url}}'):]
    if value.startswith(('http://', 'https://')):
        value = urlsplit(value).path
    value = re.sub(r'_\d{13}$', '', value)
    value = re.sub(r'/{2,}', '/', value)
    if not value.startswith('/'):
        value = '/' + value
    return value or '/'


def _extract_url(yapi_data: dict) -> str:
    """YApi 接口统一导入为 {{base_url}}/相对路径。

    域名由执行环境中的 base_url 决定，避免测试、预发和生产地址散落在接口定义里。
    """
    return '{{base_url}}' + _normalize_yapi_path(yapi_data.get('path', ''))


def _field_value(item: dict, *keys) -> str:
    """按顺序取第一个非空字段值"""
    for k in keys:
        v = item.get(k)
        if v not in (None, ''):
            return str(v)
    return ''


def _is_required(item: dict) -> bool:
    """兼容 YApi 的 required 多种取值（bool / '1' / '0' / 'true'）"""
    v = item.get('required')
    if v is None:
        return False
    if isinstance(v, str):
        return v.lower() in ('1', 'true', 'yes', 'y')
    return bool(v)


def _extract_params(yapi_data: dict) -> list:
    """从 YApi 提取请求参数列表（路径参数 + query 参数），不遗漏任何参数"""
    params = []
    # 路径参数（YApi 路径参数必填）
    for p in yapi_data.get('req_params', []) or []:
        params.append({
            'key': p.get('name', ''),
            'value': _field_value(p, 'example', 'value', 'desc', 'name'),
            'enabled': True,
            'description': p.get('desc', ''),
            'required': True,
        })
    # query 参数
    for q in yapi_data.get('req_query', []) or []:
        params.append({
            'key': q.get('name', ''),
            'value': _field_value(q, 'value', 'example', 'default'),
            'enabled': True,
            'description': q.get('desc', ''),
            'required': _is_required(q),
        })
    return params


def _extract_headers(yapi_data: dict) -> list:
    """从 YApi 提取请求头（保留全部 header，不遗漏）"""
    headers = []
    for h in yapi_data.get('req_headers', []) or []:
        headers.append({
            'key': h.get('name', ''),
            'value': _field_value(h, 'value', 'example'),
            'enabled': True,
            'description': h.get('desc', ''),
            'required': _is_required(h),
        })
    # 添加默认 Content-Type（仅当未显式声明时）
    req_body_type = yapi_data.get('req_body_type', 'none')
    default_ct = {
        'json': 'application/json',
        'form': 'application/x-www-form-urlencoded',
        'file': 'multipart/form-data',
    }.get(req_body_type)
    if default_ct and not any(
        str(h.get('key', '')).lower() == 'content-type' for h in headers
    ):
        headers.append({
            'key': 'Content-Type', 'value': default_ct,
            'enabled': True, 'description': '请求体类型', 'required': False,
        })
    return headers


def _extract_body(yapi_data: dict) -> dict:
    """从 YApi 提取请求体（覆盖 json / form / file / raw 全部类型，表单字段不遗漏）"""
    body_type = yapi_data.get('req_body_type', 'none')
    body_other = yapi_data.get('req_body_other', '')

    if body_type == 'json' and body_other:
        try:
            data = json.loads(body_other)
            if isinstance(data, dict) and ('properties' in data or 'items' in data):
                # JSON Schema 格式 → 生成示例
                return {'type': 'json', 'data': _json_schema_to_example(data)}
            return {'type': 'json', 'data': data}
        except Exception:
            return {'type': 'raw', 'data': body_other}
    elif body_type == 'form':
        # YApi 的 form = x-www-form-urlencoded
        return {'type': 'x-www-form-urlencoded', 'data': _extract_form_fields(yapi_data)}
    elif body_type == 'file':
        # YApi 的 file = multipart/form-data（含文件字段）
        return {'type': 'form-data', 'data': _extract_form_fields(yapi_data)}
    elif body_type == 'raw' and body_other:
        return {'type': 'raw', 'data': body_other}
    return {'type': 'none', 'data': None}


def _extract_form_fields(yapi_data: dict) -> list:
    """从 req_body_form 提取表单字段，保留类型/必填/说明"""
    fields = []
    for f in yapi_data.get('req_body_form', []) or []:
        fields.append({
            'key': f.get('name', ''),
            'value': _field_value(f, 'example', 'value', 'default'),
            'enabled': True,
            'description': f.get('desc', ''),
            'required': _is_required(f),
            'type': f.get('type', 'text'),  # text | file
        })
    return fields


def _extract_response(yapi_data: dict) -> tuple:
    """从 YApi 提取响应体定义 → (res_body, res_body_type, res_body_is_json_schema)"""
    body_type = yapi_data.get('res_body_type', '')
    raw = yapi_data.get('res_body', '')
    is_schema = bool(yapi_data.get('res_body_is_json_schema'))

    if body_type != 'json' or not raw:
        return (raw or None), (body_type or 'none'), is_schema

    try:
        data = json.loads(raw)
        return data, 'json', is_schema
    except Exception:
        return raw, 'raw', False


def _json_schema_to_example(schema) -> object:
    """JSON Schema → 示例 JSON（保留类型与结构，数组不丢元素结构）"""
    if isinstance(schema, list):
        return [_json_schema_to_example(x) for x in schema]
    if not isinstance(schema, dict):
        return schema

    # 优先使用显式示例 / 默认值 / enum
    for key in ('example', 'default'):
        if key in schema and schema[key] is not None:
            return schema[key]
    if schema.get('enum'):
        return schema['enum'][0]

    ptype = schema.get('type')

    if ptype == 'object' or 'properties' in schema:
        example = {}
        for key, prop in (schema.get('properties') or {}).items():
            example[key] = _json_schema_to_example(prop)
        return example
    if ptype == 'array':
        items = schema.get('items')
        if items:
            item_example = _json_schema_to_example(items)
            return [item_example] if item_example is not None else []
        return []
    if ptype == 'integer':
        return schema.get('example', 0)
    if ptype == 'number':
        return schema.get('example', 0)
    if ptype == 'boolean':
        return False
    if ptype == 'null':
        return None
    # string 及其他类型
    return schema.get('description', '')


def _yapi_method_to_http(yapi_method: str) -> str:
    m = (yapi_method or 'GET').upper()
    return m if m in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS') else 'POST'


class YApiSyncService:

    def __init__(self, connection: YApiConnection):
        self.conn = connection
        self.client = YApiClient(
            base_url=connection.yapi_url,
            token=connection.yapi_token,
            project_id=connection.yapi_project_id,
            uid=connection.yapi_uid,
        )

    async def sync(self, cat_ids: list = None, path_prefixes: list = None) -> dict:
        """执行同步，可按分类ID或路径前缀筛选"""
        yapi_interfaces = await self.client.fetch_all_interfaces()

        if cat_ids:
            cat_set = set(cat_ids)
            yapi_interfaces = [i for i in yapi_interfaces if i.get('catid') in cat_set]
        if path_prefixes:
            yapi_interfaces = [i for i in yapi_interfaces
                              if any(i.get('path', '').startswith(p) for p in path_prefixes)]

        # fetch details only for the filtered interfaces, avoid pulling all
        yapi_interfaces = await self.client.fetch_details(yapi_interfaces)

        result = await sync_to_async(self._do_sync)(yapi_interfaces)
        return result

    def _do_sync(self, yapi_interfaces: List[dict]) -> dict:
        log_entry = YApiSyncLog.objects.create(
            connection=self.conn, status='running',
            total_interfaces=len(yapi_interfaces),
        )

        try:
            cat_map = self._ensure_collections_sync(yapi_interfaces)

            new_count = 0
            updated_count = 0
            skipped_count = 0
            detail_list = []

            for yd in yapi_interfaces:
                try:
                    r = self._sync_one_interface(yd, cat_map)
                    if r == 'new': new_count += 1
                    elif r == 'updated': updated_count += 1
                    else: skipped_count += 1
                    detail_list.append({
                        'title': yd.get('title', ''),
                        'path': yd.get('path', ''),
                        'method': yd.get('method', 'GET'),
                        'result': r,
                    })
                except Exception as e:
                    logger.error(f'同步接口失败: {yd.get("title")} - {e}')
                    skipped_count += 1

            log_entry.new_count = new_count
            log_entry.updated_count = updated_count
            log_entry.skipped_count = skipped_count
            log_entry.status = 'success'
            log_entry.detail = {'interfaces': detail_list}

        except Exception as e:
            log_entry.status = 'failed'
            log_entry.error_message = str(e)[:500]
            logger.error(f'YApi 同步失败: {e}')

        log_entry.save()
        self.conn.last_synced_at = timezone.now()
        self.conn.save(update_fields=['last_synced_at'])

        return {
            'status': log_entry.status,
            'total': log_entry.total_interfaces,
            'new': log_entry.new_count,
            'updated': log_entry.updated_count,
            'skipped': log_entry.skipped_count,
            'error': log_entry.error_message,
        }

    def _ensure_collections_sync(self, yapi_interfaces: List[dict]) -> dict:
        """确保分类集合存在（同步版本）"""
        cat_names = set()
        for yd in yapi_interfaces:
            cat = yd.get('_cat_name', '未分类') or '未分类'
            cat_names.add(cat)

        api_project = self.conn.project
        cat_map = {}
        for cat_name in cat_names:
            collection, _ = ApiCollection.objects.get_or_create(
                name=cat_name,
                project=api_project,
                defaults={'description': f'从 YApi 自动导入 — {cat_name}'},
            )
            cat_map[cat_name] = collection
        return cat_map

    def _sync_one_interface(self, yd: dict, cat_map: dict) -> str:
        """同步单个接口: 匹配已有 → 更新或创建"""
        raw_path = yd.get('path', '')
        # 异常路径处理：去掉 YApi 自动追加的 _<时间戳> 后缀
        path = _normalize_yapi_path(raw_path)
        method = _yapi_method_to_http(yd.get('method', 'GET'))
        cat_name = yd.get('_cat_name', '未分类') or '未分类'
        collection = cat_map.get(cat_name)

        # 查找已存在的同 path+method 接口（兼容裸 path / 完整 URL / {{base_url}} 前缀，避免重复创建）
        full_url = _extract_url(yd)
        # 同时用原始路径匹配，便于把历史同步的异常路径记录就地更新（如去掉 _时间戳 后缀）
        candidate_urls = {path, full_url, raw_path}
        for u in list(candidate_urls):
            if u.startswith(('http://', 'https://', '//')):
                continue
            candidate_urls.add('{{base_url}}' + u if u.startswith('/') else '{{base_url}}/' + u)
        candidate_urls.discard('')
        existing = ApiRequest.objects.filter(
            url__in=candidate_urls,
            method=method,
            collection__project=self.conn.project,
        ).first()

        res_body, res_body_type, res_body_is_json_schema = _extract_response(yd)

        defaults = {
            'name': yd.get('title', path),
            'description': yd.get('desc', '') or yd.get('markdown', '') or '',
            'url': _extract_url(yd),
            'method': method,
            'params': _extract_params(yd),
            'headers': _extract_headers(yd),
            'body': _extract_body(yd),
            'res_body': res_body,
            'res_body_type': res_body_type,
            'res_body_is_json_schema': res_body_is_json_schema,
            'request_type': 'HTTP',
            'collection': collection,
        }

        if existing:
            for key, val in defaults.items():
                if key != 'name':  # 名称不改，保留用户修改
                    setattr(existing, key, val)
            existing.save()
            return 'updated'
        else:
            ApiRequest.objects.create(**defaults, created_by=self.conn.created_by)
            return 'new'
