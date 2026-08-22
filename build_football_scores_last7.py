from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date()
START_DATE = TODAY - timedelta(days=7)
END_DATE = TODAY - timedelta(days=1)
LOCAL_INPUT = Path("manual_scores.csv")
SHEET_URL_FILE = Path("google_sheet_url.txt")
OUTPUT = Path("football_scores_last7.xml")
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores_last7.xml"


def clean(value: str | None) -> str:
    return (value or "").strip()


def parse_date(value: str):
    value = clean(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def valid_score(value: str) -> bool:
    try:
        int(clean(value))
        return True
    except Exception:
        return False


def include_row(row: dict[str, str]) -> bool:
    game_date = parse_date(row.get("date", ""))
    if game_date is None or not (START_DATE <= game_date <= END_DATE):
        return False

    return valid_score(row.get("away_score", "")) and valid_score(row.get("home_score", ""))


def game_key(row: dict[str, str]) -> str:
    game_date = parse_date(row.get("date", ""))
    teams = sorted([
        clean(row.get("away_team")).lower(),
        clean(row.get("home_team")).lower(),
    ])
    return f"{game_date.isoformat()}|{'|'.join(teams)}"


def load_rows() -> list[dict[str, str]]:
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

    if LOCAL_INPUT.exists():
        with LOCAL_INPUT.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    return []


def main() -> None:
    rows = [r for r in load_rows() if include_row(r)]

    # Last row for a matchup on a given date wins, allowing score corrections
    # without creating duplicate RSS items.
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[game_key(row)] = row

    games = list(deduped.values())
    games.sort(
        key=lambda row: (
            parse_date(row.get("date", "")),
            clean(row.get("away_team")).lower(),
            clean(row.get("home_team")).lower(),
        ),
        reverse=True,
    )

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Eastern NC & Horry County Football Scores — Last 7 Days"
    ET.SubElement(channel, "link").text = FEED_URL
    ET.SubElement(channel, "description").text = (
        "High school football scores from the previous 7 calendar days, excluding today. "
        "Google Sheet manual entries enabled."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(TZ))

    for row in games:
        game_date = parse_date(row.get("date", ""))
        away = clean(row.get("away_team"))
        home = clean(row.get("home_team"))
        away_score = clean(row.get("away_score"))
        home_score = clean(row.get("home_score"))
        status = clean(row.get("status")).upper()

        date_text = game_date.strftime("%a %b %-d")
        score_text = f"{away} {away_score} — {home} {home_score}"
        title = f"{date_text} — {score_text}"
        if status and status != "FINAL":
            title += f" ({status})"

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = title
        ET.SubElement(item, "guid", isPermaLink="false").text = game_key(row)
        item_dt = datetime.combine(game_date, datetime.min.time(), tzinfo=TZ)
        ET.SubElement(item, "pubDate").text = format_datetime(item_dt)

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
