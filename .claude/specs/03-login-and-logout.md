# Spec: Login and Logout

## Overview
Login and logout give registered users the ability to authenticate and
maintain a session while using Spendly. Login validates credentials
against the database; logout clears the session. Together they gate
every feature from Step 4 onward behind authentication.

## Depends on
- Step 1: Database Setup (complete)
- Step 2: Registration (complete)

## Routes
- `POST /login` — validate credentials, create session, redirect to
  dashboard — public
- `GET /logout` — clear session, redirect to landing page — logged-in

## Database changes
No database changes. The `users` table already contains `id`, `email`,
and `password_hash` which are sufficient for authentication.

## Templates
- **Modify:** `templates/login.html` — add value retention for the
  email field on failed login and give show eye icon for passowrd also so users don't have to retype it.
- **Modify:** `templates/base.html` — make the navbar context-aware:
  show "Sign in / Get started" links for anonymous users and
  "Logout" for logged-in users. Display flash messages for both
  success and error categories.

## Files to change
- `app.py`
  - Import `session` from Flask and `check_password_hash` from
    `werkzeug.security`.
  - Add `POST /login` handler: look up user by email, verify password
    hash, store `user_id` and `user_name` in `session`, redirect to
    `/` (landing for now — dashboard will come in a later step).
  - Implement `GET /logout`: clear session with `session.clear()`,
    flash a goodbye message, redirect to `/`.
  - Add a `login_required` decorator that checks `session["user_id"]`
    and redirects to `/login` with a flash message when missing.
    Apply it to `/logout` and `/profile` placeholder.
  - Update the `register` success redirect: after creating the account,
    redirect to `/login` (already done).
  - Inject `logged_in` and `user_name` into every template via
    `@app.context_processor`.
- `templates/login.html` — retain email value on error; display error
  message returned by the POST handler.
- `templates/base.html` — conditionally render nav links based on
  `logged_in` context variable.

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security.check_password_hash` and
`flask.session` are already available.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only.
- Parameterised queries only — never interpolate user input into SQL.
- Passwords checked with `werkzeug.security.check_password_hash`.
- Use CSS variables from the existing stylesheet — never hardcode hex
  values.
- All templates extend `base.html`.
- On failed login, show a single generic message:
  "Invalid email or password." — do not reveal whether the email
  exists.
- Store only `user_id` and `user_name` in the Flask session — never
  store the password or hash.
- The `login_required` decorator must use `functools.wraps` to
  preserve the wrapped function's name.
- `app.secret_key` is already set via `os.urandom(24)`.
- After login, redirect to `/` (the landing page for now; a dashboard
  route will replace this in a future step).
- After logout, flash "You have been signed out." and redirect to `/`.

## Definition of done
- [ ] `POST /login` with valid credentials sets `session["user_id"]`
      and `session["user_name"]` and redirects to `/`
- [ ] `POST /login` with wrong password shows "Invalid email or
      password." without revealing which field was wrong
- [ ] `POST /login` with non-existent email shows the same generic
      error message
- [ ] Email field retains its value after a failed login attempt
- [ ] `GET /logout` clears the session and redirects to `/` with
      flash message "You have been signed out."
- [ ] Navbar shows "Sign in / Get started" for anonymous visitors
- [ ] Navbar shows user's name and "Logout" link for logged-in users
- [ ] `login_required` decorator redirects unauthenticated users to
      `/login` with flash message "Please sign in to continue."
- [ ] `/logout` is protected by `login_required`
- [ ] App starts without errors
- [ ] Registration flow still works end-to-end
- [ ] No existing functionality is broken
