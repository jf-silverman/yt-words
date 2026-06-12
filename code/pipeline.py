"""
Mad Money daily pipeline.

Steps:
  1. Discover new Mad Money episodes on the CNBC YouTube channel
  2. Fetch transcripts (saved to data/output/)
  3. Analyze with Claude Haiku → structured JSON (sections + stocks)
  4. Update data/stock_sentiments.json
  5. Find matching podcast episode in RSS feed → build Overcast deep links
  6. Format HTML email
  7. Send via Gmail (smtp or mcp mode)

Usage:
    python pipeline.py [--max-episodes N] [--email-mode smtp|mcp] [--dry-run]

Environment variables:
    ANTHROPIC_API_KEY     required for Haiku analysis
    GMAIL_APP_PASSWORD    required for --email-mode smtp
    GMAIL_FROM            sender address (default: joelfsilverman@gmail.com)
    GMAIL_TO              recipient address (default: joelfsilverman@gmail.com)
"""

import argparse
import json
import os
import smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

import anthropic
import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent


def _load_dotenv() -> None:
    """Load .env file from project root into os.environ (no third-party deps)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()
import re
import subprocess

DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
DOCS_DIR = ROOT / "docs"
SENTIMENTS_FILE = DATA_DIR / "stock_sentiments.json"
PROCESSED_FILE = DATA_DIR / "processed_episodes.json"
RULES_FILE = ROOT / "prompts" / "mad_money_rules.md"

CNBC_CHANNEL_ID = "UCrp_UI8XtuYfpiqluWLD7Lw"
MAD_MONEY_RSS = "https://feeds.simplecast.com/TkQfZXMD"
GITHUB_PAGES_BASE = "https://jf-silverman.github.io/yt-words"

GMAIL_FROM = "joelfsilverman@gmail.com"
GMAIL_TO = "joelfsilverman@gmail.com"
GMAIL_SMTP = ("smtp.gmail.com", 587)

SENTIMENT_COLORS = {
    "strong_buy":    "#1a7f37",
    "buy":           "#2da44e",
    "buy_on_pullback": "#4ac26b",
    "mild_buy":      "#80e09a",
    "hold":          "#d4a017",
    "wait":          "#f0c040",
    "caution":       "#f0a030",
    "neutral":       "#8b949e",
    "concern":       "#e06060",
    "avoid":         "#d03030",
    "sell":          "#a00000",
}


# ── 1. Episode discovery ───────────────────────────────────────────────────────

def load_processed() -> list[dict]:
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return []


def save_processed(records: list[dict]) -> None:
    PROCESSED_FILE.write_text(json.dumps(records, indent=2))


def discover_new_episodes(max_n: int = 5) -> list[dict]:
    """Return up to max_n unprocessed Mad Money video dicts [{id, title, date}]."""
    processed_ids = {r["video_id"] for r in load_processed()}

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": 200,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(
            f"https://www.youtube.com/channel/{CNBC_CHANNEL_ID}/videos",
            download=False,
        )

    episodes = []
    for entry in result.get("entries", []):
        title = entry.get("title") or ""
        if "Mad Money" not in title:
            continue
        vid = entry.get("id")
        if vid in processed_ids:
            continue
        episodes.append({"id": vid, "title": title})
        if len(episodes) >= max_n:
            break

    return episodes


# ── 2. Transcript fetch ────────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m}:{s:02d}]"


def _get_upload_date(video_id: str) -> str:
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    raw = info.get("upload_date", "")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def fetch_transcript(video_id: str) -> tuple[str, list, str]:
    """Returns (date_str, snippets, transcript_text). Skips download if file exists."""
    date_str = _get_upload_date(video_id)
    out_path = OUTPUT_DIR / f"{date_str}_transcript.txt"

    if out_path.exists():
        print(f"  Transcript already on disk: {out_path.name}")
        text = out_path.read_text()
        # Return empty snippets list — text is all we need for analysis
        return date_str, [], text

    api = YouTubeTranscriptApi()
    snippets = api.fetch(video_id).snippets
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"{_fmt_ts(s.start)} {s.text}" for s in snippets]
    text = "\n".join(lines)
    out_path.write_text(text)
    return date_str, snippets, text


# ── 3. Haiku analysis ──────────────────────────────────────────────────────────

def analyze_with_haiku(date_str: str, transcript_text: str) -> dict:
    """Call Claude Haiku with the Mad Money rules. Returns parsed analysis dict."""
    system_prompt = RULES_FILE.read_text()
    client = anthropic.Anthropic()

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Episode date: {date_str}\n\n"
                    f"Transcript:\n{transcript_text}"
                ),
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip accidental markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(raw)


# ── 4. Sentiment JSON update ───────────────────────────────────────────────────

def update_stock_sentiments(analysis: dict) -> None:
    if SENTIMENTS_FILE.exists():
        db = json.loads(SENTIMENTS_FILE.read_text())
    else:
        db = {
            "_schema": {
                "sentiment_values": list(SENTIMENT_COLORS.keys()),
                "segment_values": [
                    "opening_commentary", "caller_qa", "interview",
                    "in_depth_analysis", "lightning_round", "closing_commentary",
                ],
            },
            "stocks": {},
        }

    stocks = db.setdefault("stocks", {})
    for stock in analysis.get("stocks", []):
        ticker = stock.get("ticker", "").upper()
        if not ticker:
            continue
        entry = stocks.setdefault(ticker, {
            "company": stock.get("company", ""),
            "mentions": [],
        })
        mention = {
            "date": analysis["episode_date"],
            "sentiment": stock.get("sentiment", "neutral"),
            "segment": stock.get("segment", ""),
            "note": stock.get("note", ""),
        }
        if "price_target" in stock:
            mention["price_target"] = stock["price_target"]
        if "price_level" in stock:
            mention["price_level"] = stock["price_level"]
        entry["mentions"].append(mention)

    SENTIMENTS_FILE.write_text(json.dumps(db, indent=2))


# ── 5. Podcast RSS + Overcast links ───────────────────────────────────────────

def _parse_rss_pubdate(pubdate_str: str) -> date | None:
    """Parse RFC 2822 pubDate like 'Wed, 17 Sep 2025 22:00:00 +0000'."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(pubdate_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def find_podcast_episode(date_str: str) -> str | None:
    """
    Fetch Mad Money RSS feed and return the audio enclosure URL for the episode
    matching date_str (YYYY-MM-DD), or None if not found.
    """
    target = date.fromisoformat(date_str)
    try:
        resp = requests.get(MAD_MONEY_RSS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  RSS fetch failed: {e}")
        return None

    root = ET.fromstring(resp.content)
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}

    for item in root.iter("item"):
        pubdate_el = item.find("pubDate")
        if pubdate_el is None or not pubdate_el.text:
            continue
        ep_date = _parse_rss_pubdate(pubdate_el.text)
        if ep_date != target:
            continue
        enclosure = item.find("enclosure")
        if enclosure is not None:
            return enclosure.get("url")

    return None


def yt_link(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


# ── 6. GitHub Pages redirect pages ────────────────────────────────────────────

def _section_slug(name: str) -> str:
    """'Interview: Honeywell International (HON)' → 'interview-honeywell-international-hon'"""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _redirect_page_html(section_name: str, date_label: str, time_label: str,
                        audio_url: str, seconds: int) -> str:
    overcast_url = f"overcast://x-callback-url/add?url={quote(audio_url)}&t={seconds}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{section_name} · Mad Money {date_label}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, Arial, sans-serif; background: #f6f8fa;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; padding: 20px; }}
    .card {{ background: #fff; border-radius: 16px; padding: 32px 28px;
             max-width: 380px; width: 100%; text-align: center;
             box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
    .show  {{ font-size: 12px; font-weight: 600; letter-spacing: .08em;
              color: #8b949e; text-transform: uppercase; margin-bottom: 6px; }}
    h1     {{ font-size: 20px; color: #24292f; margin-bottom: 6px; line-height: 1.3; }}
    .meta  {{ font-size: 13px; color: #8b949e; margin-bottom: 28px; }}
    .btn   {{ display: block; background: #fc7a1e; color: #fff; padding: 15px 20px;
              border-radius: 12px; text-decoration: none; font-size: 17px;
              font-weight: 600; margin-bottom: 12px; }}
    .btn:active {{ opacity: .85; }}
    .hint  {{ font-size: 12px; color: #8b949e; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="show">Mad Money · Jim Cramer</div>
    <h1>{section_name}</h1>
    <div class="meta">{date_label} &middot; {time_label}</div>
    <a class="btn" href="{overcast_url}">🎙 Open in Overcast</a>
    <div class="hint">Tap the button to jump to this moment in the episode.</div>
  </div>
</body>
</html>"""


def generate_redirect_pages(analysis: dict, audio_url: str | None,
                             date_str: str) -> dict[str, str]:
    """
    Write one HTML redirect page per section (and subsection).
    Returns a dict mapping section start_seconds → GitHub Pages URL.
    Only generates pages when audio_url is available (needed for Overcast link).
    Falls back to YouTube links (handled in build_email_html) when audio_url is None.
    """
    if not audio_url:
        return {}

    dt = datetime.fromisoformat(date_str)
    date_label = dt.strftime("%b %-d, %Y")
    redirect_dir = DOCS_DIR / "redirect" / date_str
    redirect_dir.mkdir(parents=True, exist_ok=True)

    pages: dict[str, str] = {}

    def _write(section: dict, parent_slug: str = "") -> None:
        secs = section.get("start_seconds", 0)
        name = section.get("name", "section")
        slug = _section_slug(name)
        if parent_slug:
            slug = f"{parent_slug}-{slug}"
        time_label = _fmt_seconds(secs)
        html = _redirect_page_html(name, date_label, time_label, audio_url, secs)
        page_path = redirect_dir / f"{slug}.html"
        page_path.write_text(html)
        pages[secs] = f"{GITHUB_PAGES_BASE}/redirect/{date_str}/{slug}.html"

        for sub in section.get("subsections", []):
            _write(sub, parent_slug=slug)

    for section in analysis.get("sections", []):
        _write(section)

    return pages


# ── 7. HTML email formatter ────────────────────────────────────────────────────

def _sentiment_badge(sentiment: str) -> str:
    color = SENTIMENT_COLORS.get(sentiment, "#8b949e")
    label = sentiment.replace("_", " ").upper()
    return (
        f'<span style="background:{color};color:#fff;padding:2px 7px;'
        f'border-radius:3px;font-size:11px;font-weight:bold">{label}</span>'
    )


def _fmt_seconds(s: int) -> str:
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def build_email_html(summaries: list[dict]) -> str:
    """
    summaries: list of dicts with keys:
        date_str, analysis, audio_url (or None), video_id, redirect_pages
    redirect_pages: dict mapping start_seconds (int) → GitHub Pages URL
    """
    parts = ["""
<html><head><meta charset="utf-8">
<style>
  body { font-family: -apple-system, Arial, sans-serif; color: #24292f;
         max-width: 700px; margin: 0 auto; padding: 20px; }
  h2   { color: #0969da; border-bottom: 2px solid #0969da; padding-bottom: 6px; }
  h3   { margin: 20px 0 4px; }
  h3 a { color: #24292f; text-decoration: none; }
  h3 a:hover { text-decoration: underline; }
  .sub   { margin-left: 20px; }
  .summary { color: #57606a; margin: 4px 0 12px; font-size: 14px; }
  table  { border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 13px; }
  th     { background: #f6f8fa; text-align: left; padding: 6px 10px;
           border-bottom: 2px solid #d0d7de; }
  td     { padding: 5px 10px; border-bottom: 1px solid #d0d7de;
           vertical-align: top; }
  .ticker { font-weight: bold; font-family: monospace; }
  .note   { color: #57606a; font-size: 12px; }
  .footer { margin-top: 24px; color: #8b949e; font-size: 11px; border-top: 1px solid #d0d7de; padding-top: 8px; }
</style></head><body>
"""]

    for ep in summaries:
        analysis = ep["analysis"]
        audio_url = ep.get("audio_url")
        video_id = ep["video_id"]
        redirect_pages = ep.get("redirect_pages", {})
        ep_date = analysis.get("episode_date", ep["date_str"])
        dt = datetime.fromisoformat(ep_date)
        date_label = dt.strftime("%A, %B %-d, %Y")

        parts.append(f'<h2>Mad Money &mdash; {date_label}</h2>')
        parts.append(f'<p>{analysis.get("market_summary", "")}</p>')

        def _section_parts(section: dict, indent: bool = False) -> None:
            secs = section.get("start_seconds", 0)
            ts_label = _fmt_seconds(secs)
            name = section.get("name", "")
            # Prefer GitHub Pages redirect URL; fall back to YouTube
            href = redirect_pages.get(secs) or yt_link(video_id, secs)
            icon = "🎙" if secs in redirect_pages else "▶"
            tag_open = '<div class="sub">' if indent else ""
            tag_close = "</div>" if indent else ""
            parts.append(
                f'{tag_open}<h3><a href="{href}">{icon} {name} [{ts_label}]</a></h3>'
                f'<p class="summary">{section.get("summary", "")}</p>{tag_close}'
            )
            for sub in section.get("subsections", []):
                _section_parts(sub, indent=True)

        for section in analysis.get("sections", []):
            _section_parts(section)

        # Stock table
        stocks = analysis.get("stocks", [])
        if stocks:
            parts.append('<h3>Stocks Mentioned</h3>')
            parts.append(
                '<table><tr>'
                '<th>Ticker</th><th>Company</th><th>Sentiment</th>'
                '<th>Segment</th><th>Note</th>'
                '</tr>'
            )
            for s in stocks:
                seg = s.get("segment", "").replace("_", " ").title()
                pt = ""
                if "price_target" in s:
                    pt = f' (target ${s["price_target"]})'
                elif "price_level" in s:
                    pt = f' (at ${s["price_level"]})'
                parts.append(
                    f'<tr>'
                    f'<td class="ticker">{s.get("ticker","")}</td>'
                    f'<td>{s.get("company","")}</td>'
                    f'<td>{_sentiment_badge(s.get("sentiment","neutral"))}{pt}</td>'
                    f'<td>{seg}</td>'
                    f'<td class="note">{s.get("note","")}</td>'
                    f'</tr>'
                )
            parts.append('</table>')

        parts.append('<br>')

    has_overcast = any(ep.get("redirect_pages") for ep in summaries)
    link_note = ("🎙 section links open a page that jumps to Overcast at that timestamp"
                 if has_overcast else
                 "▶ section links open on YouTube (podcast RSS not matched)")
    parts.append(
        f'<div class="footer">Generated by Claude Haiku &middot; {link_note} &middot; '
        f'stock_sentiments.json updated</div>'
    )
    parts.append("</body></html>")
    return "\n".join(parts)


# ── 7. Email delivery ──────────────────────────────────────────────────────────

def send_email_smtp(html: str, subject: str) -> None:
    import os
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD environment variable not set")

    sender = os.environ.get("GMAIL_FROM", GMAIL_FROM)
    recipient = os.environ.get("GMAIL_TO", GMAIL_TO)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(*GMAIL_SMTP) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"  Email sent to {recipient}")


def send_email_mcp(html: str, subject: str) -> None:
    """
    Placeholder for Gmail MCP delivery used by the cloud-scheduled agent.
    When running as a cloud agent, replace this body with the MCP tool calls.
    """
    raise NotImplementedError(
        "MCP email mode is for use inside a Claude Code cloud agent. "
        "Run locally with --email-mode smtp instead."
    )


def send_email(html: str, subject: str, mode: str = "smtp") -> None:
    if mode == "smtp":
        send_email_smtp(html, subject)
    elif mode == "mcp":
        send_email_mcp(html, subject)
    else:
        raise ValueError(f"Unknown email mode: {mode!r}")


# ── 9. Git commit + push ──────────────────────────────────────────────────────

def commit_and_push(date_str: str) -> None:
    """Stage docs/ and data/, commit, and push to origin/main."""
    try:
        subprocess.run(["git", "add", "docs/", "data/"], cwd=ROOT, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Mad Money {date_str}: redirect pages + sentiment update"],
            cwd=ROOT, check=True,
        )
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
        print("  Pushed redirect pages to GitHub Pages")
    except subprocess.CalledProcessError as e:
        print(f"  Git push failed: {e} — links will use YouTube fallback until next push")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-episodes", type=int, default=1,
                        help="Max new episodes to process (default: 1)")
    parser.add_argument("--email-mode", choices=["smtp", "mcp"], default="smtp",
                        help="Email delivery mode (default: smtp)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze and format but do not send email")
    args = parser.parse_args()

    episodes = discover_new_episodes(args.max_episodes)
    if not episodes:
        print("No new episodes found.")
        return

    print(f"Found {len(episodes)} new episode(s):")
    for ep in episodes:
        print(f"  {ep['id']} — {ep['title']}")

    summaries = []
    processed = load_processed()

    for ep in episodes:
        video_id = ep["id"]
        print(f"\n── Processing {video_id} ──")

        print("  Fetching transcript...")
        date_str, snippets, transcript_text = fetch_transcript(video_id)
        print(f"  Date: {date_str}  Lines: {len(snippets)}")

        print("  Analyzing with Claude Haiku...")
        analysis = analyze_with_haiku(date_str, transcript_text)
        n_stocks = len(analysis.get("stocks", []))
        n_sections = len(analysis.get("sections", []))
        print(f"  Sections: {n_sections}  Stocks: {n_stocks}")

        print("  Updating stock_sentiments.json...")
        update_stock_sentiments(analysis)

        print("  Looking up podcast episode in RSS feed...")
        audio_url = find_podcast_episode(date_str)
        link_mode = "Overcast" if audio_url else "YouTube (RSS not matched)"
        print(f"  Links: {link_mode}")

        print("  Generating redirect pages...")
        redirect_pages = generate_redirect_pages(analysis, audio_url, date_str)
        print(f"  Redirect pages: {len(redirect_pages)}")

        summaries.append({
            "date_str": date_str,
            "analysis": analysis,
            "audio_url": audio_url,
            "video_id": video_id,
            "redirect_pages": redirect_pages,
        })
        processed.append({"video_id": video_id, "date": date_str})

    # Build email
    dates = [s["date_str"] for s in summaries]
    total_stocks = sum(len(s["analysis"].get("stocks", [])) for s in summaries)
    if len(dates) == 1:
        dt = datetime.fromisoformat(dates[0])
        subject = f"Mad Money — {dt.strftime('%a %b %-d')} · {total_stocks} stocks"
    else:
        subject = f"Mad Money — {dates[-1]} to {dates[0]} · {total_stocks} stocks"

    # Push redirect pages to GitHub Pages (needed before email so links are live)
    if not args.dry_run:
        print("\nPushing redirect pages to GitHub...")
        commit_and_push(dates[0])

    html = build_email_html(summaries)

    if args.dry_run:
        out = OUTPUT_DIR / f"{dates[0]}_email_preview.html"
        out.write_text(html)
        print(f"\nDry run — redirect pages written to docs/ (not pushed)")
        print(f"Email preview saved to {out}")
    else:
        print(f"\nSending email: {subject}")
        send_email(html, subject, mode=args.email_mode)

    save_processed(processed)
    print("\nDone.")


if __name__ == "__main__":
    main()
