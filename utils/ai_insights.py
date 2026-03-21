"""AI-powered financial insights helpers for SmartFin."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from urllib import error, request

import pandas as pd

from utils.database import fetch_user_category_budgets, get_db_connection


MONTH_NAME_MAP = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


def _fetch_user_transactions_frame(user_id: int) -> pd.DataFrame:
    """Load and normalize one user's transaction data."""
    connection = get_db_connection()
    frame = pd.read_sql_query(
        """
        SELECT amount, category, type, description, date
        FROM transactions
        WHERE user_id = ?
        ORDER BY date ASC
        """,
        connection,
        params=(user_id,),
    )
    connection.close()

    if frame.empty:
        return frame

    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    frame = frame.dropna(subset=["date"]).copy()
    frame["month"] = frame["date"].dt.to_period("M").astype(str)
    frame["category"] = frame["category"].astype(str)
    frame["type"] = frame["type"].astype(str)
    frame["description"] = frame["description"].astype(str)
    return frame


def _summary_from_frame(frame: pd.DataFrame) -> dict:
    """Build income/expense summary for a frame slice."""
    if frame.empty:
        return {
            "total_income": 0.0,
            "total_expense": 0.0,
            "balance": 0.0,
            "savings_rate": 0.0,
        }

    total_income = float(frame.loc[frame["type"] == "Income", "amount"].sum())
    total_expense = float(frame.loc[frame["type"] == "Expense", "amount"].sum())
    balance = total_income - total_expense
    savings_rate = (balance / total_income * 100.0) if total_income > 0 else 0.0

    return {
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "balance": round(balance, 2),
        "savings_rate": round(savings_rate, 2),
    }


def _resolve_period_slice(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[frame["month"] == period].copy()


def build_financial_context(user_id: int) -> dict:
    """Build compact, transaction-grounded context for AI responses."""
    frame = _fetch_user_transactions_frame(user_id)
    if frame.empty:
        return {
            "currency": "Rs",
            "overall": _summary_from_frame(frame),
            "current_month": None,
            "previous_month": None,
            "top_categories": [],
            "monthly_spending_trend": [],
            "monthly_summary_by_month": {},
            "categories_increased": [],
            "overspending_alerts": ["Add more transactions to unlock personalized insights."],
            "budget_usage": [],
        }

    months = sorted(frame["month"].unique().tolist())
    current_month = months[-1]
    previous_month = months[-2] if len(months) >= 2 else None

    expenses = frame[frame["type"] == "Expense"].copy()
    current_expenses = _resolve_period_slice(expenses, current_month)
    previous_expenses = _resolve_period_slice(expenses, previous_month) if previous_month else pd.DataFrame()

    overall = _summary_from_frame(frame)
    current_summary = _summary_from_frame(_resolve_period_slice(frame, current_month))
    previous_summary = _summary_from_frame(_resolve_period_slice(frame, previous_month)) if previous_month else _summary_from_frame(pd.DataFrame())

    top_categories_frame = (
        current_expenses.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    )
    current_total_expense = float(current_summary["total_expense"])
    top_categories = []
    for item in top_categories_frame.head(5).to_dict(orient="records"):
        share = (float(item["amount"]) / current_total_expense * 100.0) if current_total_expense > 0 else 0.0
        top_categories.append(
            {
                "category": item["category"],
                "amount": round(float(item["amount"]), 2),
                "share_of_current_expense": round(share, 2),
            }
        )

    monthly_expense_map = expenses.groupby("month")["amount"].sum().to_dict()
    monthly_spending = [{"month": month, "amount": float(monthly_expense_map.get(month, 0.0))} for month in months]
    monthly_spending_trend = [
        {"month": item["month"], "amount": round(float(item["amount"]), 2)}
        for item in monthly_spending
    ]

    monthly_summary_by_month = {
        month: _summary_from_frame(_resolve_period_slice(frame, month))
        for month in months
    }

    categories_increased: list[dict] = []
    if not previous_expenses.empty and not current_expenses.empty:
        current_map = current_expenses.groupby("category")["amount"].sum().to_dict()
        previous_map = previous_expenses.groupby("category")["amount"].sum().to_dict()
        for category, current_amount in current_map.items():
            previous_amount = float(previous_map.get(category, 0.0))
            if previous_amount <= 0:
                continue
            change_pct = (float(current_amount) - previous_amount) / previous_amount * 100.0
            if change_pct > 0:
                categories_increased.append(
                    {
                        "category": category,
                        "previous": round(previous_amount, 2),
                        "current": round(float(current_amount), 2),
                        "change_percent": round(change_pct, 2),
                    }
                )
    categories_increased.sort(key=lambda item: item["change_percent"], reverse=True)

    overspending_alerts: list[str] = []
    if current_summary["total_income"] > 0:
        expense_ratio = current_summary["total_expense"] / current_summary["total_income"]
        if expense_ratio > 0.8:
            overspending_alerts.append(
                f"Current month expenses are {expense_ratio * 100:.1f}% of income, above the 80% threshold."
            )

    budgets = fetch_user_category_budgets(user_id)
    budget_usage: list[dict] = []
    for category, budget in budgets.items():
        spent = float(current_expenses.loc[current_expenses["category"] == category, "amount"].sum())
        usage = (spent / budget * 100.0) if budget > 0 else 0.0
        budget_usage.append(
            {
                "category": category,
                "spent": round(spent, 2),
                "budget": round(float(budget), 2),
                "usage_percent": round(usage, 2),
            }
        )
        if budget > 0 and usage >= 85.0:
            overspending_alerts.append(
                f"{category} budget is at {usage:.1f}% usage this month (Rs. {spent:.2f} / Rs. {budget:.2f})."
            )

    return {
        "currency": "Rs",
        "overall": overall,
        "current_month": {
            "period": current_month,
            "summary": current_summary,
        },
        "previous_month": {
            "period": previous_month,
            "summary": previous_summary,
        }
        if previous_month
        else None,
        "top_categories": top_categories,
        "monthly_spending_trend": monthly_spending_trend,
        "monthly_summary_by_month": monthly_summary_by_month,
        "categories_increased": categories_increased[:5],
        "overspending_alerts": overspending_alerts,
        "budget_usage": sorted(budget_usage, key=lambda item: item["usage_percent"], reverse=True),
    }


def generate_personalized_suggestions(user_id: int) -> list[dict]:
    """Generate prioritized savings suggestions from user transaction behavior."""
    context = build_financial_context(user_id)
    current = context.get("current_month")
    previous = context.get("previous_month")
    current_summary = current.get("summary") if current else None
    previous_summary = previous.get("summary") if previous else None

    if not current_summary:
        return [
            {
                "type": "info",
                "title": "Need More Data",
                "message": "Add income and expense transactions to unlock personalized saving suggestions.",
            }
        ]

    suggestions: list[dict] = []

    income = float(current_summary.get("total_income", 0.0))
    expense = float(current_summary.get("total_expense", 0.0))
    savings_rate = float(current_summary.get("savings_rate", 0.0))

    top_categories = context.get("top_categories", [])
    category_share = {item["category"]: float(item["share_of_current_expense"]) for item in top_categories}

    if income > 0 and savings_rate < 20:
        suggestions.append(
            {
                "priority": 100,
                "type": "warning",
                "title": "Low Savings Rate",
                "message": f"Your savings this month are {savings_rate:.1f}% of income. Set a target of at least 20% and cap non-essential spending.",
            }
        )

    if income > 0 and expense / income > 0.8:
        suggestions.append(
            {
                "priority": 95,
                "type": "danger",
                "title": "Overspending Risk",
                "message": f"Expenses are {expense / income * 100:.1f}% of your income this month. Delay optional purchases until savings recover.",
            }
        )

    food_share = category_share.get("Food", 0.0)
    if income > 0 and food_share > 30.0:
        suggestions.append(
            {
                "priority": 90,
                "type": "warning",
                "title": "High Food Spending",
                "message": f"Food spending is {food_share:.1f}% of your current month expenses. Consider reducing restaurant and delivery orders.",
            }
        )

    for growth in context.get("categories_increased", []):
        if float(growth["change_percent"]) > 20.0:
            suggestions.append(
                {
                    "priority": 80,
                    "type": "warning",
                    "title": f"{growth['category']} Is Rising",
                    "message": (
                        f"{growth['category']} increased by {growth['change_percent']:.1f}% versus last month "
                        f"(Rs. {growth['previous']:.2f} to Rs. {growth['current']:.2f})."
                    ),
                }
            )

    for category in ("Shopping", "Entertainment"):
        share = category_share.get(category, 0.0)
        if share >= 18.0:
            suggestions.append(
                {
                    "priority": 75,
                    "type": "info",
                    "title": "Discretionary Spend Check",
                    "message": f"{category} is {share:.1f}% of this month's expenses. Set a tighter weekly cap for discretionary purchases.",
                }
            )

    transport_growth = next(
        (item for item in context.get("categories_increased", []) if item["category"].lower() == "transport"),
        None,
    )
    if transport_growth and float(transport_growth["change_percent"]) > 10.0:
        suggestions.append(
            {
                "priority": 70,
                "type": "info",
                "title": "Transport Cost Optimization",
                "message": (
                    f"Transport spending rose {transport_growth['change_percent']:.1f}% month-over-month. "
                    "Try route clustering, ride sharing, or public transport passes."
                ),
            }
        )

    high_budget_usage = [item for item in context.get("budget_usage", []) if float(item["usage_percent"]) >= 90.0]
    if high_budget_usage:
        highest = high_budget_usage[0]
        suggestions.append(
            {
                "priority": 88,
                "type": "danger",
                "title": "Budget Limit Near",
                "message": (
                    f"{highest['category']} has used {highest['usage_percent']:.1f}% of this month's budget. "
                    "Reduce spend in this category to avoid crossing the limit."
                ),
            }
        )

    if not suggestions and previous_summary and income > 0:
        previous_expense = float(previous_summary.get("total_expense", 0.0))
        if previous_expense > 0:
            delta = (expense - previous_expense) / previous_expense * 100.0
            if delta <= 0:
                suggestions.append(
                    {
                        "priority": 50,
                        "type": "success",
                        "title": "Good Spending Control",
                        "message": f"Expenses are down by {abs(delta):.1f}% compared to last month. Keep this pattern to grow savings.",
                    }
                )

    suggestions.sort(key=lambda item: item["priority"], reverse=True)
    cleaned: list[dict] = []
    for item in suggestions[:5]:
        cleaned.append(
            {
                "type": item["type"],
                "title": item["title"],
                "message": item["message"],
            }
        )

    if not cleaned:
        cleaned.append(
            {
                "type": "success",
                "title": "Stable Month",
                "message": "Your spending pattern looks balanced this month. Keep tracking transactions regularly.",
            }
        )

    return cleaned


def _extract_text_from_llm_response(response_json: dict) -> str | None:
    """Normalize text extraction for multiple provider-style response payloads."""
    if not isinstance(response_json, dict):
        return None

    if isinstance(response_json.get("text"), str):
        return response_json["text"].strip()

    if isinstance(response_json.get("response"), str):
        return response_json["response"].strip()

    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"].strip()
            if isinstance(first.get("text"), str):
                return first["text"].strip()

    return None


def call_llm_api(prompt: str) -> str | None:
    """Call an external LLM endpoint when configured, else return None.

    This is a provider-agnostic placeholder so Gemini/OpenRouter can be plugged in later.
    """
    endpoint = os.environ.get("SMARTFIN_LLM_ENDPOINT", "").strip()
    api_key = os.environ.get("SMARTFIN_LLM_API_KEY", "").strip()

    if not endpoint or not api_key:
        return None

    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=12) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body)
        return _extract_text_from_llm_response(parsed)
    except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def _resolve_question_month(question: str, available_months: list[str]) -> str | None:
    """Map month words in user question to one of available YYYY-MM keys."""
    lower = question.casefold()
    this_year = str(datetime.today().year)

    for month_name, month_num in MONTH_NAME_MAP.items():
        if month_name in lower:
            year_match = re.search(r"(20\d{2})", lower)
            if year_match:
                candidate = f"{year_match.group(1)}-{month_num}"
                if candidate in available_months:
                    return candidate

            for year in [this_year, "2026", "2025", "2024"]:
                candidate = f"{year}-{month_num}"
                if candidate in available_months:
                    return candidate
            for item in available_months:
                if item.endswith(f"-{month_num}"):
                    return item
    return None


def _extract_explicit_period(question: str) -> str | None:
    """Extract YYYY-MM style month from user question when present."""
    match = re.search(r"(20\d{2})\s*[-/]\s*(\d{1,2})", question)
    if not match:
        return None

    year = match.group(1)
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    return f"{year}-{month:02d}"


def extract_month_from_question(question: str, available_months: list[str]) -> str | None:
    """Extract a target month from question using YYYY-MM or month-name patterns."""
    explicit_period = _extract_explicit_period(question)
    if explicit_period:
        return explicit_period

    return _resolve_question_month(question, available_months)


def get_monthly_income_expense(monthly_summary_by_month: dict, target_month: str) -> dict | None:
    """Return one month summary dictionary when available."""
    summary = monthly_summary_by_month.get(target_month)
    if not isinstance(summary, dict):
        return None
    return summary


def get_highest_expense_month(monthly_summary_by_month: dict) -> tuple[str, dict] | tuple[None, None]:
    """Return month and summary with highest total expense."""
    if not monthly_summary_by_month:
        return None, None

    month, summary = max(
        monthly_summary_by_month.items(),
        key=lambda item: float(item[1].get("total_expense", 0.0)),
    )
    return month, summary


def get_month_top_categories(context: dict, target_month: str) -> list[dict]:
    """Get top expense categories for a specific month from user transaction data."""
    user_id = context.get("_user_id")
    if not user_id:
        return []

    frame = _fetch_user_transactions_frame(int(user_id))
    if frame.empty:
        return []

    monthly_expenses = frame[(frame["month"] == target_month) & (frame["type"] == "Expense")].copy()
    if monthly_expenses.empty:
        return []

    grouped = (
        monthly_expenses.groupby("category", as_index=False)["amount"]
        .sum()
        .sort_values("amount", ascending=False)
    )
    return [
        {
            "category": item["category"],
            "amount": round(float(item["amount"]), 2),
        }
        for item in grouped.head(5).to_dict(orient="records")
    ]


def generate_rule_based_reply(context: dict, question: str) -> str:
    """Return a local fallback answer grounded in computed financial context."""
    q = question.casefold()
    current = context.get("current_month")
    previous = context.get("previous_month")

    if not current:
        return "I need more transaction history before I can answer. Add a few income and expense entries first."

    current_period = current["period"]
    current_summary = current["summary"]
    previous_summary = previous["summary"] if previous else None
    monthly_summary_by_month: dict = context.get("monthly_summary_by_month", {})
    available_months = sorted(monthly_summary_by_month.keys())
    target_month = extract_month_from_question(question, available_months)

    requested_month_not_found = bool(target_month and target_month not in monthly_summary_by_month)

    if requested_month_not_found:
        return f"No records were found for {target_month}. Please check the month or add transactions for that period."

    if ("highest" in q or "max" in q) and (
        "spend" in q or "spent" in q or "spending" in q or "expense" in q or "sped" in q
    ):
        highest_month, highest_summary = get_highest_expense_month(monthly_summary_by_month)
        if not highest_month or not highest_summary:
            return "I need more transaction history to determine your highest spending month."

        return (
            f"Your highest spending month is {highest_month} with total expenses of "
            f"Rs. {float(highest_summary.get('total_expense', 0.0)):.2f}."
        )

    if target_month and ("income" in q or "earn" in q or "salary" in q):
        target_summary = get_monthly_income_expense(monthly_summary_by_month, target_month)
        if not target_summary:
            return f"No records were found for {target_month}. Please check the month or add transactions for that period."
        return f"Income for {target_month} is Rs. {float(target_summary.get('total_income', 0.0)):.2f}."

    if target_month and ("spend" in q or "spent" in q or "spending" in q or "expense" in q or "sped" in q):
        target_summary = get_monthly_income_expense(monthly_summary_by_month, target_month)
        if not target_summary:
            return f"No records were found for {target_month}. Please check the month or add transactions for that period."
        return f"Total expenses for {target_month} are Rs. {float(target_summary.get('total_expense', 0.0)):.2f}."

    if "overspend" in q or "overspending" in q:
        alerts = context.get("overspending_alerts", [])
        if alerts:
            return "Top overspending signals: " + " ".join(alerts[:3])
        return "No major overspending alert is active right now. Your current expense pattern is within the configured thresholds."

    if "compare" in q and "last month" in q and previous and previous_summary:
        current_expense = float(current_summary.get("total_expense", 0.0))
        previous_expense = float(previous_summary.get("total_expense", 0.0))
        if previous_expense > 0:
            delta = (current_expense - previous_expense) / previous_expense * 100.0
            direction = "up" if delta >= 0 else "down"
            return (
                f"Comparison for {current_period} vs {previous['period']}: expenses are {abs(delta):.1f}% {direction} "
                f"(Rs. {current_expense:.2f} vs Rs. {previous_expense:.2f})."
            )
        return f"Comparison is limited because last month ({previous['period']}) has very low or zero expenses recorded."

    if "save" in q or "saving" in q:
        suggestions = generate_personalized_suggestions(int(context.get("_user_id", 0))) if context.get("_user_id") else []
        if suggestions:
            top = suggestions[0]
            return f"Top savings action: {top['title']}. {top['message']}"
        return "Your savings pattern looks stable. Keep monthly expense caps for discretionary categories to preserve savings."

    if "summarize" in q or "summary" in q:
        if target_month and target_month in monthly_summary_by_month:
            month_summary = monthly_summary_by_month[target_month]
            top_categories = get_month_top_categories(context, target_month)
            top_text = ", ".join(
                f"{item['category']} (Rs. {item['amount']:.2f})" for item in top_categories[:3]
            )
            return (
                f"Summary for {target_month}: income Rs. {float(month_summary.get('total_income', 0.0)):.2f}, "
                f"expenses Rs. {float(month_summary.get('total_expense', 0.0)):.2f}, "
                f"balance Rs. {float(month_summary.get('balance', 0.0)):.2f}. "
                f"Top categories: {top_text if top_text else 'no expense categories recorded for this month.'}"
            )
        top_categories = context.get("top_categories", [])
        top_text = ", ".join(
            f"{item['category']} (Rs. {item['amount']:.2f})" for item in top_categories[:3]
        )
        return (
            f"Summary for {current_period}: income Rs. {current_summary['total_income']:.2f}, "
            f"expenses Rs. {current_summary['total_expense']:.2f}, balance Rs. {current_summary['balance']:.2f}. "
            f"Top categories: {top_text if top_text else 'no major expense categories yet'}.")

    increased = context.get("categories_increased", [])
    increased_text = ""
    if increased:
        top_change = increased[0]
        increased_text = (
            f" Biggest increase: {top_change['category']} up {top_change['change_percent']:.1f}% "
            f"(Rs. {top_change['previous']:.2f} to Rs. {top_change['current']:.2f})."
        )

    return (
        f"For {current_period}, your income is Rs. {current_summary['total_income']:.2f}, "
        f"expenses are Rs. {current_summary['total_expense']:.2f}, and savings rate is {current_summary['savings_rate']:.1f}%."
        + increased_text
    )


def generate_ai_response(user_id: int, user_question: str) -> dict:
    """Generate a finance-focused chat response using user context and LLM fallback."""
    cleaned_question = (user_question or "").strip()
    if not cleaned_question:
        return {
            "answer": "Please ask a finance question, for example: 'Where did I overspend this month?'",
            "source": "local",
        }

    context = build_financial_context(user_id)
    context["_user_id"] = user_id
    prompt = (
        "You are SmartFin AI, a personal finance assistant. Answer only using the provided user financial context. "
        "Do not rely on general internet knowledge. Keep answers concise, practical, and finance-focused. "
        "If data is missing, clearly say what is missing.\n\n"
        f"User Question: {cleaned_question}\n\n"
        f"Financial Context JSON:\n{json.dumps(context, ensure_ascii=True)}"
    )

    llm_answer = call_llm_api(prompt)
    if llm_answer:
        return {
            "answer": llm_answer,
            "source": "llm",
        }

    fallback = generate_rule_based_reply(context, cleaned_question)
    return {
        "answer": fallback,
        "source": "local",
    }
