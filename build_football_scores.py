from __future__ import annotations

import csv
import io
import time
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date().isoformat()
LOCAL_INPUT = Path("manual_scores.csv")
SHEET_URL_FILE = Path("google_sheet_url.txt")
OUTPUT = Path("football_scores.xml")
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores.xml"

LIVE_WORDS = (
    "Q1", "Q2", "Q3", "Q4", "1ST", "2ND", "3RD", "4TH",
    "HALF", "HALFTIME", "OT", "LIVE", "IN PROGRESS", "FINAL"
)


def clean(value: str | None) -> str:
    return (value or "").strip()


def normalize_date(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def valid_score(value: str) -> bool:
    try:
        int(value)
        return True
    except Exception:
        return False


def include_row(row: dict[str, str]) -> bool:
    # Current-score feed must only contain games dated TODAY.
    if normalize_date(row.get("date", "")) != TODAY:
        return False

    status = clean(row.get("status")).upper()
    away_score = clean(row.get("away_score"))
    home_score = clean(row.get("home_score"))

    # Do not show scheduled/pregame rows just because a score cell contains 0.
    # A game must explicitly be marked live/in progress/final.
    has_progress = any(word in status for word in LIVE_WORDS)
    if not has_progress:
        return False

    # Live/final games may have scores, but status is the deciding factor.
    if away_score or home_score:
        return valid_score(away_score) and valid_score(home_score)
    return True


def game_key(row: dict[str, str]) -> str:
    teams = sorted([
        clean(row.get("away_team")).lower(),
        clean(row.get("home_team")).lower(),
    ])
    return f"{TODAY}|{'|'.join(teams)}"


def cache_busted_url(url: str) -> str:
    """Add/replace a timestamp query parameter to avoid stale published CSV responses."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_cb"] = str(int(time.time()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def load_rows() -> list[dict[str, str]]:
    # Primary source: published Google Sheet CSV URL.
    if SHEET_URL_FILE.exists():
        sheet_url = clean(SHEET_URL_FILE.read_text(encoding="utf-8"))
        if sheet_url and not sheet_url.startswith("PASTE_"):
            try:
                fresh_url = cache_busted_url(sheet_url)
                req = Request(
                    fresh_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )
                with urlopen(req, timeout=20) as response:
                    text = response.read().decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(text)))
                print(f"Loaded {len(rows)} rows from Google Sheet CSV")
                return rows
            except Exception as exc:
                print(f"Google Sheet read failed; using local fallback: {exc}")

    # Fallback while the Google Sheet is being connected.
    if LOCAL_INPUT.exists():
        with LOCAL_INPUT.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            print(f"Loaded {len(rows)} rows from local fallback CSV")
            return rows
    return []


def main() -> None:
    loaded_rows = load_rows()
    rows = [r for r in loaded_rows if include_row(r)]
    print(f"Included {len(rows)} current-score rows for {TODAY}")

    # Last row for the same matchup wins, so editing/updating a game does not duplicate it.
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[game_key(row)] = row

    games = list(deduped.values())

    def sort_key(row: dict[str, str]):
        status = clean(row.get("status")).upper()
        final = status.startswith("FINAL")
        return (
            final,
            clean(row.get("away_team")).lower(),
            clean(row.get("home_team")).lower(),
        )

    games.sort(key=sort_key)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Eastern NC & Horry County Football Scores"
    ET.SubElement(channel, "link").text = FEED_URL
    ET.SubElement(channel, "description").text = (
        "Today's high school football scores and live game progress. "
        "Includes structured fields for vMix."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(TZ))

    for row in games:
        away = clean(row.get("away_team"))
        home = clean(row.get("home_team"))
        away_score = clean(row.get("away_score"))
        home_score = clean(row.get("home_score"))
        status = clean(row.get("status")).upper() or "LIVE"

        score_text = (
            f"{away} {away_score} — {home} {home_score}"
            if away_score and home_score
            else f"{away} at {home}"
        )
        title = f"{status} — {score_text}"

        item = ET.SubElement(channel, "item")
        # Standard RSS fields.
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = title
        ET.SubElement(item, "guid", isPermaLink="false").text = game_key(row)
        ET.SubElement(item, "pubDate").text = format_datetime(datetime.now(TZ))

        # Structured fields for vMix XML Data Source mapping.
        ET.SubElement(item, "status").text = status
        ET.SubElement(item, "awayTeam").text = away
        ET.SubElement(item, "awayScore").text = away_score
        ET.SubElement(item, "homeTeam").text = home
        ET.SubElement(item, "homeScore").text = home_score

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
