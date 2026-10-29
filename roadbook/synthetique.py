"""Construction de traces synthétiques (tests et exemples).

Une « tortue » avance dans un plan local en mètres puis convertit le tracé
en latitude/longitude autour d'une origine.
"""

from __future__ import annotations

import math

import numpy as np

from .geometry import depuis_plan_local


class Tortue:
    def __init__(self, cap_deg: float = 0.0, pas_m: float = 8.0):
        self.x, self.y, self.cap = 0.0, 0.0, cap_deg
        self.pas = pas_m
        self.points: list[tuple[float, float]] = [(0.0, 0.0)]

    def _avance(self, d: float) -> None:
        r = math.radians(self.cap)
        self.x += d * math.sin(r)
        self.y += d * math.cos(r)
        self.points.append((self.x, self.y))

    def droit(self, longueur: float) -> "Tortue":
        n = max(1, round(longueur / self.pas))
        for _ in range(n):
            self._avance(longueur / n)
        return self

    def arc(self, rayon: float, angle: float, pas_m: float | None = None) -> "Tortue":
        """Arc de cercle ; angle > 0 = à droite."""
        if angle == 0:
            return self
        longueur = rayon * math.radians(abs(angle))
        n = max(2, math.ceil(longueur / (pas_m or min(self.pas, 3.0))))
        # chaque pas est une corde : demi-rotation, avance, demi-rotation
        da = angle / n
        corde = 2 * rayon * math.sin(math.radians(abs(da)) / 2)
        for _ in range(n):
            self.cap += da / 2
            self._avance(corde)
            self.cap += da / 2
        return self

    def coin(self, angle: float) -> "Tortue":
        """Virage net (sommet unique)."""
        self.cap += angle
        return self

    def rond_point(self, rayon: float, sortie_deg: float, deflexion: float = 70.0,
                   sens: str = "droite") -> "Tortue":
        """Traversée de rond-point. ``sortie_deg`` = changement de cap net (+ droite).

        Circulation antihoraire si ``sens == "droite"`` : déflexion à droite
        en entrée, anneau parcouru vers la gauche, déflexion à droite en sortie.
        """
        s = 1 if sens == "droite" else -1
        anneau = 2 * deflexion - s * sortie_deg
        while anneau <= 10:
            anneau += 360
        self.arc(10, s * deflexion)
        self.arc(rayon, -s * anneau)
        self.arc(10, s * deflexion)
        return self

    def latlon(self, lat0: float, lon0: float, bruit_m: float = 0.0, graine: int = 0):
        xy = np.array(self.points)
        if bruit_m > 0:
            rng = np.random.default_rng(graine)
            xy = xy + rng.normal(0, bruit_m, xy.shape)
        lat, lon = depuis_plan_local(xy[:, 0], xy[:, 1], lat0, lon0)
        return lat, lon


def ecrire_gpx(chemin, etapes, waypoints=()) -> None:
    """etapes : liste de (nom, lat, lon, ele|None) ; waypoints : (nom, lat, lon, desc, type)."""
    import gpxpy.gpx

    gpx = gpxpy.gpx.GPX()
    gpx.creator = "roadbook (exemple synthétique)"
    for nom, lat, lon, ele in etapes:
        trk = gpxpy.gpx.GPXTrack(name=nom)
        seg = gpxpy.gpx.GPXTrackSegment()
        for i in range(len(lat)):
            seg.points.append(gpxpy.gpx.GPXTrackPoint(
                round(float(lat[i]), 7), round(float(lon[i]), 7),
                elevation=None if ele is None else round(float(ele[i]), 1)))
        trk.segments.append(seg)
        gpx.tracks.append(trk)
    for nom, lat, lon, desc, typ in waypoints:
        w = gpxpy.gpx.GPXWaypoint(round(lat, 7), round(lon, 7), name=nom, description=desc or None)
        w.type = typ
        gpx.waypoints.append(w)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(gpx.to_xml())
