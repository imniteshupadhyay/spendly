# Spec: Date Filter in Profile

## Overview
The Profile page currently renders the transaction history, summary
stats ("Total spent", "Transactions", "Top category"), and the
category breakdown from hardcoded values. This step replaces those
hardcoded blocks with **real data from the `expenses` table for the
logged-in user**, controlled by a **date filter** at the top of the
page. The filter offers preset ranges (All time, Last 7 days, Last
30 days, This month, Custom) plus a custom `from` / `to` date range.
Selecting a range re-renders the transactions table, the summary
stat cards, and the category breakdown so they all reflect the same
filtered window. This is the first time real expense data is shown
on the Profile page and establishes the query pattern used by later
steps (add / edit / delete expense).

## Depends on
- Step 1: Database Setup (complete)
- Step 2: Registration (complete)
- Step 3: Login and Logout (complete)
- Step 4: Profile Page (complete)

## Routes
- `GET /profile` — extended to accept optional query string
  parameters that drive the date filter:
  - `range` — one of `all`, `7d`, `30d`, `month`, `custom`
    (default `all`)
  - `from` — `YYYY-MM-DD` (required when `range=custom`)
  - `to` — `YYYY-MM-DD` (required when `range=custom`)
  Loads the user's expenses filtered by the resolved date window
  and renders `profile.html` with real transactions, stats, and
  category totals — logged-in.

No additional new routes. `POST /profile` and
`POST /profile/password` continue to behave exactly as today.

## Database changes
No database changes. The existing `expenses` table already has
`user_id`, `amount`, `category`, `date`, and `description`, which
covers every field the filter needs.

## Templates
- **Create:** none.
- **Modify:**
  - `templates/profile.html`
    - Add a date filter card / bar above the existing top grid with:
      - Preset range pills (`All`, `7d`, `30d`,`60d`, `90d` `Month`, `Custom`)
      - Custom range inputs (`<input type="date" name="from">` and
        `<input type="date" name="to">`) that are visible only when
        the active preset is `Custom`
      - A submit button that performs `GET /profile` with the
        selected query string parameters (the form uses
        `method="GET"` so URLs are shareable / bookmarkable)
      - Display the active range label (e.g. "Showing: Last 30 days
        (Mar 30 — Apr 29, 2026)")
    - Replace hardcoded numbers in the **summary stat cards** with
      Jinja variables (`total_spent`, `txn_count`, `top_category`,
      `top_category_amount`).
    - Replace the hardcoded `<tbody>` rows in the
      **transactions table** with a `{% for expense in expenses %}`
      loop. Show an "empty state" row / message when the filtered
      list is empty.
    - Replace the hardcoded **category breakdown** rows with a
      `{% for row in category_breakdown %}` loop that renders
      `label`, `pct`, and `amount` from the backend.
    - The note under each stat card ("This month", etc.) must
      reflect the active range, not always say "This month".
  - `static/css/style.css` — add styles for:
    - `.filter-bar`, `.filter-presets`, `.filter-pill`,
      `.filter-pill--active`
    - `.filter-custom-range` (custom date inputs row)
    - `.txn-empty` (empty state inside the transactions card)
    Reuse existing CSS variables — do not introduce new hex
    colours.

## Files to change
- `app.py`
  - Update the `GET /profile` handler to:
    - Read `range`, `from`, `to` from `request.args`.
    - Resolve the active range to a concrete `(start_date, end_date)`
      tuple (both `YYYY-MM-DD` strings, inclusive). If `range` is
      missing or invalid, default to `all` (no date filter).
    - Validate custom dates with `datetime.strptime(..., "%Y-%m-%d")`;
      on failure, fall back to `all` (do not raise). If `from` is
      after `to`, swap them or fall back to `all`.
    - Query expenses for the logged-in user inside the resolved
      window using a parameterised `SELECT` ordered by `date DESC,
      id DESC`.
    - Compute `total_spent` (sum of amounts), `txn_count`
      (`len(expenses)` or a `COUNT(*)` query), and
      `top_category` + `top_category_amount` (category with the
      highest sum in the window; `None` / empty string when the
      list is empty).
    - Compute `category_breakdown` — a list of
      `{label, amount, pct}` dicts ordered by `amount` descending,
      where `pct` is `amount / total_spent * 100` (0 when total is
      0).
    - Build a human readable `range_label` (e.g. "Last 30 days
      (Mar 30 — Apr 29, 2026)") for display.
    - Pass `range`, `from_date`, `to_date`, `range_label`,
      `expenses`, `total_spent`, `txn_count`, `top_category`,
      `top_category_amount`, and `category_breakdown` to
      `render_template`.
  - Do not change `POST /profile` or `POST /profile/password`.
- `templates/profile.html` — wire the variables above into the
  existing layout (see **Templates** section).
- `static/css/style.css` — add filter-bar styles.

## Files to create
None.

## New dependencies
No new dependencies. `datetime` and `sqlite3` are already in use.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only.
- Parameterised queries only — never interpolate user input
  (including `from` / `to` values) into SQL. Use `?` placeholders.
- Passwords hashed with `werkzeug.security.generate_password_hash`
  and verified with `check_password_hash` (unchanged from Step 4).
- Use CSS variables from `static/css/style.css` — never hardcode
  hex values.
- All templates extend `base.html`.
- Protect every profile route with the existing `login_required`
  decorator.
- Always scope expense queries by `WHERE user_id = ?` using
  `session["user_id"]` — never trust query string or form input
  for identity. A user must never be able to see another user's
  expenses by tampering with `range`, `from`, or `to`.
- Validate `range` against an allow-list:
  `{"all", "7d", "30d", "60d", "90d", "month", "custom"}`. Anything else falls
  back to `all`.
- Validate `from` / `to` with `datetime.strptime(..., "%Y-%m-%d")`.
  Reject strings that do not parse — fall back to `all`. Never
  pass raw user-supplied date strings into SQL without parsing
  first.
- Use today's date from `datetime.now()` (or `date.today()`) when
  resolving `7d`, `30d`, `60d`, `90d`  and `month`. Do not hardcode dates.
- The date column in `expenses` is stored as `TEXT` in
  `YYYY-MM-DD` format — string comparison with `BETWEEN ? AND ?`
  is correct and must be used (no Python-side filtering of all
  rows).
- The transactions table must show an empty state when the
  filtered list is empty — never render an empty `<tbody>` with no
  message.
- Format `expense.date` for display (e.g. "Apr 18, 2026") in the
  template using a Jinja filter or a Python-side formatting step
  — do not show the raw `YYYY-MM-DD` value.
- The amount column must display as currency with two decimals
  (e.g. `$22.30`).
- Category badges must continue to use the existing
  `txn-category--<slug>` classes; lowercase the category name to
  build the slug.
- The active preset pill must be visually marked
  (`.filter-pill--active`) based on the resolved `range`, so the
  UI matches the URL after a page load or share.
- Custom range inputs must round-trip — when the URL has
  `range=custom&from=...&to=...`, the inputs must show those
  values on render.

## Definition of done
- [ ] `GET /profile` (no query string) renders all of the user's
      expenses, with `total_spent`, `txn_count`, `top_category`,
      and `category_breakdown` computed from the database — not
      hardcoded
- [ ] `GET /profile?range=7d` shows only expenses dated within the
      last 7 days (inclusive of today) and the stat cards / category
      breakdown reflect the same window
- [ ] `GET /profile?range=30d` shows only expenses from the last 30
      days and the stat cards / category breakdown reflect the same
      window
- [ ] `GET /profile?range=60d` shows only expenses from the last 60
      days and the stat cards / category breakdown reflect the same
      window
- [ ] `GET /profile?range=90d` shows only expenses from the last 90
      days and the stat cards / category breakdown reflect the same
      window
- [ ] `GET /profile?range=month` shows only expenses dated in the
      current calendar month
- [ ] `GET /profile?range=custom&from=2026-04-01&to=2026-04-15`
      shows only expenses between those dates inclusive, and the
      `from` / `to` date inputs show those values when the page
      re-renders
- [ ] Submitting the custom range form updates the URL query string
      and the page re-renders with the new window without a full
      backend round-trip error
- [ ] An invalid `range` value (e.g. `?range=hack`) falls back to
      `all` instead of raising an error
- [ ] An invalid or non-parseable `from` / `to` (e.g.
      `?range=custom&from=abc&to=xyz`) falls back to `all` instead
      of raising an error
- [ ] When the filter window has zero expenses, the transactions
      card shows an empty state (e.g. "No transactions in this
      range"), and the stat cards show `$0.00`, `0`, `—`
      respectively — without crashing or dividing by zero in the
      category breakdown
- [ ] The active preset pill is visually highlighted to match the
      resolved `range` after page load
- [ ] A second user's expenses never appear under user A's profile,
      regardless of query string tampering
- [ ] Anonymous users visiting `/profile?range=...` are still
      redirected to `/login` with the existing flash message
- [ ] App starts without errors
- [ ] Registration, login, logout, profile update, and password
      change flows still work end-to-end
- [ ] No existing functionality is broken
