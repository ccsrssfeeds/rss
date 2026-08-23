from __future__ import annotations

import csv
import io
import re
import time
from datetime import datetime
from email.utils import format_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY_DATE = datetime.now(TZ).date()
TODAY = TODAY_DATE.isoformat()
LOCAL_INPUT = Path("manual_scores.csv")
SHEET_URL_FILE = Path("google_sheet_url.txt")
OUTPUT = Path("football_scores.xml")
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores.xml"

LIVE_WORDS = (
    "Q1", "Q2", "Q3", "Q4", "1ST", "2ND", "3RD", "4TH",
    "HALF", "HALFTIME", "OT", "LIVE", "IN PROGRESS", "FINAL"
)

REGIONAL_TEAMS = {
    "whiteville", "east columbus", "south columbus", "west columbus",
    "east bladen", "west bladen", "north brunswick", "south brunswick", "west brunswick",
    "fairmont", "lumberton", "purnell swett", "red springs", "st pauls", "st. pauls", "south robeson",
    "ashley", "hoggard", "laney", "new hanover", "pender", "heide trask", "topsail",
    "clinton", "hobbton", "lakewood", "midway", "union", "east duplin", "james kenan", "north duplin", "wallace-rose hill",
    "jacksonville", "northside", "southwest onslow", "white oak", "richlands", "swansboro", "dixon",
    "west carteret", "east carteret", "croatan", "new bern", "havelock", "west craven",
    "d.h. conley", "jh rose", "j.h. rose", "north pitt", "south central", "ayden-grifton", "ayden - grifton", "farmville central",
    "kinston", "north lenoir", "south lenoir", "eastern wayne", "southern wayne", "c.b. aycock", "goldsboro", "rosewood", "spring creek",
    "pamlico county", "jones senior", "aynor", "carolina forest", "conway", "green sea floyds", "loris", "myrtle beach",
    "north myrtle beach", "socastee", "st james", "st. james",
}

ALIASES = {"nmbhs": "north myrtle beach", "gsfhs": "green sea floyds", "jh rose": "j.h. rose"}


def clean(value: str | None) -> str:
    return (value or "").strip()


def normalize_team(name: str) -> str:
    name = re.sub(r"\(#?\d+\)", "", clean(name))
    name = re.sub(r"^#\d+\s*", "", name).replace("’", "'")
    name = re.sub(r"[^A-Za-z0-9.&' -]+", " ", name)
    n = " ".join(name.lower().split()).strip(" -")
    return ALIASES.get(n, n)


def is_regional(name: str) -> bool:
    n = normalize_team(name)
    if n in REGIONAL_TEAMS:
        return True
    collapsed = re.sub(r"[^a-z0-9]", "", n)
    return any(re.sub(r"[^a-z0-9]", "", t) == collapsed for t in REGIONAL_TEAMS)


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


def status_is_live(status: str) -> bool:
    s = clean(status).upper()
    return any(word in s for word in LIVE_WORDS)


def include_manual_row(row: dict[str, str]) -> bool:
    if normalize_date(row.get("date", "")) != TODAY:
        return False
    status = clean(row.get("status")).upper()
    if not status_is_live(status):
        return False
    a = clean(row.get("away_score"))
    h = clean(row.get("home_score"))
    if a or h:
        return valid_score(a) and valid_score(h)
    return True


def game_key(row: dict[str, str]) -> str:
    teams = sorted([normalize_team(row.get("away_team", "")), normalize_team(row.get("home_team", ""))])
    return f"{TODAY}|{'|'.join(teams)}"


def cache_busted_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_cb"] = str(int(time.time()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def load_manual_rows() -> list[dict[str, str]]:
    if SHEET_URL_FILE.exists():
        sheet_url = clean(SHEET_URL_FILE.read_text(encoding="utf-8"))
        if sheet_url and not sheet_url.startswith("PASTE_"):
            try:
                req = Request(cache_busted_url(sheet_url), headers={
                    "User-Agent": "Mozilla/5.0",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                })
                with urlopen(req, timeout=20) as response:
                    text = response.read().decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(text)))
                print(f"Loaded {len(rows)} rows from Google Sheet CSV")
                return rows
            except Exception as exc:
                print(f"Google Sheet read failed; using local fallback: {exc}")
    if LOCAL_INPUT.exists():
        with LOCAL_INPUT.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    return []


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style") and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip:
            t = " ".join(data.split())
            if t:
                self.parts.append(t)


def fetch_html(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_web_games(state: str) -> list[dict[str, str]]:
    date_text = f"{TODAY_DATE.month}/{TODAY_DATE.day}/{TODAY_DATE.year}"
    url = f"https://www.maxpreps.com/{state}/football/scores/?date={quote(date_text)}&mobile=1"
    try:
        page = fetch_html(url)
    except Exception as exc:
        print(f"{state.upper()} scoreboard read failed: {exc}")
        return []

    p = TextParser(); p.feed(page)
    text = " ".join(p.parts)
    # Normalize common scoreboard status text so regex can find boundaries.
    status_pat = r"(Final|Q1|Q2|Q3|Q4|1st|2nd|3rd|4th|Half|Halftime|OT|Live|In Progress)"
    # Typical MaxPreps text is score/team pairs followed by status.
    rx = re.compile(r"(?:^|\s)(\d{1,3})\s+(.+?)\s+(\d{1,3})\s+(.+?)\s+" + status_pat + r"(?:\s|$)", re.I)
    games, seen = [], set()
    for m in rx.finditer(text):
        away_score, away_team, home_score, home_team, status = m.groups()
        away_team = away_team.strip(" -*|—–")
        home_team = home_team.strip(" -*|—–")
        if not away_team or not home_team:
            continue
        if not (is_regional(away_team) or is_regional(home_team)):
            continue
        row = {
            "date": TODAY,
            "away_team": away_team,
            "away_score": away_score,
            "home_team": home_team,
            "home_score": home_score,
            "status": status.upper(),
            "source": "web",
        }
        key = game_key(row)
        if key not in seen:
            seen.add(key)
            games.append(row)
    print(f"{state.upper()} web current scores: {len(games)}")
    return games


def main() -> None:
    # Start with web scores from NC and SC.
    merged: dict[str, dict[str, str]] = {}
    for state in ("nc", "sc"):
        for row in parse_web_games(state):
            merged[game_key(row)] = row

    # Manual Sheet entries supplement the web and override the same matchup.
    manual = [r for r in load_manual_rows() if include_manual_row(r)]
    print(f"Included {len(manual)} manual rows for {TODAY}")
    for row in manual:
        row = dict(row)
        row["source"] = "manual"
        merged[game_key(row)] = row

    games = list(merged.values())
    games.sort(key=lambda r: (
        clean(r.get("status")).upper().startswith("FINAL"),
        normalize_team(r.get("away_team", "")),
        normalize_team(r.get("home_team", "")),
    ))

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Eastern NC & Horry County Football Scores"
    ET.SubElement(channel, "link").text = FEED_URL
    ET.SubElement(channel, "description").text = "Today's regional football scores from web sources plus manual Google Sheet overrides. Includes structured fields for vMix."
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
        ET.SubElement(item, "status").text = status
        ET.SubElement(item, "awayTeam").text = away
        ET.SubElement(item, "awayScore").text = away_score
        ET.SubElement(item, "homeTeam").text = home
        ET.SubElement(item, "homeScore").text = home_score
        ET.SubElement(item, "source").text = clean(row.get("source"))

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
