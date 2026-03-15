#!/usr/bin/env python3
"""
spordle_scraper.py - AHM Anjou
Scrape équipes, rosters, horaires et classements depuis Spordle (pages publiques)
"""

import os, json, time, logging, re
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL     = "https://page.spordle.com/fr/ahm-anjou"
SPORDLE_ROOT = "https://page.spordle.com"
OUTPUT_FILE  = "data/spordle_data.json"

# ── Seules ces catégories seront scrappées ─────────────────────────────────
TARGET_CATEGORIES = ["M11", "M13"]  # ← ajouter M7, M9, M15, M18 quand prêt

NAV_WORDS = {"horaire", "classement", "joueurs", "accueil", "contact", "inscription", "équipes"}


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
    """
    Scrape la liste des équipes M11/M13.
    La catégorie est dans le titre de section (ex: 'M11 A MIXTE'),
    pas dans le nom de l'équipe (ex: 'EXPRESS').
    On cherche donc la section parente pour déterminer la catégorie.
    """
    log.info("Scraping équipes...")
    wait_and_load(page, f"{BASE_URL}/teams", wait_ms=5000)

    # Sauvegarder pour debug
    os.makedirs("data", exist_ok=True)
    page.screenshot(path="data/teams_debug.png")

    teams = []
    seen_urls = set()

    # Chercher tous les liens vers des pages d'équipe (/teams/XXXXX)
    links = page.query_selector_all("a[href*='/teams/']")
    log.info(f"  → {len(links)} liens d'équipes trouvés au total")

    for link in links:
        name = link.inner_text().strip()
        href = link.get_attribute("href") or ""

        if not href or href in seen_urls:
            continue
        if name.lower() in NAV_WORDS or len(name) < 2:
            continue

        seen_urls.add(href)

        # Chercher la catégorie dans les éléments parents (section, div, h2, h3...)
        cat = None
        try:
            # Remonter jusqu'à 5 niveaux pour trouver un titre de section M11/M13
            parent_text = page.evaluate("""(el) => {
                let node = el;
                for (let i = 0; i < 8; i++) {
                    node = node.parentElement;
                    if (!node) break;
                    const text = node.innerText || '';
                    if (text.match(/\\bM11\\b/)) return 'M11';
                    if (text.match(/\\bM13\\b/)) return 'M13';
                    if (text.match(/\\bM7\\b/))  return 'M7';
                    if (text.match(/\\bM9\\b/))  return 'M9';
                    if (text.match(/\\bM15\\b/)) return 'M15';
                    if (text.match(/\\bM18\\b/)) return 'M18';
                }
                return null;
            }""", link)
            if parent_text in TARGET_CATEGORIES:
                cat = parent_text
        except Exception:
            pass

        # Fallback : chercher dans le nom du lien lui-même
        if not cat:
            for tc in TARGET_CATEGORIES:
                if re.search(rf'\b{tc}\b', name.upper()):
                    cat = tc
                    break

        if cat:
            full_url = SPORDLE_ROOT + href if href.startswith("/") else href
            teams.append({"name": name, "url": full_url, "category": cat})
            log.info(f"    ✓ {cat} — {name}")

    log.info(f"  → {len(teams)} équipes {TARGET_CATEGORIES} trouvées")
    return teams


def scrape_team_detail(page, team: dict) -> dict:
    """Scrape le roster, l'horaire et le classement d'une équipe via URL directe"""
    result = {"roster": [], "schedule": [], "standings": []}
    url = team.get("url", "")
    if not url:
        return result

    base_url = url.split("?")[0]

    try:
        # ── Roster ──
        wait_and_load(page, base_url, wait_ms=3000)
        for row in page.query_selector_all("table tr"):
            text = row.inner_text().strip()
            if text and 2 < len(text) < 120:
                result["roster"].append(text)

        # ── Horaire — URL directe ──
        wait_and_load(page, f"{base_url}?tab=schedule", wait_ms=4000)
        # L'horaire Spordle utilise des divs, pas des tables
        # Structure: titre de date (h2/h3) + carte de match (div)
        # On capture tout le texte visible de la section principale
        game_containers = page.query_selector_all(
            "[class*='game'], [class*='match'], [class*='event'], "
            "[class*='schedule'], [class*='card'], [class*='Game'], "
            "[class*='Match'], [class*='Event']"
        )
        seen_games = set()
        for g in game_containers:
            text = g.inner_text().strip()
            if text and 10 < len(text) < 400 and text not in seen_games:
                seen_games.add(text)
                result["schedule"].append({"raw": text})

        # Fallback: chercher les sections de date + contenu adjacent
        if not result["schedule"]:
            sections = page.query_selector_all("h2, h3, h4, [class*='date'], [class*='Date']")
            for s in sections:
                text = s.inner_text().strip()
                if text and any(m in text.upper() for m in ["JANV", "FÉVR", "MARS", "AVRIL", "MAI", "JUIN",
                                                              "JUIL", "AOÛT", "SEPT", "OCT", "NOV", "DÉC",
                                                              "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                                              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
                                                              "LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI",
                                                              "SAMEDI", "DIMANCHE", "2025", "2026"]):
                    result["schedule"].append({"date_header": text})

        # ── Classement — dropdown React custom ──
        wait_and_load(page, f"{base_url}?tab=standings", wait_ms=4000)
        try:
            # Cliquer sur le dropdown pour l'ouvrir (composant React, pas un <select>)
            dropdown_trigger = page.query_selector(
                "[class*='dropdown'], [class*='Dropdown'], "
                "[class*='select'], [class*='Select'], "
                "[placeholder*='horaire'], [placeholder*='Horaire'], "
                "[placeholder*='Sélectionnez'], [placeholder*='selectionnez']"
            )
            if dropdown_trigger:
                dropdown_trigger.click()
                time.sleep(1.5)

                # Lire les options qui apparaissent après l'ouverture
                options = page.query_selector_all(
                    "[class*='option'], [role='option'], "
                    "[class*='item'], [class*='Item'], "
                    "[class*='menu'] li, [class*='Menu'] li, "
                    "[class*='list'] li"
                )
                log.info(f"    Classement: {len(options)} options trouvées")

                for opt in options[:4]:  # Max 4 classements
                    opt_text = opt.inner_text().strip()
                    if not opt_text or len(opt_text) < 2:
                        continue
                    try:
                        opt.click()
                        time.sleep(2)
                        rows = page.query_selector_all("table tr")
                        standing_rows = []
                        for r in rows:
                            txt = r.inner_text().strip()
                            if txt and len(txt) > 2:
                                standing_rows.append(txt)
                        if standing_rows:
                            result["standings"].append({
                                "division": opt_text,
                                "rows": standing_rows
                            })
                            log.info(f"    '{opt_text}': {len(standing_rows)} rangées")
                        # Rouvrir le dropdown pour la prochaine option
                        if dropdown_trigger:
                            dropdown_trigger.click()
                            time.sleep(1)
                    except Exception as e:
                        log.debug(f"    Option '{opt_text}': {e}")
            else:
                log.info("    Dropdown non trouvé — lecture directe")
                rows = page.query_selector_all("table tr")
                for r in rows:
                    txt = r.inner_text().strip()
                    if txt and len(txt) > 2:
                        result["standings"].append(txt)
        except Exception as e:
            log.warning(f"    Classement erreur: {e}")

    except Exception as e:
        log.warning(f"  Erreur {team.get('name')}: {e}")

    return result

def scrape_schedule_global(page) -> list:
    """Scrape l'horaire global de l'association"""
    log.info("Scraping horaire global...")
    wait_and_load(page, f"{BASE_URL}/schedule", wait_ms=5000)
    games = []
    for sel in ["[class*='game']", "[class*='match']", "[class*='event']", "[class*='schedule']", "table tr"]:
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
            result["teams"] = scrape_teams(page)

            log.info(f"Scraping détails de {len(result['teams'])} équipes...")
            for i, team in enumerate(result["teams"]):
                log.info(f"  [{i+1}/{len(result['teams'])}] {team['name']} ({team['category']})")
                detail = scrape_team_detail(page, team)
                team.update(detail)
                log.info(f"    → {len(detail['roster'])} joueurs | {len(detail['schedule'])} matchs | {len(detail['standings'])} classements")
                time.sleep(0.5)

            result["schedule"] = scrape_schedule_global(page)

            for team in result["teams"]:
                if team.get("standings"):
                    result["standings"].extend(team["standings"])

        except Exception as e:
            log.error(f"Erreur: {e}")
            raise
        finally:
            browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"\n✅ {OUTPUT_FILE}")
    log.info(f"   {len(result['schedule'])} matchs | {len(result['teams'])} équipes | {len(result['standings'])} classements")


if __name__ == "__main__":
    main()
