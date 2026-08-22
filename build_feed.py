import re
import base64
import gzip
from copy import deepcopy
from datetime import datetime
from email.utils import format_datetime
from io import BytesIO
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import Element, SubElement, ElementTree, parse, fromstring

import requests
from bs4 import BeautifulSoup

ET = ZoneInfo('America/New_York')
YEAR = 2026
START = datetime(2026, 8, 1, 0, 0, tzinfo=ET)
CUTOFF = datetime(2026, 11, 30, 23, 59, tzinfo=ET)
FEED = 'feed.xml'

# Verified 136-event seed feed (football, volleyball, boys soccer). This is only
# used when a live source cannot be read or the existing feed has no items.
SEED_GZ_B64 = '''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'''

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
        if opponent:
            events.append({'school':school,'sport':sport,'dt':dt,'opponent':opponent,'homeaway':homeaway,'url':url})
    uniq = {(e['dt'].isoformat(), e['opponent']): e for e in events}
    result = sorted(uniq.values(), key=lambda e:e['dt'])
    print(f'{school} {sport}: {len(result)} events')
    return result

def items_from_root(root):
    grouped = {}
    channel = root.find('channel')
    if channel is None:
        return grouped
    for item in channel.findall('item'):
        url = item.findtext('link','')
        if url:
            grouped.setdefault(url, []).append(deepcopy(item))
    return grouped

def seed_items_by_url():
    try:
        raw = gzip.decompress(base64.b64decode(SEED_GZ_B64))
        return items_from_root(fromstring(raw))
    except Exception as exc:
        print(f'SEED FAILED: {exc}')
        return {}

def old_items_by_url():
    try:
        grouped = items_from_root(parse(FEED).getroot())
        if grouped:
            return grouped
    except Exception:
        pass
    return seed_items_by_url()

def new_item(e):
    item = Element('item')
    SubElement(item,'title').text = f"{e['dt'].strftime('%b %-d, %-I:%M %p')} — {e['school']} {e['sport']} vs {e['opponent']} ({e['homeaway']})"
    SubElement(item,'link').text = e['url']
    SubElement(item,'guid',{'isPermaLink':'false'}).text = f"ccs|{e['school']}|{e['sport']}|{e['dt'].isoformat()}|{e['opponent']}"
    SubElement(item,'pubDate').text = format_datetime(e['dt'])
    SubElement(item,'category').text = e['school']
    SubElement(item,'category').text = e['sport']
    SubElement(item,'description').text = f"{e['school']} {e['sport']} — {e['homeaway']} vs {e['opponent']}, {e['dt'].strftime('%A, %B %-d, %Y at %-I:%M %p')} Eastern. Source: MaxPreps."
    return item

def build():
    previous = old_items_by_url()
    rss = Element('rss',{'version':'2.0'})
    channel = SubElement(rss,'channel')
    SubElement(channel,'title').text = 'Columbus County Schools Fall Sports 2026'
    SubElement(channel,'link').text = 'https://raw.githubusercontent.com/ccsrssfeeds/rss/main/feed.xml'
    SubElement(channel,'description').text = 'Fall sports schedules for West Columbus, South Columbus, and East Columbus through November 30, 2026. Refreshed hourly; verified last-known schedules are preserved whenever a live source cannot be read.'
    SubElement(channel,'language').text = 'en-us'
    SubElement(channel,'lastBuildDate').text = format_datetime(datetime.now(ET))
    total = 0
    for school,sport,url in SOURCES:
        fresh = scrape_source(school,sport,url)
        source_items = [new_item(e) for e in fresh] if fresh else previous.get(url,[])
        for item in source_items:
            channel.append(item)
            total += 1
    if total == 0:
        for source_items in seed_items_by_url().values():
            for item in source_items:
                channel.append(item)
                total += 1
    ElementTree(rss).write(FEED,encoding='utf-8',xml_declaration=True)
    print(f'Wrote {total} total items')

if __name__ == '__main__':
    build()
