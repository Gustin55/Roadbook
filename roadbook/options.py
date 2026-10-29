"""Description des options pour l'interface graphique (libellés, types, aide).

``impact`` indique ce qu'il faut refaire quand l'option change :

* ``rendu``   : seulement le PDF (instantané) ;
* ``analyse`` : relire la trace et redétecter les manœuvres.
"""

from __future__ import annotations

import json
from typing import Any


def _champ(chemin: str, libelle: str, type_: str, aide: str = "", impact: str = "rendu", **extra) -> dict:
    return {"chemin": chemin, "libelle": libelle, "type": type_, "aide": aide, "impact": impact, **extra}


def _choix(*paires) -> list[dict]:
    return [{"valeur": v, "libelle": l} for v, l in paires]


SECTIONS: list[dict[str, Any]] = [
    {
        "id": "epreuve", "titre": "Épreuve", "icone": "flag",
        "champs": [
            _champ("epreuve.nom", "Nom de l'épreuve", "texte", "Affiché en haut à droite de chaque page."),
            _champ("epreuve.equipage", "Équipage", "texte", "Sous le nom de l'épreuve (facultatif)."),
            _champ("epreuve.depart_prevu", "Départ prévu", "texte",
                   "Format AAAA-MM-JJ HH:MM ou HH:MM. Sert aux horaires estimés.", placeholder="2027-02-20 07:30"),
            _champ("epreuve.vitesse_moyenne_kmh", "Vitesse moyenne", "nombre",
                   "Pour la durée estimée de chaque étape.", unite="km/h", min=5, max=150, pas=1),
            _champ("epreuve.decoupage_etapes", "Étapes", "choix",
                   "Une trace du GPX = une étape, ou tout le GPX en une seule étape.", impact="analyse",
                   choix=_choix(("par_trace", "Une par trace GPX"), ("unique", "Une seule étape"))),
            _champ("epreuve.noms_etapes", "Noms des étapes", "liste",
                   "Un nom par ligne, dans l'ordre (remplace les noms lus dans le GPX).", impact="analyse"),
        ],
    },
    {
        "id": "page", "titre": "Mise en page", "icone": "layout",
        "champs": [
            _champ("affichage.format", "Format", "choix", "A5 : carnet type 4L Trophy. Rouleau : bande continue.",
                   choix=_choix(("a5", "A5 portrait"), ("a4", "A4 portrait"), ("rouleau", "Rouleau"))),
            _champ("affichage.hauteur_case_mm", "Hauteur des cases", "curseur",
                   "Plus haut = plus lisible, moins de cases par page.", unite="mm", min=15, max=50, pas=1),
            _champ("affichage.lignes_par_page", "Cases par page", "nombre",
                   "Laisser vide pour le calcul automatique d'après la hauteur des cases.", min=1, max=30, pas=1,
                   vide=True),
            _champ("affichage.colonnes_pct", "Largeur des colonnes", "colonnes",
                   "Répartition distances / schéma / commentaires.",
                   noms=["Distances", "Schéma", "Commentaires"]),
            _champ("affichage.largeur_rouleau_mm", "Largeur du rouleau", "nombre", "Format rouleau uniquement.",
                   unite="mm", min=80, max=300, pas=1),
            _champ("affichage.longueur_max_rouleau_mm", "Longueur max. d'une bande", "nombre",
                   "Une étape plus longue est coupée en plusieurs bandes.", unite="mm", min=300, max=5000, pas=50),
            _champ("affichage.couleurs", "Couleurs", "booleen",
                   "Contrôles en bleu, dangers en rouge. Désactiver pour une impression noir et blanc."),
            _champ("affichage.lignes_alternees", "Lignes alternées", "booleen", "Fond gris une case sur deux."),
            _champ("affichage.mini_carte", "Mini-carte par page", "booleen",
                   "Tracé de l'étape sous les cases, portion de la page en gras (A5/A4)."),
            _champ("affichage.mini_carte_hauteur_mm", "Hauteur de la mini-carte", "curseur", "", unite="mm",
                   min=25, max=90, pas=1),
        ],
    },
    {
        "id": "textes", "titre": "Textes et distances", "icone": "type",
        "champs": [
            _champ("affichage.textes", "Style des libellés", "choix", "« AD », « LÉG. AG »… ou phrases complètes.",
                   choix=_choix(("abrege", "Abrégé (AD, AG, TD)"), ("complet", "Complet (Tourner à droite)"))),
            _champ("affichage.majuscules", "Commentaires en capitales", "booleen", ""),
            _champ("affichage.afficher_cap", "Afficher le cap (C.235)", "booleen",
                   "Cap boussole de la route après la case."),
            _champ("affichage.afficher_pente", "Signaler les fortes pentes", "booleen",
                   "Si l'altitude est présente dans le GPX."),
            _champ("calcul.seuil_pente_pct", "Pente signalée à partir de", "nombre", "", unite="%", min=1, max=30,
                   pas=1),
            _champ("affichage.decimales_total", "Décimales du total", "choix", "",
                   choix=_choix((1, "1 (12,3)"), (2, "2 (12,34)"), (3, "3 (12,345)"))),
            _champ("affichage.decimales_partiel", "Décimales du partiel", "choix", "",
                   choix=_choix((1, "1 (1,2)"), (2, "2 (1,23)"))),
            _champ("affichage.separateur_decimal", "Séparateur décimal", "choix", "",
                   choix=_choix((",", "Virgule"), (".", "Point"))),
            _champ("calcul.tranches_angle_deg", "Classes d'angle", "triple",
                   "Bornes : légère ≤ a < normale ≤ b < forte ≤ c < épingle.",
                   noms=["Légère", "Normale", "Forte"], unite="°"),
            _champ("abreviations", "Abréviations", "dictionnaire",
                   "Appliquées seulement quand un texte ne tient pas dans sa case."),
        ],
    },
    {
        "id": "pages", "titre": "Pages et numérotation", "icone": "pages",
        "champs": [
            _champ("affichage.page_legende", "Page de légende", "booleen", "Symboles et abréviations, en début."),
            _champ("affichage.page_garde", "Page de garde par étape", "booleen",
                   "Distance, durée, contrôles, dangers et carte de l'étape."),
            _champ("affichage.depart_arrivee", "Cases départ et arrivée", "booleen", ""),
            _champ("affichage.remise_a_zero", "Compteur total", "choix", "",
                   choix=_choix(("etape", "Remis à zéro à chaque étape"), ("epreuve", "Cumulé sur l'épreuve"))),
            _champ("affichage.numerotation", "Numéros de case", "choix", "",
                   choix=_choix(("etape", "Repartent à 1 par étape"), ("epreuve", "Continus"))),
            _champ("affichage.numerotation_pas", "Pas de numérotation", "nombre", "", min=1, max=10, pas=1),
            _champ("calcul.rappel_km", "Case de rappel tous les", "nombre",
                   "Case « TD » sur les longues lignes droites (0 = jamais).", unite="km", min=0, max=50, pas=0.5),
            _champ("calcul.cap_distance_m", "Cap mesuré sur", "nombre", "", unite="m", min=20, max=500, pas=10),
            _champ("calcul.poi_fusion_m", "Point d'intérêt rattaché à une case à moins de", "nombre",
                   "Sinon il crée sa propre case.", unite="m", min=0, max=300, pas=5),
        ],
    },
    {
        "id": "detection", "titre": "Détection des virages", "icone": "turn",
        "champs": [
            _champ("calcul.seuil_virage_deg", "Seuil de virage", "curseur",
                   "En dessous, pas d'instruction.", impact="analyse", unite="°", min=5, max=60, pas=1),
            _champ("calcul.fenetre_virage_m", "Fenêtre de mesure", "curseur",
                   "Distance sur laquelle le changement de cap doit se produire.", impact="analyse", unite="m",
                   min=10, max=100, pas=5),
            _champ("calcul.fusion_virages_m", "Fusion des virages proches", "curseur", "", impact="analyse",
                   unite="m", min=0, max=100, pas=5),
            _champ("calcul.lissage_m", "Lissage du cap", "curseur", "Contre le bruit GPS.", impact="analyse",
                   unite="m", min=0, max=50, pas=5),
            _champ("calcul.stabilite_m", "Longueur de stabilité", "curseur",
                   "Tronçons avant/après servant à mesurer l'angle.", impact="analyse", unite="m",
                   min=10, max=100, pas=5),
            _champ("calcul.demi_tour_deg", "Demi-tour à partir de", "nombre", "", impact="analyse", unite="°",
                   min=120, max=180, pas=1),
            _champ("calcul.pas_reechantillonnage_m", "Pas de calcul", "nombre", "", impact="analyse", unite="m",
                   min=1, max=20, pas=1),
            _champ("calcul.sens_circulation", "Circulation", "choix", "Sens de rotation des rond-points.",
                   impact="analyse", choix=_choix(("droite", "À droite"), ("gauche", "À gauche"))),
            _champ("calcul.rond_point.actif", "Détecter les rond-points (sans OSM)", "booleen", "",
                   impact="analyse"),
            _champ("calcul.rond_point.rayon_max_m", "Rayon max. d'un rond-point", "nombre", "", impact="analyse",
                   unite="m", min=5, max=100, pas=1),
            _champ("calcul.poi_tolerance_m", "Distance max. point d'intérêt / trace", "nombre", "",
                   impact="analyse", unite="m", min=5, max=500, pas=5),
        ],
    },
    {
        "id": "osm", "titre": "Routes (OpenStreetMap)", "icone": "road",
        "champs": [
            _champ("osm.actif", "Télécharger OpenStreetMap", "booleen",
                   "Carrefours, rond-points numérotés, noms de routes. Nécessite Internet (puis cache).",
                   impact="analyse"),
            _champ("osm.carrefours_td", "Carrefours affichés", "choix", "", impact="analyse",
                   choix=_choix(("importants", "Importants"), ("tous", "Tous ceux avec un choix"),
                                ("aucun", "Seulement quand on tourne"))),
            _champ("osm.tolerance_m", "Écart max. trace / route", "curseur",
                   "À augmenter pour une trace dessinée à la main.", impact="analyse", unite="m",
                   min=4, max=40, pas=1),
            _champ("osm.fusion_carrefours_m", "Carrefours complexes regroupés sous", "nombre", "",
                   impact="analyse", unite="m", min=0, max=80, pas=5),
            _champ("osm.virages_hors_carrefour", "Garder les virages sans carrefour", "booleen",
                   "Courbes et lacets sur route.", impact="analyse"),
            _champ("osm.poi_auto", "Repères automatiques", "booleen",
                   "Feux, stops, passages à niveau, stations-service.", impact="analyse"),
        ],
    },
]


def chemins_analyse() -> list[str]:
    return [c["chemin"] for s in SECTIONS for c in s["champs"] if c["impact"] == "analyse"]


def lire(cfg: dict, chemin: str):
    v = cfg
    for k in chemin.split("."):
        v = v[k]
    return v


def empreinte_analyse(cfg: dict) -> str:
    """Résumé des options qui obligent à refaire l'analyse (et non un simple rendu)."""
    utiles = {p: lire(cfg, p) for p in chemins_analyse()}
    utiles["rond_point"] = cfg["calcul"]["rond_point"]
    utiles["osm"] = cfg["osm"]
    for k in ("doublon_m", "saut_max_m"):
        utiles[k] = cfg["calcul"][k]
    return json.dumps(utiles, sort_keys=True, default=str)
