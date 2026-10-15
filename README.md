# ADC Brew Cafe — Flask Backend

A beginner-friendly backend for the ADC Brew Cafe website using **Python, Flask, and SQLite**.

## Features
- Serves the cafe website at `/`
- `GET /api/health` — check whether the backend is running
- `GET /api/menu` and `GET /api/menu?category=coffee` — sample menu API
- `POST /api/reservations` — validates and stores table requests in SQLite
- `POST /api/contact` — validates and stores contact messages in SQLite
- Creates `adc_brew_cafe.db` automatically on startup

## Run on Windows

1. Install Python 3.10 or newer.
2. Extract this ZIP folder.
3. Open the extracted `adc_brew_cafe_backend` folder.
4. Click the folder address bar in File Explorer, type `cmd`, and press Enter.
5. Run:

   ```bash
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```

6. Open **http://127.0.0.1:5000** in your browser.
7. Check the backend at **http://127.0.0.1:5000/api/health**.

Keep the terminal open while using the website. Do not open `templates/index.html` directly; the form needs the Flask server.

## Database
Reservations and contact messages are stored in the local SQLite database file `adc_brew_cafe.db`. Back up this file if you need to keep submissions.

## Before publishing
- Replace placeholder address and phone details in the website.
- Use a production WSGI server instead of Flask's development server.
- Add an admin login before building a page that displays customer submissions.
- Configure HTTPS and appropriate privacy/retention practices before collecting real customer data.

## API example

```json
{
  "name": "Aarav Sharma",
  "email": "aarav@example.com",
  "phone": "9876543210",
  "guests": 2,
  "date": "2026-12-20",
  "time": "18:30",
  "message": "Window-side table if available"
}
```

## Deploy on Vercel
1. Upload the files to a GitHub repository.
2. On vercel.com choose **Add New -> Project**, import the repo, keep the default settings, and click **Deploy**.
3. Open the `.vercel.app` URL and check `/api/health`.

## Website features
- Menu with **Add to cart**, cart drawer, and **Place order** (pay at the counter)
- **Sign in / Create account** (passwords are hashed, login uses a signed cookie)
- **My account** shows your recent orders
- **Reserve a table** and **Send a message** forms
- Prices are always calculated on the server, never trusted from the browser

## Settings (environment variables on Vercel)
| Name | What it is |
|------|-----------|
| `SECRET_KEY` | **Required.** A long random text that signs login cookies. Create one with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Added automatically when you connect Neon. Needed to keep data permanently. |

Add them in Vercel: **Project -> Settings -> Environment Variables**, then **Redeploy**.

## Permanent database (Neon Postgres)
The app uses Postgres when `DATABASE_URL` exists, and a local SQLite file otherwise.
1. In your Vercel project open **Storage** (or **Marketplace**) -> **Neon** -> create a free database and connect it to the project.
2. Vercel adds `DATABASE_URL` automatically. Redeploy the project.
3. Tables (users, orders, order_items, reservations, contact_messages) are created automatically on first use.
4. View data in the Neon dashboard -> **Tables** or **SQL Editor** (`SELECT * FROM orders;`).

Without `DATABASE_URL`, data on Vercel is stored in temporary `/tmp` and is lost.

## API (new)
- `POST /api/auth/register` `{name, email, password}`
- `POST /api/auth/login` `{email, password}`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/orders` `{items:[{id, quantity}], note}` (login required)
- `GET /api/orders` your recent orders (login required)

## Before real customers
- Add online payment (for example Razorpay) if you do not want pay-at-counter only.
- Add rate limiting on login and an admin page (with its own login) to view and update orders.
- Add privacy policy and password-reset by email.
