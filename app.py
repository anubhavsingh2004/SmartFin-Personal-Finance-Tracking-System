"""Main Flask application for SmartFin."""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models.expense_model import expense_categorizer
from utils.database import get_db_connection, init_db, seed_demo_account
from utils.ml_utils import (
    build_chart_payload,
    calculate_summary,
    detect_overspending,
    generate_financial_suggestions,
)


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SMARTFIN_SECRET_KEY", "smartfin-dev-secret-key")


def login_required(view_function):
    """Redirect unauthenticated users to the login page."""

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapped_view


def fetch_user_transactions(user_id: int) -> list[dict]:
    """Return a user's transactions as dictionaries."""
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT id, user_id, amount, category, type, description, date
        FROM transactions
        WHERE user_id = ?
        ORDER BY date DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def build_model_notes(prediction: dict, overspending: dict) -> list[dict]:
    """Return concise logic notes for demo and viva explanations."""
    prediction_status = prediction.get("status", "unknown")
    readable_prediction = {
        "predicted": "Linear Regression is trained on monthly expense totals to estimate the next month's spending.",
        "limited-history": "There is only limited history, so SmartFin uses the latest monthly total as the forecast baseline.",
        "no-expenses": "Prediction will appear after expense history is available.",
        "insufficient-data": "Add transactions across multiple months to unlock forecasting.",
        "invalid-dates": "Prediction is skipped until transaction dates are stored in valid YYYY-MM-DD format.",
    }.get(prediction_status, "Prediction is generated from historical monthly expense data.")

    return [
        {
            "title": "Expense Categorization",
            "detail": "Descriptions are transformed into TF-IDF features and classified with Multinomial Naive Bayes.",
        },
        {
            "title": "Expense Prediction",
            "detail": readable_prediction,
        },
        {
            "title": "Overspending Rule",
            "detail": f"A rule-based check compares expenses against income. Current expense ratio: {overspending['ratio']:.2f}%.",
        },
    ]


@app.route("/")
@login_required
def dashboard():
    user_id = int(session["user_id"])
    transactions = fetch_user_transactions(user_id)
    chart_payload = build_chart_payload(transactions)
    summary = calculate_summary(transactions)
    overspending = detect_overspending(transactions)
    suggestions = generate_financial_suggestions(transactions)
    recent_transactions = transactions[:5]

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name", "User"),
        summary=summary,
        overspending=overspending,
        suggestions=suggestions,
        prediction=chart_payload["prediction"],
        recent_transactions=recent_transactions,
        model_notes=build_model_notes(chart_payload["prediction"], overspending),
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, email, password, confirm_password]):
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        connection = get_db_connection()
        existing_user = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing_user:
            connection.close()
            flash("An account with this email already exists.", "danger")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)
        connection.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (name, email, hashed_password),
        )
        connection.commit()
        connection.close()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_db_connection()
        user = connection.execute(
            "SELECT id, name, email, password FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        connection.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/demo-login")
def demo_login():
    connection = get_db_connection()
    user = connection.execute(
        "SELECT id, name FROM users WHERE email = ?",
        ("demo@smartfin.com",),
    ).fetchone()
    connection.close()

    if user is None:
        flash("Demo account is not available right now.", "danger")
        return redirect(url_for("login"))

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    flash("Logged in with the SmartFin demo account.", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/add_transaction", methods=["GET", "POST"])
@login_required
def add_transaction():
    predicted_category = None

    if request.method == "POST":
        amount = request.form.get("amount", "0").strip()
        category = request.form.get("category", "").strip()
        transaction_type = request.form.get("type", "Expense").strip()
        description = request.form.get("description", "").strip()
        date_value = request.form.get("date", "").strip()

        try:
            amount_value = float(amount)
            if amount_value < 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a valid non-negative number.", "danger")
            return render_template("add_transaction.html", predicted_category=predicted_category)

        if not description or not date_value:
            flash("Description and date are required.", "danger")
            return render_template("add_transaction.html", predicted_category=predicted_category)

        try:
            datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError:
            flash("Date must be in YYYY-MM-DD format.", "danger")
            return render_template("add_transaction.html", predicted_category=predicted_category)

        if transaction_type == "Expense":
            predicted_category = expense_categorizer.predict_category(description)
            category = category or predicted_category
        else:
            category = category or "Income"

        connection = get_db_connection()
        connection.execute(
            """
            INSERT INTO transactions (user_id, amount, category, type, description, date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session["user_id"], amount_value, category, transaction_type, description, date_value),
        )
        connection.commit()
        connection.close()

        if transaction_type == "Expense":
            expense_categorizer.retrain_with_latest_data()

        flash(f"Transaction added successfully under {category}.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_transaction.html", predicted_category=predicted_category)


@app.route("/reports")
@login_required
def reports():
    user_id = int(session["user_id"])
    transactions = fetch_user_transactions(user_id)
    chart_payload = build_chart_payload(transactions)
    summary = calculate_summary(transactions)
    suggestions = generate_financial_suggestions(transactions)
    overspending = detect_overspending(transactions)

    return render_template(
        "reports.html",
        summary=summary,
        suggestions=suggestions,
        overspending=overspending,
        chart_payload=chart_payload,
        transactions=transactions[:15],
        model_notes=build_model_notes(chart_payload["prediction"], overspending),
    )


@app.route("/api/chart_data")
@login_required
def chart_data():
    user_id = int(session["user_id"])
    transactions = fetch_user_transactions(user_id)
    return jsonify(build_chart_payload(transactions))


@app.route("/api/transactions")
@login_required
def get_transactions():
    user_id = int(session["user_id"])
    return jsonify(fetch_user_transactions(user_id))


def bootstrap() -> None:
    """Initialize the database before the server starts."""
    init_db()
    seed_demo_account()


bootstrap()


if __name__ == "__main__":
    app.run(debug=True)