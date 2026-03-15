#!/usr/bin/env python3
"""
spordle_scraper.py
Scrape les données publiques de l'AHM Anjou depuis Spordle
Pages publiques — pas de login requis
"""

import os
import json
import time
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL    = "https://page.spordle.com/fr/ahm-anjou"
OUTPUT_FILE = "data/spordle_data.json"
CATEGORIES  = ["M7", "M9", "M11", "M13", "M15", "M18"]


def new_browser(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--ignore-certificate-errors", "--disable-web-security", "--no-sandbox"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="fr-CA",
        ignore_https_errors=True,
    )
    return browser, context


def wait_and_get_html(page, url: str, wait_selector: str = None, wait_ms: int = 4000) -> str:
    """Charge une page, attend le JS, retourne le HTML"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(wait_ms / 1000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=10000)
            except PlaywrightTimeout:
                log.warning(f"  Sélecteur '{wait_selector}' non trouvé sur {url}")
        return page.content()
    except Exception as e:
        log.warning(f"  Erreur chargement {url}: {e}")
        return ""


def scrape_teams(page) -> list:
    """Scrape la liste des équipes"""
    log.info("Scraping équipes...")
    url  = f"{BASE_URL}/teams"
    html = wait_and_get_html(page, url, wait_ms=5000)

    # Sauvegarder pour diagnostic
    os.makedirs("data", exist_ok=True)
    with open("data/teams_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    page.screenshot(path="data/teams_debug.png")

    teams = []
    # Chercher liens d'équipes
    links = page.query_selector_all("a[href*='/team'], a[href*='/equipe'], a[href*='teams/']")
    log.info(f"  → {len(links)} liens d'équipes trouvés")
    for link in links:
        name = link.inner_text().strip()
        href = link.get_attribute("href") or ""
        if name and len(name) > 2:
            cat = next((c for c in CATEGORIES if c.upper() in name.upper()), "Autre")
            teams.append({"name": name, "url": href, "category": cat})

    # Fallback : chercher cartes / items génériques
    if not teams:
        items = page.query_selector_all("[class*='team'], [class*='card'], [class*='item']")
        log.info(f"  → {len(items)} items génériques trouvés")
        for item in items:
            text = item.inner_text().strip()
            if text and len(text) > 2:
                cat = next((c for c in CATEGORIES if c in text.upper()), "Autre")
                teams.append({"name": text[:80], "category": cat})

    return teams


def scrape_schedule(page) -> list:
    """Scrape l'horaire"""
    log.info("Scraping horaire...")
    url  = f"{BASE_URL}/schedule"
    html = wait_and_get_html(page, url, wait_ms=5000)

    with open("data/schedule_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    page.screenshot(path="data/schedule_debug.png")

    games = []
    selectors = [
        "[class*='game']", "[class*='match']", "[class*='event']",
        "[class*='schedule']", "table tr", "[class*='card']"
    ]
    for sel in selectors:
        items = page.query_selector_all(sel)
        if len(items) > 1:
            log.info(f"  → {len(items)} éléments avec '{sel}'")
            for item in items:
                text = item.inner_text().strip()
                if text and len(text) > 8:
                    games.append({"raw": text[:200], "source": sel})
            if games:
                break

    log.info(f"  → {len(games)} matchs trouvés")
    return games


def scrape_standings(page) -> list:
    """Scrape les classements"""
    log.info("Scraping classements...")
    url  = f"{BASE_URL}/standings"
    html = wait_and_get_html(page, url, wait_ms=5000)

    with open("data/standings_debug.html", "w", encoding="utf-8") as f:
        f.write(html)

    standings = []
    selectors = ["table tr", "[class*='standing']", "[class*='rank']", "[class*='classement']"]
    for sel in selectors:
        items = page.query_selector_all(sel)
        if len(items) > 1:
            for item in items:
                text = item.inner_text().strip()
                if text and len(text) > 2:
                    standings.append({"raw": text[:200]})
            if standings:
                break

    log.info(f"  → {len(standings)} rangées de classement")
    return standings


def main():
    os.makedirs("data", exist_ok=True)
    result = {
        "scraped_at": datetime.now().isoformat(),
        "source":      "spordle",
        "association": "AHM Anjou",
        "schedule":    [],
        "teams":       [],
        "standings":   [],
    }

    with sync_playwright() as p:
        browser, context = new_browser(p)
        page = context.new_page()

        try:
            result["teams"]     = scrape_teams(page)
            result["schedule"]  = scrape_schedule(page)
            result["standings"] = scrape_standings(page)
        except Exception as e:
            log.error(f"Erreur scraping Spordle: {e}")
        finally:
            browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"✅ Données Spordle sauvegardées → {OUTPUT_FILE}")
    log.info(f"   {len(result['schedule'])} matchs | {len(result['teams'])} équipes | {len(result['standings'])} classements")


if __name__ == "__main__":
    main()
