let expenseCategoryChart;
let monthlyTrendChart;
let savingsExpenseChart;

async function loadChartData() {
    const chartTargets = [
        document.getElementById('expenseCategoryChart'),
        document.getElementById('monthlyTrendChart'),
        document.getElementById('savingsExpenseChart'),
    ];

    if (!chartTargets.some(Boolean)) {
        return;
    }

    try {
        let endpoint = '/api/chart_data';
        const reportContext = document.getElementById('reportChartContext');
        if (reportContext) {
            const params = new URLSearchParams();
            const reportType = reportContext.dataset.reportType || '';
            const month = reportContext.dataset.month || '';
            const year = reportContext.dataset.year || '';
            const compareRange = reportContext.dataset.compareRange || '';

            if (reportType) {
                params.set('report_type', reportType);
            }
            if (month) {
                params.set('month', month);
            }
            if (year) {
                params.set('year', year);
            }
            if (compareRange) {
                params.set('compare_range', compareRange);
            }

            if (params.toString()) {
                endpoint = endpoint + '?' + params.toString();
            }
        }

        const response = await fetch(endpoint);
        if (!response.ok) {
            throw new Error('Failed to load chart data');
        }

        const payload = await response.json();
        renderExpenseCategoryChart(payload.category_distribution);
        renderMonthlyTrendChart(payload.monthly_spending);
        renderSavingsExpenseChart(payload.savings_vs_expenses);
    } catch (error) {
        console.error('Chart loading error:', error);
    }
}

function destroyChart(instance) {
    if (instance) {
        instance.destroy();
    }
}

function renderExpenseCategoryChart(categories) {
    const canvas = document.getElementById('expenseCategoryChart');
    if (!canvas) {
        return;
    }

    destroyChart(expenseCategoryChart);
    expenseCategoryChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: categories.map((item) => item.category),
            datasets: [{
                data: categories.map((item) => item.amount),
                backgroundColor: ['#0c8a9e', '#1e9f70', '#d05454', '#f2a83b', '#6c8cff', '#9357d9', '#4f6670'],
                borderWidth: 0,
                hoverOffset: 10,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                },
            },
        },
    });
}

function renderMonthlyTrendChart(monthlySpending) {
    const canvas = document.getElementById('monthlyTrendChart');
    if (!canvas) {
        return;
    }

    destroyChart(monthlyTrendChart);
    monthlyTrendChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: monthlySpending.map((item) => item.month),
            datasets: [{
                label: 'Expenses',
                data: monthlySpending.map((item) => item.amount),
                borderColor: '#0c8a9e',
                backgroundColor: 'rgba(12, 138, 158, 0.12)',
                fill: true,
                tension: 0.35,
                pointRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                },
            },
        },
    });
}

function renderSavingsExpenseChart(monthlyFinancials) {
    const canvas = document.getElementById('savingsExpenseChart');
    if (!canvas) {
        return;
    }

    const reportContext = document.getElementById('reportChartContext');
    const compareRange = reportContext ? (reportContext.dataset.compareRange || 'last_3_months') : 'last_3_months';
    const incomeLabel = compareRange === 'last_month' ? 'Income (Last Month)' : 'Income (Last 3 Months)';
    const expenseLabel = compareRange === 'last_month' ? 'Expenses (Last Month)' : 'Expenses (Last 3 Months)';
    const savingsLabel = compareRange === 'last_month' ? 'Savings (Last Month)' : 'Savings (Last 3 Months)';

    destroyChart(savingsExpenseChart);
    savingsExpenseChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: monthlyFinancials.map((item) => item.month),
            datasets: [
                {
                    label: incomeLabel,
                    data: monthlyFinancials.map((item) => item.income),
                    backgroundColor: '#1e9f70',
                    borderRadius: 8,
                },
                {
                    label: expenseLabel,
                    data: monthlyFinancials.map((item) => item.expense),
                    backgroundColor: '#d05454',
                    borderRadius: 8,
                },
                {
                    label: savingsLabel,
                    data: monthlyFinancials.map((item) => item.savings),
                    backgroundColor: '#0c8a9e',
                    borderRadius: 8,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                },
            },
        },
    });
}

document.addEventListener('DOMContentLoaded', loadChartData);