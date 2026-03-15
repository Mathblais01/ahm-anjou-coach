#!/usr/bin/env python3
"""
spordle_scraper.py
Scrape les données de l'AHM Anjou depuis Spordle (authentifié)
Credentials via variables d'environnement (GitHub Secrets)
"""

import os
import json
import time
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SPORDLE_URL   = "https://page.spordle.com/fr/ahm-anjou"
LOGIN_URL     = "https://id.spordle.com"
EMAIL         = os.environ["SPORDLE_EMAIL"]
PASSWORD      = os.environ["SPORDLE_PASSWORD"]
OUTPUT_FILE   = "data/spordle_data.json"

CATEGORIES = ["M7", "M9", "M11", "M13", "M15", "M18"]

def login(page):
    log.info("Connexion à Spordle...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(4)  # Attendre le JS

    # Sauvegarder la page de login pour diagnostic
    os.makedirs("data", exist_ok=True)
    with open("data/login_debug.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    page.screenshot(path="data/login_debug.png")
    log.info(f"  URL actuelle: {page.url}")

    # Lister tous les inputs visibles
    inputs = page.query_selector_all("input")
    log.info(f"  {len(inputs)} input(s) trouvé(s) sur la page")
    for inp in inputs:
        t = inp.get_attribute("type") or ""
        n = inp.get_attribute("name") or ""
        i = inp.get_attribute("id") or ""
        p = inp.get_attribute("placeholder") or ""
        log.info(f"    input: type={t} name={n} id={i} placeholder={p}")

    # Tentative de remplissage avec timeout plus long
    try:
        page.wait_for_selector("input", timeout=15000)
        email_sel = "input[type=email], input[name*=email], input[id*=email], input[placeholder*=mail], input[placeholder*=courriel]"
        pwd_sel   = "input[type=password]"
        page.fill(email_sel, EMAIL, timeout=10000)
        page.fill(pwd_sel,   PASSWORD, timeout=10000)
        page.click("button[type=submit], button:has-text(Connexion), button:has-text(Se connecter), button:has-text(Login)")
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)
        log.info(f"  Connecté. URL: {page.url}")
    except Exception as e:
        log.error(f"  Échec login: {e}")
        raise

def scrape_schedule(page) -> list:
    """Scrape l'horaire de toutes les équipes AHM Anjou"""
    log.info("Scraping horaire AHM Anjou...")
    games = []

    page.goto(f"{SPORDLE_URL}/schedule", wait_until="networkidle")
    time.sleep(3)

    # Essayer plusieurs sélecteurs possibles selon la structure Spordle
    selectors = [
        ".schedule-game", ".game-item", "[class*='game']",
        "[class*='match']", "[class*='schedule']",
        "table tr", ".event-item"
    ]

    found = False
    for sel in selectors:
        items = page.query_selector_all(sel)
        if len(items) > 2:
            log.info(f"  → {len(items)} éléments trouvés avec '{sel}'")
            found = True
            for item in items:
                text = item.inner_text().strip()
                if text and len(text) > 10:
                    games.append({"raw": text, "source": "spordle_schedule"})
            break

    if not found:
        # Fallback: capturer tout le HTML de la page pour analyse
        content = page.content()
        log.warning("Sélecteurs standards non trouvés — sauvegarde HTML brut pour analyse")
        os.makedirs("data", exist_ok=True)
        with open("data/spordle_debug.html", "w", encoding="utf-8") as f:
            f.write(content)

    return games

def scrape_teams(page) -> list:
    """Scrape la liste des équipes et leurs rosters"""
    log.info("Scraping équipes AHM Anjou...")
    teams = []

    page.goto(f"{SPORDLE_URL}/teams", wait_until="networkidle")
    time.sleep(3)

    # Chercher les équipes par catégorie
    team_links = page.query_selector_all("a[href*='/team/'], a[href*='/equipe/']")
    log.info(f"  → {len(team_links)} liens d'équipes trouvés")

    for link in team_links:
        name = link.inner_text().strip()
        href = link.get_attribute("href") or ""
        if name:
            cat = next((c for c in CATEGORIES if c in name.upper()), "Autre")
            teams.append({"name": name, "url": href, "category": cat})

    return teams

def scrape_standings(page) -> list:
    """Scrape les classements"""
    log.info("Scraping classements...")
    standings = []

    page.goto(f"{SPORDLE_URL}/standings", wait_until="networkidle")
    time.sleep(3)

    rows = page.query_selector_all("table tr, [class*='standing'] [class*='row'], [class*='rank']")
    for row in rows:
        text = row.inner_text().strip()
        if text and len(text) > 3:
            standings.append({"raw": text})

    log.info(f"  → {len(standings)} rangées de classement")
    return standings

def scrape_roster(page, team_url: str) -> list:
    """Scrape le roster d'une équipe spécifique"""
    players = []
    full_url = f"https://page.spordle.com{team_url}" if team_url.startswith("/") else team_url
    page.goto(full_url, wait_until="networkidle")
    time.sleep(2)

    player_items = page.query_selector_all(
        "[class*='player'], [class*='joueur'], table.roster tr, [class*='member']"
    )
    for item in player_items:
        text = item.inner_text().strip()
        if text and len(text) > 2:
            players.append({"raw": text})

    return players

def main():
    os.makedirs("data", exist_ok=True)
    result = {
        "scraped_at": datetime.now().isoformat(),
        "source": "spordle",
        "association": "AHM Anjou",
        "schedule": [],
        "teams": [],
        "standings": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            login(page)

            result["schedule"]  = scrape_schedule(page)
            result["teams"]     = scrape_teams(page)
            result["standings"] = scrape_standings(page)

            # Scraper les rosters des équipes trouvées (max 10)
            for team in result["teams"][:10]:
                if team.get("url"):
                    log.info(f"  Roster: {team['name']}")
                    team["roster"] = scrape_roster(page, team["url"])
                    time.sleep(1)

        except PlaywrightTimeout as e:
            log.error(f"Timeout Spordle: {e}")
        except Exception as e:
            log.error(f"Erreur scraping Spordle: {e}")
            raise
        finally:
            browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"✅ Données Spordle sauvegardées → {OUTPUT_FILE}")
    log.info(f"   {len(result['schedule'])} matchs | {len(result['teams'])} équipes | {len(result['standings'])} classements")

if __name__ == "__main__":
    main()
