"""Libellés français du road book (regroupés ici pour une future traduction)."""

from __future__ import annotations

SENS = {
    # (abrégé, complet)
    1: ("AD", "à droite"),
    -1: ("AG", "à gauche"),
}

CLASSES = ("legere", "normale", "franche", "epingle")


def texte_virage(classe: str, signe: int, style: str) -> str:
    abr, complet = SENS[signe]
    if style == "abrege":
        return {
            "legere": f"LÉG. {abr}",
            "normale": abr,
            "franche": f"{abr} FORT",
            "epingle": f"ÉPINGLE {abr}",
        }[classe]
    return {
        "legere": f"Légèrement {complet}",
        "normale": f"Tourner {complet}",
        "franche": f"Tourner franchement {complet}",
        "epingle": f"Épingle {complet}",
    }[classe]


def texte_demi_tour(style: str) -> str:
    return "DEMI-TOUR" if style == "abrege" else "Faire demi-tour"


def direction_sortie(angle: float) -> str:
    """Direction de sortie d'un rond-point : droite, td, gauche ou demi-tour."""
    if abs(angle) >= 150:
        return "demi_tour"
    if angle > 30:
        return "droite"
    if angle < -30:
        return "gauche"
    return "td"


def texte_rond_point(angle: float, style: str) -> str:
    d = direction_sortie(angle)
    if style == "abrege":
        return {"droite": "RP SORTIE AD", "gauche": "RP SORTIE AG", "td": "RP SORTIE TD",
                "demi_tour": "RP DEMI-TOUR"}[d]
    return {"droite": "Rond-point, sortie à droite", "gauche": "Rond-point, sortie à gauche",
            "td": "Rond-point, sortie en face", "demi_tour": "Rond-point, demi-tour"}[d]


def texte_tout_droit(style: str) -> str:
    return "TD" if style == "abrege" else "Tout droit"


TEXTES_FIXES = {
    "depart": ("DÉPART", "Départ"),
    "arrivee": ("ARRIVÉE", "Arrivée"),
}

TYPES_POI = {
    "controle": "Contrôle",
    "danger": "Danger",
    "ravitaillement": "Ravitaillement",
    "passage_niveau": "Passage à niveau",
    "stop": "Stop",
    "carrefour": "Carrefour",
    "info": "Information",
    "depart": "Départ",
    "arrivee": "Arrivée",
}

LEGENDE_ABREVIATIONS = [
    ("TC / Total", "Compteur kilométrique cumulé (remis à zéro au départ)"),
    ("Partiel", "Distance depuis la case précédente"),
    ("AD / AG", "À droite / à gauche"),
    ("TD", "Tout droit"),
    ("LÉG.", "Légèrement (virage de moins de 45°)"),
    ("FORT", "Virage de plus de 90°"),
    ("RP", "Rond-point"),
    ("C.235", "Cap à suivre en degrés (boussole) après la case"),
    ("PP", "Piste principale"),
    ("SVE / TJS", "Suivre / toujours"),
    ("! à !!!", "Danger, de modéré à très dangereux"),
]
