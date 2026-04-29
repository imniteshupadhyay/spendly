# Spec: Profile Page

## Overview
The Profile Page gives logged-in users a single place to view their
account details (name, email, member-since date), with a fully designed profile page showing static, hardcoded data. The goal is to establish the complete UI layout — user info card, transaction history table, summary stats, and category breakdown — before any real database queries are wired up in Step 5. Building the UI first lets the team validate the design in isolation and ensures the templates are ready for the backend-connection step.
and update user info part. It
replaces the placeholder string currently returned by `GET /profile`
and is the first authenticated, user-specific page in Spendly. It
establishes the patterns — protected route, form POST, database

## Depends on
- Step 1: Database Setup (complete)
- Step 2: Registration (complete)
- Step 3: Login and Logout (complete)

## Routes
- `GET /profile` — render the profile page with the current user's
  details — logged-in and this should be the first page after login.
- `POST /profile` — update the logged-in user's name and/or email,
  redirect back to `/profile` with a flash message — logged-in
- `POST /profile/password` — change the logged-in user's password,
  redirect back to `/profile` with a flash message — logged-in

## Database changes
No database changes. The existing `users` table already has `id`,
`name`, `email`, `password_hash`, and `created_at`, which covers
every field needed to display and update a profile.

## Templates
- **Create:** `templates/profile.html` — profile page extending
  `base.html`. Shows the user's name, email, and "Member since"
  (formatted `created_at`). Contains two forms:
  1. Update profile form (name, email)
  2. Change password form (current password, new password)
  Both display per-section error and success messages.
- **Modify:** `templates/base.html` — add a "Profile" link to the
  logged-in side of the navbar (next to the greeting / Sign out).
  3. **Summary stats row** — total spent, number of transactions, top category (hardcoded)
  4. **Transaction history table** — list of recent expenses with date, description, category badge, amount (hardcoded rows)
  5. **Category breakdown** — per-category totals displayed as a simple list or progress-bar rows (hardcoded)

## Files to change
- `app.py`
  - Replace the placeholder `profile()` route with a real
    `GET /profile` handler that loads the logged-in user from the
    database and renders `profile.html`.
  - Add `POST /profile` handler that validates and updates name and
    email, handles duplicate-email `IntegrityError`, keeps
    `session["user_name"]` in sync, and redirects back to `/profile`
    with a flash message.
  - Add `POST /profile/password` handler that verifies the current
    password with `check_password_hash`, validates the new password
    (min 8 chars), hashes it with `generate_password_hash`, updates
    the row, and redirects back to `/profile` with a flash message.
  - All three handlers must use the existing `login_required`
    decorator.
- `templates/base.html` — add a "Profile" nav link shown only when
  `logged_in`.
- `static/css/style.css` — add styles for the profile layout (card,
  field rows, two-column forms). Reuse existing CSS variables — do
  not introduce new hex colours.

## Files to create
- `templates/profile.html`

## New dependencies
No new dependencies. `werkzeug.security`, `flask.session`,
`flask.flash`, and `sqlite3` are already in use.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only.
- Parameterised queries only — never interpolate user input into SQL.
- Passwords hashed with `werkzeug.security.generate_password_hash`
  and verified with `check_password_hash`.
- Use CSS variables from `static/css/style.css` — never hardcode
  hex values.
- All templates extend `base.html`.
- Protect every profile route with the existing `login_required`
  decorator.
- Load the user with `SELECT id, name, email, created_at FROM users
  WHERE id = ?` using `session["user_id"]` — never trust form input
  for identity.
- Server-side validation for profile update:
  - Name: required, stripped, max 100 characters.
  - Email: required, must contain `@`, max 254 characters, stored
    lowercased.
- Server-side validation for password change:
  - Current password must match the stored hash.
  - New password: min 8 characters.
  - New password must differ from current password.
- On duplicate-email `sqlite3.IntegrityError` during update, re-render
  the profile with a friendly error — do not expose a stack trace.
- After a successful name change, update `session["user_name"]` so
  the navbar greeting stays correct.
- Never display the password hash in the template or session.
- Use Flask's `flash()` with a category when possible (e.g.
  `flash("Profile updated.", "success")`) so error and success
  states can be styled differently later; if categories are not yet
  rendered in `base.html`, a plain message is acceptable.
- Format `created_at` for display (e.g. "April 2026") using a Jinja
  filter or a Python-side formatting step — do not show the raw
  SQLite timestamp.

## Definition of done
- [ ] `GET /profile` renders `templates/profile.html` with the
      logged-in user's name, email, and formatted "Member since" date
- [ ] Anonymous users visiting `/profile` are redirected to `/login`
      with flash message "Please sign in to continue."
- [ ] `POST /profile` updates the user's name and email in the
      database
- [ ] After a name update, the navbar greeting reflects the new name
      immediately (same request cycle / next page load)
- [ ] Submitting an empty name, invalid email, or over-length value
      shows a validation error and does not update the database
- [ ] Submitting an email already used by another account shows a
      friendly error, not a stack trace
- [ ] `POST /profile/password` changes the password when the current
      password is correct and the new password is valid
- [ ] Wrong current password shows an error and does not update the
      hash
- [ ] New password shorter than 8 characters shows an error
- [ ] After a successful password change, the user can log out and
      log back in with the new password
- [ ] Navbar shows a "Profile" link for logged-in users and does not
      show it for anonymous users
- [ ] Password field values are never retained across form submissions
- [ ] App starts without errors
- [ ] Registration, login, and logout flows still work end-to-end
- [ ] No existing functionality is broken
