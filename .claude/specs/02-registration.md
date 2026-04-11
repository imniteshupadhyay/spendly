# Spec: Registration

## Overview
User registration allows new visitors to create a Spendly account by
providing their name, email, and password. This is the first user-facing
feature that writes to the database and is a prerequisite for login,
profile, and all expense-management steps that follow.

## Depends on
- Step 1: Database Setup (complete)

## Routes
- `GET /register` — render the registration form — public
- `POST /register` — validate input, create user, redirect to login — public

## Database changes
No database changes. The `users` table already exists with the required
schema (id, name, email, password_hash, created_at).

## Templates
- **Modify:** `templates/register.html` — add value retention on validation
  failure so fields are re-populated with the user's previous input
  (name and email only, never password).
- **Modify:** `templates/base.html` — add support for `flash` messages so
  a success message can be shown after registration redirects to login.

## Files to change
- `app.py` — split `/register` into GET and POST handlers with validation,
  password hashing, duplicate-email handling, and redirect to `/login` on
  success with a flash message.
- `templates/register.html` — retain form values on error, display error
  messages.
- `templates/base.html` — render flash messages.

## Files to create
None.

## New dependencies
None. `werkzeug.security` and `flask` (including `flash`, `redirect`,
`request`, `url_for`) are already available.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only.
- Parameterised queries only — never interpolate user input into SQL.
- Hash passwords with `werkzeug.security.generate_password_hash`.
- Use CSS variables from the existing stylesheet — never hardcode hex values.
- All templates extend `base.html`.
- Flask `flash()` requires a `secret_key` on the app — set
  `app.secret_key` using `os.urandom(24)` (or a constant dev key if one
  is already defined).
- Server-side validation rules:
  - Name: required, max 100 characters, stripped of leading/trailing whitespace.
  - Email: required, must contain `@`, max 254 characters, lowercased before storage.
  - Password: required, minimum 8 characters.
- On validation failure, re-render the form with the error message and
  previously entered name and email (never the password).
- On duplicate email (`UNIQUE` constraint violation), show a friendly error
  — do not expose a stack trace.
- On success, redirect to `/login` with a flash message:
  "Account created — please sign in."

## Definition of done
- [ ] `GET /register` renders the registration form
- [ ] `POST /register` with valid data creates a user in the database
- [ ] Password is stored as a werkzeug hash, never in plain text
- [ ] Submitting with an empty name, email, or short password shows a
      validation error without creating a user
- [ ] Submitting with a duplicate email shows a friendly error message
- [ ] After successful registration, user is redirected to `/login`
- [ ] Flash message "Account created — please sign in." appears on the
      login page after redirect
- [ ] Name and email fields retain their values when the form is
      re-displayed after a validation error
- [ ] App starts without errors
- [ ] No existing functionality is broken
