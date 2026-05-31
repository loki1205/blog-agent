"""
dry_run.py — Janani connectivity checker.
Tests each integration independently and reports pass/fail.
Run locally: python dry_run.py
"""

import os
import json
import smtplib
import datetime
from zoneinfo import ZoneInfo
# ── Dependency check first ────────────────────────────────────────────────────
MISSING = []
try:
    import requests
except ImportError:
    MISSING.append("requests")
try:
    import google.generativeai as genai
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except ImportError:
    MISSING.append("google-generativeai / google-api-python-client")

if MISSING:
    print(f"\n❌ Missing packages: {', '.join(MISSING)}")
    print("   Run: pip install -r requirements.txt\n")
    exit(1)

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional; fall through to os.environ

# ─────────────────────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "
results = []


def check(label: str, fn):
    try:
        note = fn()
        results.append((PASS, label, note or ""))
    except Exception as e:
        results.append((FAIL, label, str(e)))


def env(key):
    val = os.environ.get(key, "").strip()
    if not val:
        raise EnvironmentError(f"{key} is not set")
    return val


# ── 1. Env vars present ───────────────────────────────────────────────────────
def check_env_vars():
    required = [
        "GEMINI_API_KEY",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CALENDAR_ID",
        "PEXELS_API_KEY",
        "DEVTO_API_KEY",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "NOTIFY_EMAIL",
    ]
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise EnvironmentError(f"Missing: {', '.join(missing)}")
    return f"All {len(required)} secrets present"

check("Environment variables", check_env_vars)


# ── 2. Service account JSON is valid ─────────────────────────────────────────
def check_sa_json():
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON")
    data = json.loads(raw)
    email = data.get("client_email", "?")
    if data.get("type") != "service_account":
        raise ValueError("JSON 'type' is not 'service_account'")
    return f"client_email: {email}"

check("Service account JSON (parse)", check_sa_json)


# ── 3. Google Calendar API ────────────────────────────────────────────────────
def check_calendar():
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON")
    calendar_id = env("GOOGLE_CALENDAR_ID")

    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    service = build("calendar", "v3", credentials=creds)

    # 1. Force the timezone to IST (Asia/Kolkata)
    ist_tz = ZoneInfo("Asia/Kolkata")

    # 2. Get the current date explicitly in IST
    today = datetime.datetime.now(ist_tz).date()

    # 3. Build timezone-aware start and end times for today
    start_of_day = datetime.datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=ist_tz)
    end_of_day = datetime.datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=ist_tz)

    # 4. Generate the proper ISO strings (Python automatically handles the "+05:30" offset)
    t_min = start_of_day.isoformat()
    t_max = end_of_day.isoformat()

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=t_min,
        timeMax=t_max,
        singleEvents=True,
        maxResults=10,
    ).execute()

    events = result.get("items", [])
    blog_events = [e for e in events if e.get("summary", "").startswith("BLOG - ")]
    total = len(events)
    blog_count = len(blog_events)

    note = f"{total} event(s) today"
    if blog_count:
        titles = ", ".join(f'"{e["summary"]}"' for e in blog_events)
        note += f" — {blog_count} BLOG event(s): {titles}"
    else:
        note += " — no BLOG - events found (that's fine for a dry run)"
    return note

check("Google Calendar API", check_calendar)


# ── 4. Gemini API ─────────────────────────────────────────────────────────────
def check_gemini():
    genai.configure(api_key=env("GEMINI_API_KEY"))
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config=genai.GenerationConfig(max_output_tokens=32),
    )
    resp = model.generate_content("Reply with only the word: JANANI")
    text = resp.text.strip()
    return f"Response: '{text}'"

check("Gemini API", check_gemini)


# ── 5. Pexels API ─────────────────────────────────────────────────────────────
def check_pexels():
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": env("PEXELS_API_KEY")},
        params={"query": "circuit board", "per_page": 1, "orientation": "landscape"},
        timeout=10,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        raise ValueError("No photos returned — check API key quota")
    url = photos[0]["src"]["medium"]
    return f"Image found: {url[:60]}..."

check("Pexels API", check_pexels)


# ── 6. Dev.to API ─────────────────────────────────────────────────────────────
def check_devto():
    resp = requests.get(
        "https://dev.to/api/users/me",
        headers={"api-key": env("DEVTO_API_KEY")},
        timeout=10,
    )
    resp.raise_for_status()
    username = resp.json().get("username", "?")
    return f"Authenticated as @{username}"

check("Dev.to API", check_devto)


# ── 7. Gmail SMTP ─────────────────────────────────────────────────────────────
def check_gmail():
    gmail = env("GMAIL_ADDRESS")
    password = env("GMAIL_APP_PASSWORD").replace(" ", "")  # strip spaces if any
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
        server.login(gmail, password)
    return f"Login OK for {gmail}"

check("Gmail SMTP", check_gmail)


# ── Print results ─────────────────────────────────────────────────────────────
print()
print("=" * 58)
print("  Agent Janani — Dry Run")
print("=" * 58)

all_passed = True
for status, label, note in results:
    print(f"  {status}  {label}")
    if note:
        print(f"       {note}")
    if status == FAIL:
        all_passed = False

print("=" * 58)
if all_passed:
    print("  🎉 All checks passed. Janani is ready to run!")
else:
    print("  🔧 Some checks failed. Fix the issues above and re-run.")
print("=" * 58)
print()

exit(0 if all_passed else 1)
