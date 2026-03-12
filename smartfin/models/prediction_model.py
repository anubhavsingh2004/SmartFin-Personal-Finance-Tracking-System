"""Monthly expense prediction utilities."""

from __future__ import annotations

import math

import pandas as pd
from sklearn.linear_model import LinearRegression


def predict_next_month_expense(transactions: list[dict]) -> dict:
    """Predict next month's expense from monthly expense totals."""
    if not transactions:
        return {"predicted_expense": 0.0, "status": "insufficient-data"}

    frame = pd.DataFrame(transactions)
    if frame.empty:
        return {"predicted_expense": 0.0, "status": "insufficient-data"}

    expense_frame = frame[frame["type"] == "Expense"].copy()
    if expense_frame.empty:
        return {"predicted_expense": 0.0, "status": "no-expenses"}

    expense_frame["date"] = pd.to_datetime(expense_frame["date"], format="%Y-%m-%d", errors="coerce")
    expense_frame = expense_frame.dropna(subset=["date"])

    if expense_frame.empty:
        return {"predicted_expense": 0.0, "status": "invalid-dates"}

    expense_frame["month"] = expense_frame["date"].dt.to_period("M").astype(str)
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
    next_index = [[len(monthly_totals)]]
    prediction = float(model.predict(next_index)[0])

    return {
        "predicted_expense": round(max(prediction, 0.0), 2),
        "status": "predicted",
        "months_used": int(len(monthly_totals)),
        "average_monthly_expense": round(float(y_values.mean()), 2),
        "trend_slope": round(float(model.coef_[0]), 2) if not math.isnan(float(model.coef_[0])) else 0.0,
    }
