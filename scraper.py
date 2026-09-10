"""
Scraper: pulls every Bellhaven community from the website.
Outputs data/communities.json
"""

import json, re, os
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://analyst-assessment-production.up.railway.app"
DATA_DIR = Path(__file__).parent / "data"


def get_slugs() -> list[str]:
    """Crawl paginated listing + homepage to collect all community slugs."""
    slugs = set()
    page = 1
    while True:
        html = requests.get(f"{BASE}/communities", params={"page": page}).text
        for m in re.findall(r'href="/communities/([^"]+)"', html):
            slugs.add(m)
        if f"page={page + 1}" not in html:
            break
        page += 1

    # Homepage may announce new communities not yet in the listing
    home = requests.get(BASE).text
    for m in re.findall(r'href="/communities/([^"]+)"', home):
        slugs.add(m)

    return sorted(slugs)


def scrape_community(slug: str) -> dict:
    """Scrape a single community detail page."""
    html = requests.get(f"{BASE}/communities/{slug}").text
    soup = BeautifulSoup(html, "html.parser")

    name = ""
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)

    # Parse <dt>/<dd> pairs
    fields = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            fields[dt.get_text(strip=True)] = dd

    street = city = state = zipcode = care = admin = phone = ""

    if "Address" in fields:
        dd = fields["Address"]
        parts = list(dd.stripped_strings)
        if parts:
            street = parts[0]
        if len(parts) > 1:
            m = re.match(r"(.*?),\s*(\w{2})\s+(\d{5})", parts[1])
            if m:
                city, state, zipcode = m.group(1), m.group(2), m.group(3)

    if "Care Offerings" in fields:
        badges = fields["Care Offerings"].find_all("span", class_="badge")
        if badges:
            care = ", ".join(b.get_text(strip=True) for b in badges)
        else:
            care = fields["Care Offerings"].get_text(strip=True)

    if "Administrator" in fields:
        admin = fields["Administrator"].get_text(strip=True)
    if "Phone" in fields:
        phone = fields["Phone"].get_text(strip=True)

    return {
        "slug": slug, "name": name, "street": street,
        "city": city, "state": state, "zip": zipcode,
        "care": care, "admin": admin, "phone": phone,
    }


def main():
    DATA_DIR.mkdir(exist_ok=True)

    print("Fetching community slugs...")
    slugs = get_slugs()
    print(f"Found {len(slugs)} communities")

    print("Scraping details...")
    communities = []
    for slug in slugs:
        c = scrape_community(slug)
        communities.append(c)
        print(f"  ✓ {c['name']} — {c['city']}, {c['state']}")

    out = DATA_DIR / "communities.json"
    out.write_text(json.dumps(communities, indent=2))
    print(f"\nSaved {len(communities)} communities to {out}")


if __name__ == "__main__":
    main()
