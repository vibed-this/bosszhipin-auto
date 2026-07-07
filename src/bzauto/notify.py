"""通知系统 — napcat OneBot v11 HTTP API + 合并通知。"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from bzauto.config import get_config

log = logging.getLogger("boss.notify")


def format_task_lines(task_name: str, result: dict[str, Any] | list) -> list[str]:
    """将任务结果格式化为通知行列表。scheduler 和 UI 共用。"""
    if task_name == "采集":
        return [f"采集 {result.get('scraped', 0)} 个"]

    if task_name == "投递":
        if result.get("skipped"):
            return [f"跳过: {result['skipped']}"]
        success = result.get("success", 0)
        failed = result.get("failed", 0)
        return [f"投递 {success + failed} 个 (成功 {success}, 失败 {failed})"]

    if task_name in ("扫描", "聊天爬取"):
        items = result if isinstance(result, dict) else {}
        lines = []
        new_conv = items.get("new", 0)
        if new_conv:
            lines.append(f"新对话 {new_conv} 条")
        deleted = items.get("deleted", 0)
        if deleted:
            lines.append(f"删拒 {deleted} 条")
        updated = items.get("updated", 0)
        if updated:
            lines.append(f"更新 {updated} 条")
        for r in items.get("rejections", [])[:5]:
            lines.append(f"  {r}")
        unread = items.get("unread", [])
        if unread:
            lines.append(f"未读 {len(unread)} 条")
        return lines or ["已完成"]

    if task_name == "删拒":
        n = result.get("deleted", 0) if isinstance(result, dict) else len(result) if isinstance(result, list) else 0
        return [f"删除 {n} 条"]

    return [f"已完成"]


class Notifier(Protocol):
    async def send(self, title: str, body: str) -> None: ...


class NullNotifier:
    async def send(self, title: str, body: str) -> None:
        pass


class NapCatNotifier:
    """基于 OneBot v11 HTTP API 的 napcat 通知。"""

    def __init__(self, base_url: str, msg_type: str, target_id: int, token: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        if msg_type == "group":
            self._url = f"{self._base_url}/send_group_msg"
            self._id_key = "group_id"
        else:
            self._url = f"{self._base_url}/send_private_msg"
            self._id_key = "user_id"
        self._target_id = target_id
        self._token = token
        self._client = httpx.AsyncClient(timeout=10.0)

    async def send(self, title: str, body: str) -> None:
        await self._send_message(f"{title}\n{body}")

    async def send_raw(self, message: str) -> None:
        await self._send_message(message)

    async def _send_message(self, message: str) -> None:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        payload = {self._id_key: self._target_id, "message": message}
        resp = await self._client.post(self._url, json=payload, headers=headers)
        resp.raise_for_status()
        log.info("通知已发送: %s", self._url)

    async def close(self) -> None:
        await self._client.aclose()


def get_notifier() -> Notifier:
    cfg = get_config().notification
    if not cfg.enabled:
        return NullNotifier()
    nc = cfg.napcat
    return NapCatNotifier(nc.base_url, nc.msg_type, nc.target_id, nc.token)


class NotificationAggregator:
    """合并多条通知为一条消息。"""

    def __init__(self, notifier: Notifier, title: str) -> None:
        self._notifier = notifier
        self._title = title
        self._sections: list[str] = []

    def add_section(self, account_name: str, lines: list[str]) -> None:
        self._sections.append(f"【{account_name}】\n" + "\n".join(lines))

    async def flush(self) -> None:
        if not self._sections:
            return
        body = "\n\n".join(self._sections)
        await self._notifier.send(self._title, body)
        self._sections.clear()
