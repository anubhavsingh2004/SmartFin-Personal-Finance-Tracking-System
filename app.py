"""Main Flask application for SmartFin."""

from __future__ import annotations

import os
import csv
import smtplib
import time
import re
from threading import Lock
from io import BytesIO, StringIO
from datetime import datetime
from email.message import EmailMessage
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

from utils.database import (
    DEFAULT_CATEGORY_BUDGETS,
    fetch_user_category_budgets,
    get_db_connection,
    init_db,
    seed_demo_account,
    seed_user_budgets,
    update_user_category_budgets,
)
from utils.ai_insights import generate_ai_response, generate_personalized_suggestions
from utils.ml_utils import (
    auto_categorize,
    build_chart_payload,
    calculate_summary,
    check_budget_threshold_alerts,
    check_overspending,
    collect_new_budget_crossings,
    generate_financial_suggestions,
    get_ai_suggestions,
    predict_monthly_expense,
)


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SMARTFIN_SECRET_KEY", "smartfin-dev-secret-key")

EMAIL_REPORT_COOLDOWN_SECONDS = 10
_email_report_cooldowns: dict[int, float] = {}
_email_report_cooldown_lock = Lock()


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


def fetch_transaction_by_id(user_id: int, transaction_id: int) -> dict | None:
    """Return one transaction for the current user or None when not found."""
    connection = get_db_connection()
    row = connection.execute(
        """
        SELECT id, user_id, amount, category, type, description, date
        FROM transactions
        WHERE id = ? AND user_id = ?
        """,
        (transaction_id, user_id),
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def fetch_user_profile(user_id: int) -> dict | None:
    """Return minimal profile fields needed for notifications."""
    connection = get_db_connection()
    row = connection.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def resolve_report_month(raw_month: str | None) -> str:
    """Normalize report month input to YYYY-MM, defaulting to current month."""
    month_value = (raw_month or "").strip()
    if not month_value:
        return datetime.today().strftime("%Y-%m")

    try:
        datetime.strptime(month_value, "%Y-%m")
    except ValueError:
        return datetime.today().strftime("%Y-%m")

    return month_value


def format_month_year(month_value: str) -> str:
    """Convert YYYY-MM into Mon-YYYY (example: 2026-03 -> Mar-2026)."""
    try:
        parsed = datetime.strptime(month_value, "%Y-%m")
    except ValueError:
        return month_value
    return parsed.strftime("%b-%Y")


def resolve_report_year(raw_year: str | None) -> str:
    """Normalize report year input to YYYY, defaulting to current year."""
    year_value = (raw_year or "").strip()
    if not year_value:
        return datetime.today().strftime("%Y")

    if not re.fullmatch(r"\d{4}", year_value):
        return datetime.today().strftime("%Y")

    try:
        datetime.strptime(year_value, "%Y")
    except ValueError:
        return datetime.today().strftime("%Y")

    return year_value


def resolve_report_type(raw_report_type: str | None) -> str:
    """Return a supported report type value."""
    report_type = (raw_report_type or "monthly").strip().lower()
    return "yearly" if report_type == "yearly" else "monthly"


def available_report_years(transactions: list[dict]) -> list[str]:
    """Return available years from transactions plus current year, newest first."""
    years = {datetime.today().strftime("%Y")}
    for item in transactions:
        date_value = str(item.get("date", ""))
        if len(date_value) >= 4 and date_value[:4].isdigit():
            years.add(date_value[:4])
    return sorted(years, reverse=True)


def filter_transactions_by_month(transactions: list[dict], month: str) -> list[dict]:
    """Return only transactions whose date falls in the provided YYYY-MM month."""
    month_prefix = f"{month}-"
    return [item for item in transactions if str(item.get("date", "")).startswith(month_prefix)]


def filter_transactions_by_year(transactions: list[dict], year: str) -> list[dict]:
    """Return only transactions whose date falls in the provided YYYY year."""
    year_prefix = f"{year}-"
    return [item for item in transactions if str(item.get("date", "")).startswith(year_prefix)]


def build_category_breakdown(transactions: list[dict]) -> list[dict]:
    """Aggregate expense totals by category, sorted descending by amount."""
    totals: dict[str, float] = {}
    for transaction in transactions:
        if str(transaction.get("type", "")) != "Expense":
            continue
        category = str(transaction.get("category", "Other")) or "Other"
        amount = float(transaction.get("amount", 0.0) or 0.0)
        totals[category] = totals.get(category, 0.0) + amount

    return [
        {"category": category, "amount": round(amount, 2)}
        for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def build_yearly_monthly_trend(transactions: list[dict], year: str) -> list[dict]:
    """Build expense trend for all months in a selected year."""
    monthly_totals = {index: 0.0 for index in range(1, 13)}

    for transaction in transactions:
        if str(transaction.get("type", "")) != "Expense":
            continue
        date_value = str(transaction.get("date", ""))
        try:
            parsed_date = datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError:
            continue
        if parsed_date.strftime("%Y") != year:
            continue

        monthly_totals[parsed_date.month] += float(transaction.get("amount", 0.0) or 0.0)

    return [
        {
            "month": datetime(int(year), month_number, 1).strftime("%b"),
            "amount": round(monthly_totals[month_number], 2),
        }
        for month_number in range(1, 13)
    ]


def build_report_csv(
    user_name: str,
    report_type: str,
    period_label: str,
    summary: dict,
    transactions: list[dict],
    suggestions: list[str],
    category_breakdown: list[dict],
    monthly_trend: list[dict],
) -> str:
    """Create report CSV content for monthly or yearly periods."""
    output = StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow(["SmartFin Financial Report"])
    writer.writerow(["User", user_name])
    writer.writerow(["Report Type", report_type.title()])
    writer.writerow(["Period", period_label])
    writer.writerow(["Title", f"Financial Report - {period_label}"])
    writer.writerow([])

    writer.writerow(["Summary"])
    writer.writerow(["Total Income", f"{summary['total_income']:.2f}"])
    writer.writerow(["Total Expenses", f"{summary['total_expenses']:.2f}"])
    writer.writerow(["Balance", f"{summary['balance']:.2f}"])
    writer.writerow(["Savings Rate (%)", f"{summary['savings_rate']:.2f}"])
    writer.writerow([])

    writer.writerow(["Suggestions"])
    if suggestions:
        for suggestion in suggestions:
            writer.writerow([suggestion])
    else:
        writer.writerow([f"No suggestions available for this {report_type} period."])
    writer.writerow([])

    writer.writerow(["Category-wise Breakdown"])
    writer.writerow(["Category", "Total Expense"])
    if category_breakdown:
        for item in category_breakdown:
            writer.writerow([item["category"], f"{float(item['amount']):.2f}"])
    else:
        writer.writerow(["No expense categories available", "0.00"])
    writer.writerow([])

    if report_type == "yearly":
        writer.writerow(["Monthly Trend (Expenses)"])
        writer.writerow(["Month", "Amount"])
        for item in monthly_trend:
            writer.writerow([item["month"], f"{float(item['amount']):.2f}"])
        writer.writerow([])

    writer.writerow(["Transactions"])
    writer.writerow(["Date", "Description", "Category", "Type", "Amount"])
    for transaction in transactions:
        writer.writerow(
            [
                transaction.get("date", ""),
                transaction.get("description", ""),
                transaction.get("category", ""),
                transaction.get("type", ""),
                f"{float(transaction.get('amount', 0.0)):.2f}",
            ]
        )

    if not transactions:
        writer.writerow(["-", f"No transactions available for this {report_type} report", "-", "-", "0.00"])

    return output.getvalue()


def generate_report(
    user_name: str,
    transactions: list[dict],
    report_type: str,
    selected_month: str,
    selected_year: str,
) -> dict:
    """Build shared report data used by UI, export, and email flows."""
    if report_type == "yearly":
        scoped_transactions = filter_transactions_by_year(transactions, selected_year)
        period_label = selected_year
        file_period_label = selected_year
        monthly_trend = build_yearly_monthly_trend(scoped_transactions, selected_year)
    else:
        scoped_transactions = filter_transactions_by_month(transactions, selected_month)
        period_label = format_month_year(selected_month)
        file_period_label = period_label
        monthly_trend = []

    scoped_summary = calculate_summary(scoped_transactions)
    suggestions = generate_financial_suggestions(scoped_transactions)
    category_breakdown = build_category_breakdown(scoped_transactions)
    csv_content = build_report_csv(
        user_name=user_name,
        report_type=report_type,
        period_label=period_label,
        summary=scoped_summary,
        transactions=scoped_transactions,
        suggestions=suggestions,
        category_breakdown=category_breakdown,
        monthly_trend=monthly_trend,
    )

    filename = f"smartfin-{report_type}-report-{file_period_label.lower()}.csv"
    return {
        "report_type": report_type,
        "period_label": period_label,
        "summary": scoped_summary,
        "transactions": scoped_transactions,
        "suggestions": suggestions,
        "category_breakdown": category_breakdown,
        "monthly_trend": monthly_trend,
        "csv_content": csv_content,
        "filename": filename,
        "title": f"Financial Report - {period_label}",
    }


def _smtp_config() -> dict:
    """Return SMTP configuration loaded from environment variables."""
    return {
        "host": os.environ.get("SMARTFIN_SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMARTFIN_SMTP_PORT", "587")),
        "username": os.environ.get("SMARTFIN_SMTP_USERNAME", "").strip(),
        "password": os.environ.get("SMARTFIN_SMTP_PASSWORD", "").strip(),
        "from_email": os.environ.get("SMARTFIN_EMAIL_FROM", "").strip(),
        "use_tls": os.environ.get("SMARTFIN_SMTP_USE_TLS", "true").strip().lower() == "true",
    }


def _is_email_configured() -> bool:
    config = _smtp_config()
    return bool(config["host"] and config["from_email"])


def send_budget_alert_email(user_profile: dict, event: dict) -> bool:
    """Send one budget threshold alert email. Returns True when send succeeds."""
    config = _smtp_config()
    if not _is_email_configured() or not user_profile.get("email"):
        return False

    subject = f"SmartFin Budget Alert: {event['threshold_percent']}% crossed for {event['category']}"
    body = (
        f"Hi {user_profile.get('name', 'User')},\n\n"
        f"{event['message']}\n"
        f"Month: {event['month']}\n"
        f"Category: {event['category']}\n"
        f"Spent: Rs. {event['spent']:.2f}\n"
        f"Budget: Rs. {event['budget']:.2f}\n"
        f"Usage: {event['usage_percent']:.1f}%\n\n"
        "Please review your budget settings and recent transactions in SmartFin.\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from_email"]
    message["To"] = user_profile["email"]
    message.set_content(body)

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
            if config["use_tls"]:
                server.starttls()
            if config["username"] and config["password"]:
                server.login(config["username"], config["password"])
            server.send_message(message)
        return True
    except Exception:
        return False


def send_report_email(user_profile: dict, report_type: str, period_label: str, report_csv: str, summary: dict) -> bool:
    """Email a monthly/yearly CSV report to the current user."""
    config = _smtp_config()
    if not _is_email_configured() or not user_profile.get("email"):
        return False

    subject = f"SmartFin {report_type.title()} Report - {period_label}"
    body = (
        f"Hi {user_profile.get('name', 'User')},\n\n"
        f"Your SmartFin {report_type} report for {period_label} is attached.\n\n"
        f"Summary:\n"
        f"- Total Income: Rs. {summary['total_income']:.2f}\n"
        f"- Total Expenses: Rs. {summary['total_expenses']:.2f}\n"
        f"- Balance: Rs. {summary['balance']:.2f}\n"
        f"- Savings Rate: {summary['savings_rate']:.2f}%\n\n"
        "Thanks for using SmartFin.\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from_email"]
    message["To"] = user_profile["email"]
    message.set_content(body)
    period_slug = period_label.replace(" ", "-").lower()
    message.add_attachment(
        report_csv.encode("utf-8"),
        maintype="text",
        subtype="csv",
        filename=f"smartfin-{report_type}-report-{period_slug}.csv",
    )

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
            if config["use_tls"]:
                server.starttls()
            if config["username"] and config["password"]:
                server.login(config["username"], config["password"])
            server.send_message(message)
        return True
    except Exception:
        return False


def can_send_report_email(user_id: int, cooldown_seconds: int = EMAIL_REPORT_COOLDOWN_SECONDS) -> tuple[bool, int]:
    """Return whether user can send now and remaining cooldown seconds if blocked."""
    now = time.monotonic()
    with _email_report_cooldown_lock:
        last_sent_at = _email_report_cooldowns.get(user_id)
        if last_sent_at is not None:
            elapsed = now - last_sent_at
            if elapsed < cooldown_seconds:
                remaining = int(cooldown_seconds - elapsed)
                return False, max(1, remaining)

        _email_report_cooldowns[user_id] = now
        return True, 0


def can_send_monthly_report_email(user_id: int, cooldown_seconds: int = EMAIL_REPORT_COOLDOWN_SECONDS) -> tuple[bool, int]:
    """Backward-compatible wrapper for monthly email cooldown checks."""
    return can_send_report_email(user_id, cooldown_seconds)


def process_budget_notifications(user_id: int) -> list[dict]:
    """Create in-app and email notifications for newly crossed budget thresholds."""
    new_events = collect_new_budget_crossings(user_id)
    if not new_events:
        return []

    top_event = new_events[0]
    if top_event["threshold_percent"] >= 100:
        flash(f"Critical budget alert: {top_event['message']}", "danger")
    else:
        flash(f"Budget alert: {top_event['message']}", "warning")

    user_profile = fetch_user_profile(user_id)
    if user_profile is None:
        return new_events

    if not _is_email_configured():
        flash("Budget email alerts are disabled. Configure SMARTFIN_SMTP_* and SMARTFIN_EMAIL_FROM to enable them.", "info")
        return new_events

    delivered_count = sum(1 for event in new_events if send_budget_alert_email(user_profile, event))
    if delivered_count > 0:
        flash(f"Email notification sent for {delivered_count} new budget alert(s).", "info")

    return new_events


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
            "detail": "Descriptions are converted into word-count vectors (CountVectorizer) and classified using Multinomial Naive Bayes.",
        },
        {
            "title": "Expense Prediction",
            "detail": readable_prediction,
        },
        {
            "title": "Overspending Rule",
            "detail": f"Current month category spend is compared against the previous 6-month average. Current expense ratio: {overspending['ratio']:.2f}%.",
        },
    ]


@app.route("/")
@login_required
def dashboard():
    user_id = int(session["user_id"])
    transactions = fetch_user_transactions(user_id)
    summary = calculate_summary(transactions)
    overspending_alerts = check_overspending(user_id)
    suggestions = get_ai_suggestions(user_id)
    personalized_suggestions = generate_personalized_suggestions(user_id)
    prediction = predict_monthly_expense(user_id)
    budget_alerts = check_budget_threshold_alerts(user_id)
    recent_transactions = transactions[:5]

    expense_ratio = (summary["total_expenses"] / summary["total_income"] * 100) if summary["total_income"] > 0 else 0.0
    overspending = {
        "is_overspending": bool(overspending_alerts),
        "message": (
            "Your category-wise spending is currently within expected levels."
            if not overspending_alerts
            else overspending_alerts[0]
        ),
        "ratio": round(expense_ratio, 2),
        "alerts": overspending_alerts,
    }

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name", "User"),
        summary=summary,
        overspending=overspending,
        suggestions=suggestions,
        personalized_suggestions=personalized_suggestions,
        prediction=prediction,
        budget_alerts=budget_alerts,
        recent_transactions=recent_transactions,
        model_notes=build_model_notes(prediction, overspending),
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
        created_user_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        connection.commit()
        connection.close()
        seed_user_budgets(created_user_id)

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
            predicted_category = auto_categorize(description)
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

        process_budget_notifications(int(session["user_id"]))

        flash(f"Transaction added successfully under {category}.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_transaction.html", predicted_category=predicted_category)


@app.route("/transaction/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id: int):
    user_id = int(session["user_id"])
    transaction = fetch_transaction_by_id(user_id, transaction_id)

    if transaction is None:
        flash("Transaction not found or you do not have permission to edit it.", "danger")
        return redirect(url_for("reports"))

    predicted_category = auto_categorize(transaction["description"]) if transaction["type"] == "Expense" else None

    if request.method == "POST":
        amount = request.form.get("amount", "0").strip()
        category = request.form.get("category", "").strip()
        transaction_type = request.form.get("type", "Expense").strip()
        description = request.form.get("description", "").strip()
        date_value = request.form.get("date", "").strip()

        editable_transaction = dict(transaction)
        editable_transaction.update(
            {
                "amount": amount,
                "category": category,
                "type": transaction_type,
                "description": description,
                "date": date_value,
            }
        )

        try:
            amount_value = float(amount)
            if amount_value < 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a valid non-negative number.", "danger")
            return render_template(
                "edit_transaction.html",
                transaction=editable_transaction,
                predicted_category=predicted_category,
            )

        if not description or not date_value:
            flash("Description and date are required.", "danger")
            return render_template(
                "edit_transaction.html",
                transaction=editable_transaction,
                predicted_category=predicted_category,
            )

        try:
            datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError:
            flash("Date must be in YYYY-MM-DD format.", "danger")
            return render_template(
                "edit_transaction.html",
                transaction=editable_transaction,
                predicted_category=predicted_category,
            )

        if transaction_type == "Expense":
            predicted_category = auto_categorize(description)
            category = category or predicted_category
        else:
            category = category or "Income"

        connection = get_db_connection()
        connection.execute(
            """
            UPDATE transactions
            SET amount = ?, category = ?, type = ?, description = ?, date = ?
            WHERE id = ? AND user_id = ?
            """,
            (amount_value, category, transaction_type, description, date_value, transaction_id, user_id),
        )
        connection.commit()
        connection.close()

        process_budget_notifications(user_id)

        flash("Transaction updated successfully.", "success")
        next_page = request.form.get("next", "reports").strip().lower()
        if next_page == "dashboard":
            return redirect(url_for("dashboard"))
        return redirect(url_for("reports"))

    return render_template("edit_transaction.html", transaction=transaction, predicted_category=predicted_category)


@app.route("/transaction/<int:transaction_id>/delete", methods=["POST"])
@login_required
def delete_transaction(transaction_id: int):
    user_id = int(session["user_id"])
    transaction = fetch_transaction_by_id(user_id, transaction_id)

    if transaction is None:
        flash("Transaction not found or you do not have permission to delete it.", "danger")
    else:
        connection = get_db_connection()
        connection.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, user_id),
        )
        connection.commit()
        connection.close()
        flash("Transaction deleted successfully.", "success")

    next_page = request.form.get("next", "reports").strip().lower()
    if next_page == "dashboard":
        return redirect(url_for("dashboard"))
    return redirect(url_for("reports"))


@app.route("/reports")
@login_required
def reports():
    user_id = int(session["user_id"])
    report_type = resolve_report_type(request.args.get("report_type"))
    selected_month = resolve_report_month(request.args.get("month"))
    selected_year = resolve_report_year(request.args.get("year"))
    transactions = fetch_user_transactions(user_id)
    report = generate_report(
        user_name=session.get("user_name", "User"),
        transactions=transactions,
        report_type=report_type,
        selected_month=selected_month,
        selected_year=selected_year,
    )
    summary = report["summary"]
    suggestions = get_ai_suggestions(user_id)
    prediction = predict_monthly_expense(user_id)
    overspending_alerts = check_overspending(user_id)
    budget_alerts = check_budget_threshold_alerts(user_id)
    expense_ratio = (summary["total_expenses"] / summary["total_income"] * 100) if summary["total_income"] > 0 else 0.0
    overspending = {
        "is_overspending": bool(overspending_alerts),
        "message": (
            "No category has crossed the 30% overspending threshold this month."
            if not overspending_alerts
            else overspending_alerts[0]
        ),
        "ratio": round(expense_ratio, 2),
        "alerts": overspending_alerts,
    }

    return render_template(
        "reports.html",
        summary=summary,
        suggestions=suggestions,
        report_suggestions=report["suggestions"],
        overspending=overspending,
        prediction=prediction,
        overspending_alerts=overspending_alerts,
        budget_alerts=budget_alerts,
        transactions=report["transactions"][:15],
        model_notes=build_model_notes(prediction, overspending),
        report_type=report_type,
        selected_month=selected_month,
        selected_year=selected_year,
        selected_period_label=report["period_label"],
        available_years=available_report_years(transactions),
        current_year=datetime.today().year,
        monthly_summary=report["summary"],
        monthly_transaction_count=len(report["transactions"]),
        category_breakdown=report["category_breakdown"],
        yearly_monthly_trend=report["monthly_trend"],
        no_data_message=(
            f"No transactions found for {report['period_label']}. Try selecting a different period."
            if not report["transactions"]
            else ""
        ),
    )


@app.route("/reports/export")
@login_required
def export_report():
    user_id = int(session["user_id"])
    report_type = resolve_report_type(request.args.get("report_type"))
    selected_month = resolve_report_month(request.args.get("month"))
    selected_year = resolve_report_year(request.args.get("year"))

    transactions = fetch_user_transactions(user_id)
    report = generate_report(
        user_name=session.get("user_name", "User"),
        transactions=transactions,
        report_type=report_type,
        selected_month=selected_month,
        selected_year=selected_year,
    )

    if not report["transactions"]:
        flash(f"No transactions found for {report['period_label']}.", "info")
        return redirect(url_for("reports", report_type=report_type, month=selected_month, year=selected_year))

    return send_file(
        BytesIO(report["csv_content"].encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=report["filename"],
    )


@app.route("/reports/monthly/download")
@login_required
def download_monthly_report():
    selected_month = resolve_report_month(request.args.get("month"))
    return redirect(url_for("export_report", report_type="monthly", month=selected_month))


@app.route("/reports/email", methods=["POST"])
@login_required
def send_email_report():
    user_id = int(session["user_id"])
    report_type = resolve_report_type(request.form.get("report_type"))
    selected_month = resolve_report_month(request.form.get("month"))
    selected_year = resolve_report_year(request.form.get("year"))
    user_profile = fetch_user_profile(user_id)

    if user_profile is None or not user_profile.get("email"):
        flash("No email address found for your account.", "danger")
        return redirect(url_for("reports", report_type=report_type, month=selected_month, year=selected_year))

    if not _is_email_configured():
        flash("Report email is disabled. Configure SMARTFIN_SMTP_* and SMARTFIN_EMAIL_FROM to enable it.", "info")
        return redirect(url_for("reports", report_type=report_type, month=selected_month, year=selected_year))

    can_send, remaining_seconds = can_send_report_email(user_id)
    if not can_send:
        flash(f"Please wait {remaining_seconds} seconds before sending another report email.", "warning")
        return redirect(url_for("reports", report_type=report_type, month=selected_month, year=selected_year))

    transactions = fetch_user_transactions(user_id)
    report = generate_report(
        user_name=user_profile.get("name", "User"),
        transactions=transactions,
        report_type=report_type,
        selected_month=selected_month,
        selected_year=selected_year,
    )

    if not report["transactions"]:
        with _email_report_cooldown_lock:
            _email_report_cooldowns.pop(user_id, None)
        flash(f"No transactions found for {report['period_label']}.", "info")
        return redirect(url_for("reports", report_type=report_type, month=selected_month, year=selected_year))

    if send_report_email(user_profile, report_type, report["period_label"], report["csv_content"], report["summary"]):
        flash(f"{report_type.title()} report for {report['period_label']} was emailed to {user_profile['email']}.", "success")
    else:
        with _email_report_cooldown_lock:
            _email_report_cooldowns.pop(user_id, None)
        flash("Unable to send report email right now. Please verify SMTP settings and try again.", "danger")

    return redirect(url_for("reports", report_type=report_type, month=selected_month, year=selected_year))


@app.route("/reports/monthly/email", methods=["POST"])
@login_required
def email_monthly_report():
    return send_email_report()


@app.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    user_id = int(session["user_id"])
    categories = list(DEFAULT_CATEGORY_BUDGETS.keys())

    if request.method == "POST":
        updated_budgets: dict[str, float] = {}
        for category in categories:
            raw_value = request.form.get(category, "0").strip()
            try:
                budget_value = float(raw_value)
                if budget_value < 0:
                    raise ValueError
            except ValueError:
                flash(f"Budget for {category} must be a valid non-negative number.", "danger")
                existing_budgets = fetch_user_category_budgets(user_id)
                return render_template(
                    "budgets.html",
                    categories=categories,
                    budgets=existing_budgets,
                    email_enabled=_is_email_configured(),
                )
            updated_budgets[category] = budget_value

        update_user_category_budgets(user_id, updated_budgets)
        flash("Monthly category budgets updated successfully.", "success")
        return redirect(url_for("budgets"))

    existing_budgets = fetch_user_category_budgets(user_id)
    for category in categories:
        existing_budgets.setdefault(category, DEFAULT_CATEGORY_BUDGETS[category])

    return render_template(
        "budgets.html",
        categories=categories,
        budgets=existing_budgets,
        email_enabled=_is_email_configured(),
    )


@app.route("/api/chart_data")
@login_required
def chart_data():
    user_id = int(session["user_id"])
    transactions = fetch_user_transactions(user_id)
    raw_report_type = request.args.get("report_type")
    if raw_report_type:
        report_type = resolve_report_type(raw_report_type)
        if report_type == "yearly":
            selected_year = resolve_report_year(request.args.get("year"))
            scoped_transactions = filter_transactions_by_year(transactions, selected_year)
        else:
            selected_month = resolve_report_month(request.args.get("month"))
            scoped_transactions = filter_transactions_by_month(transactions, selected_month)
        return jsonify(build_chart_payload(scoped_transactions, user_id=user_id))

    return jsonify(build_chart_payload(transactions, user_id=user_id))


@app.route("/api/transactions")
@login_required
def get_transactions():
    user_id = int(session["user_id"])
    return jsonify(fetch_user_transactions(user_id))


@app.route("/ai-chat", methods=["POST"])
@login_required
def ai_chat():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    response = generate_ai_response(int(session["user_id"]), question)
    return jsonify(response)


def bootstrap() -> None:
    """Initialize the database before the server starts."""
    init_db()
    seed_demo_account()


bootstrap()


if __name__ == "__main__":
    app.run(debug=True)