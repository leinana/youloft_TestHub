"""
YApi 客户端 — 从 YApi 拉取接口定义
"""
import httpx
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class YApiClient:
    """YApi API 客户端（只读）"""

    def __init__(self, base_url: str, token: str, project_id: int, uid: int = None):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.uid = uid or 0
        self.project_id = project_id
        self.api_base = f'{self.base_url}/api'

    def _cookies(self) -> dict:
        return {'_yapi_token': self.token, '_yapi_uid': str(self.uid)}

    async def _get(self, path: str, **params) -> dict:
        url = f'{self.api_base}{path}'
        async with httpx.AsyncClient(timeout=30, cookies=self._cookies()) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if data.get('errcode') and data['errcode'] != 0:
                errcode = data['errcode']
                if errcode == 40011:
                    # YApi 登录态失效：给出明确指引
                    raise Exception('YApi Token 已失效（40011 请登录），请到 YApi 同步页点击「更新 Token」重新获取后重试')
                raise Exception(f"YApi Error [{errcode}]: {data.get('errmsg')}")
            return data

    async def get_project_info(self) -> dict:
        return await self._get('/project/get', project_id=self.project_id)

    async def get_cat_menu(self) -> List[dict]:
        """获取完整分类树（含版本名称）"""
        r = await self._get('/interface/getCatMenu', project_id=self.project_id)
        return (r.get('data') or []) if isinstance(r, dict) else []

    async def fetch_all_interfaces(self) -> List[dict]:
        """拉取所有接口，并附带分类名称"""
        cat_map = {}
        try:
            cats = await self.get_cat_menu()
            for c in cats:
                cat_map[c.get('_id', 0)] = c.get('name', '未分类')
        except Exception:
            pass

        all_items = []
        page = 1
        while True:
            r = await self._get('/interface/list', project_id=self.project_id,
                               page=page, limit=100)
            data = r.get('data', {})
            items = data.get('list', []) if isinstance(data, dict) else []
            if not items:
                break
            for item in items:
                cid = item.get('catid', 0)
                item['_cat_name'] = cat_map.get(cid, f'分类{cid}')
            all_items.extend(items)
            # YApi total 是总页数，当前页不足100条说明是最后一页
            if len(items) < 100:
                break
            page += 1
        return all_items

    async def get_interface_detail(self, interface_id: int) -> dict:
        return await self._get('/interface/get', id=interface_id)

    async def fetch_details(self, interfaces: List[dict]) -> List[dict]:
        """Fetch details for the given interface list"""
        detailed = []
        for i, iface in enumerate(interfaces):
            iface_id = iface.get('_id')
            if not iface_id:
                continue
            try:
                detail = await self.get_interface_detail(iface_id)
                merged = {**iface, **detail.get('data', {})}
                detailed.append(merged)
            except Exception as e:
                logger.warning(f'Detail failed for {iface.get("title", iface_id)}: {e}')
                detailed.append(iface)
        return detailed

    async def fetch_all_with_details(self) -> List[dict]:
        """Fetch all interfaces with details"""
        interfaces = await self.fetch_all_interfaces()
        return await self.fetch_details(interfaces)
