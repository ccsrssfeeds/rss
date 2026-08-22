import re
import html
from datetime import datetime
from email.utils import format_datetime
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import Element, SubElement, ElementTree

import pandas as pd
import requests

ET = ZoneInfo('America/New_York')
YEAR = 2026
CUTOFF = datetime(2026, 11, 30, 23, 59, tzinfo=ET)

SOURCES = [
    ('West Columbus','Football','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/football/schedule/'),
    ('West Columbus','Volleyball','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/volleyball/schedule/'),
    ('West Columbus','Boys Soccer','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/soccer/schedule/'),
    ('West Columbus','Girls Tennis','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/tennis/schedule/'),
    ('West Columbus','Cross Country','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/cross-country/schedule/'),
    ('West Columbus','Girls Golf','https://www.maxpreps.com/nc/cerro-gordo/west-columbus-vikings/girls-golf/schedule/'),
    ('South Columbus','Football','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/football/schedule/'),
    ('South Columbus','Volleyball','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/volleyball/schedule/'),
    ('South Columbus','Boys Soccer','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/soccer/schedule/'),
    ('South Columbus','Girls Tennis','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/tennis/schedule/'),
    ('South Columbus','Cross Country','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/cross-country/schedule/'),
    ('South Columbus','Girls Golf','https://www.maxpreps.com/nc/tabor-city/south-columbus-stallions/girls-golf/schedule/'),
    ('East Columbus','Football','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/football/schedule/'),
    ('East Columbus','Volleyball','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/volleyball/schedule/'),
    ('East Columbus','Boys Soccer','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/soccer/schedule/'),
    ('East Columbus','Girls Tennis','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/tennis/schedule/'),
    ('East Columbus','Cross Country','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/cross-country/schedule/'),
    ('East Columbus','Girls Golf','https://www.maxpreps.com/nc/lake-waccamaw/east-columbus-gators/girls-golf/schedule/'),
]

HEADERS = {'User-Agent':'Mozilla/5.0 (compatible; CCS-RSS/1.0)'}

DATE_PATTERNS = [
    re.compile(r'(?P<date>\d{1,2}/\d{1,2})(?:/\d{2,4})?\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)', re.I),
    re.compile(r'(?P<date>\d{1,2}/\d{1,2})(?:/\d{2,4})?'),
]

def clean(v):
    s = html.unescape(str(v))
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def parse_dt(text):
    text = clean(text)
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        d = m.group('date')
        t = m.groupdict().get('time')
        try:
            if t:
                return datetime.strptime(f'{d}/{YEAR} {t.upper().replace(" ","")}', '%m/%d/%Y %I:%M%p').replace(tzinfo=ET)
            return datetime.strptime(f'{d}/{YEAR}', '%m/%d/%Y').replace(tzinfo=ET)
        except ValueError:
            pass
    return None

def fetch_tables(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return []
    try:
        return pd.read_html(r.text)
    except ValueError:
        return []

def row_to_event(school, sport, row, url):
    vals = [clean(x) for x in row.tolist() if clean(x) and clean(x).lower() != 'nan']
    if not vals:
        return None
    combined = ' | '.join(vals)
    dt = parse_dt(combined)
    if not dt or dt.year != YEAR or dt > CUTOFF:
        return None

    opponent = None
    homeaway = ''
    for v in vals:
        low = v.lower()
        if low in {'home','away','neutral'}:
            homeaway = v.title()
    # Prefer cells containing common opponent markers, otherwise choose a text-heavy non-date cell.
    candidates = []
    for v in vals:
        if parse_dt(v):
            continue
        if re.fullmatch(r'\d+[-–]\d+', v):
            continue
        if len(v) < 2:
            continue
        candidates.append(v)
    if candidates:
        opponent = max(candidates, key=lambda x: (bool(re.search(r'[A-Za-z]', x)), len(x)))
    if not opponent:
        opponent = 'TBA'

    # Clean typical schedule prefixes/suffixes.
    opponent = re.sub(r'^(vs\.?|@)\s*', '', opponent, flags=re.I)
    return {
        'school': school,
        'sport': sport,
        'dt': dt,
        'opponent': opponent,
        'homeaway': homeaway,
        'url': url,
    }

def collect():
    out = []
    for school, sport, url in SOURCES:
        for table in fetch_tables(url):
            for _, row in table.iterrows():
                e = row_to_event(school, sport, row, url)
                if e:
                    out.append(e)
    # Deduplicate conservatively.
    uniq = {}
    for e in out:
        key = (e['school'], e['sport'], e['dt'].isoformat(), e['opponent'])
        uniq[key] = e
    return sorted(uniq.values(), key=lambda e: e['dt'])

def build(events):
    rss = Element('rss', {'version':'2.0'})
    channel = SubElement(rss, 'channel')
    SubElement(channel, 'title').text = 'Columbus County Schools Fall Sports 2026'
    SubElement(channel, 'link').text = 'https://raw.githubusercontent.com/ccsrssfeeds/rss/main/feed.xml'
    SubElement(channel, 'description').text = 'Live fall sports schedules for West Columbus, South Columbus, and East Columbus through November 30, 2026. Refreshed hourly from published MaxPreps schedule pages.'
    SubElement(channel, 'language').text = 'en-us'
    SubElement(channel, 'lastBuildDate').text = format_datetime(datetime.now(ET))
    for e in events:
        item = SubElement(channel, 'item')
        suffix = f" ({e['homeaway']})" if e['homeaway'] else ''
        SubElement(item, 'title').text = f"{e['dt'].strftime('%b %-d, %-I:%M %p')} — {e['school']} {e['sport']} vs {e['opponent']}{suffix}"
        SubElement(item, 'link').text = e['url']
        SubElement(item, 'guid', {'isPermaLink':'false'}).text = f"{e['school']}|{e['sport']}|{e['dt'].isoformat()}|{e['opponent']}"
        SubElement(item, 'pubDate').text = format_datetime(e['dt'])
        SubElement(item, 'category').text = e['school']
        SubElement(item, 'category').text = e['sport']
        desc = f"{e['school']} {e['sport']} scheduled for {e['dt'].strftime('%A, %B %-d, %Y at %-I:%M %p')} Eastern vs {e['opponent']}"
        if e['homeaway']:
            desc += f" ({e['homeaway']})"
        SubElement(item, 'description').text = desc + '. Source: MaxPreps.'
    ElementTree(rss).write('feed.xml', encoding='utf-8', xml_declaration=True)

if __name__ == '__main__':
    events = collect()
    build(events)
    print(f'Wrote {len(events)} events')
