import re
from copy import deepcopy
from datetime import datetime
from email.utils import format_datetime
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import Element, SubElement, ElementTree, parse

import requests
from bs4 import BeautifulSoup

ET = ZoneInfo('America/New_York')
YEAR = 2026
START = datetime(2026, 8, 1, 0, 0, tzinfo=ET)
CUTOFF = datetime(2026, 11, 30, 23, 59, tzinfo=ET)
FEED = 'feed.xml'

SOURCES = [
    ('West Columbus','Varsity Football','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/football/schedule/'),
    ('West Columbus','Varsity Volleyball','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/volleyball/schedule/'),
    ('West Columbus','Varsity Boys Soccer','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/soccer/schedule/'),
    ('West Columbus','Varsity Girls Tennis','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/tennis/schedule/'),
    ('West Columbus','Varsity Cross Country','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/cross-country/schedule/'),
    ('West Columbus','Varsity Girls Golf','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/girls-golf/schedule/'),
    ('South Columbus','Varsity Football','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/football/schedule/'),
    ('South Columbus','Varsity Volleyball','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/volleyball/schedule/'),
    ('South Columbus','Varsity Boys Soccer','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/soccer/schedule/'),
    ('South Columbus','Varsity Girls Tennis','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/tennis/schedule/'),
    ('South Columbus','Varsity Cross Country','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/cross-country/schedule/'),
    ('South Columbus','Varsity Girls Golf','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/girls-golf/schedule/'),
    ('East Columbus','Varsity Football','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/football/schedule/'),
    ('East Columbus','Varsity Volleyball','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/volleyball/schedule/'),
    ('East Columbus','Varsity Boys Soccer','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/soccer/schedule/'),
    ('East Columbus','Varsity Girls Tennis','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/tennis/schedule/'),
    ('East Columbus','Varsity Cross Country','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/cross-country/schedule/'),
    ('East Columbus','Varsity Girls Golf','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/girls-golf/schedule/'),
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

COMBINED = re.compile(r'(?<!\d)(\d{1,2}/\d{1,2})\s*(\d{1,2}:\d{2}\s*(?:am|pm))', re.I)
DATE_ONLY = re.compile(r'^\s*(\d{1,2}/\d{1,2})\s*$')
TIME_ONLY = re.compile(r'^\s*(\d{1,2}:\d{2}\s*(?:am|pm))\s*$', re.I)
OPPONENT = re.compile(r'^\s*(vs\.?|@)\s*(.+?)\s*$', re.I)


def clean(s):
    return re.sub(r'\s+', ' ', str(s)).strip()


def make_dt(d, t):
    try:
        compact = re.sub(r'\s+', '', t).upper()
        dt = datetime.strptime(f'{d}/{YEAR} {compact}', '%m/%d/%Y %I:%M%p').replace(tzinfo=ET)
        return dt if START <= dt <= CUTOFF else None
    except ValueError:
        return None


def scrape_source(school, sport, url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as exc:
        print(f'FETCH FAILED {school} {sport}: {exc}')
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    lines = [clean(x) for x in soup.get_text('\n', strip=True).splitlines() if clean(x)]
    events = []

    for i, line in enumerate(lines):
        d = t = None
        m = COMBINED.search(line)
        if m:
            d, t = m.group(1), m.group(2)
        else:
            dm = DATE_ONLY.match(line)
            if dm:
                d = dm.group(1)
                for j in range(i + 1, min(i + 4, len(lines))):
                    tm = TIME_ONLY.match(lines[j])
                    if tm:
                        t = tm.group(1)
                        break
        if not (d and t):
            continue

        dt = make_dt(d, t)
        if not dt:
            continue

        opponent = None
        homeaway = None
        for j in range(i + 1, min(i + 14, len(lines))):
            om = OPPONENT.match(lines[j])
            if om:
                marker, opponent = om.group(1), om.group(2)
                opponent = re.sub(r'[*]+$', '', opponent).strip()
                homeaway = 'Away' if marker.startswith('@') else 'Home'
                break
        if not opponent:
            continue

        events.append({
            'school': school, 'sport': sport, 'dt': dt,
            'opponent': opponent, 'homeaway': homeaway, 'url': url
        })

    uniq = {}
    for e in events:
        uniq[(e['dt'].isoformat(), e['opponent'])] = e
    result = sorted(uniq.values(), key=lambda e: e['dt'])
    print(f'{school} {sport}: {len(result)} events')
    return result


def old_items_by_url():
    grouped = {}
    try:
        root = parse(FEED).getroot()
        channel = root.find('channel')
        if channel is None:
            return grouped
        for item in channel.findall('item'):
            url = item.findtext('link', '')
            if url:
                grouped.setdefault(url, []).append(deepcopy(item))
    except Exception:
        pass
    return grouped


def new_item(e):
    item = Element('item')
    SubElement(item, 'title').text = f"{e['dt'].strftime('%b %-d, %-I:%M %p')} — {e['school']} {e['sport']} vs {e['opponent']} ({e['homeaway']})"
    SubElement(item, 'link').text = e['url']
    SubElement(item, 'guid', {'isPermaLink':'false'}).text = f"ccs|{e['school']}|{e['sport']}|{e['dt'].isoformat()}|{e['opponent']}"
    SubElement(item, 'pubDate').text = format_datetime(e['dt'])
    SubElement(item, 'category').text = e['school']
    SubElement(item, 'category').text = e['sport']
    SubElement(item, 'description').text = f"{e['school']} {e['sport']} — {e['homeaway']} vs {e['opponent']}, {e['dt'].strftime('%A, %B %-d, %Y at %-I:%M %p')} Eastern. Source: MaxPreps."
    return item


def build():
    previous = old_items_by_url()
    rss = Element('rss', {'version':'2.0'})
    channel = SubElement(rss, 'channel')
    SubElement(channel, 'title').text = 'Columbus County Schools Fall Sports 2026'
    SubElement(channel, 'link').text = 'https://raw.githubusercontent.com/ccsrssfeeds/rss/main/feed.xml'
    SubElement(channel, 'description').text = 'Fall sports schedules for West Columbus, South Columbus, and East Columbus through November 30, 2026. Refreshed hourly; last known schedule is preserved if a source cannot be read.'
    SubElement(channel, 'language').text = 'en-us'
    SubElement(channel, 'lastBuildDate').text = format_datetime(datetime.now(ET))

    total = 0
    for school, sport, url in SOURCES:
        fresh = scrape_source(school, sport, url)
        if fresh:
            for e in fresh:
                channel.append(new_item(e))
                total += 1
        else:
            for item in previous.get(url, []):
                channel.append(item)
                total += 1

    ElementTree(rss).write(FEED, encoding='utf-8', xml_declaration=True)
    print(f'Wrote {total} total items')


if __name__ == '__main__':
    build()
