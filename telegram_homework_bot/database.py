from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)


@dataclass
class OrderRecord:
    order_id: int
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    order_type: str
    subject: str
    description: str
    file_id: Optional[str]
    file_type: Optional[str]
    additional_info: Optional[str]
    deadline: Optional[str]
    budget: str
    status: str
    executor_id: Optional[int]
    executor_username: Optional[str]
    group_message_id: Optional[int]
    decline_reason: Optional[str]


class Database:
    """Asynchronous wrapper around a SQLite database."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create tables if they do not exist."""
        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                order_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                file_id TEXT,
                file_type TEXT,
                additional_info TEXT,
                deadline TEXT,
                budget TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                executor_id INTEGER,
                executor_username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                group_message_id INTEGER,
                decline_reason TEXT
            );
            """
        )

        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    async def create_order(self, data: Dict[str, Any]) -> int:
        """Insert a new order into the database and return its ID."""
        cursor = await self._execute(
            """
            INSERT INTO orders (
                user_id,
                username,
                first_name,
                last_name,
                order_type,
                subject,
                description,
                file_id,
                file_type,
                additional_info,
                deadline,
                budget
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                data["user_id"],
                data.get("username"),
                data.get("first_name"),
                data.get("last_name"),
                data.get("order_type_label") or data["order_type"],
                data["subject"],
                data["description"],
                data.get("file_id"),
                data.get("file_type"),
                data.get("additional_info"),
                data.get("deadline"),
                data["budget"],
            ),
        )
        order_id = cursor.lastrowid
        LOGGER.debug("Created order %s", order_id)
        return order_id

    async def store_group_message(self, order_id: int, message_id: int) -> None:
        """Persist group message identifier for follow-up actions."""
        await self._execute(
            "UPDATE orders SET group_message_id = ? WHERE order_id = ?;",
            (message_id, order_id),
        )

    async def set_user_state(
        self,
        user_id: int,
        state: Optional[str],
        data: Optional[Dict[str, Any]],
    ) -> None:
        """Store the current conversation state for a user."""
        data_json = json.dumps(data or {})
        await self._execute(
            """
            INSERT INTO user_states (user_id, state, data)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state,
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (user_id, state, data_json),
        )

    async def clear_user_state(self, user_id: int) -> None:
        """Remove stored conversation state for a user."""
        await self._execute("DELETE FROM user_states WHERE user_id = ?;", (user_id,))

    async def get_user_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve stored conversation state for a user."""
        cursor = await self._execute(
            "SELECT state, data FROM user_states WHERE user_id = ?;", (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["data"]) if row["data"] else {}
        except json.JSONDecodeError:
            data = {}
        return {"state": row["state"], "data": data}

    async def get_order(self, order_id: int) -> Optional[OrderRecord]:
        """Fetch a single order by ID."""
        cursor = await self._execute(
            """
            SELECT
                order_id,
                user_id,
                username,
                first_name,
                last_name,
                order_type,
                subject,
                description,
                file_id,
                file_type,
                additional_info,
                deadline,
                budget,
                status,
                executor_id,
                executor_username,
                group_message_id,
                decline_reason
            FROM orders
            WHERE order_id = ?;
            """,
            (order_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return OrderRecord(
            order_id=row["order_id"],
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            order_type=row["order_type"],
            subject=row["subject"],
            description=row["description"],
            file_id=row["file_id"],
            file_type=row["file_type"],
            additional_info=row["additional_info"],
            deadline=row["deadline"],
            budget=row["budget"],
            status=row["status"],
            executor_id=row["executor_id"],
            executor_username=row["executor_username"],
            group_message_id=row["group_message_id"],
            decline_reason=row["decline_reason"],
        )

    async def update_order_status(
        self,
        order_id: int,
        status: str,
        *,
        executor_id: Optional[int] = None,
        executor_username: Optional[str] = None,
        decline_reason: Optional[str] = None,
    ) -> None:
        """Update status-related fields for an order."""
        await self._execute(
            """
            UPDATE orders
            SET status = ?,
                executor_id = COALESCE(?, executor_id),
                executor_username = COALESCE(?, executor_username),
                decline_reason = COALESCE(?, decline_reason)
            WHERE order_id = ?;
            """,
            (status, executor_id, executor_username, decline_reason, order_id),
        )

    async def reset_order_executor(self, order_id: int) -> None:
        """Clear executor info for an order."""
        await self._execute(
            """
            UPDATE orders
            SET executor_id = NULL,
                executor_username = NULL
            WHERE order_id = ?;
            """,
            (order_id,),
        )

    async def _execute(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute SQL in a thread-safe manner."""
        async with self._lock:
            return await asyncio.to_thread(self._execute_sync, query, params)

    def _execute_sync(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Cursor:
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        self._conn.commit()
        return cursor

    async def close(self) -> None:
        """Close the database connection."""
        async with self._lock:
            await asyncio.to_thread(self._conn.close)

