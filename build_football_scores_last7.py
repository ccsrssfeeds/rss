from __future__ import annotations

import re
from datetime import datetime, timedelta
from email.utils import format_datetime
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date()
START_DATE = TODAY - timedelta(days=7)
END_DATE = TODAY - timedelta(days=1)
OUTPUT = "football_scores_last7.xml"
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores_last7.xml"

# Eastern / southeastern NC public-school football footprint plus Horry County, SC.
REGIONAL_TEAMS = {
    # Columbus / Bladen / Brunswick / Robeson
    "whiteville", "east columbus", "south columbus", "west columbus",
    "east bladen", "west bladen",
    "north brunswick", "south brunswick", "west brunswick",
    "fairmont", "lumberton", "purnell swett", "red springs", "st pauls", "st. pauls", "south robeson",
    # New Hanover / Pender
    "ashley", "hoggard", "laney", "new hanover",
    "pender", "heide trask", "topsail",
    # Sampson / Duplin
    "clinton", "hobbton", "lakewood", "midway", "union",
    "east duplin", "james kenan", "north duplin", "wallace-rose hill",
    # Onslow / Carteret / Craven
    "jacksonville", "northside", "southwest onslow", "white oak", "richlands", "swansboro", "dixon",
    "west carteret", "east carteret", "croatan",
    "new bern", "havelock", "west craven",
    # Pitt / Lenoir / Wayne / nearby eastern NC
    "d.h. conley", "jh rose", "j.h. rose", "north pitt", "south central", "ayden-grifton", "ayden - grifton", "farmville central",
    "kinston", "north lenoir", "south lenoir",
    "eastern wayne", "southern wayne", "c.b. aycock", "goldsboro", "rosewood", "spring creek",
    "pamlico county", "jones senior",
    # Horry County, SC
    "aynor", "carolina forest", "conway", "green sea floyds", "loris", "myrtle beach",
    "north myrtle beach", "socastee", "st james", "st. james",
}


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.li_depth = 0
        self.li_parts: list[str] = []
        self.lines: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style"):
            self.skip_depth += 1
        if tag == "li" and not self.skip_depth:
            self.li_depth += 1
            if self.li_depth == 1:
                self.li_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style") and self.skip_depth:
            self.skip_depth -= 1
        if tag == "li" and self.li_depth:
            if self.li_depth == 1:
                line = " ".join(" ".join(self.li_parts).split())
                if line:
                    self.lines.append(line)
                self.li_parts = []
            self.li_depth -= 1

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        if self.li_depth:
            self.li_parts.append(text)


def fetch_html(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def normalize_team(name: str) -> str:
    name = re.sub(r"\(#?\d+\)", "", name)
    name = re.sub(r"^#\d+\s*", "", name)
    name = name.replace("’", "'")
    name = re.sub(r"[^A-Za-z0-9.&' -]+", " ", name)
    return " ".join(name.lower().split()).strip(" -")


def is_regional(name: str) -> bool:
    n = normalize_team(name)
    if n in REGIONAL_TEAMS:
        return True
    collapsed = re.sub(r"[^a-z0-9]", "", n)
    return any(re.sub(r"[^a-z0-9]", "", team) == collapsed for team in REGIONAL_TEAMS)


def parse_game_line(line: str):
    line = " ".join(line.split())
    if "Final" not in line:
        return None

    m = re.search(r"(?:^|\s)(\d{1,3})\s+(.+?)\s+(\d{1,3})\s+(.+?)\s+Final(?:\s|$)", line, re.I)
    if not m:
        return None

    away_score, away_team, home_score, home_team = m.groups()
    away_team = away_team.strip(" -*|—–")
    home_team = home_team.strip(" -*|—–")

    if not away_team or not home_team:
        return None
    if not (is_regional(away_team) or is_regional(home_team)):
        return None

    return away_team, away_score, home_team, home_score


def scrape_scoreboard(state: str, game_date) -> list[dict[str, str]]:
    date_text = f"{game_date.month}/{game_date.day}/{game_date.year}"
    url = f"https://www.maxpreps.com/{state}/football/scores/?date={quote(date_text)}&mobile=1"
    html = fetch_html(url)
    parser = VisibleTextParser()
    parser.feed(html)

    candidates = list(parser.lines)
    candidates.extend(re.split(r"(?<=Final)", " ".join(parser.parts)))

    games: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for line in candidates:
        parsed = parse_game_line(line)
        if not parsed:
            continue
        away_team, away_score, home_team, home_score = parsed
        key = (normalize_team(away_team), away_score, normalize_team(home_team), home_score)
        if key in seen:
            continue
        seen.add(key)
        games.append({
            "date": game_date.isoformat(),
            "away_team": away_team,
            "away_score": away_score,
            "home_team": home_team,
            "home_score": home_score,
            "source": url,
        })
    return games


def game_key(row: dict[str, str]) -> str:
    teams = sorted([normalize_team(row["away_team"]), normalize_team(row["home_team"])])
    return f"{row['date']}|{'|'.join(teams)}"


def main() -> None:
    rows: list[dict[str, str]] = []
    game_date = START_DATE
    while game_date <= END_DATE:
        for state in ("nc", "sc"):
            try:
                found = scrape_scoreboard(state, game_date)
                print(f"{state.upper()} {game_date}: found {len(found)} regional finals")
                rows.extend(found)
            except Exception as exc:
                print(f"{state.upper()} {game_date}: scoreboard read failed: {exc}")
        game_date += timedelta(days=1)

    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[game_key(row)] = row

    games = list(deduped.values())
    games.sort(key=lambda r: (r["date"], normalize_team(r["away_team"]), normalize_team(r["home_team"])), reverse=True)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Eastern NC & Horry County Football Scores — Last 7 Days"
    ET.SubElement(channel, "link").text = FEED_URL
    ET.SubElement(channel, "description").text = (
        "Varsity high school football final scores for the Eastern North Carolina regional school list "
        "and Horry County, South Carolina, from the previous 7 calendar days, excluding today."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(TZ))

    for row in games:
        game_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        date_label = f"{game_date.month}/{game_date.day}"
        title = f"{date_label} — {row['away_team']} {row['away_score']} — {row['home_team']} {row['home_score']}"

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = row["source"]
        ET.SubElement(item, "description").text = f"Final: {title}"
        ET.SubElement(item, "guid", isPermaLink="false").text = game_key(row)
        item_dt = datetime.combine(game_date, datetime.min.time(), tzinfo=TZ)
        ET.SubElement(item, "pubDate").text = format_datetime(item_dt)

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
