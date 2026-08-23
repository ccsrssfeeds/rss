from __future__ import annotations

import csv
import io
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date().isoformat()
LOCAL_INPUT = Path("manual_scores.csv")
SHEET_URL_FILE = Path("google_sheet_url.txt")
OUTPUT = Path("football_scores.xml")
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores.xml"

LIVE_WORDS = ("Q1", "Q2", "Q3", "Q4", "1ST", "2ND", "3RD", "4TH", "HALF", "HALFTIME", "OT", "LIVE", "IN PROGRESS", "FINAL")


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
    teams = sorted([clean(row.get("away_team")).lower(), clean(row.get("home_team")).lower()])
    return f"{TODAY}|{'|'.join(teams)}"


def load_rows() -> list[dict[str, str]]:
    # Primary source: published Google Sheet CSV URL.
    if SHEET_URL_FILE.exists():
        sheet_url = clean(SHEET_URL_FILE.read_text(encoding="utf-8"))
        if sheet_url and not sheet_url.startswith("PASTE_"):
            try:
                req = Request(sheet_url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=20) as response:
                    text = response.read().decode("utf-8-sig")
                return list(csv.DictReader(io.StringIO(text)))
            except Exception as exc:
                print(f"Google Sheet read failed; using local fallback: {exc}")

    # Fallback while the Google Sheet is being connected.
    if LOCAL_INPUT.exists():
        with LOCAL_INPUT.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    return []


def main() -> None:
    rows = [r for r in load_rows() if include_row(r)]

    # Last row for the same matchup wins, so editing/updating a game does not duplicate it.
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[game_key(row)] = row

    games = list(deduped.values())

    def sort_key(row: dict[str, str]):
        status = clean(row.get("status")).upper()
        final = status.startswith("FINAL")
        return (final, clean(row.get("away_team")).lower(), clean(row.get("home_team")).lower())

    games.sort(key=sort_key)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Eastern NC & Horry County Football Scores"
    ET.SubElement(channel, "link").text = FEED_URL
    ET.SubElement(channel, "description").text = "Today's high school football scores and live game progress. Google Sheet manual entries enabled."
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(TZ))

    for row in games:
        away = clean(row.get("away_team"))
        home = clean(row.get("home_team"))
        away_score = clean(row.get("away_score"))
        home_score = clean(row.get("home_score"))
        status = clean(row.get("status")).upper() or "LIVE"

        score_text = f"{away} {away_score} — {home} {home_score}" if away_score and home_score else f"{away} at {home}"
        title = f"{status} — {score_text}"

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = title
        ET.SubElement(item, "guid", isPermaLink="false").text = game_key(row)
        ET.SubElement(item, "pubDate").text = format_datetime(datetime.now(TZ))

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
