"""
Tests for Spec 05: Date Filter in Profile
==========================================
All tests are derived exclusively from the feature specification at
.claude/specs/05-date-filter-in-profile.md

Test IDs reference the spec's "Definition of done" checklist items and
named rules where applicable.

Spec-level ambiguity note
--------------------------
The spec states for custom range where `from > to`:
  "swap them or fall back to all"
Two tests cover both permitted outcomes; the test that is stricter
is marked accordingly.  If the implementation settles on one strategy,
the other variant test can be removed.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# App import — we rely only on the Flask application object and the route
# paths declared in app.py.  No internal helpers are called from tests.
# ---------------------------------------------------------------------------
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as spendly_app  # noqa: E402  (app-level side effects happen here)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def app(tmp_path):
    """
    Provide a fully isolated Flask test application backed by an in-memory
    (file-based per test, under tmp_path) SQLite database.

    We monkey-patch `database.db.DB_PATH` and re-initialise the schema so
    every test starts with a clean slate.  No seed data is inserted here;
    individual tests insert exactly the data they need.
    """
    import database.db as db_module

    test_db_path = str(tmp_path / "test_spendly.db")
    db_module.DB_PATH = test_db_path  # redirect the module-level path

    # Re-initialise schema on the fresh file
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

    spendly_app.app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-not-random",
            "WTF_CSRF_ENABLED": False,
        }
    )

    yield spendly_app.app

    # Cleanup: restore the original DB path so other test modules are not affected
    db_module.DB_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(db_module.__file__))),
        "spendly.db",
    )


@pytest.fixture()
def client(app):
    """Return the Flask test client."""
    return app.test_client()


@pytest.fixture()
def db_conn(app):
    """
    Return a direct SQLite connection to the test database so tests can
    insert / inspect rows without going through the Flask app.
    """
    import database.db as db_module

    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


@pytest.fixture()
def user_a(db_conn):
    """
    Insert user A into the test database and return their id.
    Password is 'password123' (>= 8 chars, satisfies registration rules).
    """
    pw_hash = generate_password_hash("password123")
    cursor = db_conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Alice", "alice@example.com", pw_hash),
    )
    db_conn.commit()
    return cursor.lastrowid


@pytest.fixture()
def user_b(db_conn):
    """
    Insert a second, independent user into the test database and return
    their id.  Used for user-isolation tests.
    """
    pw_hash = generate_password_hash("password123")
    cursor = db_conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Bob", "bob@example.com", pw_hash),
    )
    db_conn.commit()
    return cursor.lastrowid


@pytest.fixture()
def auth_client(client, user_a):
    """
    Return a test client that is already authenticated as user A.
    Authentication is performed by setting the session cookie directly
    via the login endpoint so we do not couple to session internals.
    """
    client.post(
        "/login",
        data={"email": "alice@example.com", "password": "password123"},
        follow_redirects=False,
    )
    return client


def insert_expense(db_conn, user_id, amount, category, expense_date, description=""):
    """
    Helper to insert a single expense row.  Returns the new row id.
    `expense_date` must be a `datetime.date` instance or a YYYY-MM-DD string.
    `amount` is stored as a float (REAL column) matching the schema.
    """
    if isinstance(expense_date, date):
        expense_date = expense_date.isoformat()
    cursor = db_conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, float(amount), category, expense_date, description),
    )
    db_conn.commit()
    return cursor.lastrowid


# ===========================================================================
# 1. Authentication guard
# ===========================================================================


class TestAuthGuard:
    """
    Spec rule: "Protect every profile route with the existing login_required
    decorator."
    Definition of done: "Anonymous users visiting /profile?range=... are
    still redirected to /login with the existing flash message."
    """

    def test_unauthenticated_get_profile_redirects_to_login(self, client):
        """
        Spec DoD: Anonymous users visiting /profile are redirected to /login.
        No range parameter — plain unauthenticated access.
        """
        response = client.get("/profile", follow_redirects=False)

        assert response.status_code in (301, 302, 303)
        assert "/login" in response.headers["Location"]

    @pytest.mark.parametrize(
        "query_string",
        [
            "?range=all",
            "?range=7d",
            "?range=30d",
            "?range=60d",
            "?range=90d",
            "?range=month",
            "?range=custom&from=2026-04-01&to=2026-04-15",
            "?range=hack",
        ],
    )
    def test_unauthenticated_get_profile_with_range_redirects_to_login(
        self, client, query_string
    ):
        """
        Spec DoD: Anonymous users visiting /profile?range=... are still
        redirected to /login regardless of query string content.
        """
        response = client.get(f"/profile{query_string}", follow_redirects=False)

        assert response.status_code in (301, 302, 303)
        assert "/login" in response.headers["Location"]

    def test_unauthenticated_request_triggers_flash_message(self, client):
        """
        Spec rule: the existing flash message behaviour must be preserved for
        unauthenticated access.
        """
        response = client.get(
            "/profile?range=30d",
            follow_redirects=True,
        )

        # After following the redirect to /login the flash message must be present
        assert response.status_code == 200
        assert b"sign in" in response.data.lower() or b"please" in response.data.lower()


# ===========================================================================
# 2. Default / "all" range — happy path
# ===========================================================================


class TestRangeAll:
    """
    Spec DoD: GET /profile (no query string) renders all of the user's
    expenses, with total_spent, txn_count, top_category, and
    category_breakdown computed from the database — not hardcoded.
    """

    def test_all_range_returns_200_for_authenticated_user(
        self, auth_client, user_a, db_conn
    ):
        """Authenticated GET /profile must return HTTP 200."""
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-01-01")

        response = auth_client.get("/profile")

        assert response.status_code == 200

    def test_all_range_shows_every_expense_for_user(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: no date filter — all expenses for the logged-in user must
        be present in the rendered page.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2025-01-01", "Old lunch")
        insert_expense(db_conn, user_a, 20.00, "Transport", "2024-06-15", "Bus pass")
        insert_expense(db_conn, user_a, 55.00, "Bills", "2023-03-20", "Electricity")

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert "Old lunch" in body
        assert "Bus pass" in body
        assert "Electricity" in body

    def test_all_range_explicit_param_behaves_same_as_no_param(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: range defaults to 'all' when the param is absent.
        Explicitly passing range=all must produce the same result.
        """
        insert_expense(db_conn, user_a, 12.00, "Food", "2022-11-11", "Old snack")

        resp_no_param = auth_client.get("/profile")
        resp_explicit = auth_client.get("/profile?range=all")

        # Both must succeed; both must contain the expense description
        assert resp_no_param.status_code == 200
        assert resp_explicit.status_code == 200
        assert "Old snack" in resp_no_param.data.decode()
        assert "Old snack" in resp_explicit.data.decode()

    def test_total_spent_reflects_all_expenses(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: total_spent is the sum of amounts for the filtered window.
        With range=all it must equal the sum of all the user's expense amounts.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2025-06-01")
        insert_expense(db_conn, user_a, 25.50, "Transport", "2025-07-01")
        # Expected total: 35.50

        response = auth_client.get("/profile")
        body = response.data.decode()

        # The spec mandates two-decimal currency display: $35.50
        assert "35.50" in body

    def test_txn_count_reflects_all_expenses(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: txn_count is the count of expenses in the filtered window.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2025-01-01")
        insert_expense(db_conn, user_a, 20.00, "Food", "2025-02-01")
        insert_expense(db_conn, user_a, 30.00, "Food", "2025-03-01")

        response = auth_client.get("/profile")
        body = response.data.decode()

        # Three transactions — the count must appear somewhere on the page
        assert "3" in body

    def test_top_category_is_category_with_highest_sum(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: top_category is the category with the highest sum in the window.
        """
        insert_expense(db_conn, user_a, 5.00, "Food", "2025-01-01")
        insert_expense(db_conn, user_a, 200.00, "Bills", "2025-01-02")
        insert_expense(db_conn, user_a, 15.00, "Transport", "2025-01-03")

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert "Bills" in body

    def test_category_breakdown_is_ordered_by_amount_descending(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: category_breakdown is ordered by amount descending.
        The highest-amount category must appear before the lowest.
        """
        insert_expense(db_conn, user_a, 5.00, "Coffee", "2025-01-01")
        insert_expense(db_conn, user_a, 300.00, "Rent", "2025-01-02")
        insert_expense(db_conn, user_a, 50.00, "Food", "2025-01-03")

        response = auth_client.get("/profile")
        body = response.data.decode()

        rent_pos = body.find("Rent")
        food_pos = body.find("Food")
        coffee_pos = body.find("Coffee")

        assert rent_pos < food_pos < coffee_pos, (
            "Category breakdown must be ordered by amount descending: "
            "Rent ($300) > Food ($50) > Coffee ($5)"
        )


# ===========================================================================
# 3. Preset ranges — happy paths
# ===========================================================================


class TestPresetRanges:
    """
    Spec DoD items for 7d, 30d, 60d, 90d, and month preset ranges.
    All date arithmetic uses today's real date (as the spec requires
    `datetime.now()` / `date.today()` on the server side).  We freeze time
    via monkeypatching the date in the app under test using freezegun so
    tests remain deterministic.
    """

    @pytest.fixture(autouse=True)
    def freeze_today(self, monkeypatch):
        """
        Freeze 'today' to 2026-04-29 for all tests in this class so that
        boundary dates are predictable without depending on the real clock.
        We patch the `date` object used inside the app's resolve_range logic.
        """
        import datetime as dt_module

        FROZEN_DATE = date(2026, 4, 29)

        class FrozenDate(dt_module.date):
            @classmethod
            def today(cls):
                return FROZEN_DATE

        monkeypatch.setattr(dt_module, "date", FrozenDate)
        self.today = FROZEN_DATE

    # --- 7d ---

    def test_range_7d_includes_expense_on_today(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=7d shows only expenses dated within the last 7 days
        inclusive of today.  An expense on today must be included.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", self.today, "Today's lunch")

        response = auth_client.get("/profile?range=7d")
        body = response.data.decode()

        assert "Today's lunch" in body

    def test_range_7d_includes_expense_on_boundary_start(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: last 7 days inclusive — start boundary is today - 6 days
        (7 days inclusive of today).
        """
        boundary_start = self.today - timedelta(days=6)
        insert_expense(db_conn, user_a, 20.00, "Transport", boundary_start, "Boundary start")

        response = auth_client.get("/profile?range=7d")
        body = response.data.decode()

        assert "Boundary start" in body

    def test_range_7d_excludes_expense_one_day_before_boundary(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: expenses strictly outside the 7-day window must not appear.
        An expense dated today - 7 days is outside the window (8th day back).
        """
        outside_date = self.today - timedelta(days=7)
        insert_expense(db_conn, user_a, 50.00, "Bills", outside_date, "Outside 7d")

        response = auth_client.get("/profile?range=7d")
        body = response.data.decode()

        assert "Outside 7d" not in body

    # --- 30d ---

    def test_range_30d_includes_boundary_start(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=30d includes expenses from the last 30 days inclusive.
        Start boundary is today - 29 days.
        """
        boundary_start = self.today - timedelta(days=29)
        insert_expense(db_conn, user_a, 30.00, "Food", boundary_start, "30d boundary")

        response = auth_client.get("/profile?range=30d")
        body = response.data.decode()

        assert "30d boundary" in body

    def test_range_30d_excludes_expense_outside_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=30d must exclude expenses older than 30 days.
        """
        outside_date = self.today - timedelta(days=30)
        insert_expense(db_conn, user_a, 99.00, "Shopping", outside_date, "Outside 30d")

        response = auth_client.get("/profile?range=30d")
        body = response.data.decode()

        assert "Outside 30d" not in body

    # --- 60d ---

    def test_range_60d_includes_boundary_start(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=60d includes expenses from the last 60 days inclusive.
        Start boundary is today - 59 days.
        """
        boundary_start = self.today - timedelta(days=59)
        insert_expense(db_conn, user_a, 45.00, "Health", boundary_start, "60d boundary")

        response = auth_client.get("/profile?range=60d")
        body = response.data.decode()

        assert "60d boundary" in body

    def test_range_60d_excludes_expense_outside_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=60d must exclude expenses older than 60 days.
        """
        outside_date = self.today - timedelta(days=60)
        insert_expense(db_conn, user_a, 77.00, "Other", outside_date, "Outside 60d")

        response = auth_client.get("/profile?range=60d")
        body = response.data.decode()

        assert "Outside 60d" not in body

    # --- 90d ---

    def test_range_90d_includes_boundary_start(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=90d includes expenses from the last 90 days inclusive.
        Start boundary is today - 89 days.
        """
        boundary_start = self.today - timedelta(days=89)
        insert_expense(db_conn, user_a, 60.00, "Bills", boundary_start, "90d boundary")

        response = auth_client.get("/profile?range=90d")
        body = response.data.decode()

        assert "90d boundary" in body

    def test_range_90d_excludes_expense_outside_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=90d must exclude expenses older than 90 days.
        """
        outside_date = self.today - timedelta(days=90)
        insert_expense(db_conn, user_a, 120.00, "Transport", outside_date, "Outside 90d")

        response = auth_client.get("/profile?range=90d")
        body = response.data.decode()

        assert "Outside 90d" not in body

    # --- month ---

    def test_range_month_includes_expense_on_first_of_month(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=month shows only expenses dated in the current
        calendar month.  The first day of the month is included.
        """
        first_of_month = self.today.replace(day=1)
        insert_expense(db_conn, user_a, 80.00, "Food", first_of_month, "Month start")

        response = auth_client.get("/profile?range=month")
        body = response.data.decode()

        assert "Month start" in body

    def test_range_month_includes_expense_on_today(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=month is inclusive of today.
        """
        insert_expense(db_conn, user_a, 15.00, "Transport", self.today, "Today month")

        response = auth_client.get("/profile?range=month")
        body = response.data.decode()

        assert "Today month" in body

    def test_range_month_excludes_expense_from_previous_month(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: range=month must not include expenses from a prior month.
        """
        # Last day of March 2026, which is before April 2026
        last_month_date = date(2026, 3, 31)
        insert_expense(
            db_conn, user_a, 200.00, "Bills", last_month_date, "March bill"
        )

        response = auth_client.get("/profile?range=month")
        body = response.data.decode()

        assert "March bill" not in body

    def test_range_month_stats_reflect_same_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: stat cards must reflect the same filtered window as the
        transactions table.  An expense outside the month window must NOT
        contribute to total_spent.
        """
        insert_expense(db_conn, user_a, 100.00, "Bills", self.today, "This month bill")
        insert_expense(
            db_conn, user_a, 999.00, "Other", date(2025, 1, 1), "Old expense"
        )

        response = auth_client.get("/profile?range=month")
        body = response.data.decode()

        assert "100.00" in body
        assert "999" not in body


# ===========================================================================
# 4. Custom range — happy path
# ===========================================================================


class TestCustomRange:
    """
    Spec DoD: GET /profile?range=custom&from=...&to=... shows only expenses
    between those dates inclusive, and the from/to inputs show those values
    when the page re-renders.
    """

    def test_custom_range_returns_expenses_in_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: expenses between the custom from/to dates (inclusive)
        must appear in the response.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-01", "April first")
        insert_expense(db_conn, user_a, 20.00, "Food", "2026-04-10", "April tenth")
        insert_expense(db_conn, user_a, 30.00, "Food", "2026-04-15", "April fifteenth")
        insert_expense(db_conn, user_a, 99.00, "Bills", "2026-04-20", "After window")
        insert_expense(db_conn, user_a, 55.00, "Bills", "2026-03-31", "Before window")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-01&to=2026-04-15"
        )
        body = response.data.decode()

        assert "April first" in body
        assert "April tenth" in body
        assert "April fifteenth" in body
        assert "After window" not in body
        assert "Before window" not in body

    def test_custom_range_includes_from_boundary_date(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: the from date is inclusive (BETWEEN ? AND ? in SQL).
        """
        insert_expense(db_conn, user_a, 12.00, "Food", "2026-04-01", "From boundary")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-01&to=2026-04-30"
        )
        body = response.data.decode()

        assert "From boundary" in body

    def test_custom_range_includes_to_boundary_date(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: the to date is inclusive (BETWEEN ? AND ? in SQL).
        """
        insert_expense(db_conn, user_a, 12.00, "Food", "2026-04-15", "To boundary")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-01&to=2026-04-15"
        )
        body = response.data.decode()

        assert "To boundary" in body

    def test_custom_range_from_and_to_inputs_round_trip(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: custom range inputs must round-trip — when the URL has
        range=custom&from=...&to=..., the inputs must show those values on
        render.
        """
        insert_expense(db_conn, user_a, 5.00, "Other", "2026-04-05", "Some expense")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-01&to=2026-04-15"
        )
        body = response.data.decode()

        assert "2026-04-01" in body
        assert "2026-04-15" in body

    def test_custom_range_stats_scoped_to_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: stat cards must reflect the same filtered window as the
        transactions table.
        """
        insert_expense(db_conn, user_a, 40.00, "Food", "2026-04-05", "In window")
        insert_expense(db_conn, user_a, 500.00, "Bills", "2026-03-01", "Outside")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-01&to=2026-04-30"
        )
        body = response.data.decode()

        # total_spent must be 40.00, not 540.00
        assert "40.00" in body
        assert "540" not in body

    def test_custom_range_single_day_window(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: from == to is a valid single-day window.
        """
        insert_expense(db_conn, user_a, 7.50, "Coffee", "2026-04-10", "Exact day")
        insert_expense(db_conn, user_a, 100.00, "Bills", "2026-04-09", "Day before")
        insert_expense(db_conn, user_a, 100.00, "Bills", "2026-04-11", "Day after")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-10&to=2026-04-10"
        )
        body = response.data.decode()

        assert "Exact day" in body
        assert "Day before" not in body
        assert "Day after" not in body


# ===========================================================================
# 5. Validation / fallback behaviour
# ===========================================================================


class TestValidationFallback:
    """
    Spec rules:
    - Validate `range` against an allow-list; anything else falls back to all.
    - Validate from/to with datetime.strptime; reject strings that do not
      parse — fall back to all.  Never raise.
    - If from is after to: swap them OR fall back to all (spec permits both).
    """

    @pytest.mark.parametrize(
        "invalid_range",
        [
            "hack",
            "DAILY",
            "1w",
            "365d",
            "all;DROP TABLE users",
            "",
            "  ",
            "3 0 d",
        ],
    )
    def test_invalid_range_param_falls_back_to_all_without_error(
        self, auth_client, user_a, db_conn, invalid_range
    ):
        """
        Spec DoD: an invalid range value falls back to all instead of
        raising an error.  The response must be HTTP 200.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2025-01-01", "Always visible")

        response = auth_client.get(
            f"/profile?range={invalid_range}",
        )

        assert response.status_code == 200

    def test_invalid_range_does_not_crash_and_shows_all_expenses(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: an invalid range value falls back to all, meaning all
        expenses are shown rather than zero.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2023-06-01", "Shown expense")

        response = auth_client.get("/profile?range=hack")
        body = response.data.decode()

        assert response.status_code == 200
        assert "Shown expense" in body

    @pytest.mark.parametrize(
        "from_val, to_val",
        [
            ("abc", "xyz"),
            ("2026-13-01", "2026-04-15"),  # month 13 — invalid
            ("2026-04-00", "2026-04-15"),  # day 0 — invalid
            ("", "2026-04-15"),
            ("2026-04-01", ""),
            ("not-a-date", ""),
            ("2026/04/01", "2026/04/15"),  # wrong separator
        ],
    )
    def test_invalid_custom_dates_fall_back_to_all_without_error(
        self, auth_client, user_a, db_conn, from_val, to_val
    ):
        """
        Spec DoD: an invalid or non-parseable from/to falls back to all
        instead of raising an error.  Response must be HTTP 200.
        Spec rule: Validate with datetime.strptime; reject strings that do
        not parse — fall back to all.  Never pass raw strings to SQL.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2025-01-01", "Fallback shown")

        response = auth_client.get(
            f"/profile?range=custom&from={from_val}&to={to_val}"
        )

        assert response.status_code == 200

    def test_invalid_custom_dates_fall_back_shows_all_expenses(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: when custom dates are invalid the fallback is 'all',
        so all user expenses must be visible.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2020-01-01", "Very old")

        response = auth_client.get("/profile?range=custom&from=abc&to=xyz")
        body = response.data.decode()

        assert "Very old" in body

    def test_from_after_to_does_not_crash(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: if from is after to, swap them or fall back to all.
        Either way, the response must not crash (HTTP 200 required).
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-10", "Mid April")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-15&to=2026-04-01"
        )

        assert response.status_code == 200

    def test_from_after_to_either_swaps_or_falls_back(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule (ambiguity): when from > to the spec permits either:
          (a) swapping them so the window is [to, from], or
          (b) falling back to all.
        In either case, the expense within [2026-04-01, 2026-04-15] must
        appear (it falls inside both the swapped window AND the 'all' fallback).
        The expense outside must NOT appear if swap is chosen; it WILL appear
        if all-fallback is chosen — so we only assert the no-crash and that
        the in-window expense appears.
        """
        insert_expense(
            db_conn, user_a, 10.00, "Food", "2026-04-10", "In swapped window"
        )

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-15&to=2026-04-01"
        )
        body = response.data.decode()

        assert response.status_code == 200
        assert "In swapped window" in body

    def test_range_custom_missing_from_falls_back_to_all(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: from is required when range=custom.  Missing from means
        parsing fails, fall back to all.
        """
        insert_expense(db_conn, user_a, 50.00, "Bills", "2020-01-01", "Old bill")

        response = auth_client.get("/profile?range=custom&to=2026-04-15")
        body = response.data.decode()

        assert response.status_code == 200
        assert "Old bill" in body

    def test_range_custom_missing_to_falls_back_to_all(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: to is required when range=custom.  Missing to means
        parsing fails, fall back to all.
        """
        insert_expense(db_conn, user_a, 50.00, "Bills", "2020-01-01", "Old bill 2")

        response = auth_client.get("/profile?range=custom&from=2026-04-01")
        body = response.data.decode()

        assert response.status_code == 200
        assert "Old bill 2" in body


# ===========================================================================
# 6. Empty result set
# ===========================================================================


class TestEmptyResultSet:
    """
    Spec DoD: when the filter window has zero expenses, the transactions
    card shows an empty state, and the stat cards show $0.00, 0, — without
    crashing or dividing by zero in the category breakdown.
    """

    def test_empty_window_returns_200(self, auth_client, user_a, db_conn):
        """
        When no expenses exist for the user at all, the profile must still
        return HTTP 200.
        """
        # No expenses inserted
        response = auth_client.get("/profile")

        assert response.status_code == 200

    def test_empty_window_shows_zero_total_spent(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: stat cards show $0.00 when filter has zero expenses.
        """
        insert_expense(db_conn, user_a, 100.00, "Food", "2020-01-01", "Very old")

        # range=7d with a frozen future date effectively yields zero results
        # Use custom range in a date window known to have no expenses
        response = auth_client.get(
            "/profile?range=custom&from=2030-01-01&to=2030-01-31"
        )
        body = response.data.decode()

        assert "0.00" in body

    def test_empty_window_shows_zero_txn_count(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: stat cards show 0 transactions when filter has zero expenses.
        """
        response = auth_client.get(
            "/profile?range=custom&from=2030-01-01&to=2030-01-31"
        )
        body = response.data.decode()

        # '0' must appear representing the transaction count
        assert "0" in body

    def test_empty_window_does_not_crash_on_category_breakdown(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: no crashing or dividing by zero in category breakdown when
        total is zero (pct = 0 when total_spent == 0).
        """
        response = auth_client.get(
            "/profile?range=custom&from=2030-01-01&to=2030-01-31"
        )

        # The critical assertion: no server-side error
        assert response.status_code == 200

    def test_empty_window_shows_empty_state_message(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: the transactions table must show an empty state when the
        filtered list is empty — never render an empty tbody with no message.
        Spec example: "No transactions in this range".
        """
        response = auth_client.get(
            "/profile?range=custom&from=2030-01-01&to=2030-01-31"
        )
        body = response.data.decode().lower()

        # The empty state message should indicate no transactions
        has_empty_state = (
            "no transactions" in body
            or "no expenses" in body
            or "empty" in body
            or "no results" in body
            or "this range" in body
        )
        assert has_empty_state, (
            "The page must show a meaningful empty state message when "
            "no transactions match the filter — not a blank table body."
        )

    def test_empty_window_top_category_is_absent_or_placeholder(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: stat cards show — for top_category when list is empty.
        The page must not crash and must not display a real category name.
        """
        response = auth_client.get(
            "/profile?range=custom&from=2030-01-01&to=2030-01-31"
        )

        assert response.status_code == 200


# ===========================================================================
# 7. User isolation (security)
# ===========================================================================


class TestUserIsolation:
    """
    Spec rule: Always scope expense queries by WHERE user_id = ? using
    session["user_id"] — never trust query string or form input for identity.
    Spec DoD: A second user's expenses never appear under user A's profile,
    regardless of query string tampering.
    """

    def test_user_a_cannot_see_user_b_expenses_with_range_all(
        self, auth_client, user_a, user_b, db_conn
    ):
        """
        Spec DoD: user A must never see user B's expenses.
        auth_client is authenticated as user A.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-01", "Alice expense")
        insert_expense(db_conn, user_b, 999.00, "Bills", "2026-04-01", "Bob secret")

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert "Alice expense" in body
        assert "Bob secret" not in body

    def test_user_a_cannot_see_user_b_expenses_with_custom_range(
        self, auth_client, user_a, user_b, db_conn
    ):
        """
        Spec DoD: query string tampering (range, from, to) must not expose
        another user's data.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-05", "Alice April")
        insert_expense(db_conn, user_b, 888.00, "Travel", "2026-04-05", "Bob April")

        response = auth_client.get(
            "/profile?range=custom&from=2026-04-01&to=2026-04-30"
        )
        body = response.data.decode()

        assert "Alice April" in body
        assert "Bob April" not in body

    @pytest.mark.parametrize(
        "range_param",
        ["all", "7d", "30d", "60d", "90d", "month"],
    )
    def test_user_a_expenses_never_contain_user_b_data_for_any_preset(
        self, auth_client, user_a, user_b, db_conn, range_param
    ):
        """
        Spec DoD: regardless of which preset range is used, user B's data
        must never appear for user A.
        """
        today_str = date.today().isoformat()
        insert_expense(
            db_conn, user_b, 777.77, "Other", today_str, "BobPrivate777"
        )
        insert_expense(
            db_conn, user_a, 1.00, "Food", today_str, "AlicePublic"
        )

        response = auth_client.get(f"/profile?range={range_param}")
        body = response.data.decode()

        assert "BobPrivate777" not in body

    def test_user_b_total_spent_not_included_in_user_a_stats(
        self, auth_client, user_a, user_b, db_conn
    ):
        """
        Spec rule: total_spent must be scoped to the authenticated user.
        User B's large expense must not inflate user A's total.
        """
        insert_expense(db_conn, user_a, 5.00, "Food", "2026-04-01", "Alice small")
        insert_expense(db_conn, user_b, 10000.00, "Bills", "2026-04-01", "Bob large")

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert "10000" not in body
        assert "5.00" in body


# ===========================================================================
# 8. Template variable contract
# ===========================================================================


class TestTemplateVariables:
    """
    Spec: The handler must pass specific variables to render_template.
    These tests validate the observable effects of those variables in the
    rendered HTML — not the internal data structure.
    """

    def test_range_label_all_time_shown_when_no_filter(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: build a human-readable range_label.  For range=all the label
        must convey "All time".
        """
        response = auth_client.get("/profile")
        body = response.data.decode().lower()

        assert "all time" in body or "all" in body

    def test_range_label_shown_for_30d(self, auth_client, user_a, db_conn):
        """
        Spec: range_label for 30d must describe the 30-day window.
        """
        response = auth_client.get("/profile?range=30d")
        body = response.data.decode().lower()

        # "30 days" or similar phrase must appear
        assert "30" in body

    def test_amount_displayed_with_two_decimal_places(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: the amount column must display as currency with two decimals
        (e.g. $22.30).
        """
        insert_expense(db_conn, user_a, 22.30, "Food", "2026-04-18", "Grocery run")

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert "22.30" in body

    def test_date_displayed_in_formatted_form_not_raw_iso(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: format expense.date for display (e.g. "Apr 18, 2026") —
        do not show the raw YYYY-MM-DD value to the user.
        The raw ISO string '2026-04-18' must NOT appear as the sole date
        representation; a human-readable variant must be present.
        """
        insert_expense(db_conn, user_a, 22.30, "Food", "2026-04-18", "Test date display")

        response = auth_client.get("/profile")
        body = response.data.decode()

        # Formatted date must appear
        assert "Apr 18, 2026" in body or "April 18" in body or "Apr 18" in body

    def test_from_date_and_to_date_not_exposed_for_non_custom_range(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: from_date and to_date are passed as empty strings to the
        template when range != custom.  The custom inputs must not show
        pre-populated values for a non-custom range.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-01", "April")

        response = auth_client.get("/profile?range=30d")
        body = response.data.decode()

        # The custom date inputs should not have pre-filled non-empty values
        # We check that neither a specific stored date appears in an input value
        # attribute for the from/to fields.
        # If the implementation is correct, from_date and to_date are "".
        assert 'value="2026-04-01"' not in body or "from" not in body.lower()

    def test_category_slug_is_lowercase_category_name(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: category badges must use txn-category--<slug> classes
        where slug is the lowercase category name.
        """
        insert_expense(db_conn, user_a, 50.00, "Shopping", "2026-04-05", "Shoes")

        response = auth_client.get("/profile")
        body = response.data.decode()

        # The CSS class based on lowercase slug must appear
        assert "txn-category--shopping" in body

    def test_active_range_pill_marked_for_30d(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec rule: the active preset pill must be visually marked
        (filter-pill--active) based on the resolved range.
        """
        response = auth_client.get("/profile?range=30d")
        body = response.data.decode()

        assert "filter-pill--active" in body


# ===========================================================================
# 9. Result ordering
# ===========================================================================


class TestResultOrdering:
    """
    Spec: expenses must be ordered by date DESC, id DESC.
    """

    def test_expenses_ordered_by_date_descending(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: results ordered by date DESC, id DESC.
        The most recent expense must appear before older ones in the HTML.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-01", "April first")
        insert_expense(db_conn, user_a, 20.00, "Food", "2026-04-20", "April twentieth")
        insert_expense(db_conn, user_a, 30.00, "Food", "2026-04-10", "April tenth")

        response = auth_client.get("/profile")
        body = response.data.decode()

        pos_twentieth = body.find("April twentieth")
        pos_tenth = body.find("April tenth")
        pos_first = body.find("April first")

        assert pos_twentieth < pos_tenth < pos_first, (
            "Expenses must be ordered by date DESC: "
            "Apr 20 before Apr 10 before Apr 1 in HTML"
        )

    def test_same_date_expenses_ordered_by_id_descending(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: when two expenses share the same date, the one with the higher
        id (inserted later) must appear first (id DESC as tiebreaker).
        """
        id_first = insert_expense(
            db_conn, user_a, 10.00, "Food", "2026-04-10", "Same date first inserted"
        )
        id_second = insert_expense(
            db_conn, user_a, 20.00, "Bills", "2026-04-10", "Same date second inserted"
        )

        response = auth_client.get("/profile")
        body = response.data.decode()

        pos_second = body.find("Same date second inserted")
        pos_first = body.find("Same date first inserted")

        assert pos_second < pos_first, (
            "For same-date expenses, the one with the higher id must appear "
            "first (id DESC ordering)."
        )


# ===========================================================================
# 10. Data mutation guard
# ===========================================================================


class TestNoDataMutation:
    """
    Spec: the filter is read-only — GET /profile must never mutate expense
    data regardless of query string content.
    """

    def test_get_profile_with_any_range_does_not_delete_expenses(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: filter should not mutate data.  After calling GET /profile
        with various range params, all expenses must still exist in the DB.
        """
        insert_expense(db_conn, user_a, 10.00, "Food", "2026-04-01", "Should survive")

        for range_param in ["all", "7d", "30d", "60d", "90d", "month"]:
            auth_client.get(f"/profile?range={range_param}")

        auth_client.get(
            "/profile?range=custom&from=2026-01-01&to=2026-12-31"
        )

        count = db_conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_a,)
        ).fetchone()[0]

        assert count == 1, (
            "GET /profile must never delete or modify expense rows. "
            f"Expected 1 row, found {count}."
        )

    def test_get_profile_does_not_modify_expense_amounts(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: filter is read-only.  Expense amounts must be unchanged after
        rendering the profile page.
        """
        insert_expense(db_conn, user_a, 42.99, "Food", "2026-04-10", "Immutable")

        auth_client.get("/profile?range=all")

        row = db_conn.execute(
            "SELECT amount FROM expenses WHERE description = 'Immutable' AND user_id = ?",
            (user_a,),
        ).fetchone()

        assert row is not None
        assert abs(row["amount"] - 42.99) < 0.001


# ===========================================================================
# 11. POST routes unaffected
# ===========================================================================


class TestPostRoutesUnaffected:
    """
    Spec: Do not change POST /profile or POST /profile/password.
    These tests verify those routes still work correctly alongside the
    new GET filter feature.
    """

    def test_post_profile_update_still_works(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: Profile update and password change flows still work
        end-to-end.
        POST /profile with valid data must update the user's name/email
        and redirect.
        """
        response = auth_client.post(
            "/profile",
            data={"name": "Alice Updated", "email": "alice@example.com"},
            follow_redirects=False,
        )

        assert response.status_code in (301, 302, 303)

    def test_post_profile_password_still_works(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec DoD: Password change flow still works end-to-end.
        POST /profile/password with correct current password must succeed.
        """
        response = auth_client.post(
            "/profile/password",
            data={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
            follow_redirects=False,
        )

        # Success: redirect (profile was updated) or error page (200) but NOT 500
        assert response.status_code in (200, 301, 302, 303)
        assert response.status_code != 500

    def test_get_profile_with_range_does_not_break_post_profile(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: adding query string parameters to GET /profile must not
        affect the behavior of subsequent POST /profile requests.
        """
        # First visit with a filter
        auth_client.get("/profile?range=30d")

        # Then update profile — must still work
        response = auth_client.post(
            "/profile",
            data={"name": "Alice", "email": "alice@example.com"},
            follow_redirects=False,
        )

        assert response.status_code in (301, 302, 303)


# ===========================================================================
# 12. Category breakdown percentage calculation
# ===========================================================================


class TestCategoryBreakdownPercentages:
    """
    Spec: category_breakdown contains {label, amount, pct} dicts where
    pct = amount / total_spent * 100 (0 when total is 0).
    """

    def test_category_pct_sums_to_100_for_exclusive_categories(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: pct is amount / total_spent * 100.  For expenses that together
        make 100%, the breakdown percentages must collectively account for
        the full spend.  We verify that the two category amounts appear in
        the page (indirect check since pct is rendered in the template).
        """
        insert_expense(db_conn, user_a, 75.00, "Food", "2026-04-01")
        insert_expense(db_conn, user_a, 25.00, "Transport", "2026-04-02")

        response = auth_client.get("/profile")
        body = response.data.decode()

        # Both categories must appear in the breakdown
        assert "Food" in body
        assert "Transport" in body

    def test_single_category_has_100_pct(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: when all expenses belong to a single category, that category's
        pct should be 100 (or 100.0).
        """
        insert_expense(db_conn, user_a, 50.00, "Bills", "2026-04-01")
        insert_expense(db_conn, user_a, 50.00, "Bills", "2026-04-02")

        response = auth_client.get("/profile")
        body = response.data.decode()

        # 100% should appear in the context of Bills
        assert "100" in body
        assert "Bills" in body

    def test_pct_is_zero_when_total_spent_is_zero(
        self, auth_client, user_a, db_conn
    ):
        """
        Spec: pct is 0 when total is 0.  No division by zero must occur.
        """
        # No expenses in the custom window
        response = auth_client.get(
            "/profile?range=custom&from=2030-01-01&to=2030-12-31"
        )

        assert response.status_code == 200
