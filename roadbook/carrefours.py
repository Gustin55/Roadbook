"""Carrefours et rond-points lus dans OpenStreetMap.

Pour chaque noeud OSM où se rejoignent au moins trois branches de route et
près duquel passe la trace, on cherche par quelle branche la trace arrive et
par laquelle elle repart : on compare l'extrémité de chaque branche (à ~20 m
du noeud) avec la position de la trace 20 m avant et 20 m après. Un noeud
proche de la trace mais dont aucune branche ne correspond (route parallèle,
pont, autre chaussée) est ignoré.

On en déduit :

* l'angle exact du changement de direction et les autres routes du carrefour
  (dessinées en trait fin sur le schéma) ;
* pour les rond-points (``junction=roundabout``), le **numéro de la sortie**,
  en comptant les sorties autorisées entre l'entrée et la sortie empruntées ;
* le numéro ou le nom de la route prise, et le panneau de direction
  (``destination``) s'il est renseigné.

Un carrefour où l'on suit simplement la route principale (pas de route plus
importante, pas de branche proche de la direction suivie) n'a pas de case
en mode ``importants``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geometry import TraceEchantillonnee, depuis_plan_local, diff_cap
from .instructions import Manoeuvre
from .osm import IndexTrace, Reseau, Voie
from .poi import PointInteret


@dataclass(eq=False)
class Branche:
    voie: Voie
    pos: int  # position du noeud de départ dans la voie
    sens: int  # +1 : vers les indices croissants de la voie
    x: float  # extrémité de la branche (plan local, m)
    y: float
    longueur: float
    cap: float  # depuis le noeud vers l'extrémité

    @property
    def sortie_autorisee(self) -> bool:
        return self.voie.sens_unique in (0, self.sens)

    @property
    def entree_autorisee(self) -> bool:
        return self.voie.sens_unique in (0, -self.sens)

    @property
    def anneau(self) -> bool:
        return self.voie.rond_point


@dataclass
class Passage:
    noeud: int
    s: float
    entree: Branche
    sortie: Branche
    branches: list[Branche]

    @property
    def cap_arrivee(self) -> float:
        return (self.entree.cap + 180.0) % 360.0


@dataclass
class _Groupe:
    passages: list[Passage] = field(default_factory=list)


class AnalyseOSM:
    def __init__(self, tr: TraceEchantillonnee, reseau: Reseau, cfg: dict):
        self.tr = tr
        self.reseau = reseau
        self.cfg = cfg
        self.o = cfg["osm"]
        self.cal = cfg["calcul"]
        self.index = IndexTrace(tr)
        self._xy: dict[int, tuple[float, float]] = {}
        self._branches: dict[int, list[Branche]] = {}
        self._succ_anneau: dict[int, int] | None = None
        self._groupe_anneau: dict[int, int] | None = None

    # -- géométrie --------------------------------------------------------------

    def xy(self, n: int) -> tuple[float, float]:
        if n not in self._xy:
            lat, lon = self.reseau.coord(n)
            x, y = self.index.plan(lat, lon)
            self._xy[n] = (float(x), float(y))
        return self._xy[n]

    def point_trace(self, s: float) -> tuple[float, float]:
        s = min(max(s, 0.0), self.tr.longueur)
        return float(np.interp(s, self.tr.s, self.index.x)), float(np.interp(s, self.tr.s, self.index.y))

    def branches(self, n: int) -> list[Branche]:
        if n in self._branches:
            return self._branches[n]
        L = self.o["longueur_branche_m"]
        x0, y0 = self.xy(n)
        resultat = []
        for iv, pos in self.reseau.incidences.get(n, ()):
            v = self.reseau.voies[iv]
            for sens in (1, -1):
                k = pos
                if not 0 <= k + sens < len(v.noeuds):
                    continue
                px, py, parcouru = x0, y0, 0.0
                while 0 <= k + sens < len(v.noeuds):
                    qx, qy = self.xy(v.noeuds[k + sens])
                    d = math.hypot(qx - px, qy - py)
                    if parcouru + d >= L and d > 0:
                        t = (L - parcouru) / d
                        px, py, parcouru = px + t * (qx - px), py + t * (qy - py), L
                        break
                    px, py, parcouru, k = qx, qy, parcouru + d, k + sens
                if parcouru < 1.0:
                    continue
                cap = math.degrees(math.atan2(px - x0, py - y0)) % 360.0
                resultat.append(Branche(v, pos, sens, px, py, parcouru, cap))
        self._branches[n] = resultat
        return resultat

    # -- rond-points ----------------------------------------------------------------

    def _preparer_anneaux(self) -> None:
        succ: dict[int, int] = {}
        parent: dict[int, int] = {}

        def racine(a):
            while parent.setdefault(a, a) != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for v in self.reseau.voies:
            if not v.rond_point:
                continue
            noeuds = v.noeuds if v.sens_unique >= 0 else v.noeuds[::-1]
            for a, b in zip(noeuds, noeuds[1:]):
                if a != b:
                    succ[a] = b
                    parent[racine(a)] = racine(b)
        self._succ_anneau = succ
        self._groupe_anneau = {n: racine(n) for n in parent}

    def compter_sorties(self, entree: int, sortie: int) -> int | None:
        if self._succ_anneau is None:
            self._preparer_anneaux()
        n, compte = entree, 0
        for _ in range(1000):
            n = self._succ_anneau.get(n)
            if n is None or n == entree:
                return None
            if n == sortie:
                return compte + 1
            compte += sum(1 for b in self.branches(n) if not b.anneau and b.sortie_autorisee)
        return None

    def noeuds_anneau(self, n: int) -> list[int]:
        if self._groupe_anneau is None:
            self._preparer_anneaux()
        g = self._groupe_anneau.get(n)
        return [k for k, v in self._groupe_anneau.items() if v == g]

    # -- détection des passages ------------------------------------------------------

    def passages(self) -> list[Passage]:
        tol = self.o["tolerance_m"]
        tol_branche = 1.25 * tol
        noeuds = np.array(list(self.reseau.incidences.keys()))
        if len(noeuds) == 0:
            return []
        coords = np.array([self.reseau.coord(int(n)) for n in noeuds])
        X, Y = self.index.plan(coords[:, 0], coords[:, 1])
        c = self.index.cellule
        cellules = set(self.index.grille)
        proches = [i for i, (cx, cy) in enumerate(zip((X // c).astype(int), (Y // c).astype(int)))
                   if any((cx + dx, cy + dy) in cellules for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
        resultat: list[Passage] = []
        for i in proches:
            n = int(noeuds[i])
            br = self.branches(n)
            mini_rp = self.reseau.tags_noeuds.get(n, {}).get("highway") == "mini_roundabout"
            if len(br) < 3 and not mini_rp:
                continue
            lat, lon = self.reseau.coord(n)
            for s, _ in self.index.passages(lat, lon, tol):
                meilleure_entree, meilleure_sortie = None, None
                for b in br:
                    if s - b.longueur < -1 or s + b.longueur > self.tr.longueur + 1:
                        continue
                    ex, ey = self.point_trace(s - b.longueur)
                    sx, sy = self.point_trace(s + b.longueur)
                    d_in = math.hypot(b.x - ex, b.y - ey) + (0 if b.entree_autorisee else tol)
                    d_out = math.hypot(b.x - sx, b.y - sy) + (0 if b.sortie_autorisee else tol)
                    if d_in <= tol_branche and (meilleure_entree is None or d_in < meilleure_entree[0]):
                        meilleure_entree = (d_in, b)
                    if d_out <= tol_branche and (meilleure_sortie is None or d_out < meilleure_sortie[0]):
                        meilleure_sortie = (d_out, b)
                if meilleure_entree and meilleure_sortie and meilleure_entree[1] is not meilleure_sortie[1]:
                    resultat.append(Passage(n, s, meilleure_entree[1], meilleure_sortie[1], br))
        resultat.sort(key=lambda p: p.s)
        return resultat

    # -- interprétation ---------------------------------------------------------------

    def _sur_la_trace(self, b: Branche) -> bool:
        """Branche qui longe la trace (liaison interne d'un carrefour complexe)."""
        lat, lon = self._latlon_plan(b.x, b.y)
        return len(self.index.proches(lat, lon, 6.0)) > 0

    def _latlon_plan(self, x, y):
        lat, lon = depuis_plan_local(x, y, self.index.lat0, self.index.lon0)
        return float(lat), float(lon)

    def rond_point(self, entree: Passage, sortie: Passage, intermediaires: list[Passage]) -> Manoeuvre:
        h_in = entree.cap_arrivee
        angle = float(diff_cap(h_in, sortie.sortie.cap))
        noeuds = self.noeuds_anneau(entree.noeud)
        cx = float(np.mean([self.xy(n)[0] for n in noeuds]))
        cy = float(np.mean([self.xy(n)[1] for n in noeuds]))

        def position(n):
            x, y = self.xy(n)
            return float(diff_cap(h_in, math.degrees(math.atan2(x - cx, y - cy)) % 360))

        autres = []
        for n in noeuds:
            if n in (entree.noeud, sortie.noeud):
                continue
            if any(not b.anneau for b in self.branches(n)):
                p = position(n)
                if all(abs(diff_cap(p, a)) > 12 for a in autres):
                    autres.append(p)
        num = self.compter_sorties(entree.noeud, sortie.noeud)
        m = Manoeuvre("rond_point", entree.s, angle, entree.s - 20, sortie.s + 20, source="osm",
                      branches=autres, position_sortie=position(sortie.noeud), sortie_num=num)
        if num is None:
            m.remarques.append("rond-point OSM : sens de circulation incohérent, n° de sortie non calculé")
        self._decorer(m, entree.entree.voie, sortie.sortie.voie, [entree, sortie] + intermediaires, force_route=True)
        return m

    def carrefour(self, groupe: list[Passage]) -> tuple[Manoeuvre | None, str]:
        premier, dernier = groupe[0], groupe[-1]
        h_in = premier.cap_arrivee
        angle = float(diff_cap(h_in, dernier.sortie.cap))
        entree_v, sortie_v = premier.entree.voie, dernier.sortie.voie
        autres: list[tuple[float, Branche]] = []
        for p in groupe:
            for b in p.branches:
                if b is p.entree or b is p.sortie:
                    continue
                if len(groupe) > 1 and self._sur_la_trace(b):
                    continue
                rel = float(diff_cap(h_in, b.cap))
                if all(abs(diff_cap(rel, a)) > 12 for a, _ in autres):
                    autres.append((rel, b))
        concurrentes = [(a, b) for a, b in autres if b.sortie_autorisee]
        seuil = self.cal["seuil_virage_deg"]
        mini_rp = any(self.reseau.tags_noeuds.get(p.noeud, {}).get("highway") == "mini_roundabout"
                      for p in groupe)
        if not concurrentes and not mini_rp:
            return None, "aucun autre choix possible"
        continuation = entree_v.id == sortie_v.id or (entree_v.libelle and entree_v.libelle == sortie_v.libelle)
        rang_max = max((b.voie.rang for _, b in concurrentes), default=0)
        ambigu = any(abs(diff_cap(a, angle)) < 30 for a, _ in concurrentes)
        evident = continuation and abs(angle) < 45 and rang_max <= sortie_v.rang and not ambigu
        mode = self.o["carrefours_td"]
        if mode == "tous":
            garder = True
        elif mode == "importants":
            # route croisée plus importante que la nôtre (ou égale si notre route change de nom)
            croise_plus_grande = rang_max > sortie_v.rang or (not continuation and rang_max >= sortie_v.rang)
            garder = not evident and (abs(angle) >= seuil or croise_plus_grande or ambigu)
        else:
            garder = not evident and abs(angle) >= seuil
        if mini_rp:
            garder = True
        if not garder:
            return None, "route évidente"

        s_debut, s_fin = premier.s - 20, dernier.s + 20
        if mini_rp:
            droite = self.cal["sens_circulation"] == "droite"
            avant = [a for a, _ in concurrentes if (a > angle if droite else a < angle)]
            m = Manoeuvre("rond_point", premier.s, angle, s_debut, s_fin, source="osm",
                          branches=[a for a, _ in autres], position_sortie=angle, sortie_num=len(avant) + 1)
        else:
            type_ = "demi_tour" if abs(angle) >= self.cal["demi_tour_deg"] else "virage"
            m = Manoeuvre(type_, premier.s, angle, s_debut, s_fin, source="osm", branches=[a for a, _ in autres])
        self._decorer(m, entree_v, sortie_v, groupe, force_route=abs(angle) < seuil)
        return m, ""

    def _decorer(self, m: Manoeuvre, entree_v: Voie, sortie_v: Voie, passages: list[Passage],
                 force_route: bool) -> None:
        if sortie_v.libelle and (force_route or sortie_v.libelle != entree_v.libelle):
            m.route = sortie_v.libelle
        dest = sortie_v.tags.get("destination") or sortie_v.tags.get("destination:ref") or ""
        m.direction = dest.replace(";", " / ")
        if any(self.reseau.tags_noeuds.get(p.noeud, {}).get("highway") == "traffic_signals" for p in passages):
            m.notes.append("FEUX")

    def manoeuvres(self) -> tuple[list[Manoeuvre], list[float], list[str]]:
        """Manœuvres OSM, abscisses de tous les carrefours traversés, remarques."""
        passages = self.passages()
        remarques: list[str] = []
        resultat: list[Manoeuvre] = []
        traverses = [p.s for p in passages]
        i = 0
        fusion = self.o["fusion_carrefours_m"]
        while i < len(passages):
            p = passages[i]
            # entrée sur un anneau de rond-point : on cherche la sortie
            if not p.entree.anneau and p.sortie.anneau:
                j = i + 1
                while j < len(passages) and passages[j].s - p.s < 800:
                    q = passages[j]
                    if q.entree.anneau and not q.sortie.anneau:
                        break
                    j += 1
                if j < len(passages) and passages[j].entree.anneau and not passages[j].sortie.anneau:
                    resultat.append(self.rond_point(p, passages[j], passages[i + 1 : j]))
                    i = j + 1
                    continue
                remarques.append(f"rond-point OSM à {p.s / 1000:.2f} km : sortie introuvable")
            if p.entree.anneau and p.sortie.anneau:
                i += 1  # noeud intermédiaire d'un anneau déjà traité
                continue
            groupe = [p]
            while (i + 1 < len(passages) and passages[i + 1].s - groupe[-1].s <= fusion
                   and not passages[i + 1].sortie.anneau):
                i += 1
                groupe.append(passages[i])
            m, _ = self.carrefour(groupe)
            if m is not None:
                resultat.append(m)
            i += 1
        return resultat, traverses, remarques

    # -- réseau proche : la trace est-elle sur une route ? ------------------------------

    def sur_route(self, s_liste: list[float]) -> list[bool]:
        tol = self.o["tolerance_m"] + 5
        pts_x, pts_y = [], []
        cellules = set(self.index.grille)
        c = self.index.cellule
        for v in self.reseau.voies:
            xy = np.array([self.xy(n) for n in v.noeuds])
            for (ax, ay), (bx, by) in zip(xy, xy[1:]):
                if not any((int(px // c) + dx, int(py // c) + dy) in cellules
                           for px, py in ((ax, ay), (bx, by), ((ax + bx) / 2, (ay + by) / 2))
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                    continue
                n = max(1, int(math.hypot(bx - ax, by - ay) // 8))
                t = np.linspace(0, 1, n + 1)
                pts_x.append(ax + t * (bx - ax))
                pts_y.append(ay + t * (by - ay))
        if not pts_x:
            return [False] * len(s_liste)
        X, Y = np.concatenate(pts_x), np.concatenate(pts_y)
        resultat = []
        for s in s_liste:
            x, y = self.point_trace(s)
            resultat.append(bool(np.min(np.hypot(X - x, Y - y)) <= tol))
        return resultat

    # -- points d'intérêt automatiques -------------------------------------------------

    def pois(self) -> list[PointInteret]:
        resultat = []
        for n, tags in self.reseau.tags_noeuds.items():
            if tags.get("railway") == "level_crossing":
                type_, texte, tol = "passage_niveau", "PASSAGE À NIVEAU", self.o["tolerance_m"]
            elif tags.get("amenity") == "fuel":
                nom = tags.get("name") or tags.get("brand") or ""
                type_, texte, tol = "ravitaillement", f"STATION {nom}".strip(), 60.0
            elif tags.get("highway") == "stop":
                type_, texte, tol = "stop", "STOP", 6.0
            else:
                continue
            lat, lon = self.reseau.coord(n)
            if self.index.passages(lat, lon, tol):
                resultat.append(PointInteret(lat, lon, type_, texte, source=f"OSM:{n}"))
        return resultat


def integrer_osm(tr: TraceEchantillonnee, manoeuvres_trace: list[Manoeuvre], reseau: Reseau,
                 cfg: dict) -> tuple[list[Manoeuvre], list[PointInteret], list[str]]:
    """Remplace les virages « géométriques » par les carrefours OSM là où il y a des routes."""
    analyse = AnalyseOSM(tr, reseau, cfg)
    osm, traverses, remarques = analyse.manoeuvres()
    distance = max(40.0, cfg["calcul"]["fusion_virages_m"])
    positions = sorted([m.s for m in osm] + traverses)
    restantes = []
    candidates = []
    for m in manoeuvres_trace:
        k = np.searchsorted(positions, m.s)
        voisins = positions[max(0, k - 1) : k + 1]
        if any(abs(v - m.s) <= distance for v in voisins):
            continue  # carrefour OSM traité (case ou route évidente)
        candidates.append(m)
    if candidates and not cfg["osm"]["virages_hors_carrefour"]:
        sur_route = analyse.sur_route([m.s for m in candidates])
        for m, route in zip(candidates, sur_route):
            if route and m.type != "demi_tour":
                continue
            if not route:
                m.remarques.append("hors réseau OSM : virage déduit de la trace")
            restantes.append(m)
    else:
        restantes = candidates
    pois = analyse.pois() if cfg["osm"]["poi_auto"] else []
    if not osm and not traverses:
        remarques.append("aucun carrefour OSM trouvé sur la trace (réseau absent ou trace hors route)")
    else:
        remarques.append(f"{len(osm)} carrefour(s) OSM retenu(s) sur {len(traverses)} noeud(s) traversé(s)")
    return sorted(osm + restantes, key=lambda m: m.s), pois, remarques
