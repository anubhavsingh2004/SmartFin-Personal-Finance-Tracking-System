"""Analytics, chart preparation, and financial suggestion helpers."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
from sklearn.linear_model import LinearRegression

from models.expense_model import expense_categorizer
from utils.database import create_budget_alert_event, fetch_user_category_budgets, get_db_connection


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


def build_chart_payload(transactions: list[dict], user_id: int | None = None) -> dict:
    patterns = analyze_spending_patterns(transactions)
    summary = calculate_summary(transactions)
    if user_id is not None:
        prediction = predict_monthly_expense(user_id)
    else:
        # Fallback to transaction-only prediction when user_id is not available.
        prediction = {
            "predicted_expense": 0.0,
            "status": "insufficient-data",
        }
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


def _fetch_user_transactions_frame(user_id: int) -> pd.DataFrame:
    """Load one user's transactions from SQLite into a clean Pandas DataFrame."""
    connection = get_db_connection()
    frame = pd.read_sql_query(
        """
        SELECT id, user_id, amount, category, type, description, date
        FROM transactions
        WHERE user_id = ?
        """,
        connection,
        params=(user_id,),
    )
    connection.close()

    if frame.empty:
        return frame

    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    return frame.dropna(subset=["date"])


def check_overspending(user_id: int) -> list[str]:
    """Return category alerts when current-month spend is >30% above last-6-month average."""
    frame = _fetch_user_transactions_frame(user_id)
    if frame.empty:
        return []

    expenses = frame[frame["type"] == "Expense"].copy()
    if expenses.empty:
        return []

    # Compare current month with a rolling baseline of the previous 6 full months.
    current_period = pd.Timestamp.today().to_period("M")
    history_periods = pd.period_range(end=current_period - 1, periods=6, freq="M")

    expenses["month"] = expenses["date"].dt.to_period("M")
    current_month_expense = (
        expenses[expenses["month"] == current_period]
        .groupby("category")["amount"]
        .sum()
    )

    historical = expenses[expenses["month"].isin(history_periods)]
    if historical.empty:
        return []

    alerts: list[str] = []
    for category in current_month_expense.index:
        category_history = (
            historical[historical["category"] == category]
            .groupby("month")["amount"]
            .sum()
            .reindex(history_periods, fill_value=0.0)
        )
        historical_average = float(category_history.mean())
        current_total = float(current_month_expense.loc[category])

        if historical_average <= 0:
            continue

        increase_ratio = (current_total - historical_average) / historical_average
        if increase_ratio > 0.30:
            alerts.append(
                f"Overspending alert: {category} spending is {increase_ratio * 100:.1f}% above your 6-month average this month."
            )

    return alerts


def auto_categorize(description: str) -> str:
    """Predict an expense category from free-text description using the shared ML model."""
    cleaned_description = description.strip()
    if not cleaned_description:
        return "Other"

    lowered = cleaned_description.casefold()
    health_keywords = (
        "medical",
        "hospital",
        "clinic",
        "doctor",
        "pharmacy",
        "medicine",
        "checkup",
        "dental",
        "physio",
        "therapy",
        "counsel",
        "vaccin",
        "lab test",
        "blood test",
    )
    if any(keyword in lowered for keyword in health_keywords):
        return "Health"

    return expense_categorizer.predict_category(cleaned_description)


def predict_monthly_expense(user_id: int) -> dict:
    """Predict upcoming month's total expense using monthly aggregates and linear regression."""
    frame = _fetch_user_transactions_frame(user_id)
    if frame.empty:
        return {"predicted_expense": 0.0, "status": "insufficient-data"}

    expense_frame = frame[frame["type"] == "Expense"].copy()
    if expense_frame.empty:
        return {"predicted_expense": 0.0, "status": "no-expenses"}

    expense_frame["month"] = expense_frame["date"].dt.to_period("M")
    monthly_totals = (
        expense_frame.groupby("month", as_index=False)["amount"]
        .sum()
        .sort_values("month")
        .reset_index(drop=True)
    )

    if len(monthly_totals) < 2:
        return {
            "predicted_expense": round(float(monthly_totals["amount"].iloc[-1]), 2),
            "status": "limited-history",
        }

    x_values = monthly_totals.index.to_numpy().reshape(-1, 1)
    y_values = monthly_totals["amount"].to_numpy()

    model = LinearRegression()
    model.fit(x_values, y_values)

    next_month_index = [[len(monthly_totals)]]
    predicted_expense = float(model.predict(next_month_index)[0])
    next_month_period = (monthly_totals["month"].iloc[-1] + 1).strftime("%Y-%m")

    return {
        "predicted_expense": round(max(predicted_expense, 0.0), 2),
        "next_month": next_month_period,
        "months_used": int(len(monthly_totals)),
        "status": "predicted",
    }


def get_ai_suggestions(user_id: int) -> list[str]:
    """Generate rule-based finance suggestions from income, food spend, and savings behavior."""
    frame = _fetch_user_transactions_frame(user_id)
    if frame.empty:
        return ["Add transactions to unlock AI suggestions."]

    total_income = float(frame.loc[frame["type"] == "Income", "amount"].sum())
    total_expense = float(frame.loc[frame["type"] == "Expense", "amount"].sum())
    food_expense = float(
        frame.loc[
            (frame["type"] == "Expense") & (frame["category"].str.lower() == "food"),
            "amount",
        ].sum()
    )

    if total_income <= 0:
        return ["Add at least one income transaction so AI suggestions can be calculated."]

    savings_amount = total_income - total_expense
    suggestions: list[str] = []

    if food_expense > 0.30 * total_income:
        suggestions.append("Food spending is above 30% of income. Consider reducing dining out.")

    if savings_amount < 0.20 * total_income:
        suggestions.append("Savings are below 20% of income. Consider setting a stricter budget.")

    if not suggestions:
        suggestions.append("Your spending and savings pattern looks healthy. Keep tracking consistently.")

    return suggestions


def check_budget_threshold_alerts(user_id: int, threshold: float = 0.85) -> list[dict]:
    """Return budget usage alerts when category spend crosses the configured threshold."""
    frame = _fetch_user_transactions_frame(user_id)
    if frame.empty:
        return []

    monthly_budgets = fetch_user_category_budgets(user_id)
    if not monthly_budgets:
        return []

    expenses = frame[frame["type"] == "Expense"].copy()
    if expenses.empty:
        return []

    current_month = pd.Timestamp.today().to_period("M")
    expenses["month"] = expenses["date"].dt.to_period("M")
    current_totals = (
        expenses[expenses["month"] == current_month]
        .groupby("category")["amount"]
        .sum()
    )

    alerts: list[dict] = []
    for category, budget in monthly_budgets.items():
        spent = float(current_totals.get(category, 0.0))
        usage_ratio = spent / budget if budget > 0 else 0.0

        if usage_ratio >= threshold:
            alerts.append(
                {
                    "category": category,
                    "budget": round(budget, 2),
                    "spent": round(spent, 2),
                    "usage_percent": round(usage_ratio * 100, 1),
                    "message": f"Alert: You have used {usage_ratio * 100:.1f}% of your monthly {category.lower()} budget.",
                    "is_exceeded": usage_ratio >= 1.0,
                }
            )

    alerts.sort(key=lambda item: item["usage_percent"], reverse=True)
    return alerts


def collect_new_budget_crossings(user_id: int, thresholds: tuple[int, ...] = (85, 100)) -> list[dict]:
    """Persist and return new monthly budget threshold crossing events for notifications."""
    alerts = check_budget_threshold_alerts(user_id, threshold=min(thresholds) / 100)
    if not alerts:
        return []

    current_month = pd.Timestamp.today().strftime("%Y-%m")
    new_events: list[dict] = []

    for alert in alerts:
        usage_percent = float(alert["usage_percent"])
        for threshold in sorted(thresholds):
            if usage_percent < threshold:
                continue

            was_created = create_budget_alert_event(
                user_id=user_id,
                category=alert["category"],
                month=current_month,
                threshold_percent=int(threshold),
                usage_percent=usage_percent,
            )
            if was_created:
                new_events.append(
                    {
                        "category": alert["category"],
                        "month": current_month,
                        "threshold_percent": int(threshold),
                        "usage_percent": usage_percent,
                        "budget": alert["budget"],
                        "spent": alert["spent"],
                        "message": (
                            f"You crossed {threshold}% of your monthly {alert['category'].lower()} budget "
                            f"({usage_percent:.1f}% used)."
                        ),
                    }
                )

    new_events.sort(key=lambda item: (item["threshold_percent"], item["usage_percent"]), reverse=True)
    return new_events
