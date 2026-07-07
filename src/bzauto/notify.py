"""通知系统 — napcat OneBot v11 HTTP API + 合并通知。"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from bzauto.config import get_config

log = logging.getLogger("boss.notify")


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
