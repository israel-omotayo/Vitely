# Vitely

A production-ready Django booking platform for wellness businesses.

**Live demo:** [vitely.coreapp.name.ng](https://vitely.coreapp.name.ng) *(Render Free — first load may take ~10 s after inactivity)*

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6, Python 3.12 |
| Database | PostgreSQL (Supabase) |
| Cache / Sessions | Redis (Upstash) |
| Frontend | Django Templates + HTMX, Tailwind CSS CDN |
| Email | Resend HTTP API |
| Rate limiting | Cache-backed atomic counter |
| Hosting | Render |

---

## Architecture

```
Request → View → DTO (schemas.py) → Service → Model → DB
```

- **Views** — thin. Read the request, call a service, return a response. No business logic.
- **DTOs** (`schemas.py`) — validate and type-annotate data before it reaches services.
- **Services** — all business logic lives here. Never touch `request`. Fully unit-testable.
- **Decorators** — enforce owner/staff permissions before the view runs.
- **Context processors** — inject active business profile into every template.

---

## Features

**Public booking flow**
- Browse services with duration, price, and description
- Calendar widget highlights available dates
- HTMX slot picker — click a date, see available periods without a full reload
- Booking form — name, email, phone, notes
- Email verification — slot held for 30 minutes, confirmed on click
- Magic link — customers look up their bookings by email
- Customer cancellation via unique link — enforces notice window

**Dashboard (owner + staff)**
- Home — today's appointments, weekly/monthly stats, revenue chart (owner only)
- Calendar — FullCalendar month/week/list view, colour-coded by service
- Appointments — filterable, searchable, paginated list (10 per page)
- Appointment detail — full booking info, status update
- New booking — admin creates a confirmed booking on behalf of a customer
- Services — create, edit, toggle active/inactive
- Availability — weekly schedule (per day, open/closed, hours)
- Blocked times — block out holidays, training days, leave
- Staff — invite by email, view pending invites, revoke access

**Auth**
- One-time business setup at `/accounts/setup/`
- Login with rate limiting (10 attempts/min per IP)
- Password reset via Django's built-in flow with Vitely-branded emails
- Staff invite flow — UUID token, 48-hour expiry
- Password change (logged in)

---

## Project Structure

```
vitely/
├── core/                    # Rate limiter, email utils, middleware
├── accounts/                # Auth: setup, login, password reset, staff invite
├── bookings/                # Public booking flow, slot algorithm, caching
├── dashboard/               # Admin panel, services, availability, staff
├── templates/               # All HTML templates
├── static/                  # CSS, favicon
└── vitely/
    └── settings/
        ├── base.py          # Shared settings
        ├── dev.py           # Local development
        └── prod.py          # Production (Render)
```

---

## Local Setup

```bash
git clone https://github.com/israel-omotayo/vitely.git
cd vitely
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` in the project root:

```ini
SECRET_KEY=any-random-string-for-dev
DB_NAME=vitely_dev
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432

# Leave empty in dev — emails print to terminal
RESEND_API_KEY=
RESEND_FROM_EMAIL=
CRON_SECRET=
```

```bash
python manage.py migrate --settings=vitely.settings.dev
python manage.py runserver --settings=vitely.settings.dev
```

Visit `http://127.0.0.1:8000/accounts/setup/` to create your owner account and business profile.

---

## Deploying to Render

### Prerequisites

| Service | Purpose |
|---|---|
| [Supabase](https://supabase.com) | PostgreSQL database |
| [Upstash](https://upstash.com) | Redis (cache, sessions, rate limiting) — optional |
| [Resend](https://resend.com) | Transactional email |

---

### Step 1 — Database (Supabase)

1. Create a project at [supabase.com](https://supabase.com).
2. Go to **Settings → Database → Connection string** tab.
3. Select **Session pooler** (not Transaction pooler — that mode breaks Django's prepared statements).
4. Note these values:
   - `DB_HOST` — `aws-0-<region>.pooler.supabase.com`
   - `DB_USER` — `postgres.<project-ref>`
   - `DB_PASSWORD` — your database password
   - `DB_PORT` — always `5432`

### Step 2 — Redis (Upstash) — optional

1. Create an account at [upstash.com](https://upstash.com).
2. Create a Redis database — pick the region closest to your Render server.
3. Copy the **Redis URL** (starts with `rediss://`).

Without Redis, Vitely falls back to in-process LocMem cache — fine for low traffic.

### Step 3 — Email (Resend)

1. Create an account at [resend.com](https://resend.com).
2. Add and verify your sending domain under **Domains**.
3. Generate an API key under **API Keys** (send-only scope is fine).

> **Note:** Render blocks outbound SMTP (ports 587/465). Vitely calls the Resend HTTP API directly from `core/utils.py`, bypassing this entirely.

### Step 4 — Deploy the Web Service

1. Render → **New Web Service** → connect your GitHub repo.
2. **Runtime:** Python
3. **Build command:**
   ```
   pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate && python manage.py create_superuser_from_env
   ```
4. **Start command:**
   ```
   gunicorn vitely.wsgi:application --workers 1 --timeout 120 --bind 0.0.0.0:$PORT
   ```
   > Keep workers at **1** on the free tier (512 MB RAM). More workers will OOM-kill the instance.

5. Set all environment variables (Step 5).

---

### Step 5 — Environment Variables

| Variable | Value |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `vitely.settings.prod` |
| `SECRET_KEY` | Strong random string |
| `ALLOWED_HOSTS` | `yourapp.onrender.com` (add custom domain if you have one) |
| `RENDER_EXTERNAL_HOSTNAME` | `yourapp.onrender.com` |
| `BASE_FRONTEND_URL` | `yourapp.onrender.com` (or custom domain, no https://) |
| `DB_HOST` | Supabase Session Pooler host |
| `DB_PORT` | `5432` |
| `DB_NAME` | `postgres` |
| `DB_USER` | Supabase Session Pooler user |
| `DB_PASSWORD` | Your Supabase database password |
| `REDIS_URL` | From Upstash — starts with `rediss://` *(optional)* |
| `RESEND_API_KEY` | From Resend |
| `RESEND_FROM_EMAIL` | e.g. `noreply@yourdomain.com` |
| `CRON_SECRET` | A long random string |

---

### Step 6 — First-time Setup

After your first deploy, visit:

```
https://yourapp.onrender.com/accounts/setup/
```

This page is only available once. Fill in your business name and create your owner account. It closes itself permanently after setup — no one else can ever access it again.

---

### Step 7 — Scheduled Jobs (cron-job.org)

Vitely uses [cron-job.org](https://cron-job.org) to trigger scheduled tasks via HTTP. No separate worker process needed.

Create an account, then add two jobs. For each:
- **Method:** POST
- **Header:** `X-Cron-Secret: <your CRON_SECRET value>`

| Job | URL | Schedule |
|---|---|---|
| Expire unverified bookings | `https://yourapp.onrender.com/cron/expire/` | `*/15 * * * *` |
| Send appointment reminders | `https://yourapp.onrender.com/cron/reminders/` | `0 8 * * *` |

All times are UTC.

---

## Performance Notes

- **Slot caching** — available slots cached per `(service, date)` for 60 s; available dates cached per `(service, month)` for 5 min. Cache is invalidated immediately on booking create/cancel.
- **N+1 fix** — `get_available_dates` pre-fetches all availability, appointments, and blocked times for the whole month in 3 queries instead of up to 93.
- **Sessions in Redis** — zero DB writes per page load for authenticated users (when `REDIS_URL` is set).
- **`CONN_MAX_AGE=60`** — persistent DB connections; avoids ~5 ms setup cost per request.
- **WhiteNoise + `CompressedManifestStaticFilesStorage`** — static files served directly from Gunicorn with gzip + cache-busting hashes; no Nginx needed.
- **`CONN_HEALTH_CHECKS=True`** — stale connections detected and replaced instead of causing a 500 error.
- **`@transaction.atomic` on `create_booking`** — re-checks slot availability inside the transaction to prevent double-booking under concurrent load.