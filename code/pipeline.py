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
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
SENTIMENTS_FILE = DATA_DIR / "stock_sentiments.json"
PROCESSED_FILE = DATA_DIR / "processed_episodes.json"
RULES_FILE = ROOT / "prompts" / "mad_money_rules.md"

CNBC_CHANNEL_ID = "UCrp_UI8XtuYfpiqluWLD7Lw"
MAD_MONEY_RSS = "https://feeds.simplecast.com/TkQfZXMD"

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


def overcast_link(audio_url: str, seconds: float) -> str:
    return f"overcast://x-callback-url/add?url={quote(audio_url)}&t={int(seconds)}"


def yt_link(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


def section_link(section: dict, audio_url: str | None, video_id: str) -> str:
    secs = section.get("start_seconds", 0)
    if audio_url:
        return overcast_link(audio_url, secs)
    return yt_link(video_id, secs)


# ── 6. HTML email formatter ────────────────────────────────────────────────────

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
        date_str, analysis, audio_url (or None), video_id
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
        ep_date = analysis.get("episode_date", ep["date_str"])
        dt = datetime.fromisoformat(ep_date)
        date_label = dt.strftime("%A, %B %-d, %Y")
        n_stocks = len(analysis.get("stocks", []))

        parts.append(f'<h2>Mad Money &mdash; {date_label}</h2>')
        parts.append(f'<p>{analysis.get("market_summary", "")}</p>')

        # Sections
        for section in analysis.get("sections", []):
            secs = section.get("start_seconds", 0)
            ts_label = _fmt_seconds(secs)
            href = section_link(section, audio_url, video_id)
            link_type = "🎙" if audio_url else "▶"
            parts.append(
                f'<h3><a href="{href}">{link_type} {section["name"]} [{ts_label}]</a></h3>'
            )
            parts.append(f'<p class="summary">{section.get("summary", "")}</p>')

            for sub in section.get("subsections", []):
                sub_secs = sub.get("start_seconds", 0)
                sub_ts = _fmt_seconds(sub_secs)
                sub_href = section_link(sub, audio_url, video_id)
                parts.append(
                    f'<div class="sub"><h3><a href="{sub_href}">'
                    f'{link_type} {sub["name"]} [{sub_ts}]</a></h3>'
                    f'<p class="summary">{sub.get("summary", "")}</p></div>'
                )

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

    link_type_note = "🎙 links open in Overcast" if any(
        e.get("audio_url") for e in summaries
    ) else "▶ links open on YouTube (podcast RSS not matched)"

    parts.append(
        f'<div class="footer">Generated by Claude Haiku &middot; '
        f'{link_type_note} &middot; '
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

        summaries.append({
            "date_str": date_str,
            "analysis": analysis,
            "audio_url": audio_url,
            "video_id": video_id,
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

    html = build_email_html(summaries)

    if args.dry_run:
        out = OUTPUT_DIR / f"{dates[0]}_email_preview.html"
        out.write_text(html)
        print(f"\nDry run — email preview saved to {out}")
    else:
        print(f"\nSending email: {subject}")
        send_email(html, subject, mode=args.email_mode)

    save_processed(processed)
    print("\nDone.")


if __name__ == "__main__":
    main()
