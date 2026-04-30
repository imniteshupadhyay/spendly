import functools
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db

app = Flask(__name__)
app.secret_key = os.urandom(24)

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_auth():
    return {
        "logged_in": "user_id" in session,
        "user_name": session.get("user_name", ""),
    }


VALID_RANGES = {"all", "7d", "30d", "60d", "90d", "month", "custom"}
PRESET_DAYS = {"7d": 7, "30d": 30, "60d": 60, "90d": 90}


def _format_window_label(prefix, start, end):
    return f"{prefix} ({start.strftime('%b %d')} — {end.strftime('%b %d, %Y')})"


def resolve_range(args):
    range_key = args.get("range", "all")
    if range_key not in VALID_RANGES:
        range_key = "all"

    today = date.today()

    if range_key in PRESET_DAYS:
        days = PRESET_DAYS[range_key]
        end = today
        start = end - timedelta(days=days - 1)
        return range_key, start, end, _format_window_label(f"Last {days} days", start, end)

    if range_key == "month":
        start = today.replace(day=1)
        end = today
        return range_key, start, end, _format_window_label("This month", start, end)

    if range_key == "custom":
        try:
            start = datetime.strptime(args.get("from", ""), "%Y-%m-%d").date()
            end = datetime.strptime(args.get("to", ""), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return "all", None, None, "All time"
        if start > end:
            start, end = end, start
        return range_key, start, end, _format_window_label("Custom range", start, end)

    return "all", None, None, "All time"


def load_profile_view_data(db, user_id, args):
    range_key, start, end, range_label = resolve_range(args)

    if start is None:
        rows = db.execute(
            "SELECT id, amount, category, date, description "
            "FROM expenses WHERE user_id = ? "
            "ORDER BY date DESC, id DESC",
            (user_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, amount, category, date, description "
            "FROM expenses WHERE user_id = ? AND date BETWEEN ? AND ? "
            "ORDER BY date DESC, id DESC",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()

    expenses = []
    category_totals = {}
    total_spent = 0.0

    for row in rows:
        try:
            date_display = datetime.strptime(row["date"], "%Y-%m-%d").strftime("%b %d, %Y")
        except (ValueError, TypeError):
            date_display = row["date"] or ""

        amount = row["amount"] or 0.0
        category = row["category"] or "Other"
        total_spent += amount
        category_totals[category] = category_totals.get(category, 0.0) + amount

        expenses.append({
            "id": row["id"],
            "amount": amount,
            "category": category,
            "category_slug": category.lower(),
            "date": row["date"],
            "date_display": date_display,
            "description": row["description"] or "",
        })

    sorted_categories = sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)
    if sorted_categories:
        top_category, top_category_amount = sorted_categories[0]
    else:
        top_category, top_category_amount = None, 0.0

    category_breakdown = [
        {
            "label": label,
            "amount": amt,
            "pct": (amt / total_spent * 100) if total_spent else 0,
        }
        for label, amt in sorted_categories
    ]

    return {
        "range": range_key,
        "from_date": args.get("from", "") if range_key == "custom" else "",
        "to_date": args.get("to", "") if range_key == "custom" else "",
        "range_label": range_label,
        "expenses": expenses,
        "total_spent": total_spent,
        "txn_count": len(expenses),
        "top_category": top_category,
        "top_category_amount": top_category_amount,
        "category_breakdown": category_breakdown,
    }


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or len(name) > 100:
        return render_template("register.html", error="Name is required (max 100 characters).", name=name, email=email)

    if not email or "@" not in email or len(email) > 254:
        return render_template("register.html", error="A valid email address is required.", name=name, email=email)

    if len(password) < 8:
        return render_template("register.html", error="Password must be at least 8 characters.", name=name, email=email)

    password_hash = generate_password_hash(password)

    try:
        db = get_db()
        db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        db.commit()
        db.close()
    except sqlite3.IntegrityError:
        return render_template("register.html", error="An account with that email already exists.", name=name, email=email)

    flash("Account created — please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    db = get_db()
    user = db.execute(
        "SELECT id, name, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    db.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.", email=email)

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been signed out.")
    return redirect(url_for("landing"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    user = db.execute(
        "SELECT id, name, email, created_at FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()

    if not user:
        db.close()
        session.clear()
        flash("Please sign in to continue.")
        return redirect(url_for("login"))

    try:
        member_since = datetime.strptime(
            user["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%B %Y")
    except (ValueError, TypeError):
        member_since = ""

    if request.method == "GET":
        view_data = load_profile_view_data(db, session["user_id"], request.args)
        db.close()
        return render_template(
            "profile.html",
            user=user,
            member_since=member_since,
            **view_data,
        )

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()

    def rerender(msg):
        view_data = load_profile_view_data(db, session["user_id"], request.args)
        db.close()
        return render_template(
            "profile.html",
            user=user,
            member_since=member_since,
            error_profile=msg,
            form_name=name,
            form_email=email,
            **view_data,
        )

    if not name or len(name) > 100:
        return rerender("Name is required (max 100 characters).")
    if not email or "@" not in email or len(email) > 254:
        return rerender("A valid email address is required.")

    try:
        db.execute(
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            (name, email, session["user_id"]),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return rerender("That email is already in use.")

    session["user_name"] = name
    db.close()
    flash("Profile updated.")
    return redirect(url_for("profile"))


@app.route("/profile/password", methods=["POST"])
@login_required
def profile_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")

    db = get_db()
    user = db.execute(
        "SELECT id, name, email, password_hash, created_at FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()

    def rerender(msg):
        try:
            member_since = datetime.strptime(
                user["created_at"], "%Y-%m-%d %H:%M:%S"
            ).strftime("%B %Y")
        except (ValueError, TypeError):
            member_since = ""
        view_data = load_profile_view_data(db, session["user_id"], request.args)
        db.close()
        return render_template(
            "profile.html",
            user=user,
            member_since=member_since,
            error_password=msg,
            **view_data,
        )

    if not user or not check_password_hash(user["password_hash"], current):
        return rerender("Current password is incorrect.")
    if len(new) < 8:
        return rerender("New password must be at least 8 characters.")
    if check_password_hash(user["password_hash"], new):
        return rerender("New password must differ from the current password.")

    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new), session["user_id"]),
    )
    db.commit()
    db.close()
    flash("Password changed.")
    return redirect(url_for("profile"))


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
