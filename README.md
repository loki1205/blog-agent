# Agent Janani — Setup Guide

Zero-cost automated blog pipeline: Google Calendar → Gemini → Dev.to → Gmail.

---

## Files

```
janani/
├── janani.py                        # The agent
├── requirements.txt                 # Python dependencies
├── .github/
│   └── workflows/
│       └── janani.yml               # GitHub Actions schedule
└── SETUP.md                         # This file
```

---

## Step 1 — Get Your API Keys

### 1a. Gemini API Key (Free)
1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API Key**
3. Copy the key → GitHub Secret: `GEMINI_API_KEY`

---

### 1b. Google Calendar — Service Account (Free)
Janani reads your calendar from GitHub Actions using a Service Account.

1. Go to https://console.cloud.google.com
2. Create a new project (e.g. "janani-agent")
3. Enable **Google Calendar API**:
   - APIs & Services → Enable APIs → search "Google Calendar API" → Enable
4. Create a Service Account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Name it `janani-reader`, role: **Viewer**
   - After creation, click the account → **Keys** tab → Add Key → JSON
   - Download the JSON file
5. **Share your calendar** with the service account:
   - Open Google Calendar → Settings for your calendar → Share with people
   - Add the service account email (looks like `janani-reader@your-project.iam.gserviceaccount.com`)
   - Permission: **See all event details**
6. Get your **Calendar ID**:
   - Calendar Settings → scroll down → "Calendar ID" (looks like `you@gmail.com` for primary)

**GitHub Secrets to add:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` → paste the entire contents of the downloaded JSON file
- `GOOGLE_CALENDAR_ID` → your calendar ID (e.g. `you@gmail.com`)

---

### 1c. Pexels API Key (Free)
1. Go to https://www.pexels.com/api/
2. Sign up / log in → **Your API Key** section
3. Copy the key → GitHub Secret: `PEXELS_API_KEY`

---

### 1d. Dev.to API Key (Free)
1. Log in to https://dev.to
2. Settings → **Extensions** → scroll to "DEV API Keys"
3. Generate a new key → GitHub Secret: `DEVTO_API_KEY`

---

### 1e. Gmail App Password (Free)
Do NOT use your real Gmail password. Use an App Password:

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already on
3. Search "App passwords" → create one for "Mail" / "Other (janani)"
4. Copy the 16-character password

**GitHub Secrets to add:**
- `GMAIL_ADDRESS` → your full Gmail address
- `GMAIL_APP_PASSWORD` → the 16-character app password
- `NOTIFY_EMAIL` → where to send digests (can be same as Gmail, or any email)

---

## Step 2 — Add GitHub Secrets

In your GitHub repo:
1. Settings → **Secrets and variables** → Actions → **New repository secret**
2. Add all 8 secrets:

| Secret Name | Value |
|---|---|
| `GEMINI_API_KEY` | From Google AI Studio |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON file contents |
| `GOOGLE_CALENDAR_ID` | Your calendar ID |
| `PEXELS_API_KEY` | From Pexels |
| `DEVTO_API_KEY` | From Dev.to |
| `GMAIL_ADDRESS` | your@gmail.com |
| `GMAIL_APP_PASSWORD` | 16-char app password |
| `NOTIFY_EMAIL` | Where to receive digests |

---

## Step 3 — Push to GitHub

```bash
git init
git add .
git commit -m "feat: add Agent Janani"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

## Step 4 — Create Your First Blog Event

In Google Calendar:
1. Create an event on any day
2. Title it exactly: `BLOG - Your Topic Here`
   - Example: `BLOG - Why Rust is Replacing C in Systems Programming`
3. In the **Description**, add your context notes / thesis / key points:
   ```
   - Focus on memory safety without GC
   - Cover borrow checker mental model
   - Include benchmark comparison vs C
   - Target audience: senior engineers, not beginners
   ```
4. Save the event

Janani will pick it up the next time it runs (7:00 AM IST).

---

## Step 5 — Test It Manually

Don't wait for 7 AM — trigger it immediately:
1. GitHub → **Actions** tab
2. Select "Agent Janani — Daily Blog Draft"
3. Click **Run workflow** → **Run workflow**
4. Watch the logs in real time

---

## How It Works (Quick Reference)

```
07:00 AM IST daily
      │
      ▼
Google Calendar ──► Find event titled "BLOG - ..."
      │
      ▼
Gemini API ──────► Single-turn JSON: blog + tags + image keyword + LinkedIn + X
      │
      ▼
Pexels API ──────► Landscape cover image URL
      │
      ▼
Dev.to API ──────► Create draft (published: false)
      │
      ▼
Gmail SMTP ──────► Digest email with draft link + ready-to-paste social copy
```

---

## Schedule

The workflow runs at **1:30 AM UTC = 7:00 AM IST** daily.

To change the time, edit `.github/workflows/janani.yml`:
```yaml
- cron: "30 1 * * *"   # UTC time
```
Use https://crontab.guru to find your UTC equivalent.

---

## Troubleshooting

**"No BLOG - event found"** — Check the calendar event title starts exactly with `BLOG - ` (with space and dash).

**Gemini JSON parse error** — Rare; the `response_mime_type: application/json` flag enforces JSON mode. If it happens, the run will fail with a clear error in Actions logs.

**Gmail auth error** — Make sure you're using an App Password, not your real Gmail password. 2FA must be enabled.

**Pexels returns no image** — Janani automatically falls back to a generic tech image so the Dev.to draft still gets created.

**Service account calendar access denied** — Ensure you shared the calendar with the service account email and granted "See all event details" permission.
