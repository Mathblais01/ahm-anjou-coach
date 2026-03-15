#!/usr/bin/env python3
"""
pubsports_scraper.py
Scrape les statistiques adverses depuis PublicationSports / Hockey Québec
Utilise Playwright pour simuler un vrai navigateur (contourne le 403)
"""

import json
import time
import logging
import os
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL    = "https://www.publicationsports.com"
OUTPUT_FILE = "data/opponents_data.json"

OPPONENT_ASSOCIATIONS = [
    "anjou", "saint-leonard", "riviere-des-prairies",
    "montreal-nord", "rosemont", "verdun", "lasalle",
    "laval", "longueuil", "boucherville", "repentigny"
]

CATEGORIES = {
    "M7":  "atome-b",
    "M9":  "pee-wee-b",
    "M11": "pee-wee-bb",
    "M13": "midget-b",
    "M15": "midget-bb",
    "M18": "midget-a",
}


def get_html(page, url: str) -> str | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(1.5)
        return page.content()
    except PlaywrightTimeout:
        log.warning(f"  Timeout: {url}")
        return None
    except Exception as e:
        log.warning(f"  Erreur: {url} — {e}")
        return None


def parse_table(html: str) -> list:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    rows = []
    headers = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        texts = [c.get_text(strip=True) for c in cells]
        if not any(texts):
            continue
        if row.find("th") and not headers:
            headers = texts
        elif texts:
            if headers and len(texts) == len(headers):
                rows.append(dict(zip(headers, texts)))
            else:
                rows.append({"raw": " | ".join(t for t in texts if t)})
    return rows


def scrape_association(page, assoc: str, cat_key: str, cat_slug: str) -> dict:
    base = f"{BASE_URL}/stats/association/{assoc}/{cat_slug}"
    result = {}

    pages_to_scrape = {
        "standings":   f"{base}/classement.html",
        "team_stats":  f"{base}/equipes.html",
        "top_players": f"{base}/pointeurs.html",
        "schedule":    f"{base}/horaire.html",
    }

    for key, url in pages_to_scrape.items():
        html = get_html(page, url)
        data = parse_table(html)
        if data:
            result[key] = data
            log.info(f"    ✓ {key}: {len(data)} entrées")
        time.sleep(0.8)

    return result


def main():
    os.makedirs("data", exist_ok=True)

    result = {
        "scraped_at": datetime.now().isoformat(),
        "source": "publicationsports",
        "categories": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="fr-CA",
        )
        page = context.new_page()

        log.info("Initialisation du navigateur...")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        except Exception:
            pass

        for cat_key, cat_slug in CATEGORIES.items():
            log.info(f"\n=== Catégorie {cat_key} ({cat_slug}) ===")
            result["categories"][cat_key] = {"associations": {}}

            for assoc in OPPONENT_ASSOCIATIONS:
                log.info(f"  → {assoc}")
                data = scrape_association(page, assoc, cat_key, cat_slug)
                if data:
                    result["categories"][cat_key]["associations"][assoc] = data
                else:
                    log.info(f"    ✗ Aucune donnée")

        browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(
        len(cat.get("associations", {}))
        for cat in result["categories"].values()
    )
    log.info(f"\n✅ Données sauvegardées → {OUTPUT_FILE} ({total} associations)")


if __name__ == "__main__":
    main()
