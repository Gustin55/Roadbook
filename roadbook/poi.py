"""Points d'intérêt : balises, dangers, ravitaillements... (waypoints GPX ou CSV)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

TYPES_POI = (
    "controle",
    "danger",
    "ravitaillement",
    "passage_niveau",
    "stop",
    "carrefour",
    "info",
    "depart",
    "arrivee",
)

# synonymes acceptés dans la colonne « type » du CSV ou la balise <type> du GPX
_SYNONYMES = {
    "controle": "controle", "contrôle": "controle", "cp": "controle", "cs": "controle",
    "ch": "controle", "pc": "controle", "balise": "controle", "checkpoint": "controle",
    "waypoint": "controle", "wpt_controle": "controle",
    "danger": "danger", "dz": "danger", "attention": "danger", "hazard": "danger",
    "ravitaillement": "ravitaillement", "ravito": "ravitaillement", "essence": "ravitaillement",
    "carburant": "ravitaillement", "fuel": "ravitaillement", "gas station": "ravitaillement",
    "passage_niveau": "passage_niveau", "passage à niveau": "passage_niveau", "pn": "passage_niveau",
    "stop": "stop",
    "carrefour": "carrefour", "intersection": "carrefour", "croisement": "carrefour",
    "info": "info", "note": "info", "remarque": "info",
    "depart": "depart", "départ": "depart", "start": "depart",
    "arrivee": "arrivee", "arrivée": "arrivee", "finish": "arrivee", "fin": "arrivee",
}

# préfixe du nom du waypoint quand aucun type n'est fourni (ex. « CS10 », « DZ3 »)
_PREFIXES = [
    (re.compile(r"^(CP|CS|CH|PC|WPC|WPM|WPV|WPS)\s*-?\s*\d*", re.I), "controle"),
    (re.compile(r"^(DZ|DANGER|!+)", re.I), "danger"),
    (re.compile(r"^(DEP|DÉP|START)", re.I), "depart"),
    (re.compile(r"^(ARR|FIN|FINISH)", re.I), "arrivee"),
    (re.compile(r"^(RAV|ESS|FUEL)", re.I), "ravitaillement"),
    (re.compile(r"^PN\b", re.I), "passage_niveau"),
]


@dataclass
class PointInteret:
    lat: float
    lon: float
    type: str = "info"
    description: str = ""
    code: str = ""  # ex. « CS10 », affiché cerclé sur le schéma
    niveau: int = 0  # dangers : 1 à 3 (« ! » à « !!! »)
    km: float | None = None  # position imposée (km d'étape), sinon projetée
    etape: str | None = None  # étape imposée (nom), sinon déduite
    source: str = ""
    # renseignés lors du rattachement à la trace
    s_m: float | None = None
    ecart_m: float | None = None
    extras: dict = field(default_factory=dict)


def normaliser_type(brut: str | None) -> str | None:
    if not brut:
        return None
    return _SYNONYMES.get(brut.strip().lower())


def deviner_type(nom: str, type_brut: str | None = None, symbole: str | None = None) -> str:
    for candidat in (type_brut, symbole):
        t = normaliser_type(candidat)
        if t:
            return t
    for motif, t in _PREFIXES:
        if nom and motif.match(nom.strip()):
            return t
    return "info"


def _code_controle(nom: str) -> str:
    m = re.match(r"^\s*([A-Za-z]{1,4}\s*-?\s*\d+)", nom or "")
    return m.group(1).replace(" ", "").replace("-", "").upper() if m else ""


def depuis_waypoint(nom: str, lat: float, lon: float, description: str, type_brut, symbole) -> PointInteret:
    t = deviner_type(nom, type_brut, symbole)
    code = _code_controle(nom) if t == "controle" else ""
    texte = description or ("" if code == (nom or "").upper() else nom or "")
    niveau = 0
    if t == "danger":
        niveau = min(3, max(1, (nom or "").count("!"))) if "!" in (nom or "") else 2
    return PointInteret(lat, lon, t, texte.strip(), code, niveau, source=f"GPX:{nom}")


def _nombre(valeur: str | None) -> float | None:
    if valeur is None or str(valeur).strip() == "":
        return None
    return float(str(valeur).strip().replace(",", "."))


def charger_csv(chemin: str | Path) -> tuple[list[PointInteret], list[str]]:
    """Lit un CSV de POI (séparateur « ; » ou « , » détecté automatiquement).

    Colonnes : lat, lon, type, description, et facultativement code, niveau, km, etape.
    Si ``km`` est renseigné, ``lat``/``lon`` peuvent être vides.
    """
    avertissements: list[str] = []
    points: list[PointInteret] = []
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        echantillon = f.read(4096)
        f.seek(0)
        try:
            dialecte = csv.Sniffer().sniff(echantillon, delimiters=";,\t")
        except csv.Error:
            dialecte = csv.excel
        lecteur = csv.DictReader(f, dialect=dialecte)
        if lecteur.fieldnames is None:
            return [], [f"{chemin} : fichier vide"]
        lecteur.fieldnames = [c.strip().lower() for c in lecteur.fieldnames]
        for numero, ligne in enumerate(lecteur, start=2):
            ligne = {k: (v or "").strip() for k, v in ligne.items() if k}
            try:
                lat, lon, km = _nombre(ligne.get("lat")), _nombre(ligne.get("lon")), _nombre(ligne.get("km"))
            except ValueError:
                avertissements.append(f"{chemin}:{numero} : coordonnée ou km illisible, ligne ignorée")
                continue
            if (lat is None or lon is None) and km is None:
                avertissements.append(f"{chemin}:{numero} : ni coordonnées ni km, ligne ignorée")
                continue
            type_brut = ligne.get("type", "")
            t = normaliser_type(type_brut)
            if t is None:
                if type_brut:
                    avertissements.append(f"{chemin}:{numero} : type « {type_brut} » inconnu, traité comme info")
                t = "info"
            niveau = int(_nombre(ligne.get("niveau")) or (2 if t == "danger" else 0))
            points.append(
                PointInteret(
                    lat=lat if lat is not None else float("nan"),
                    lon=lon if lon is not None else float("nan"),
                    type=t,
                    description=ligne.get("description", ""),
                    code=ligne.get("code", "").upper(),
                    niveau=max(0, min(3, niveau)),
                    km=km,
                    etape=ligne.get("etape") or None,
                    source=f"CSV:{numero}",
                )
            )
    return points, avertissements
