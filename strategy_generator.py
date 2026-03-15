#!/usr/bin/env python3
"""
strategy_generator.py
Génère automatiquement les stratégies de match via Claude AI
Lit les données scrappées et produit un JSON de stratégies enrichi
"""

import os
import json
import logging
from datetime import datetime
from anthropic import Anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SPORDLE_FILE   = "data/spordle_data.json"
OPPONENTS_FILE = "data/opponents_data.json"
STRATEGY_FILE  = "data/strategies.json"

SYSTEM_PROMPT = """Tu es un analyste hockey expert spécialisé dans le hockey mineur québécois (M7 à M18).
Tu analyses les statistiques des équipes adverses et génères des stratégies de match concrètes et adaptées à chaque catégorie d'âge.

Pour chaque match, tu produis UNIQUEMENT un objet JSON valide (aucun texte avant ou après) avec cette structure exacte :
{
  "match_id": "string",
  "adversaire": "string",
  "categorie": "string",
  "date": "string",
  "niveau_menace": "faible|moyen|elevé",
  "resume_adversaire": "string (2-3 phrases)",
  "joueurs_a_surveiller": [
    {
      "nom": "string",
      "numero": "string ou null",
      "position": "string",
      "raison": "string (pourquoi surveiller ce joueur)",
      "priorite": "haute|moyenne|basse"
    }
  ],
  "strategie_offensive": {
    "titre": "string",
    "points_cles": ["string", "string", "string"],
    "formation_recommandee": "string"
  },
  "strategie_defensive": {
    "titre": "string",
    "points_cles": ["string", "string", "string"],
    "ajustements": "string"
  },
  "mises_en_jeu": "string (stratégie pour les mises en jeu)",
  "avantage_numerique": "string (conseils PP)",
  "desavantage_numerique": "string (conseils PK)",
  "message_motivationnel": "string (court, pour les jeunes)",
  "confiance_analyse": 0.0
}"""


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        log.warning(f"Fichier non trouvé: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_opponent_data(opponents_data: dict, opponent_name: str, category: str) -> dict:
    """Trouve les données d'un adversaire dans les données scrappées"""
    cat_data = opponents_data.get("categories", {}).get(category, {})
    assocs   = cat_data.get("associations", {})

    # Recherche par correspondance partielle du nom
    opponent_lower = opponent_name.lower().replace(" ", "-").replace("'", "")
    for assoc_key, assoc_data in assocs.items():
        if any(word in assoc_key for word in opponent_lower.split("-") if len(word) > 3):
            return assoc_data

    # Si pas trouvé, chercher dans toutes les équipes des classements
    for assoc_key, assoc_data in assocs.items():
        standings = assoc_data.get("standings", {}).get("standings", [])
        for row in standings:
            row_text = json.dumps(row, ensure_ascii=False).lower()
            if opponent_lower[:6] in row_text:
                return assoc_data

    return {}


def generate_strategy(match: dict, opponent_data: dict, category: str) -> dict:
    """Appel Claude pour générer une stratégie"""
    opponent_name = match.get("adversaire", match.get("raw", "Adversaire inconnu"))

    # Préparer le contexte
    context_parts = [
        f"**Match:** AHM Anjou ({category}) vs {opponent_name}",
        f"**Date:** {match.get('date', 'À déterminer')}",
        f"**Lieu:** {match.get('lieu', 'À déterminer')}",
    ]

    if opponent_data:
        standings = opponent_data.get("standings", {}).get("standings", [])
        top_players = opponent_data.get("top_players", [])
        team_stats = opponent_data.get("team_stats", [])

        if standings:
            context_parts.append(f"\n**Classement adversaire:**\n{json.dumps(standings[:5], ensure_ascii=False)}")
        if team_stats:
            context_parts.append(f"\n**Stats équipes:**\n{json.dumps(team_stats[:5], ensure_ascii=False)}")
        if top_players:
            context_parts.append(f"\n**Top pointeurs adverses:**\n{json.dumps(top_players[:10], ensure_ascii=False)}")
    else:
        context_parts.append("\n**Note:** Données adversaires limitées — analyse basée sur les tendances générales de la catégorie.")

    # Adapter le ton selon la catégorie
    age_note = {
        "M7": "Catégorie M7 (5-6 ans) — focus sur le plaisir, participation de tous, concepts de base.",
        "M9": "Catégorie M9 (7-8 ans) — développement habiletés, encourager l'initiative.",
        "M11": "Catégorie M11 (9-10 ans) — introduction tactique simple, positionnement de base.",
        "M13": "Catégorie M13 (11-12 ans) — tactiques intermédiaires, rôles définis.",
        "M15": "Catégorie M15 (13-14 ans) — stratégie avancée, systèmes de jeu.",
        "M18": "Catégorie M18 (15-17 ans) — analyse complète, préparation compétitive.",
    }.get(category, "")

    if age_note:
        context_parts.append(f"\n**Contexte d'âge:** {age_note}")

    prompt = "\n".join(context_parts) + "\n\nGénère la stratégie JSON pour ce match."

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # Nettoyer si besoin
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        strategy = json.loads(raw.strip())
        strategy["match_id"] = match.get("id", f"{category}_{opponent_name}_{datetime.now().strftime('%Y%m%d')}")
        return strategy

    except json.JSONDecodeError as e:
        log.error(f"JSON invalide pour {opponent_name}: {e}")
        return {"error": str(e), "adversaire": opponent_name, "categorie": category}
    except Exception as e:
        log.error(f"Erreur Claude pour {opponent_name}: {e}")
        return {"error": str(e), "adversaire": opponent_name, "categorie": category}


def main():
    import os
    os.makedirs("data", exist_ok=True)

    spordle_data   = load_json(SPORDLE_FILE)
    opponents_data = load_json(OPPONENTS_FILE)

    strategies = {
        "generated_at": datetime.now().isoformat(),
        "strategies": []
    }

    schedule = spordle_data.get("schedule", [])

    if not schedule:
        # Mode démo : créer des matchs fictifs pour valider le pipeline
        log.warning("Aucun horaire Spordle — génération en mode démo")
        schedule = [
            {"adversaire": "Saint-Léonard", "categorie": "M11", "date": "2025-03-20", "lieu": "Aréna Roussin"},
            {"adversaire": "Rosemont",       "categorie": "M13", "date": "2025-03-22", "lieu": "Aréna Père-Marquette"},
            {"adversaire": "Rivière-des-Prairies", "categorie": "M15", "date": "2025-03-25", "lieu": "Complexe Sportif"},
        ]

    log.info(f"Génération de stratégies pour {len(schedule)} matchs...")

    for i, match in enumerate(schedule):
        category = match.get("categorie", match.get("category", "M11"))
        opponent = match.get("adversaire", match.get("raw", ""))
        log.info(f"  [{i+1}/{len(schedule)}] {category} vs {opponent}")

        opp_data = find_opponent_data(opponents_data, opponent, category)
        strategy = generate_strategy(match, opp_data, category)
        strategy["original_match"] = match
        strategies["strategies"].append(strategy)

    with open(STRATEGY_FILE, "w", encoding="utf-8") as f:
        json.dump(strategies, f, ensure_ascii=False, indent=2)

    success = sum(1 for s in strategies["strategies"] if "error" not in s)
    log.info(f"\n✅ {success}/{len(schedule)} stratégies générées → {STRATEGY_FILE}")


if __name__ == "__main__":
    main()
