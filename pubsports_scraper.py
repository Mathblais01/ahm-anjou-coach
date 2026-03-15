#!/usr/bin/env python3
"""
pubsports_scraper.py
Scrape les statistiques adverses depuis PublicationSports / Hockey Québec
Source publique — aucun credential requis
"""

import json
import time
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL    = "https://www.publicationsports.com"
OUTPUT_FILE = "data/opponents_data.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
}

# Associations adversaires fréquentes dans la région de Montréal / Anjou
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


def get_soup(url: str, retries=3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            log.warning(f"  Tentative {attempt+1}/{retries} échouée pour {url}: {e}")
            time.sleep(2 * (attempt + 1))
    return None


def scrape_standings_for_category(assoc: str, cat_key: str, cat_slug: str) -> dict:
    """Scrape le classement d'une catégorie pour une association"""
    url = f"{BASE_URL}/stats/association/{assoc}/{cat_slug}/classement.html"
    soup = get_soup(url)
    if not soup:
        return {}

    standings = []
    table = soup.find("table", class_=lambda c: c and "classement" in c.lower()) \
             or soup.find("table")

    if table:
        rows = table.find_all("tr")
        headers = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(strip=True) for c in cells]
            if row.find("th"):
                headers = texts
            else:
                if headers and len(texts) == len(headers):
                    standings.append(dict(zip(headers, texts)))
                elif texts:
                    standings.append({"raw": " | ".join(texts)})

    return {
        "association": assoc,
        "category": cat_key,
        "url": url,
        "standings": standings
    }


def scrape_team_stats(assoc: str, cat_slug: str) -> list:
    """Scrape les stats des équipes (buts pour/contre, victoires, etc.)"""
    url = f"{BASE_URL}/stats/association/{assoc}/{cat_slug}/equipes.html"
    soup = get_soup(url)
    if not soup:
        return []

    teams = []
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        headers = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]
            if row.find("th"):
                headers = texts
            elif texts and len(texts) > 2:
                entry = dict(zip(headers, texts)) if headers else {"raw": " | ".join(texts)}
                teams.append(entry)

    return teams


def scrape_top_players(assoc: str, cat_slug: str) -> list:
    """Scrape les meilleurs pointeurs (joueurs à surveiller)"""
    url = f"{BASE_URL}/stats/association/{assoc}/{cat_slug}/pointeurs.html"
    soup = get_soup(url)
    if not soup:
        return []

    players = []
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        headers = []
        for i, row in enumerate(rows):
            if i > 30:  # Top 30 joueurs max
                break
            cells = row.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]
            if row.find("th"):
                headers = texts
            elif texts and len(texts) > 2:
                entry = dict(zip(headers, texts)) if headers else {"raw": texts}
                # Essayer de récupérer le lien vers la fiche du joueur
                link = row.find("a")
                if link:
                    entry["profile_url"] = BASE_URL + link.get("href", "")
                players.append(entry)

    return players


def scrape_schedule(assoc: str, cat_slug: str) -> list:
    """Scrape l'horaire des matchs"""
    url = f"{BASE_URL}/stats/association/{assoc}/{cat_slug}/horaire.html"
    soup = get_soup(url)
    if not soup:
        return []

    games = []
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        headers = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]
            if row.find("th"):
                headers = texts
            elif texts and any(t for t in texts):
                entry = dict(zip(headers, texts)) if headers else {"raw": " | ".join(texts)}
                games.append(entry)

    return games


def main():
    import os
    os.makedirs("data", exist_ok=True)

    result = {
        "scraped_at": datetime.now().isoformat(),
        "source": "publicationsports",
        "categories": {}
    }

    for cat_key, cat_slug in CATEGORIES.items():
        log.info(f"\n=== Catégorie {cat_key} ===")
        result["categories"][cat_key] = {
            "associations": {}
        }

        for assoc in OPPONENT_ASSOCIATIONS:
            log.info(f"  → {assoc}")
            time.sleep(0.5)  # Respecter le serveur

            standings   = scrape_standings_for_category(assoc, cat_key, cat_slug)
            team_stats  = scrape_team_stats(assoc, cat_slug)
            top_players = scrape_top_players(assoc, cat_slug)
            schedule    = scrape_schedule(assoc, cat_slug)

            if standings or team_stats or top_players:
                result["categories"][cat_key]["associations"][assoc] = {
                    "standings":   standings,
                    "team_stats":  team_stats,
                    "top_players": top_players,
                    "schedule":    schedule,
                }
                log.info(f"    ✓ {len(team_stats)} équipes | {len(top_players)} pointeurs | {len(schedule)} matchs")
            else:
                log.info(f"    ✗ Aucune donnée trouvée")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"\n✅ Données adversaires sauvegardées → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
