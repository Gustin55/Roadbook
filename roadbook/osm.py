"""Réseau routier OpenStreetMap : téléchargement (Overpass), cache et lecture de fichiers.

Sources acceptées :

* l'API Overpass (en ligne), interrogée le long de la trace, avec un cache
  disque pour pouvoir regénérer le road book sans connexion ;
* un fichier local : export OSM XML (``.osm``, ``.osm.bz2``, ``.osm.gz``,
  par ex. « Exporter » sur openstreetmap.org ou JOSM) ou réponse Overpass JSON.

Données © les contributeurs d'OpenStreetMap, licence ODbL.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import __version__
from .geometry import GEOD, TraceEchantillonnee, vers_plan_local

# importance des routes, pour juger si un carrefour mérite une case
RANG_ROUTE = {
    "motorway": 8, "trunk": 7, "primary": 6, "secondary": 5, "tertiary": 4,
    "unclassified": 3, "residential": 3, "living_street": 2, "road": 2,
    "motorway_link": 5, "trunk_link": 5, "primary_link": 4, "secondary_link": 4, "tertiary_link": 3,
    "service": 1, "track": 1,
}


class ErreurOSM(RuntimeError):
    pass


@dataclass
class Voie:
    id: int
    noeuds: list[int]
    tags: dict[str, str]

    @property
    def highway(self) -> str:
        return self.tags.get("highway", "")

    @property
    def rang(self) -> int:
        return RANG_ROUTE.get(self.highway, 2)

    @property
    def libelle(self) -> str:
        """Numéro de route si connu, sinon nom de la voie."""
        return self.tags.get("ref") or self.tags.get("name") or ""

    @property
    def rond_point(self) -> bool:
        return self.tags.get("junction") in ("roundabout", "circular")

    @property
    def sens_unique(self) -> int:
        """+1 : sens du dessin, -1 : sens inverse, 0 : double sens."""
        v = self.tags.get("oneway", "")
        if v in ("yes", "true", "1"):
            return 1
        if v in ("-1", "reverse"):
            return -1
        if v == "no":
            return 0
        if self.rond_point or self.highway in ("motorway", "motorway_link"):
            return 1
        return 0


@dataclass
class Reseau:
    noeuds: dict[int, tuple[float, float]]
    tags_noeuds: dict[int, dict[str, str]]
    voies: list[Voie]
    _incidences: dict[int, list[tuple[int, int]]] | None = field(default=None, repr=False)

    @property
    def incidences(self) -> dict[int, list[tuple[int, int]]]:
        """noeud -> [(indice de voie, position du noeud dans la voie)]."""
        if self._incidences is None:
            inc: dict[int, list[tuple[int, int]]] = {}
            for iv, v in enumerate(self.voies):
                for pos, n in enumerate(v.noeuds):
                    inc.setdefault(n, []).append((iv, pos))
            self._incidences = inc
        return self._incidences

    def fusionner(self, autre: "Reseau") -> None:
        connues = {v.id for v in self.voies}
        self.noeuds.update(autre.noeuds)
        for n, t in autre.tags_noeuds.items():
            self.tags_noeuds.setdefault(n, {}).update(t)
        self.voies += [v for v in autre.voies if v.id not in connues]
        self._incidences = None

    def filtrer(self, types_ignores: list[str], services_ignores: list[str]) -> "Reseau":
        """Retire les voies non carrossables (chemins piétons...) et les voies incomplètes."""
        gardees = []
        for v in self.voies:
            if not v.highway or v.highway in types_ignores:
                continue
            if v.highway == "service" and v.tags.get("service") in services_ignores:
                continue
            if v.tags.get("area") == "yes" or v.tags.get("access") in ("no", "private"):
                continue
            noeuds = [n for n in v.noeuds if n in self.noeuds]
            if len(noeuds) >= 2:
                gardees.append(Voie(v.id, noeuds, v.tags))
        return Reseau(self.noeuds, self.tags_noeuds, gardees)

    def coord(self, n: int) -> tuple[float, float]:
        return self.noeuds[n]


# --------------------------------------------------------------------------
# Lecture de fichiers
# --------------------------------------------------------------------------


def _ouvrir(chemin: Path):
    nom = chemin.name.lower()
    if nom.endswith(".bz2"):
        return bz2.open(chemin, "rb")
    if nom.endswith(".gz"):
        return gzip.open(chemin, "rb")
    return open(chemin, "rb")


def depuis_overpass_json(donnees: dict) -> Reseau:
    noeuds, tags_noeuds, voies = {}, {}, []
    for el in donnees.get("elements", []):
        if el["type"] == "node":
            noeuds[el["id"]] = (el["lat"], el["lon"])
            if el.get("tags"):
                tags_noeuds[el["id"]] = el["tags"]
        elif el["type"] == "way":
            voies.append(Voie(el["id"], list(el.get("nodes", [])), dict(el.get("tags", {}))))
    return Reseau(noeuds, tags_noeuds, voies)


def depuis_osm_xml(flux) -> Reseau:
    noeuds, tags_noeuds, voies = {}, {}, []
    for _, el in ET.iterparse(flux, events=("end",)):
        if el.tag == "node":
            n = int(el.get("id"))
            noeuds[n] = (float(el.get("lat")), float(el.get("lon")))
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags:
                tags_noeuds[n] = tags
            el.clear()
        elif el.tag == "way":
            voies.append(Voie(int(el.get("id")), [int(nd.get("ref")) for nd in el.findall("nd")],
                              {t.get("k"): t.get("v") for t in el.findall("tag")}))
            el.clear()
    return Reseau(noeuds, tags_noeuds, voies)


def charger_fichier(chemin: str | Path) -> Reseau:
    chemin = Path(chemin)
    with _ouvrir(chemin) as f:
        debut = f.read(64).lstrip()
    with _ouvrir(chemin) as f:
        if debut.startswith(b"{"):
            return depuis_overpass_json(json.load(f))
        try:
            return depuis_osm_xml(f)
        except ET.ParseError as exc:
            raise ErreurOSM(f"{chemin} : fichier OSM illisible ({exc})") from exc


# --------------------------------------------------------------------------
# Overpass
# --------------------------------------------------------------------------


def _simplifier(x: np.ndarray, y: np.ndarray, tolerance: float) -> list[int]:
    """Douglas-Peucker itératif ; retourne les indices conservés."""
    garder = np.zeros(len(x), dtype=bool)
    garder[0] = garder[-1] = True
    pile = [(0, len(x) - 1)]
    while pile:
        a, b = pile.pop()
        if b - a < 2:
            continue
        dx, dy = x[b] - x[a], y[b] - y[a]
        l = math.hypot(dx, dy) or 1e-9
        d = np.abs(dy * (x[a + 1 : b] - x[a]) - dx * (y[a + 1 : b] - y[a])) / l
        k = int(np.argmax(d))
        if d[k] > tolerance:
            m = a + 1 + k
            garder[m] = True
            pile += [(a, m), (m, b)]
    return list(np.flatnonzero(garder))


def requetes_overpass(trace: TraceEchantillonnee, rayon_m: float, points_par_requete: int = 200) -> list[str]:
    """Requêtes Overpass « autour de la trace » (polyligne simplifiée, découpée en morceaux)."""
    lat0, lon0 = float(trace.lat.mean()), float(trace.lon.mean())
    x, y = vers_plan_local(trace.lat, trace.lon, lat0, lon0)
    idx = _simplifier(x, y, rayon_m / 4)
    requetes = []
    for debut in range(0, len(idx) - 1, points_par_requete - 1):
        morceau = idx[debut : debut + points_par_requete]
        coords = ",".join(f"{trace.lat[i]:.6f},{trace.lon[i]:.6f}" for i in morceau)
        requetes.append(
            "[out:json][timeout:180];\n"
            "(\n"
            f"  way(around:{rayon_m:.0f},{coords})[highway];\n"
            f"  node(around:{rayon_m:.0f},{coords})[railway=level_crossing];\n"
            f"  node(around:{rayon_m:.0f},{coords})[amenity=fuel];\n"
            ");\n"
            "(._;>;);\n"
            "out body;"
        )
    return requetes


def dossier_cache_defaut() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "roadbook" / "osm"


def interroger_overpass(requete: str, serveurs: list[str], cache: Path | None, delai_s: float = 1.0,
                        journal=print) -> dict:
    cle = hashlib.sha1(requete.encode("utf-8")).hexdigest()
    if cache is not None:
        fichier = cache / f"{cle}.json"
        if fichier.exists():
            return json.loads(fichier.read_text(encoding="utf-8"))
    corps = urllib.parse.urlencode({"data": requete}).encode("utf-8")
    erreurs = []
    for tentative in range(2):
        for url in serveurs:
            try:
                req = urllib.request.Request(url, data=corps, headers={"User-Agent": f"roadbook/{__version__}"})
                with urllib.request.urlopen(req, timeout=200) as rep:
                    donnees = json.loads(rep.read().decode("utf-8"))
                if cache is not None:
                    cache.mkdir(parents=True, exist_ok=True)
                    (cache / f"{cle}.json").write_text(json.dumps(donnees), encoding="utf-8")
                time.sleep(delai_s)
                return donnees
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                erreurs.append(f"{url} : {exc}")
                journal(f"  Overpass indisponible ({url}), essai suivant...")
        time.sleep(5 * (tentative + 1))
    raise ErreurOSM("impossible d'interroger Overpass :\n  " + "\n  ".join(erreurs))


def telecharger(traces: list[TraceEchantillonnee], cfg_osm: dict, cache: Path | None, journal=print) -> Reseau:
    reseau = Reseau({}, {}, [])
    requetes = [r for t in traces for r in requetes_overpass(t, cfg_osm["rayon_requete_m"])]
    for k, requete in enumerate(requetes, start=1):
        journal(f"OpenStreetMap : requête {k}/{len(requetes)}")
        reseau.fusionner(depuis_overpass_json(interroger_overpass(requete, cfg_osm["serveurs"], cache,
                                                                  journal=journal)))
    return reseau


def charger_reseau(traces: list[TraceEchantillonnee], cfg: dict, fichiers: list[str] | None = None,
                   en_ligne: bool = False, cache: Path | None = None, journal=print) -> Reseau:
    o = cfg["osm"]
    reseau = Reseau({}, {}, [])
    for f in fichiers or []:
        reseau.fusionner(charger_fichier(f))
    if en_ligne:
        reseau.fusionner(telecharger(traces, o, cache if cache is not None else dossier_cache_defaut(), journal))
    return reseau.filtrer(o["types_ignores"], o["services_ignores"])


# --------------------------------------------------------------------------
# Index spatial simple (grille) pour retrouver les objets proches de la trace
# --------------------------------------------------------------------------


class IndexTrace:
    """Grille sur les points rééchantillonnés de la trace."""

    def __init__(self, trace: TraceEchantillonnee, cellule_m: float = 50.0):
        self.trace = trace
        self.lat0, self.lon0 = float(trace.lat.mean()), float(trace.lon.mean())
        self.x, self.y = vers_plan_local(trace.lat, trace.lon, self.lat0, self.lon0)
        self.cellule = cellule_m
        self.grille: dict[tuple[int, int], list[int]] = {}
        for i, (cx, cy) in enumerate(zip((self.x // cellule_m).astype(int), (self.y // cellule_m).astype(int))):
            self.grille.setdefault((cx, cy), []).append(i)

    def plan(self, lat, lon):
        return vers_plan_local(lat, lon, self.lat0, self.lon0)

    def proches(self, lat: float, lon: float, rayon: float) -> np.ndarray:
        """Indices des points de trace à moins de ``rayon`` mètres."""
        px, py = self.plan(lat, lon)
        cx, cy = int(px // self.cellule), int(py // self.cellule)
        n = int(math.ceil(rayon / self.cellule))
        cand = [i for dx in range(-n, n + 1) for dy in range(-n, n + 1)
                for i in self.grille.get((cx + dx, cy + dy), ())]
        if not cand:
            return np.zeros(0, dtype=int)
        cand = np.array(cand)
        d = np.hypot(self.x[cand] - px, self.y[cand] - py)
        return cand[d <= rayon]

    def passages(self, lat: float, lon: float, rayon: float) -> list[tuple[float, float]]:
        """Passages de la trace à moins de ``rayon`` : [(abscisse m, écart m)]."""
        idx = np.sort(self.proches(lat, lon, rayon))
        if len(idx) == 0:
            return []
        px, py = self.plan(lat, lon)
        groupes = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
        resultat = []
        for g in groupes:
            d = np.hypot(self.x[g] - px, self.y[g] - py)
            k = int(g[int(np.argmin(d))])
            # affinage sur les deux segments voisins
            meilleur = (float(self.trace.s[k]), float(d.min()))
            for a, b in ((k - 1, k), (k, k + 1)):
                if a < 0 or b >= len(self.x):
                    continue
                vx, vy = self.x[b] - self.x[a], self.y[b] - self.y[a]
                l2 = vx * vx + vy * vy
                if l2 == 0:
                    continue
                t = min(1.0, max(0.0, ((px - self.x[a]) * vx + (py - self.y[a]) * vy) / l2))
                ecart = math.hypot(self.x[a] + t * vx - px, self.y[a] + t * vy - py)
                if ecart < meilleur[1]:
                    meilleur = (float(self.trace.s[a] + t * (self.trace.s[b] - self.trace.s[a])), ecart)
            resultat.append(meilleur)
        return resultat


def cap(lat1, lon1, lat2, lon2) -> float:
    az, _, _ = GEOD.inv(lon1, lat1, lon2, lat2)
    return float(az) % 360.0
