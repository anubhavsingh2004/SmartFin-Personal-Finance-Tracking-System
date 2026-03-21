# SmartFin – Usage Guide for New Users

This guide walks you through setting up and using SmartFin from scratch, step-by-step.

---

## Prerequisites

Make sure you have the following installed before you start:

| Requirement | Version | Check command |
|---|---|---|
| Python | 3.10 or higher | `python --version` |
| pip | bundled with Python | `pip --version` |
| Git | any recent version | `git --version` |

---

## Step 1: Clone or download the project

If you received this as a ZIP, extract it to a folder of your choice.

If you are cloning from a repository:

```
git clone <repository-url>
cd <project-folder>
```

---

## Step 2: Create the virtual environment

Open a terminal inside the project root and run:

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

After activation you will see `(.venv)` at the start of your terminal prompt. All commands from this point must be run from that terminal.

---

## Step 3: Install dependencies

Install the required packages from the project root:

```
pip install -r requirements.txt
```

This installs Flask, Pandas, NumPy, scikit-learn, joblib, and Matplotlib.

---

## Step 4: Run the application

From the project root:

```
python app.py
```

Expected output:

```
* Serving Flask app 'app'
* Debug mode: on
* Running on http://127.0.0.1:5000
```

Open your browser and go to:

```
http://localhost:5000
```

---

## Step 5: What happens on first run

SmartFin automatically does the following when it starts for the first time:

1. Creates `database.db` with the required `users` and `transactions` tables
2. Seeds the Naive Bayes classifier from `data/seed_transactions.csv`
3. Creates a demo account with multi-month transaction history

You do not need to run any setup script or migration manually.

---

## Step 6: Try the demo account

The fastest way to see SmartFin fully populated is to use the preloaded demo account.

On the login page, click **Enter Demo Dashboard** — or log in manually with:

```
Email:    demo@smartfin.com
Password: Demo@123
```

The demo account contains 3 months of income and expenses across 7 categories, so all charts, predictions, and suggestions will be active immediately.

---

## Step 7: Register your own account

Click **Create one** on the login page and fill in the form:

- Full Name
- Email address
- Password (and confirmation)

All passwords are stored as bcrypt hashes using Werkzeug — they are never stored in plain text.

After registering, you will be taken to the login page. Log in with your credentials.

---

## Step 8: Add transactions

Click **Add Transaction** in the sidebar.

| Field | What to enter |
|---|---|
| Amount | Numeric value (e.g. `450`) |
| Type | `Income` or `Expense` |
| Category | Leave blank to auto-categorize expenses |
| Description | Plain English (e.g. `pizza dinner`, `electricity bill`) |
| Date | Pick from the date picker (stored as YYYY-MM-DD) |

When you submit an **Expense** and leave the category blank, SmartFin automatically predicts the category using the trained Naive Bayes model. The model is retrained with your new data after each submission.

---

## Step 9: View your dashboard

The dashboard shows:

- **Total Income** – sum of all income entries
- **Total Expenses** – sum of all expense entries
- **Remaining Balance** – income minus expenses
- **Predicted Next Month Expense** – Linear Regression estimate
- **Overspending Alert** – triggered when expenses exceed 80% of income
- **AI Suggestions** – dynamic Pandas-based recommendations
- **Personalized Saving Suggestions** – severity-based insight cards from real spending behavior
- **AI Financial Insights Assistant** – chat panel that answers questions using your own transaction context
- **Explainability Snapshot** – short notes on how each ML feature works
- **Charts** – Doughnut (categories), Line (monthly trend), Bar (savings vs expenses)
- **Recent Transactions** – your 5 latest entries

Charts load automatically from the `/api/chart_data` endpoint and require JavaScript to be enabled.

You can ask the AI assistant questions such as:

- `Where did I overspend this month?`
- `How can I save more?`
- `Summarize my March spending`
- `Compare this month with last month`

If no LLM API is configured, SmartFin automatically responds using local Pandas + rule-based analysis.

---

## Step 10: View reports

Click **Reports** in the sidebar for a full analytics view including:

- Summary cards
- All three charts
- AI financial suggestions
- Model summary (useful for understanding the logic or presenting at a viva)
- Last 15 transactions

---

## Step 11: Log out

Click **Logout** in the sidebar. Your session will be cleared and you will be redirected to the login page.

---

## Expense categories

SmartFin classifies expenses into these categories automatically:

| Category | Example descriptions |
|---|---|
| Food | pizza dinner, grocery shopping, cafe lunch |
| Transport | uber ride, metro recharge, fuel refill |
| Entertainment | movie tickets, netflix subscription, concert pass |
| Bills | electricity bill, internet recharge, mobile bill |
| Health | pharmacy medicine, doctor consultation, gym membership |
| Shopping | mall shopping, online order shoes, clothing purchase |
| Other | book fair, charity donation, miscellaneous items |

If you provide a description that does not match any clear pattern, the model will assign **Other**.

---

## AI suggestions logic

Suggestions are generated dynamically from your transaction data using Pandas analysis. Examples of rules applied:

- If your savings are below **20%** of income, SmartFin tells you to protect more for savings
- If any single category exceeds **30%** of income, it flags the category for review
- If expenses increase by more than **40%** month-over-month, a trend warning is shown
- Top 3 spending categories are always surfaced as a quick reference

These are checked live every time you load the dashboard or reports page.

---

## Prediction accuracy

- Prediction uses **Linear Regression** on your monthly expense totals
- At least **2 months** of expense history is needed to fit the model
- With only 1 month of history, the last known monthly total is used as the estimate
- Accuracy improves as more months are recorded

---

## Common issues

| Problem | Solution |
|---|---|
| `ModuleNotFoundError: No module named 'flask'` | Your virtual environment is not active. Run `.\.venv\Scripts\Activate.ps1` first |
| `database.db: no such table` | Delete `database.db` and restart `python app.py` to reinitialize |
| Charts not showing | Check that JavaScript is enabled in your browser and the server is running |
| Category prediction seems outdated after changing seed data | Restart the app; SmartFin now retrains automatically when `data/seed_transactions.csv` is newer than the saved model |
| Port 5000 already in use | Stop any other process using port 5000, or change the port in `app.py` to `app.run(port=5001)` |

---

## Stopping the server

Press `Ctrl + C` in the terminal where `python app.py` is running.

---

## Project structure for reference

```
project-root/
├── app.py                    Main Flask application
├── requirements.txt          Python dependencies
├── database.db               SQLite database (auto-created on first run)
├── models/
│   ├── expense_model.py      Naive Bayes categorizer
│   ├── prediction_model.py   Linear Regression forecaster
│   └── expense_classifier.joblib  Trained model (auto-created on first run)
├── utils/
│   ├── database.py           DB connection and schema helpers
│   └── ml_utils.py           Analytics, suggestions, chart data helpers
├── data/
│   └── seed_transactions.csv Training seed data for the categorizer
├── templates/                Flask HTML templates
├── static/
│   ├── css/style.css         UI styling
│   └── js/charts.js          Chart.js rendering logic
└── USAGE.md                  This file
```

---

## Quick command reference

```powershell
# Activate environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

# Open in browser
start http://localhost:5000
```




