from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import parse, ElementTree
from pathlib import Path

ET = ZoneInfo('America/New_York')
FILES = ['feed.xml', 'sports.xml']


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
    removed = 0

    for item in list(channel.findall('item')):
        pub = item.findtext('pubDate')
        if not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ET)
            else:
                dt = dt.astimezone(ET)
        except Exception:
            continue

        if dt < now:
            channel.remove(item)
            removed += 1

    ElementTree(root).write(p, encoding='utf-8', xml_declaration=True)
    print(f'{path}: removed {removed} past events')


if __name__ == '__main__':
    for f in FILES:
        prune(f)
