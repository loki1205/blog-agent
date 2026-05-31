"""
Agent Janani — Automated tech blog draft creator.
Triggered by Google Calendar events prefixed with "BLOG - ".
Runs daily via GitHub Actions. Zero cost stack:
  - Google Calendar API (free)
  - Gemini API (free tier)
  - Pexels API (free)
  - Dev.to API (free)
  - Gmail SMTP (free)
"""

import os
import json
import smtplib
import logging
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.generativeai as genai

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("janani")

# ── Constants ─────────────────────────────────────────────────────────────────
BLOG_PREFIX = "BLOG - "
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

FALLBACK_IMAGE_URL = (
    "https://images.pexels.com/photos/546819/pexels-photo-546819.jpeg"
    "?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1"
)

GEMINI_MODEL = "gemini-2.5-flash"  # fast + free tier friendly

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_env(key: str) -> str:
    """Fetch a required environment variable or raise clearly."""
    val = os.environ.get(key, "").strip()
    if not val:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return val


# ── Step 1: Calendar polling ──────────────────────────────────────────────────

def fetch_blog_event() -> dict | None:
    """
    Poll today's Google Calendar events and return the first one
    whose title starts with 'BLOG - ', or None if none found.
    """
    log.info("Polling Google Calendar for today's BLOG events...")

    service_account_json = get_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    calendar_id = get_env("GOOGLE_CALENDAR_ID")

    credentials = service_account.Credentials.from_service_account_info(
        json.loads(service_account_json),
        scopes=CALENDAR_SCOPES,
    )
    service = build("calendar", "v3", credentials=credentials)

    today = datetime.date.today()
    time_min = datetime.datetime(today.year, today.month, today.day, 0, 0, 0).isoformat() + "Z"
    time_max = datetime.datetime(today.year, today.month, today.day, 23, 59, 59).isoformat() + "Z"

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    log.info(f"Found {len(events)} event(s) today.")

    for event in events:
        title = event.get("summary", "")
        if title.startswith(BLOG_PREFIX):
            topic = title[len(BLOG_PREFIX):].strip()
            context_notes = event.get("description", "").strip()
            log.info(f"Matched blog event: '{topic}'")
            return {"topic": topic, "context_notes": context_notes}

    log.info("No BLOG - event found today. Terminating gracefully.")
    return None


# ── Step 2: Gemini single-turn structured output ──────────────────────────────

SYSTEM_PROMPT = """You are Janani, a technical content writer. Your tone is clear, 
authoritative yet accessible — like a senior engineer teaching a peer. 
You NEVER use cliché openers like "In today's fast-paced world..." or "Unleash the power of...".
You write structured, scannable content with clean Markdown (##, ###, bold, bullets, code blocks).
You ALWAYS return ONLY a raw JSON object — no markdown fences, no preamble, no explanation."""

def build_user_prompt(topic: str, context_notes: str) -> str:
    context_section = (
        f"Context notes from the author (treat these as the core thesis — prioritise heavily):\n{context_notes}"
        if context_notes
        else "No context notes provided. Write a comprehensive technical overview of the topic."
    )

    return f"""Topic: {topic}

{context_section}

Return a JSON object with exactly these keys:

{{
  "blog_markdown": "Full high-quality technical blog post in Markdown. Use ## and ### headers, bold for key terms, bullet points, and code blocks where relevant. No fluff. Minimum 600 words.",
  "dev_to_tags": ["tag1", "tag2", "tag3"],
  "image_search_keyword": "A concrete physical noun phrase for Pexels image search (e.g. 'neon server rack', 'circuit board closeup'). NOT abstract like 'artificial intelligence'.",
  "linkedin_post": "Hook-driven LinkedIn post. Use line breaks for readability. End with a CTA to read the article. 150-250 words.",
  "x_post": "Punchy tweet under 280 characters. Hook + insight + CTA. No hashtag spam — max 2 hashtags."
}}"""


def call_gemini(topic: str, context_notes: str) -> dict:
    """Call Gemini with a single structured prompt, return parsed JSON."""
    log.info("Calling Gemini API for content generation...")

    genai.configure(api_key=get_env("GEMINI_API_KEY"))

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            max_output_tokens=8192,   # blog markdown needs room; 4096 was too tight
            temperature=0.7,
            response_mime_type="application/json",  # enforce JSON mode
        ),
    )

    response = model.generate_content(build_user_prompt(topic, context_notes))

    # Log finish reason so truncation is always visible in Actions logs
    finish_reason = getattr(response.candidates[0], "finish_reason", "UNKNOWN")
    log.info(f"Gemini finish_reason: {finish_reason}")
    if str(finish_reason) in ("2", "MAX_TOKENS", "FinishReason.MAX_TOKENS"):
        raise RuntimeError(
            "Gemini hit max_output_tokens and truncated the response — "
            "the JSON is incomplete. Increase max_output_tokens or shorten the prompt."
        )

    raw = response.text.strip()

    # Strip accidental markdown fences if JSON mode isn't respected
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # Log the tail of the raw response so you can see exactly where it cut off
        preview = raw[-300:] if len(raw) > 300 else raw
        log.error(f"JSON parse failed. Last 300 chars of response:\n{preview}")
        raise RuntimeError(f"Gemini returned invalid JSON: {e}") from e

    required_keys = {"blog_markdown", "dev_to_tags", "image_search_keyword", "linkedin_post", "x_post"}
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"Gemini response missing keys: {missing}")

    log.info("Gemini content generated successfully.")
    return data


# ── Step 3: Pexels image fetch ────────────────────────────────────────────────

def fetch_pexels_image(keyword: str) -> str:
    """Search Pexels for a landscape image, return its URL."""
    log.info(f"Searching Pexels for: '{keyword}'")

    api_key = get_env("PEXELS_API_KEY")
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": api_key}
    params = {"query": keyword, "orientation": "landscape", "per_page": 5}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])

        if not photos:
            log.warning("No Pexels results — using fallback image.")
            return FALLBACK_IMAGE_URL

        image_url = photos[0]["src"]["large2x"]
        log.info(f"Pexels image found: {image_url}")
        return image_url

    except Exception as e:
        log.warning(f"Pexels API error ({e}) — using fallback image.")
        return FALLBACK_IMAGE_URL


# ── Step 4: Dev.to draft creation ─────────────────────────────────────────────

def sanitize_devto_tags(raw_tags: list) -> list:
    """
    Dev.to tag rules:
    - Max 4 tags
    - Lowercase only
    - Letters and digits only (no spaces, hyphens, dots, etc.)
    - Max 30 chars each
    """
    import re
    cleaned = []
    for tag in raw_tags:
        tag = tag.lower().strip()
        tag = re.sub(r"[^a-z0-9]", "", tag)
        tag = tag[:30]
        if tag:
            cleaned.append(tag)
    return cleaned[:4]


def create_devto_draft(topic: str, content: dict, cover_image_url: str) -> str:
    """POST a draft article to Dev.to, return the draft URL."""
    log.info("Creating Dev.to draft...")

    api_key = get_env("DEVTO_API_KEY")
    url = "https://dev.to/api/articles"
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    tags = sanitize_devto_tags(content["dev_to_tags"])
    log.info(f"Dev.to tags (sanitized): {tags}")

    # Prepend image at top of markdown body — more reliable than cover_image
    # since Dev.to's backend often rejects direct Pexels URLs for cover_image.
    image_markdown = f"![Cover Image]({cover_image_url})\n\n"
    body = image_markdown + content["blog_markdown"]

    payload = {
        "article": {
            "title": topic,
            "body_markdown": body,
            "tags": tags,
            "published": False,  # always save as draft
        }
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)

    if not resp.ok:
        log.error(f"Dev.to API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    draft_url = resp.json().get("url", "https://dev.to/dashboard")
    log.info(f"Dev.to draft created: {draft_url}")
    return draft_url


# ── Step 5: Email digest ──────────────────────────────────────────────────────

def send_email_digest(topic: str, draft_url: str, content: dict) -> None:
    """Send a digest email via Gmail SMTP with all copy ready to use."""
    log.info("Sending email digest...")

    smtp_user = get_env("GMAIL_ADDRESS")
    smtp_pass = get_env("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL", smtp_user)  # default: send to self

    subject = f"📝 Janani Draft Ready: {topic}"

    html_body = f"""
<html><body style="font-family: Arial, sans-serif; max-width: 680px; margin: auto; color: #222;">

<h2 style="color: #4F46E5;">🤖 Janani — Blog Draft Ready</h2>
<p>Your blog draft for <strong>{topic}</strong> has been created and is waiting for your review.</p>

<h3>🔗 Dev.to Draft</h3>
<p><a href="{draft_url}" style="background:#4F46E5;color:white;padding:10px 20px;
   border-radius:6px;text-decoration:none;display:inline-block;">
   Review Draft on Dev.to →
</a></p>

<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">

<h3>💼 LinkedIn Copy</h3>
<pre style="background:#f5f5f5;padding:16px;border-radius:6px;white-space:pre-wrap;
            font-family:inherit;font-size:14px;">{content["linkedin_post"]}</pre>

<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">

<h3>🐦 X / Twitter Copy</h3>
<pre style="background:#f5f5f5;padding:16px;border-radius:6px;white-space:pre-wrap;
            font-family:inherit;font-size:14px;">{content["x_post"]}</pre>

<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
<p style="font-size:12px;color:#999;">
  Sent by Agent Janani • {datetime.date.today().strftime("%B %d, %Y")}
</p>

</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, recipient, msg.as_string())

    log.info(f"Digest email sent to {recipient}.")


# ── Orchestrator ──────────────────────────────────────────────────────────────

def main():
    log.info("=== Agent Janani starting ===")

    # Step 1
    event = fetch_blog_event()
    if not event:
        log.info("=== No work today. Janani done. ===")
        return

    topic = event["topic"]
    context_notes = event["context_notes"]

    # Step 2
    content = call_gemini(topic, context_notes)

    # Step 3
    image_url = fetch_pexels_image(content["image_search_keyword"])

    # Step 4
    draft_url = create_devto_draft(topic, content, image_url)

    # Step 5
    send_email_digest(topic, draft_url, content)

    log.info("=== Agent Janani completed successfully. ===")


if __name__ == "__main__":
    main()