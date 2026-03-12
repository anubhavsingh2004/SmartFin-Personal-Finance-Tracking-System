# SmartFin - Personal Finance Tracking System

SmartFin is a Flask-based personal finance assistant built for a college final year project. It helps users track income and expenses, automatically categorize spending using Machine Learning, analyze spending behavior, detect overspending, predict next month's expenses, and visualize trends through interactive charts.

## Project Overview

SmartFin acts as an intelligent personal financial assistant with the following goals:

- Track income and expense transactions in one place
- Categorize expense descriptions automatically using Naive Bayes classification
- Analyze monthly and category-wise spending using Pandas
- Detect overspending patterns with rule-based logic
- Predict future monthly expenses using Linear Regression
- Provide data-driven financial suggestions
- Display financial reports with Chart.js visualizations

## Technology Stack

### Frontend
- HTML5
- CSS3
- JavaScript
- Chart.js

### Backend
- Python
- Flask

### Machine Learning and Analysis
- Pandas
- NumPy
- Scikit-learn
- Joblib

### Database and Security
- SQLite
- Werkzeug password hashing

## Project Structure

```text
project-root/
|-- app.py
|-- requirements.txt
|-- database.db
|-- models/
|   |-- expense_model.py
|   `-- prediction_model.py
|-- utils/
|   |-- database.py
|   `-- ml_utils.py
|-- data/
|   `-- seed_transactions.csv
|-- templates/
|   |-- base.html
|   |-- login.html
|   |-- register.html
|   |-- dashboard.html
|   |-- add_transaction.html
|   `-- reports.html
|-- static/
|   |-- css/
|   |   `-- style.css
|   `-- js/
|       `-- charts.js
`-- README.md
```

## System Architecture

### 1. Presentation Layer
HTML templates and CSS provide the user interface for registration, login, dashboard, transaction entry, and reports.

### 2. Application Layer
Flask routes manage authentication, session control, transaction submission, dashboard rendering, and JSON APIs for charts.

### 3. Data Layer
SQLite stores users and transactions. Dates are stored in `YYYY-MM-DD` format to support Pandas time-series analysis.

### 4. Intelligence Layer
- `expense_model.py` uses Naive Bayes to predict categories from descriptions.
- `prediction_model.py` uses Linear Regression to predict next month expense totals.
- `ml_utils.py` uses Pandas for analytics, suggestions, overspending alerts, and chart data preparation.

## Database Design

### Users Table
- `id` - Primary key
- `name` - User full name
- `email` - Unique email address
- `password` - Hashed password using Werkzeug

### Transactions Table
- `id` - Primary key
- `user_id` - Foreign key reference to users table
- `amount` - Transaction amount
- `category` - Transaction category
- `type` - `Income` or `Expense`
- `description` - Transaction description
- `date` - Transaction date in `YYYY-MM-DD` format

## Core Features

### User Authentication
- User registration
- User login
- User logout
- Session-based access control
- Password hashing with `generate_password_hash` and `check_password_hash`

### Dashboard
- Total income card
- Total expenses card
- Remaining balance card
- Predicted next month expense card
- Overspending alert section
- AI financial suggestion section
- Recent transactions table

### Add Transaction
- Supports both income and expense entries
- Accepts amount, type, category, description, and date
- Automatically predicts category for expenses when category is left blank

### Machine Learning Features

#### Expense Categorization
- Model: `MultinomialNB`
- Text preprocessing: `TfidfVectorizer`
- Training source: seed CSV + user expense history
- Categories supported:
  - Food
  - Transport
  - Shopping
  - Bills
  - Entertainment
  - Health
  - Other

#### Spending Pattern Analysis
- Monthly expense totals
- Category distribution
- Top spending categories
- Average monthly expense

#### Expense Prediction
- Groups past expenses by month
- Trains Linear Regression on monthly totals
- Predicts next month's expense
- Handles limited history safely

#### Overspending Detection
- If total expenses exceed 80% of income, SmartFin shows a warning alert

#### AI-Based Suggestions
Suggestions are generated dynamically from user data, for example:
- If savings are below 20% of income
- If a category consumes more than 30% of income
- If monthly expenses increase by more than 40%

## Chart Visualizations

SmartFin uses Chart.js to render:

- Doughnut Chart: Expense category distribution
- Line Chart: Monthly spending trend
- Bar Chart: Savings vs expenses

Chart data is fetched dynamically from the Flask endpoint `/api/chart_data`.

## Installation Steps

### 1. Create and activate virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

## How to Run the Project

From the project root:

```powershell
python app.py
```

Open the application in your browser:

```text
http://localhost:5000
```

On first run, SmartFin automatically:
- Creates `database.db`
- Creates required tables
- Loads the seed training dataset for ML categorization

## Application Workflow

1. Register a new user account
2. Login using your credentials
3. Add income or expense transactions
4. Let SmartFin auto-categorize expense descriptions
5. Store transaction data in SQLite
6. Analyze patterns with Pandas
7. Detect overspending
8. Predict next month expenses
9. View dashboards and reports
10. Review AI-generated suggestions
11. Logout securely

## Example Viva Explanation

This project demonstrates full-stack development and applied Machine Learning in one system.

- Flask handles routing, session management, and template rendering.
- SQLite stores users and transactions in a lightweight local database.
- Naive Bayes classifies text descriptions into financial categories.
- Pandas performs monthly grouping, category distribution analysis, and trend detection.
- Linear Regression predicts future expense values using historical monthly totals.
- Chart.js visualizes financial analytics for easier user understanding.

## Future Enhancements

- Budget goal setting
- CSV report export
- Email overspending alerts
- Dark mode toggle
- Bank API integration
- Recurring transaction automation

## Author Notes

This project is structured to be easy to explain during a viva:

- Separate modules for database, ML, and analytics
- Clear route-based Flask application design
- Readable templates and styling
- Straightforward rule-based financial suggestions
- Explainable models suitable for academic presentation


