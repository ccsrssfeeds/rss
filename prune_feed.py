from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import parse, ElementTree
from pathlib import Path
import re

ET = ZoneInfo('America/New_York')
FILES = ['feed.xml', 'sports.xml']
CCS_SCHOOLS = {'West Columbus', 'South Columbus', 'East Columbus'}


def event_datetime(item):
    pub = item.findtext('pubDate')
    if not pub:
        return None
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ET)
        return dt.astimezone(ET)
    except Exception:
        return None


def categories(item):
    return [c.text.strip() for c in item.findall('category') if c.text and c.text.strip()]


def ccs_matchup_key(item):
    cats = categories(item)
    school = next((c for c in cats if c in CCS_SCHOOLS), None)
    sport = next((c for c in cats if c not in CCS_SCHOOLS), None)
    title = item.findtext('title', '')
    dt = event_datetime(item)
    if not school or not sport or not dt:
        return None

    m = re.search(r'\bvs\s+(.+?)(?:\s+\((?:Home|Away|Neutral)\))?$', title, re.I)
    if not m:
        return None
    opponent = m.group(1).strip()
    opponent = re.sub(r'\s+\((?:Home|Away|Neutral)\)$', '', opponent, flags=re.I).strip()
    if opponent not in CCS_SCHOOLS:
        return None

    pair = tuple(sorted((school, opponent)))
    # Same sport + same calendar date + same two CCS schools = one event.
    # Using the date instead of exact time also catches minor time differences
    # between the two schools' published schedule pages.
    return (sport.lower(), dt.date().isoformat(), pair)


def prune(path: str):
    p = Path(path)
    if not p.exists():
        return

    tree = parse(p)
    root = tree.getroot()
    channel = root.find('channel')
    if channel is None:
        return

    now = datetime.now(ET)
    removed_past = 0
    removed_dupes = 0
    seen_ccs_matchups = set()

    for item in list(channel.findall('item')):
        dt = event_datetime(item)
        if dt and dt < now:
            channel.remove(item)
            removed_past += 1
            continue

        key = ccs_matchup_key(item)
        if key:
            if key in seen_ccs_matchups:
                channel.remove(item)
                removed_dupes += 1
                continue
            seen_ccs_matchups.add(key)

    ElementTree(root).write(p, encoding='utf-8', xml_declaration=True)
    print(f'{path}: removed {removed_past} past events and {removed_dupes} duplicate CCS matchups')


if __name__ == '__main__':
    for f in FILES:
        prune(f)
