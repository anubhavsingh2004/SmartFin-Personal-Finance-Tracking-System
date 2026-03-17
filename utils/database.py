"""Database utilities for SmartFin."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "database.db"

DEFAULT_CATEGORY_BUDGETS: dict[str, float] = {
    "Food": 12000.0,
    "Transport": 6000.0,
    "Bills": 9000.0,
    "Entertainment": 5000.0,
    "Health": 7000.0,
    "Shopping": 8000.0,
    "Other": 4000.0,
}


def get_db_connection() -> sqlite3.Connection:
    """Return a SQLite connection with dict-like row access."""
    # FIXED: Added timeout=10 and check_same_thread=False to prevent "database is locked" errors
    connection = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create application tables if they do not exist."""
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('Income', 'Expense')),
            description TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS category_budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            monthly_budget REAL NOT NULL,
            UNIQUE (user_id, category),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS budget_alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            month TEXT NOT NULL,
            threshold_percent INTEGER NOT NULL,
            usage_percent REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, category, month, threshold_percent),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    connection.commit()
    connection.close()


def seed_user_budgets(user_id: int) -> None:
    """Ensure a user has baseline monthly budgets for all supported categories."""
    # FIXED: Added try/finally for robust connection handling
    connection = get_db_connection()
    try:
        cursor = connection.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO category_budgets (user_id, category, monthly_budget)
            VALUES (?, ?, ?)
            """,
            [(user_id, category, budget) for category, budget in DEFAULT_CATEGORY_BUDGETS.items()],
        )
        connection.commit()
    finally:
        connection.close()


def seed_demo_account() -> None:
    """Create a demo user with realistic data for presentations and testing."""
    # FIXED: Reordered to close connection BEFORE calling seed_user_budgets() to prevent nesting
    connection = get_db_connection()
    try:
        cursor = connection.cursor()

        demo_user = cursor.execute(
            "SELECT id FROM users WHERE email = ?",
            ("demo@smartfin.com",),
        ).fetchone()

        if demo_user is None:
            cursor.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                ("Demo User", "demo@smartfin.com", generate_password_hash("Demo@123")),
            )
            demo_user_id = cursor.lastrowid
        else:
            demo_user_id = demo_user["id"]

        existing_transactions = cursor.execute(
            "SELECT COUNT(*) AS total FROM transactions WHERE user_id = ?",
            (demo_user_id,),
        ).fetchone()

        if existing_transactions and existing_transactions["total"] == 0:
            demo_transactions = [
                (demo_user_id, 50000.0, "Salary", "Income", "monthly salary credit", "2026-01-01"),
                (demo_user_id, 52000.0, "Salary", "Income", "monthly salary credit", "2026-02-01"),
                (demo_user_id, 52000.0, "Salary", "Income", "monthly salary credit", "2026-03-01"),
                (demo_user_id, 6200.0, "Food", "Expense", "grocery shopping and snacks", "2026-01-05"),
                (demo_user_id, 2800.0, "Transport", "Expense", "uber ride and metro recharge", "2026-01-08"),
                (demo_user_id, 3500.0, "Bills", "Expense", "electricity bill", "2026-01-11"),
                (demo_user_id, 4200.0, "Entertainment", "Expense", "movie tickets and gaming recharge", "2026-01-16"),
                (demo_user_id, 2600.0, "Health", "Expense", "pharmacy medicine", "2026-01-20"),
                (demo_user_id, 7900.0, "Shopping", "Expense", "mall shopping", "2026-01-25"),
                (demo_user_id, 7500.0, "Food", "Expense", "pizza dinner and cafe meals", "2026-02-04"),
                (demo_user_id, 3000.0, "Transport", "Expense", "fuel refill", "2026-02-07"),
                (demo_user_id, 4100.0, "Bills", "Expense", "internet recharge and water bill", "2026-02-09"),
                (demo_user_id, 5600.0, "Entertainment", "Expense", "concert pass", "2026-02-14"),
                (demo_user_id, 3100.0, "Health", "Expense", "doctor consultation", "2026-02-18"),
                (demo_user_id, 9200.0, "Shopping", "Expense", "online order shoes and clothing purchase", "2026-02-22"),
                (demo_user_id, 9800.0, "Food", "Expense", "restaurant dinners and groceries", "2026-03-03"),
                (demo_user_id, 3400.0, "Transport", "Expense", "cab rides", "2026-03-05"),
                (demo_user_id, 4500.0, "Bills", "Expense", "electricity and mobile bill", "2026-03-10"),
                (demo_user_id, 8900.0, "Entertainment", "Expense", "weekend trip entertainment", "2026-03-15"),
                (demo_user_id, 3500.0, "Health", "Expense", "gym membership and supplements", "2026-03-18"),
                (demo_user_id, 10400.0, "Shopping", "Expense", "gift purchase and clothing purchase", "2026-03-24"),
                (demo_user_id, 1800.0, "Other", "Expense", "book fair purchase", "2026-03-26"),
            ]
            cursor.executemany(
                """
                INSERT INTO transactions (user_id, amount, category, type, description, date)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                demo_transactions,
            )

        connection.commit()
    finally:
        connection.close()

    # FIXED: Moved this call AFTER closing the first connection to prevent nesting
    seed_user_budgets(demo_user_id)


def seed_demo_income(user_id: int) -> None:
    """Ensure a first-time user has a baseline income entry for better analytics."""
    # FIXED: Added try/finally for robust connection handling
    connection = get_db_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS total FROM transactions WHERE user_id = ? AND type = 'Income'",
            (user_id,),
        )
        result = cursor.fetchone()

        if result and result["total"] == 0:
            cursor.execute(
                """
                INSERT INTO transactions (user_id, amount, category, type, description, date)
                VALUES (?, ?, ?, ?, ?, DATE('now'))
                """,
                (user_id, 0.0, "Salary", "Income", "Initial balance setup"),
            )
            connection.commit()
    finally:
        connection.close()


def fetch_user_category_budgets(user_id: int) -> dict[str, float]:
    """Return all category budgets for a user, auto-seeding defaults when needed."""
    seed_user_budgets(user_id)
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT category, monthly_budget
        FROM category_budgets
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    connection.close()
    return {row["category"]: float(row["monthly_budget"]) for row in rows}


def update_user_category_budgets(user_id: int, budgets: dict[str, float]) -> None:
    """Upsert category budgets for a user from validated input."""
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.executemany(
        """
        INSERT INTO category_budgets (user_id, category, monthly_budget)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, category)
        DO UPDATE SET monthly_budget = excluded.monthly_budget
        """,
        [(user_id, category, amount) for category, amount in budgets.items()],
    )
    connection.commit()
    connection.close()


def create_budget_alert_event(
    user_id: int,
    category: str,
    month: str,
    threshold_percent: int,
    usage_percent: float,
) -> bool:
    """Insert a monthly alert event once; return True only when a new event is created."""
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO budget_alert_events
            (user_id, category, month, threshold_percent, usage_percent)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, category, month, threshold_percent, usage_percent),
    )
    connection.commit()
    was_created = cursor.rowcount > 0
    connection.close()
    return was_created
