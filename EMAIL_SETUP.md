# SmartFin Email Notifications Setup Guide

## Quick Setup (3 minutes)

1. **Install python-dotenv** (if not already installed):
   ```powershell
   pip install python-dotenv
   ```

2. **Copy the example .env file**:
   ```powershell
   Copy-Item .env.example .env
   ```

3. **Open `.env` and update with your Gmail credentials**:
   - Open the file `.env` in your editor
   - Replace `your-email@gmail.com` with your actual Gmail address
   - Replace `your-app-password` with your Gmail App Password

4. **Restart the Flask app**:
   ```powershell
   python app.py
   ```

5. **Verify email is enabled**:
   - Go to Budgets page in the app
   - You should see: "Email notifications are enabled"

## Getting Your Gmail App Password

1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already enabled
3. Go back to Security → App Passwords
4. Select Mail and Windows Computer
5. Google will generate a 16-character password
6. Copy and paste that into `.env` as `SMARTFIN_SMTP_PASSWORD`

## Environment Variables Explained

- `SMARTFIN_SMTP_HOST`: SMTP server address (Gmail: smtp.gmail.com)
- `SMARTFIN_SMTP_PORT`: SMTP port (Gmail: 587)
- `SMARTFIN_SMTP_USERNAME`: Your Gmail address
- `SMARTFIN_SMTP_PASSWORD`: Your Gmail App Password
- `SMARTFIN_SMTP_USE_TLS`: TLS encryption (true for Gmail)
- `SMARTFIN_EMAIL_FROM`: Email sender address

## Troubleshooting

- **Emails not sending**: Check that all variables in `.env` are filled correctly
- **App won't start**: Make sure `.env` file is in the project root (same folder as `app.py`)
- **Gmail says "Less secure app"**: You must use an App Password, not your regular password
- **SMTP connection timeout**: Check internet connection and SMTP_HOST is correct

## Testing Email Alerts

1. Go to Budgets page and set a Food budget to Rs. 1000
2. Add an expense of Rs. 900 in Food category
3. You should get:
   - In-app flash alert
   - Email notification (if configured)
4. Alerts are sent only once per category per month per threshold

## Files Modified

- `.env.example` - Template for configuration (checked into git)
- `.env` - Your actual credentials (NOT checked into git, local only)
- `requirements.txt` - Added `python-dotenv` dependency
- `app.py` - Added `load_dotenv()` at startup
