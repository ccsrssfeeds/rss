from __future__ import annotations

import re
from datetime import datetime, timedelta
from email.utils import format_datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date()
START_DATE = TODAY - timedelta(days=7)
END_DATE = TODAY - timedelta(days=1)
OUTPUT = "football_scores_last7.xml"
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores_last7.xml"

TEAMS = [
    (
        "West Columbus",
        "https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/football/schedule/",
    ),
    (
        "South Columbus",
        "https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/football/schedule/",
    ),
    (
        "East Columbus",
        "https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/football/schedule/",
    ),
]


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.cell_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.in_tr = True
            self.row = []
        elif self.in_tr and tag in ("td", "th"):
            self.in_cell = True
            self.cell_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.in_tr and tag in ("td", "th") and self.in_cell:
            text = " ".join("".join(self.cell_parts).split())
            self.row.append(text)
            self.in_cell = False
            self.cell_parts = []
        elif tag == "tr" and self.in_tr:
            if self.row:
                self.rows.append(self.row)
            self.in_tr = False
            self.row = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell_parts.append(data)


def clean(value: str | None) -> str:
    return (value or "").strip()


def fetch_html(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_game_date(text: str):
    # MaxPreps date cells render like "8/207:30pm" or "8/20 7:30pm".
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
    if not m:
        return None
    month, day = map(int, m.groups())
    try:
        return datetime(TODAY.year, month, day).date()
    except ValueError:
        return None


def normalize_opponent(text: str) -> tuple[str, bool]:
    text = clean(text).replace("*", "")
    away = text.startswith("@")
    text = re.sub(r"^(?:@|vs\.?\s*)", "", text, flags=re.I)
    return clean(text), away


def parse_result(text: str):
    # Typical MaxPreps result: W 28-14, L 53-8, T 21-21.
    m = re.search(r"\b([WLT])\s*(\d+)\s*[-–—]\s*(\d+)\b", text, re.I)
    if not m:
        return None
    outcome = m.group(1).upper()
    first = int(m.group(2))
    second = int(m.group(3))
    if outcome == "W":
        return first, second
    if outcome == "L":
        return second, first
    return first, second


def scrape_team(team: str, url: str) -> list[dict[str, str]]:
    html = fetch_html(url)
    parser = TableParser()
    parser.feed(html)
    games: list[dict[str, str]] = []

    for row in parser.rows:
        if len(row) < 3:
            continue
        game_date = parse_game_date(row[0])
        if game_date is None or not (START_DATE <= game_date <= END_DATE):
            continue

        opponent, team_is_away = normalize_opponent(row[1])
        if not opponent:
            continue

        result = parse_result(row[2])
        if result is None:
            continue
        team_score, opp_score = result

        if team_is_away:
            away_team, away_score = team, team_score
            home_team, home_score = opponent, opp_score
        else:
            away_team, away_score = opponent, opp_score
            home_team, home_score = team, team_score

        games.append(
            {
                "date": game_date.isoformat(),
                "away_team": away_team,
                "away_score": str(away_score),
                "home_team": home_team,
                "home_score": str(home_score),
                "source": url,
            }
        )

    return games


def game_key(row: dict[str, str]) -> str:
    teams = sorted([row["away_team"].lower(), row["home_team"].lower()])
    return f"{row['date']}|{'|'.join(teams)}"


def main() -> None:
    rows: list[dict[str, str]] = []
    for team, url in TEAMS:
        try:
            found = scrape_team(team, url)
            print(f"{team}: found {len(found)} qualifying scored games")
            rows.extend(found)
        except Exception as exc:
            print(f"{team}: MaxPreps read failed: {exc}")

    # Remove duplicate matchups when two CCS schools play each other.
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[game_key(row)] = row

    games = list(deduped.values())
    games.sort(key=lambda r: (r["date"], r["away_team"].lower(), r["home_team"].lower()), reverse=True)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Columbus County Schools Football Scores — Last 7 Days"
    ET.SubElement(channel, "link").text = FEED_URL
    ET.SubElement(channel, "description").text = (
        "Varsity football final scores for West Columbus, South Columbus, and East Columbus "
        "from the previous 7 calendar days, excluding today. Source: published MaxPreps schedule pages."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(TZ))

    for row in games:
        game_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        date_text = game_date.strftime("%a %b %d").replace(" 0", " ")
        title = f"{date_text} — {row['away_team']} {row['away_score']} — {row['home_team']} {row['home_score']}"

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = row["source"]
        ET.SubElement(item, "description").text = f"Final: {title}. Source: MaxPreps."
        ET.SubElement(item, "guid", isPermaLink="false").text = game_key(row)
        item_dt = datetime.combine(game_date, datetime.min.time(), tzinfo=TZ)
        ET.SubElement(item, "pubDate").text = format_datetime(item_dt)

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
