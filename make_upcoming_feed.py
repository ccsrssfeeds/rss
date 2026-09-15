from pathlib import Path
from xml.etree.ElementTree import parse, ElementTree

SOURCE = Path('sports.xml')
OUTPUT = Path('sports_upcoming.xml')


def build():
    tree = parse(SOURCE)
    root = tree.getroot()
    channel = root.find('channel')
    if channel is None:
        raise SystemExit('No RSS channel found')

    # sports.xml has already been pruned and sorted from soonest to latest.
    # Remove pubDate from each item so RSS readers do not reorder scheduled
    # future events newest-first based on the event date.
    for item in channel.findall('item'):
        pub = item.find('pubDate')
        if pub is not None:
            item.remove(pub)

    title = channel.find('title')
    if title is not None:
        title.text = 'Columbus County Schools Upcoming Fall Sports 2026'

    link = channel.find('link')
    if link is not None:
        link.text = 'https://raw.githubusercontent.com/ccsrssfeeds/rss/main/sports_upcoming.xml'

    description = channel.find('description')
    if description is not None:
        description.text = 'Upcoming Columbus County Schools fall sports events, ordered from next event to latest event.'

    ElementTree(root).write(OUTPUT, encoding='utf-8', xml_declaration=True)
    print(f'Wrote {OUTPUT}')


if __name__ == '__main__':
    build()
