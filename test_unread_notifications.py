from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from bzauto.models import ChatItem
from bzauto.pages.header import BossHeader
from bzauto.storage import Storage
from bzauto.unread_watcher import UnreadWatcher


class UnreadNotificationTests(unittest.TestCase):
    def test_old_conversation_table_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "old.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE conversations ("
                "conv_id TEXT, account TEXT, name TEXT, company TEXT, position TEXT, "
                "last_msg TEXT, last_msg_time TEXT, platform_status TEXT, status TEXT, "
                "sender TEXT, unread_count INTEGER, status_changed_at TEXT, "
                "linked_job_id TEXT, first_seen_at TEXT, last_updated TEXT, note TEXT, "
                "unique_id TEXT, encrypt_boss_id TEXT, encrypt_job_id TEXT, "
                "PRIMARY KEY (conv_id, account))"
            )
            connection.close()

            storage = Storage(db_path)
            columns = {
                row[1]
                for row in storage.db.conn.execute("PRAGMA table_info(conversations)").fetchall()
            }
            self.assertIn("last_msg_id", columns)
            self.assertIn("last_notified_msg_key", columns)
            storage.db.conn.close()

    def test_same_message_is_only_unnotified_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            item = ChatItem(
                name="王艳",
                company="上海网擎",
                position="招聘",
                time="2026-07-22T12:37:00",
                lastMsg="请问您会日语吗？",
                sender="other",
                unread_count=1,
                uniqueId="conv-1",
                lastMsgId=1001,
            )

            storage.conversations.batch_upsert("main", [item])
            self.assertEqual(
                storage.conversations.list_unnotified_unread("main", [item]),
                [item],
            )

            storage.conversations.mark_unread_notified("main", [item])
            self.assertEqual(
                storage.conversations.list_unnotified_unread("main", [item]),
                [],
            )

            newer = item.model_copy(update={"lastMsg": "新的消息", "lastMsgId": 1002})
            storage.conversations.batch_upsert("main", [newer])
            self.assertEqual(
                storage.conversations.list_unnotified_unread("main", [newer]),
                [newer],
            )
            storage.db.conn.close()


class UnreadWatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_positive_count_triggers_scan(self) -> None:
        watcher = object.__new__(UnreadWatcher)
        watcher._last_counts = {}
        watcher._request_scan = AsyncMock()

        await watcher._handle_count_change("main", 1)

        self.assertEqual(watcher._last_counts["main"], 1)
        watcher._request_scan.assert_awaited_once_with("main")


class BossHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_unread_count_normalizes_numeric_string(self) -> None:
        session = Mock()
        session.eval_js = AsyncMock(return_value="12")

        self.assertEqual(await BossHeader(session).get_unread_count(), 12)

    async def test_unread_count_keeps_number(self) -> None:
        session = Mock()
        session.eval_js = AsyncMock(return_value=3)

        self.assertEqual(await BossHeader(session).get_unread_count(), 3)

    async def test_unread_count_ignores_invalid_value(self) -> None:
        session = Mock()
        session.eval_js = AsyncMock(return_value="")

        self.assertIsNone(await BossHeader(session).get_unread_count())


if __name__ == "__main__":
    unittest.main()
