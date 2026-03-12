"""Analytics, chart preparation, and financial suggestion helpers."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from models.prediction_model import predict_next_month_expense


def _build_frame(transactions: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(transactions)
    if frame.empty:
        return frame

    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    return frame.dropna(subset=["date"])


def calculate_summary(transactions: list[dict]) -> dict:
    frame = _build_frame(transactions)
    if frame.empty:
        return {
            "total_income": 0.0,
            "total_expenses": 0.0,
            "balance": 0.0,
            "savings_rate": 0.0,
        }

    total_income = float(frame.loc[frame["type"] == "Income", "amount"].sum())
    total_expenses = float(frame.loc[frame["type"] == "Expense", "amount"].sum())
    balance = total_income - total_expenses
    savings_rate = (balance / total_income * 100) if total_income > 0 else 0.0

    return {
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "balance": round(balance, 2),
        "savings_rate": round(savings_rate, 2),
    }


def analyze_spending_patterns(transactions: list[dict]) -> dict:
    frame = _build_frame(transactions)
    if frame.empty:
        return {
            "monthly_spending": [],
            "category_distribution": [],
            "top_categories": [],
            "average_monthly_expense": 0.0,
        }

    expenses = frame[frame["type"] == "Expense"].copy()
    if expenses.empty:
        return {
            "monthly_spending": [],
            "category_distribution": [],
            "top_categories": [],
            "average_monthly_expense": 0.0,
        }

    expenses["month"] = expenses["date"].dt.to_period("M").astype(str)
    monthly_spending = (
        expenses.groupby("month", as_index=False)["amount"]
        .sum()
        .sort_values("month")
        .to_dict(orient="records")
    )
    category_distribution = (
        expenses.groupby("category", as_index=False)["amount"]
        .sum()
        .sort_values("amount", ascending=False)
        .to_dict(orient="records")
    )
    average_monthly_expense = (
        sum(item["amount"] for item in monthly_spending) / len(monthly_spending)
        if monthly_spending
        else 0.0
    )

    return {
        "monthly_spending": monthly_spending,
        "category_distribution": category_distribution,
        "top_categories": category_distribution[:3],
        "average_monthly_expense": round(float(average_monthly_expense), 2),
    }


def detect_overspending(transactions: list[dict]) -> dict:
    summary = calculate_summary(transactions)
    total_income = summary["total_income"]
    total_expenses = summary["total_expenses"]

    if total_income <= 0:
        return {
            "is_overspending": False,
            "message": "Add income transactions to enable overspending analysis.",
            "ratio": 0.0,
        }

    ratio = total_expenses / total_income
    is_overspending = ratio > 0.8
    message = (
        "Warning: You have spent over 80% of your income."
        if is_overspending
        else "Your spending is currently within a manageable range."
    )
    return {
        "is_overspending": is_overspending,
        "message": message,
        "ratio": round(ratio * 100, 2),
    }


def generate_financial_suggestions(transactions: list[dict]) -> list[str]:
    frame = _build_frame(transactions)
    if frame.empty:
        return [
            "Add income and expense transactions to unlock personalized financial suggestions.",
        ]

    summary = calculate_summary(transactions)
    patterns = analyze_spending_patterns(transactions)
    income = summary["total_income"]
    expenses = frame[frame["type"] == "Expense"].copy()
    suggestions: list[str] = []

    if income > 0 and summary["balance"] / income < 0.2:
        suggestions.append(
            f"Your savings are {summary['savings_rate']:.1f}% of income. Consider a budget that protects at least 20% for savings."
        )

    if not expenses.empty and income > 0:
        category_totals = expenses.groupby("category")["amount"].sum().to_dict()
        for category, amount in category_totals.items():
            if amount / income > 0.30:
                suggestions.append(
                    f"{category} spending is taking {amount / income * 100:.1f}% of your income. Review this category for possible cuts."
                )

    if len(patterns["monthly_spending"]) >= 2:
        previous_month = patterns["monthly_spending"][-2]["amount"]
        current_month = patterns["monthly_spending"][-1]["amount"]
        if previous_month > 0:
            increase = (current_month - previous_month) / previous_month
            if increase > 0.40:
                suggestions.append(
                    f"This month's expenses are up {increase * 100:.1f}% compared to last month. Investigate the categories driving the increase."
                )

    if patterns["top_categories"]:
        category_names = ", ".join(item["category"] for item in patterns["top_categories"])
        suggestions.append(f"Your top spending categories are {category_names}. Reviewing these first will have the biggest impact.")

    if not suggestions:
        suggestions.append("Your spending is balanced right now. Continue logging transactions consistently to keep insights accurate.")

    return suggestions


def build_chart_payload(transactions: list[dict]) -> dict:
    patterns = analyze_spending_patterns(transactions)
    summary = calculate_summary(transactions)
    prediction = predict_next_month_expense(transactions)
    frame = _build_frame(transactions)

    savings_by_month: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    if not frame.empty:
        frame["month"] = frame["date"].dt.to_period("M").astype(str)
        grouped = frame.groupby(["month", "type"], as_index=False)["amount"].sum()
        for item in grouped.to_dict(orient="records"):
            entry = savings_by_month[item["month"]]
            if item["type"] == "Income":
                entry["income"] = float(item["amount"])
            else:
                entry["expense"] = float(item["amount"])

    savings_chart = [
        {
            "month": month,
            "income": round(values["income"], 2),
            "expense": round(values["expense"], 2),
            "savings": round(values["income"] - values["expense"], 2),
        }
        for month, values in sorted(savings_by_month.items())
    ]

    return {
        "summary": summary,
        "prediction": prediction,
        "category_distribution": patterns["category_distribution"],
        "monthly_spending": patterns["monthly_spending"],
        "savings_vs_expenses": savings_chart,
    }
