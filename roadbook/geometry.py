"""Calculs géographiques : distances géodésiques, caps, rééchantillonnage.

Toutes les distances sont calculées sur l'ellipsoïde WGS84 (pyproj.Geod).
Les caps sont des azimuts en degrés, 0 = nord, sens horaire.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
RAYON_TERRE_M = 6_371_008.8


def segments(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Azimut de départ et longueur (m) de chaque segment [i, i+1]."""
    if len(lat) < 2:
        return np.zeros(0), np.zeros(0)
    az, _, dist = GEOD.inv(lon[:-1], lat[:-1], lon[1:], lat[1:])
    return np.asarray(az, dtype=float) % 360.0, np.asarray(dist, dtype=float)


def distance_cumulee(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Distance cumulée (m) depuis le premier point."""
    _, dist = segments(lat, lon)
    return np.concatenate([[0.0], np.cumsum(dist)])


def diff_cap(a, b):
    """Variation de cap de a vers b, ramenée dans ]-180, 180] (positif = à droite)."""
    d = (np.asarray(b, dtype=float) - np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0
    return np.where(d == -180.0, 180.0, d)


def deroule_cap(caps: np.ndarray) -> np.ndarray:
    """Supprime les sauts 359° -> 0° pour pouvoir lisser et soustraire."""
    if len(caps) == 0:
        return caps
    return np.degrees(np.unwrap(np.radians(caps)))


def moyenne_glissante(valeurs: np.ndarray, n: int) -> np.ndarray:
    """Moyenne glissante centrée sur n points ; les bords sont prolongés."""
    if n <= 1 or len(valeurs) < 2:
        return valeurs.copy()
    n = min(n, len(valeurs))
    gauche = n // 2
    droite = n - 1 - gauche
    etendu = np.concatenate([np.full(gauche, valeurs[0]), valeurs, np.full(droite, valeurs[-1])])
    noyau = np.ones(n) / n
    return np.convolve(etendu, noyau, mode="valid")


@dataclass
class TraceEchantillonnee:
    """Trace rééchantillonnée à pas constant (pour les calculs)."""

    s: np.ndarray  # distance cumulée (m) de chaque point
    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray | None
    s_originaux: np.ndarray  # distance cumulée des points GPX d'origine
    lat_originaux: np.ndarray
    lon_originaux: np.ndarray

    @property
    def longueur(self) -> float:
        return float(self.s[-1]) if len(self.s) else 0.0

    def position(self, s: float) -> tuple[float, float]:
        return float(np.interp(s, self.s, self.lat)), float(np.interp(s, self.s, self.lon))

    def altitude(self, s: float) -> float | None:
        if self.ele is None:
            return None
        return float(np.interp(s, self.s, self.ele))

    def cap_entre(self, s1: float, s2: float) -> float:
        """Azimut de la corde entre deux abscisses curvilignes."""
        s1, s2 = max(0.0, s1), min(self.longueur, s2)
        if s2 - s1 < 1e-6:
            s1 = max(0.0, s2 - 1.0)
        la1, lo1 = self.position(s1)
        la2, lo2 = self.position(s2)
        az, _, _ = GEOD.inv(lo1, la1, lo2, la2)
        return float(az) % 360.0


def reechantillonner(
    lat: np.ndarray, lon: np.ndarray, ele: np.ndarray | None, pas_m: float
) -> TraceEchantillonnee:
    """Points espacés de ``pas_m`` le long de la trace (géodésique entre deux points GPX).

    Le dernier point de la trace est toujours conservé. Les points d'origine
    sont gardés à part (``s_originaux``) pour positionner finement les virages.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    az, dist = segments(lat, lon)
    s_orig = np.concatenate([[0.0], np.cumsum(dist)])
    total = s_orig[-1]
    if total <= 0:
        raise ValueError("trace de longueur nulle")
    cibles = np.arange(0.0, total, pas_m)
    if total - cibles[-1] > 1e-6:
        cibles = np.append(cibles, total)
    # segment contenant chaque cible
    idx = np.clip(np.searchsorted(s_orig, cibles, side="right") - 1, 0, len(dist) - 1)
    reste = cibles - s_orig[idx]
    lon_r, lat_r, _ = GEOD.fwd(lon[idx], lat[idx], az[idx], reste)
    lat_r = np.asarray(lat_r, dtype=float)
    lon_r = np.asarray(lon_r, dtype=float)
    lat_r[-1], lon_r[-1] = lat[-1], lon[-1]
    ele_r = None
    if ele is not None:
        ele_r = np.interp(cibles, s_orig, np.asarray(ele, dtype=float))
    return TraceEchantillonnee(cibles, lat_r, lon_r, ele_r, s_orig, lat, lon)


def caps_echantillons(trace: TraceEchantillonnee) -> tuple[np.ndarray, np.ndarray]:
    """Cap déroulé de chaque segment rééchantillonné, et abscisse de son milieu."""
    az, _ = segments(trace.lat, trace.lon)
    milieux = (trace.s[:-1] + trace.s[1:]) / 2.0
    return deroule_cap(az), milieux


def angles_aux_sommets(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Changement de cap (signé) à chaque point d'origine ; 0 aux extrémités."""
    az, dist = segments(lat, lon)
    angles = np.zeros(len(lat))
    if len(az) >= 2:
        angles[1:-1] = diff_cap(az[:-1], az[1:])
    return angles


def vers_plan_local(lat, lon, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    """Projection équirectangulaire locale (m), suffisante à l'échelle d'une étape."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    x = np.radians(lon - lon0) * RAYON_TERRE_M * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * RAYON_TERRE_M
    return x, y


def depuis_plan_local(x, y, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    lat = lat0 + np.degrees(np.asarray(y, dtype=float) / RAYON_TERRE_M)
    lon = lon0 + np.degrees(np.asarray(x, dtype=float) / (RAYON_TERRE_M * np.cos(np.radians(lat0))))
    return lat, lon


def projeter_sur_trace(
    lat: float, lon: float, trace: TraceEchantillonnee, tolerance_m: float
) -> list[tuple[float, float]]:
    """Projette un point sur la trace.

    Retourne la liste des passages candidats ``(abscisse m, écart m)`` dont
    l'écart est inférieur à la tolérance, triés par abscisse. Une trace qui
    repasse au même endroit (boucle, aller-retour) donne plusieurs candidats.
    """
    x, y = vers_plan_local(trace.lat, trace.lon, lat, lon)
    ax, ay, bx, by = x[:-1], y[:-1], x[1:], y[1:]
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = np.where(l2 > 0, np.clip(-(ax * dx + ay * dy) / np.where(l2 > 0, l2, 1), 0, 1), 0)
    px, py = ax + t * dx, ay + t * dy
    ecart = np.hypot(px, py)
    s_proj = trace.s[:-1] + t * (trace.s[1:] - trace.s[:-1])

    proches = ecart <= tolerance_m
    candidats: list[tuple[float, float]] = []
    # regroupe les segments proches consécutifs : un groupe = un passage
    i = 0
    n = len(ecart)
    while i < n:
        if not proches[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and proches[j + 1]:
            j += 1
        k = i + int(np.argmin(ecart[i : j + 1]))
        candidats.append((float(s_proj[k]), float(ecart[k])))
        i = j + 1
    # deux groupes très proches en abscisse = même passage (trace bruitée)
    fusionnes: list[tuple[float, float]] = []
    for c in candidats:
        if fusionnes and c[0] - fusionnes[-1][0] < 2 * tolerance_m:
            if c[1] < fusionnes[-1][1]:
                fusionnes[-1] = c
        else:
            fusionnes.append(c)
    return fusionnes
