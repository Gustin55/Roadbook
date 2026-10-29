"""Chargement de la configuration YAML, avec valeurs par défaut.

La configuration est un dictionnaire imbriqué. Toute clé absente du fichier
utilisateur prend la valeur de ``DEFAUTS`` ; une clé inconnue déclenche un
avertissement (faute de frappe probable) mais n'arrête pas la génération.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAUTS: dict[str, Any] = {
    "epreuve": {
        "nom": "Road book",
        "equipage": "",
        "depart_prevu": None,  # ex. "2027-02-20 07:30", affiché dans l'en-tête
        "vitesse_moyenne_kmh": 40.0,
        # par_trace : chaque <trk> (ou <rte>) du GPX est une étape
        # unique    : toutes les traces sont mises bout à bout en une étape
        "decoupage_etapes": "par_trace",
        "noms_etapes": [],  # remplace les noms lus dans le GPX, dans l'ordre
    },
    "calcul": {
        "pas_reechantillonnage_m": 5.0,
        "doublon_m": 0.5,  # points consécutifs plus proches = doublons
        "saut_max_m": 1000.0,  # au-delà : avertissement « trou dans la trace »
        "lissage_m": 15.0,  # moyenne glissante sur le cap
        "fenetre_virage_m": 30.0,  # distance sur laquelle on mesure la variation de cap
        "stabilite_m": 30.0,  # longueur des tronçons avant/après servant à mesurer l'angle
        "seuil_virage_deg": 20.0,
        "fusion_virages_m": 25.0,
        # bornes (°) : légère <= 45 < normale <= 105 < franche <= 150 < épingle.
        # 105 et non 90 : un carrefour à angle droit mesuré à 91° doit rester « AD ».
        "tranches_angle_deg": [45.0, 105.0, 150.0],
        "demi_tour_deg": 165.0,
        "cap_distance_m": 100.0,  # cap de sortie mesuré sur cette distance
        "rappel_km": 0.0,  # case « TD » de rappel sur les longues lignes droites (0 = aucune)
        "sens_circulation": "droite",  # droite : rond-points tournés dans le sens antihoraire
        "rond_point": {
            "actif": True,
            "rayon_max_m": 35.0,
            "arc_min_deg": 45.0,
            "deflexion_min_deg": 15.0,
            "approche_m": 40.0,
        },
        "poi_tolerance_m": 75.0,  # distance max entre un POI et la trace
        "poi_fusion_m": 50.0,  # POI rattaché à une manœuvre aussi proche
        "seuil_pente_pct": 8.0,
    },
    "affichage": {
        "format": "a5",  # a5 | a4 | rouleau
        "hauteur_case_mm": 25.0,
        "lignes_par_page": None,  # imposé ; sinon déduit de la hauteur de case
        "largeur_rouleau_mm": 148.0,
        "longueur_max_rouleau_mm": 3000.0,
        "colonnes_pct": [22.0, 26.0, 52.0],  # distances | schéma | commentaires
        "decimales_total": 2,
        "decimales_partiel": 1,
        "separateur_decimal": ",",
        "textes": "abrege",  # abrege (AD, AG, TD...) | complet
        "afficher_cap": True,
        "afficher_pente": False,
        "couleurs": True,
        "lignes_alternees": True,
        "mini_carte": False,
        "mini_carte_hauteur_mm": 45.0,
        "page_garde": True,
        "page_legende": True,
        "remise_a_zero": "etape",  # etape | epreuve
        "numerotation": "etape",  # etape | epreuve
        "numerotation_pas": 1,
        "depart_arrivee": True,  # cases « DÉPART » et « ARRIVÉE »
    },
    # Abréviations appliquées seulement quand un texte ne tient pas dans sa case.
    "abreviations": {
        "piste principale": "PP",
        "tout droit": "TD",
        "à droite": "AD",
        "à gauche": "AG",
        "toujours": "TJS",
        "suivre": "SVE",
        "suivez": "SVE",
        "nombreuses": "NBX",
        "nombreux": "NBX",
        "rond-point": "RP",
        "carrefour": "CARF",
        "village": "VLG",
        "direction": "DIR.",
        "attention": "ATT.",
        "dangereux": "DANG.",
        "après": "AP.",
        "avant": "AV.",
    },
}


class ErreurConfig(ValueError):
    pass


def _fusion(base: dict, ajout: dict, chemin: str, avertissements: list[str]) -> dict:
    resultat = copy.deepcopy(base)
    for cle, valeur in ajout.items():
        ici = f"{chemin}.{cle}" if chemin else cle
        if cle not in base:
            # les abréviations sont libres
            if chemin == "abreviations":
                resultat[cle] = valeur
                continue
            avertissements.append(f"Configuration : clé inconnue « {ici} » ignorée")
            continue
        if isinstance(base[cle], dict) and isinstance(valeur, dict):
            resultat[cle] = _fusion(base[cle], valeur, ici, avertissements)
        else:
            resultat[cle] = valeur
    return resultat


def _valider(cfg: dict) -> None:
    aff = cfg["affichage"]
    if aff["format"] not in ("a5", "a4", "rouleau"):
        raise ErreurConfig("affichage.format doit valoir a5, a4 ou rouleau")
    if aff["textes"] not in ("abrege", "complet"):
        raise ErreurConfig("affichage.textes doit valoir abrege ou complet")
    if aff["remise_a_zero"] not in ("etape", "epreuve"):
        raise ErreurConfig("affichage.remise_a_zero doit valoir etape ou epreuve")
    if len(aff["colonnes_pct"]) != 3:
        raise ErreurConfig("affichage.colonnes_pct attend 3 valeurs")
    cal = cfg["calcul"]
    if cal["sens_circulation"] not in ("droite", "gauche"):
        raise ErreurConfig("calcul.sens_circulation doit valoir droite ou gauche")
    tranches = cal["tranches_angle_deg"]
    if len(tranches) != 3 or sorted(tranches) != list(tranches):
        raise ErreurConfig("calcul.tranches_angle_deg attend 3 bornes croissantes")
    if cal["pas_reechantillonnage_m"] <= 0:
        raise ErreurConfig("calcul.pas_reechantillonnage_m doit être positif")
    if cfg["epreuve"]["decoupage_etapes"] not in ("par_trace", "unique"):
        raise ErreurConfig("epreuve.decoupage_etapes doit valoir par_trace ou unique")


def config_par_defaut() -> dict:
    return copy.deepcopy(DEFAUTS)


def charger_config(chemin: str | Path | None) -> tuple[dict, list[str]]:
    """Retourne (configuration complète, avertissements)."""
    avertissements: list[str] = []
    if chemin is None:
        cfg = config_par_defaut()
    else:
        with open(chemin, encoding="utf-8") as f:
            donnees = yaml.safe_load(f) or {}
        if not isinstance(donnees, dict):
            raise ErreurConfig(f"{chemin} : le fichier doit contenir un dictionnaire YAML")
        cfg = _fusion(DEFAUTS, donnees, "", avertissements)
    _valider(cfg)
    return cfg, avertissements
