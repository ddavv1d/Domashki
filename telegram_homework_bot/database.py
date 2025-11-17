from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    payment_status: Optional[str]
    payment_receipt_file_id: Optional[str]
    payment_receipt_type: Optional[str]
    payment_submitted_at: Optional[str]
    payment_reviewed_by: Optional[int]
    payment_reviewed_at: Optional[str]
    payment_notes: Optional[str]
    completed_at: Optional[str]


@dataclass
class AdminRecord:
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]


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
                decline_reason TEXT,
                payment_status TEXT DEFAULT 'not_requested',
                payment_receipt_file_id TEXT,
                payment_receipt_type TEXT,
                payment_submitted_at TIMESTAMP,
                payment_reviewed_by INTEGER,
                payment_reviewed_at TIMESTAMP,
                payment_notes TEXT,
                completed_at TIMESTAMP
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

        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        await self._execute(
            """
            INSERT OR IGNORE INTO admins (user_id, username, first_name, last_name, added_by)
            VALUES (796537086, NULL, NULL, NULL, 0);
            """
        )

        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                chat_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Ensure newly required columns exist (idempotent)
        await self._ensure_column(
            "orders", "payment_status", "TEXT DEFAULT 'not_requested'"
        )
        await self._ensure_column("orders", "payment_receipt_file_id", "TEXT")
        await self._ensure_column("orders", "payment_receipt_type", "TEXT")
        await self._ensure_column("orders", "payment_submitted_at", "TIMESTAMP")
        await self._ensure_column("orders", "payment_reviewed_by", "INTEGER")
        await self._ensure_column("orders", "payment_reviewed_at", "TIMESTAMP")
        await self._ensure_column("orders", "payment_notes", "TEXT")
        await self._ensure_column("orders", "completed_at", "TIMESTAMP")

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
            payment_status=row["payment_status"],
            payment_receipt_file_id=row["payment_receipt_file_id"],
            payment_receipt_type=row["payment_receipt_type"],
            payment_submitted_at=row["payment_submitted_at"],
            payment_reviewed_by=row["payment_reviewed_by"],
            payment_reviewed_at=row["payment_reviewed_at"],
            payment_notes=row["payment_notes"],
            completed_at=row["completed_at"],
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

    async def upsert_user_profile(
        self,
        *,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        chat_id: int,
    ) -> None:
        await self._execute(
            """
            INSERT INTO user_profiles (user_id, username, first_name, last_name, chat_id, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                chat_id = excluded.chat_id,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (user_id, username, first_name, last_name, chat_id),
        )

    async def get_all_user_chat_ids(self) -> List[int]:
        cursor = await self._execute("SELECT chat_id FROM user_profiles WHERE chat_id IS NOT NULL;")
        return [row["chat_id"] for row in cursor.fetchall()]

    async def list_admins(self) -> List[AdminRecord]:
        cursor = await self._execute(
            "SELECT user_id, username, first_name, last_name FROM admins ORDER BY added_at ASC;"
        )
        return [
            AdminRecord(
                user_id=row["user_id"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
            )
            for row in cursor.fetchall()
        ]

    async def is_admin(self, user_id: int) -> bool:
        cursor = await self._execute("SELECT 1 FROM admins WHERE user_id = ?;", (user_id,))
        return cursor.fetchone() is not None

    async def add_admin(
        self,
        *,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        added_by: int,
    ) -> None:
        await self._execute(
            """
            INSERT OR REPLACE INTO admins (user_id, username, first_name, last_name, added_by, added_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
            """,
            (user_id, username, first_name, last_name, added_by),
        )

    async def remove_admin(self, user_id: int) -> None:
        await self._execute("DELETE FROM admins WHERE user_id = ?;", (user_id,))

    async def get_order_stats(self) -> Dict[str, int]:
        cursor = await self._execute(
            """
            SELECT status, COUNT(*) as total
            FROM orders
            GROUP BY status;
            """
        )
        stats = {row["status"]: row["total"] for row in cursor.fetchall()}
        return stats

    async def list_orders(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
        limit: int = 10,
    ) -> List[OrderRecord]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query = f"""
                SELECT * FROM orders
                WHERE status IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT ?
            """
            params: Tuple[Any, ...] = (*statuses, limit)
        else:
            query = """
                SELECT * FROM orders
                ORDER BY created_at DESC
                LIMIT ?
            """
            params = (limit,)

        cursor = await self._execute(query, params)
        return [
            OrderRecord(
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
                payment_status=row["payment_status"],
                payment_receipt_file_id=row["payment_receipt_file_id"],
                payment_receipt_type=row["payment_receipt_type"],
                payment_submitted_at=row["payment_submitted_at"],
                payment_reviewed_by=row["payment_reviewed_by"],
                payment_reviewed_at=row["payment_reviewed_at"],
                payment_notes=row["payment_notes"],
                completed_at=row["completed_at"],
            )
            for row in cursor.fetchall()
        ]

    async def save_payment_receipt(
        self,
        *,
        order_id: int,
        file_id: str,
        file_type: str,
        submitted_by: int,
    ) -> None:
        await self._execute(
            """
            UPDATE orders
            SET payment_status = 'submitted',
                payment_receipt_file_id = ?,
                payment_receipt_type = ?,
                payment_submitted_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND user_id = ?;
            """,
            (file_id, file_type, order_id, submitted_by),
        )

    async def update_payment_status(
        self,
        *,
        order_id: int,
        status: str,
        reviewer_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> None:
        await self._execute(
            """
            UPDATE orders
            SET payment_status = ?,
                payment_reviewed_by = COALESCE(?, payment_reviewed_by),
                payment_reviewed_at = CASE WHEN ? IS NULL THEN payment_reviewed_at ELSE CURRENT_TIMESTAMP END,
                payment_notes = COALESCE(?, payment_notes)
            WHERE order_id = ?;
            """,
            (status, reviewer_id, reviewer_id, notes, order_id),
        )

    async def mark_order_completed(self, order_id: int) -> None:
        await self._execute(
            """
            UPDATE orders
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE order_id = ?;
            """,
            (order_id,),
        )

    async def _ensure_column(self, table: str, column: str, definition: str) -> None:
        try:
            await self._execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition};")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc):
                return
            raise

