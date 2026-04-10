# Plan: Database Setup (Step 1)

## Context

The Spendly expense tracker needs a data layer before any auth or expense features can be built. `database/db.py` is currently a stub. This plan implements it per spec `.claude/specs/o1_database_setup.md` and wires it into `app.py` so the DB is ready on every startup.

---

## Files to Change

- `database/db.py` — implement all three functions
- `app.py` — import and call `init_db()` + `seed_db()` on startup

## Files to Create

- None

---

## Implementation

### `database/db.py`

**`get_db()`**
- Open `spendly.db` in the project root using `sqlite3.connect()`
- Set `conn.row_factory = sqlite3.Row`
- Execute `PRAGMA foreign_keys = ON`
- Return the connection

**`init_db()`**
- Call `get_db()`, then `CREATE TABLE IF NOT EXISTS` for both tables:

```sql
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
```
- Close connection after creation

**`seed_db()`**
- Call `get_db()`
- Check `SELECT COUNT(*) FROM users` — if > 0, return early
- Insert demo user:
  - name: `Demo User`, email: `demo@spendly.com`
  - password_hash: `generate_password_hash("demo123")` from `werkzeug.security`
- Insert 8 sample expenses linked to demo user's id, covering categories: Food, Transport, Bills, Health, Entertainment, Shopping, Other (one repeated), dates spread across 2026-04
- Use parameterized queries only (`?` placeholders)
- Close connection

---

### `app.py`

Add at the top (after existing imports):
```python
from database.db import get_db, init_db, seed_db
```

Before `if __name__ == "__main__":`, add startup block:
```python
with app.app_context():
    init_db()
    seed_db()
```

---

## Rules / Constraints

- No ORMs — raw `sqlite3` only
- Parameterized queries everywhere (`?` placeholders, never f-strings in SQL)
- `PRAGMA foreign_keys = ON` on every `get_db()` call
- `amount` stored as REAL
- Dates in `YYYY-MM-DD` format
- `seed_db()` is idempotent (COUNT check prevents duplicates)

---

## Verification

1. Run `python app.py` — should start without errors
2. Confirm `spendly.db` is created in project root
3. Open DB with `sqlite3 spendly.db`:
   - `.tables` → should show `users` and `expenses`
   - `SELECT * FROM users;` → 1 row (Demo User)
   - `SELECT COUNT(*) FROM expenses;` → 8
4. Run app again — `seed_db()` should not duplicate records
5. Test FK enforcement: insert expense with invalid `user_id` → should fail
