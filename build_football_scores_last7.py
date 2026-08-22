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
    ("West Columbus", "https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/football/schedule/"),
    ("South Columbus", "https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/football/schedule/"),
    ("East Columbus", "https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/football/schedule/"),
]


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style"):
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style") and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def fetch_html(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_date(month: str, day: str):
    try:
        return datetime(TODAY.year, int(month), int(day)).date()
    except ValueError:
        return None


def team_scores(outcome: str, first: int, second: int):
    outcome = outcome.upper()
    if outcome == "W":
        return first, second
    if outcome == "L":
        return second, first
    return first, second


def clean_opponent(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" |-*—–")
    # Remove labels that can appear between the opponent and result in rendered text.
    value = re.sub(r"\b(?:Result|Watch|Game Info|Tickets|Box Score)\b.*$", "", value, flags=re.I).strip()
    return value


def scrape_team(team: str, url: str) -> list[dict[str, str]]:
    html = fetch_html(url)
    parser = VisibleTextParser()
    parser.feed(html)
    text = " | ".join(parser.parts)

    # MaxPreps rendered schedule text contains sequences equivalent to:
    # 8/20 7:30pm | @ Whiteville | L 53-8 | Box Score
    pattern = re.compile(
        r"(?P<month>\d{1,2})/(?P<day>\d{1,2})"
        r"(?:\s*\|?\s*\d{1,2}:\d{2}\s*(?:am|pm))?"
        r"(?P<middle>.{0,180}?)"
        r"(?P<site>@|\bvs\.?\b)\s*\|?\s*"
        r"(?P<opp>[A-Za-z0-9.'’&()\- ]{2,80}?)\s*\|\s*"
        r"(?P<outcome>[WLT])\s*(?P<s1>\d+)\s*[-–—]\s*(?P<s2>\d+)",
        re.I,
    )

    games: list[dict[str, str]] = []
    for m in pattern.finditer(text):
        game_date = parse_date(m.group("month"), m.group("day"))
        if game_date is None or not (START_DATE <= game_date <= END_DATE):
            continue

        opponent = clean_opponent(m.group("opp"))
        if not opponent or opponent.lower() == team.lower():
            continue

        team_score, opp_score = team_scores(m.group("outcome"), int(m.group("s1")), int(m.group("s2")))
        team_is_away = m.group("site") == "@"

        if team_is_away:
            away_team, away_score = team, team_score
            home_team, home_score = opponent, opp_score
        else:
            away_team, away_score = opponent, opp_score
            home_team, home_score = team, team_score

        games.append({
            "date": game_date.isoformat(),
            "away_team": away_team,
            "away_score": str(away_score),
            "home_team": home_team,
            "home_score": str(home_score),
            "source": url,
        })

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
