from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timedelta
from email.utils import format_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
TODAY = datetime.now(TZ).date()
START_DATE = TODAY - timedelta(days=7)
END_DATE = TODAY - timedelta(days=1)
OUTPUT = "football_scores_last7.xml"
FEED_URL = "https://raw.githubusercontent.com/ccsrssfeeds/rss/main/football_scores_last7.xml"
MEDIA_NS = "http://search.yahoo.com/mrss/"
ET.register_namespace("media", MEDIA_NS)

REGIONAL_TEAMS = {
    "whiteville", "east columbus", "south columbus", "west columbus",
    "east bladen", "west bladen",
    "north brunswick", "south brunswick", "west brunswick",
    "fairmont", "lumberton", "purnell swett", "red springs", "st pauls", "st. pauls", "south robeson",
    "ashley", "hoggard", "laney", "new hanover",
    "pender", "heide trask", "topsail",
    "clinton", "hobbton", "lakewood", "midway", "union",
    "east duplin", "james kenan", "north duplin", "wallace-rose hill",
    "jacksonville", "northside", "southwest onslow", "white oak", "richlands", "swansboro", "dixon",
    "west carteret", "east carteret", "croatan",
    "new bern", "havelock", "west craven",
    "d.h. conley", "jh rose", "j.h. rose", "north pitt", "south central", "ayden-grifton", "ayden - grifton", "farmville central",
    "kinston", "north lenoir", "south lenoir",
    "eastern wayne", "southern wayne", "c.b. aycock", "goldsboro", "rosewood", "spring creek",
    "pamlico county", "jones senior",
    "aynor", "carolina forest", "conway", "green sea floyds", "loris", "myrtle beach",
    "north myrtle beach", "socastee", "st james", "st. james",
}

# MaxPreps sometimes shortens these names on scoreboards.
TEAM_ALIASES = {
    "nmbhs": "north myrtle beach",
    "gsfhs": "green sea floyds",
    "jh rose": "j.h. rose",
}


class ScoreboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.li_depth = 0
        self.li_parts: list[str] = []
        self.li_images: list[tuple[str, str]] = []
        self.li_links: list[tuple[str, str]] = []
        self.entries: list[tuple[str, list[tuple[str, str]], list[tuple[str, str]]]] = []
        self.skip_depth = 0
        self.anchor_href = ""
        self.anchor_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in ("script", "style"):
            self.skip_depth += 1
            return

        if tag == "li" and not self.skip_depth:
            self.li_depth += 1
            if self.li_depth == 1:
                self.li_parts = []
                self.li_images = []
                self.li_links = []

        if tag == "img" and self.li_depth and not self.skip_depth:
            alt = (attrs_dict.get("alt") or "").strip()
            src = (
                attrs_dict.get("src")
                or attrs_dict.get("data-src")
                or attrs_dict.get("data-lazy-src")
                or attrs_dict.get("data-original")
                or ""
            ).strip()
            if src:
                self.li_images.append((alt, src))

        if tag == "a" and self.li_depth and not self.skip_depth:
            self.anchor_href = (attrs_dict.get("href") or "").strip()
            self.anchor_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style") and self.skip_depth:
            self.skip_depth -= 1
            return

        if tag == "a" and self.li_depth and self.anchor_href:
            anchor_text = " ".join(" ".join(self.anchor_parts).split())
            if anchor_text:
                self.li_links.append((anchor_text, self.anchor_href))
            self.anchor_href = ""
            self.anchor_parts = []

        if tag == "li" and self.li_depth:
            if self.li_depth == 1:
                line = " ".join(" ".join(self.li_parts).split())
                if line:
                    self.entries.append((line, list(self.li_images), list(self.li_links)))
                self.li_parts = []
                self.li_images = []
                self.li_links = []
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
        if self.anchor_href:
            self.anchor_parts.append(text)


class TeamPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images: list[tuple[str, str]] = []
        self.meta_images: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "img":
            alt = (attrs_dict.get("alt") or "").strip()
            src = (
                attrs_dict.get("src")
                or attrs_dict.get("data-src")
                or attrs_dict.get("data-lazy-src")
                or attrs_dict.get("data-original")
                or ""
            ).strip()
            if src:
                self.images.append((alt, src))
        elif tag.lower() == "meta":
            prop = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            content = (attrs_dict.get("content") or "").strip()
            if content and prop in {"og:image", "twitter:image", "twitter:image:src"}:
                self.meta_images.append(content)


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
    n = " ".join(name.lower().split()).strip(" -")
    return TEAM_ALIASES.get(n, n)


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


def same_team(a: str, b: str) -> bool:
    aa = re.sub(r"[^a-z0-9]", "", normalize_team(a))
    bb = re.sub(r"[^a-z0-9]", "", normalize_team(b))
    return bool(aa and bb and (aa == bb or aa in bb or bb in aa))


def pick_inline_logo(team: str, images: list[tuple[str, str]], base_url: str) -> str:
    for alt, src in images:
        if same_team(team, alt):
            return urljoin(base_url, src)
    return ""


def pick_team_page(team: str, links: list[tuple[str, str]], base_url: str) -> str:
    for text, href in links:
        if same_team(team, text) and "/football" in href:
            return urljoin(base_url, href)
    for text, href in links:
        if same_team(team, text):
            return urljoin(base_url, href)
    return ""


def fallback_logo(team: str) -> str:
    # Always provides a valid image URL if a site's official mark cannot be resolved.
    return f"https://api.dicebear.com/9.x/initials/png?seed={quote(normalize_team(team))}&size=256"


def resolve_team_logo(team: str, team_url: str, cache: dict[str, str]) -> str:
    key = normalize_team(team)
    if key in cache:
        return cache[key]

    if not team_url:
        cache[key] = fallback_logo(team)
        return cache[key]

    try:
        page = fetch_html(team_url)
        parser = TeamPageParser()
        parser.feed(page)

        # Prefer image tags whose alt text identifies the team/school/logo.
        for alt, src in parser.images:
            alt_lower = alt.lower()
            if same_team(team, alt) or ("logo" in alt_lower and key.split()[0] in alt_lower):
                cache[key] = urljoin(team_url, src)
                return cache[key]

        # Look for structured/logo URL fields MaxPreps may emit in page JSON.
        patterns = [
            r'"(?:schoolLogoUrl|teamLogoUrl|logoUrl|logo)"\s*:\s*"([^"]+)"',
            r'"(?:imageUrl|image)"\s*:\s*"([^"]*logo[^"]*)"',
        ]
        for pattern in patterns:
            m = re.search(pattern, page, re.I)
            if m:
                candidate = html_lib.unescape(m.group(1)).replace("\\/", "/")
                if candidate.startswith("http") or candidate.startswith("//") or candidate.startswith("/"):
                    cache[key] = urljoin(team_url, candidate)
                    return cache[key]

        # Last official-page fallback: social preview image.
        if parser.meta_images:
            cache[key] = urljoin(team_url, parser.meta_images[0])
            return cache[key]
    except Exception as exc:
        print(f"{team}: logo lookup failed: {exc}")

    cache[key] = fallback_logo(team)
    return cache[key]


def scrape_scoreboard(state: str, game_date, logo_cache: dict[str, str]) -> list[dict[str, str]]:
    date_text = f"{game_date.month}/{game_date.day}/{game_date.year}"
    url = f"https://www.maxpreps.com/{state}/football/scores/?date={quote(date_text)}&mobile=1"
    page = fetch_html(url)
    parser = ScoreboardParser()
    parser.feed(page)

    candidates: list[tuple[str, list[tuple[str, str]], list[tuple[str, str]]]] = list(parser.entries)
    candidates.extend((text, [], []) for text in re.split(r"(?<=Final)", " ".join(parser.parts)))

    games: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for line, images, links in candidates:
        parsed = parse_game_line(line)
        if not parsed:
            continue
        away_team, away_score, home_team, home_score = parsed
        key = (normalize_team(away_team), away_score, normalize_team(home_team), home_score)
        if key in seen:
            continue
        seen.add(key)

        away_logo = pick_inline_logo(away_team, images, url)
        home_logo = pick_inline_logo(home_team, images, url)
        away_page = pick_team_page(away_team, links, url)
        home_page = pick_team_page(home_team, links, url)
        if not away_logo:
            away_logo = resolve_team_logo(away_team, away_page, logo_cache)
        if not home_logo:
            home_logo = resolve_team_logo(home_team, home_page, logo_cache)

        games.append({
            "date": game_date.isoformat(),
            "away_team": away_team,
            "away_score": away_score,
            "home_team": home_team,
            "home_score": home_score,
            "away_logo": away_logo,
            "home_logo": home_logo,
            "source": url,
        })
    return games


def game_key(row: dict[str, str]) -> str:
    teams = sorted([normalize_team(row["away_team"]), normalize_team(row["home_team"])])
    return f"{row['date']}|{'|'.join(teams)}"


def main() -> None:
    rows: list[dict[str, str]] = []
    logo_cache: dict[str, str] = {}
    game_date = START_DATE
    while game_date <= END_DATE:
        for state in ("nc", "sc"):
            try:
                found = scrape_scoreboard(state, game_date, logo_cache)
                print(f"{state.upper()} {game_date}: found {len(found)} regional finals")
                rows.extend(found)
            except Exception as exc:
                print(f"{state.upper()} {game_date}: scoreboard read failed: {exc}")
        game_date += timedelta(days=1)

    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        key = game_key(row)
        if key not in deduped:
            deduped[key] = row
        else:
            existing = deduped[key]
            if not existing.get("away_logo") and row.get("away_logo"):
                existing["away_logo"] = row["away_logo"]
            if not existing.get("home_logo") and row.get("home_logo"):
                existing["home_logo"] = row["home_logo"]

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
        ET.SubElement(item, "awayLogo").text = row["away_logo"]
        ET.SubElement(item, "homeLogo").text = row["home_logo"]

        # Standard Media RSS image fields improve compatibility with feed readers/displays.
        ET.SubElement(item, f"{{{MEDIA_NS}}}thumbnail", url=row["away_logo"], role="away")
        ET.SubElement(item, f"{{{MEDIA_NS}}}thumbnail", url=row["home_logo"], role="home")
        ET.SubElement(item, f"{{{MEDIA_NS}}}content", url=row["away_logo"], medium="image")
        ET.SubElement(item, f"{{{MEDIA_NS}}}content", url=row["home_logo"], medium="image")

        ET.SubElement(item, "guid", isPermaLink="false").text = game_key(row)
        item_dt = datetime.combine(game_date, datetime.min.time(), tzinfo=TZ)
        ET.SubElement(item, "pubDate").text = format_datetime(item_dt)

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
