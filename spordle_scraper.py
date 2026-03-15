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
SPORDLE_ROOT = "https://page.spordle.com"
OUTPUT_FILE = "data/spordle_data.json"
CATEGORIES  = ["M11", "M13"]  # ← ajouter M7, M9, M15, M18 quand prêt


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


def wait_and_load(page, url: str, wait_ms: int = 4000) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(wait_ms / 1000)


def scrape_teams(page) -> list:
    """Scrape la liste des équipes avec leurs URLs"""
    log.info("Scraping équipes...")
    wait_and_load(page, f"{BASE_URL}/teams", wait_ms=5000)

    teams = []
    seen_urls = set()

    links = page.query_selector_all("a[href*='/teams/']")
    log.info(f"  → {len(links)} liens d'équipes trouvés")

    for link in links:
        name = link.inner_text().strip()
        href = link.get_attribute("href") or ""
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)
        nav_words = {"horaire", "classement", "joueurs", "accueil", "contact", "inscription"}
        if name and len(name) > 2 and name.lower() not in nav_words:
            cat = next((c for c in CATEGORIES if c.upper() in name.upper()), "Autre")
            full_url = SPORDLE_ROOT + href if href.startswith("/") else href
            if cat != "Autre":  # Garder seulement les catégories ciblées
                teams.append({"name": name, "url": full_url, "category": cat})

    log.info(f"  → {len(teams)} équipes uniques")
    return teams


def scrape_team_detail(page, team: dict) -> dict:
    """Scrape le roster, l'horaire et le classement d'une équipe"""
    result = {"roster": [], "schedule": [], "standings": []}
    url = team.get("url", "")
    if not url:
        return result

    try:
        wait_and_load(page, url, wait_ms=3000)

        # ── Roster (page par défaut — Cahier d'équipe) ──
        players = page.query_selector_all("table tr, [class*='player'], [class*='joueur'], [class*='member']")
        for p in players:
            text = p.inner_text().strip()
            if text and len(text) > 2 and len(text) < 100:
                result["roster"].append(text)

        # ── Horaire — cliquer l'onglet ──
        try:
            horaire_btn = page.locator("button:has-text('Horaire'), a:has-text('Horaire')").first
            horaire_btn.click()
            time.sleep(2)
            games = page.query_selector_all("table tr, [class*='game'], [class*='match'], [class*='event']")
            for g in games:
                text = g.inner_text().strip()
                if text and len(text) > 5:
                    result["schedule"].append(text)
        except Exception as e:
            log.debug(f"    Onglet Horaire non trouvé: {e}")

        # ── Classement — cliquer l'onglet ──
        try:
            classement_btn = page.locator("button:has-text('Classement'), a:has-text('Classement')").first
            classement_btn.click()
            time.sleep(2)
            rows = page.query_selector_all("table tr, [class*='standing'], [class*='rank'], [class*='classement']")
            for r in rows:
                text = r.inner_text().strip()
                if text and len(text) > 2:
                    result["standings"].append(text)
        except Exception as e:
            log.debug(f"    Onglet Classement non trouvé: {e}")

    except Exception as e:
        log.warning(f"  Erreur scraping équipe {team.get('name')}: {e}")

    return result


def scrape_schedule_global(page) -> list:
    """Scrape l'horaire global de l'association"""
    log.info("Scraping horaire global...")
    wait_and_load(page, f"{BASE_URL}/schedule", wait_ms=5000)

    games = []
    selectors = ["[class*='game']", "[class*='match']", "[class*='event']", "[class*='schedule']", "table tr"]
    for sel in selectors:
        items = page.query_selector_all(sel)
        if len(items) > 1:
            for item in items:
                text = item.inner_text().strip()
                if text and len(text) > 8:
                    games.append({"raw": text[:200]})
            if games:
                log.info(f"  → {len(games)} matchs avec '{sel}'")
                break

    return games


def main():
    os.makedirs("data", exist_ok=True)
    result = {
        "scraped_at":  datetime.now().isoformat(),
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
            # 1. Liste des équipes
            result["teams"] = scrape_teams(page)

            # 2. Détails de chaque équipe (roster + horaire + classement)
            #    Limiter à 20 équipes pour éviter un timeout GitHub Actions
            teams_to_scrape = result["teams"][:20]
            log.info(f"Scraping détails de {len(teams_to_scrape)} équipes...")

            for i, team in enumerate(teams_to_scrape):
                log.info(f"  [{i+1}/{len(teams_to_scrape)}] {team['name']} ({team['category']})")
                detail = scrape_team_detail(page, team)
                team.update(detail)
                log.info(f"    → {len(detail['roster'])} joueurs | {len(detail['schedule'])} matchs | {len(detail['standings'])} classements")
                time.sleep(0.5)

            # 3. Horaire global
            result["schedule"] = scrape_schedule_global(page)

            # Consolider les classements depuis les équipes
            for team in result["teams"]:
                if team.get("standings"):
                    result["standings"].extend(team["standings"])

        except Exception as e:
            log.error(f"Erreur scraping Spordle: {e}")
            raise
        finally:
            browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"\n✅ Données Spordle sauvegardées → {OUTPUT_FILE}")
    log.info(f"   {len(result['schedule'])} matchs globaux | {len(result['teams'])} équipes | {len(result['standings'])} classements")


if __name__ == "__main__":
    main()
