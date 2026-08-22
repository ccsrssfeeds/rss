from __future__ import annotations

import csv
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date().isoformat()
INPUT = Path("manual_scores.csv")
OUTPUT = Path("football_scores.xml")
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores.xml"

LIVE_WORDS = ("Q1", "Q2", "Q3", "Q4", "1ST", "2ND", "3RD", "4TH", "HALF", "HALFTIME", "OT", "LIVE", "IN PROGRESS", "FINAL")


def clean(value: str | None) -> str:
    return (value or "").strip()


def valid_score(value: str) -> bool:
    try:
        int(value)
        return True
    except Exception:
        return False


def include_row(row: dict[str, str]) -> bool:
    if clean(row.get("date")) != TODAY:
        return False

    status = clean(row.get("status")).upper()
    away_score = clean(row.get("away_score"))
    home_score = clean(row.get("home_score"))

    has_scores = valid_score(away_score) and valid_score(home_score)
    has_progress = any(word in status for word in LIVE_WORDS)
    return has_scores or has_progress


def game_key(row: dict[str, str]) -> str:
    teams = sorted([clean(row.get("away_team")).lower(), clean(row.get("home_team")).lower()])
    return f"{TODAY}|{'|'.join(teams)}"


def main() -> None:
    rows: list[dict[str, str]] = []
    if INPUT.exists():
        with INPUT.open(newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if include_row(r)]

    # Last manual entry for the same matchup wins.
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
    ET.SubElement(channel, "description").text = "Today's high school football scores and live game progress. Manual entries currently enabled."
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
