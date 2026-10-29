"""Lecture et nettoyage d'un fichier GPX."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import gpxpy
import gpxpy.gpx
import numpy as np

from .geometry import segments
from .poi import PointInteret, depuis_waypoint


@dataclass
class TraceBrute:
    nom: str
    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray | None  # None si l'altitude manque sur une partie des points


@dataclass
class DonneesGPX:
    traces: list[TraceBrute]
    waypoints: list[PointInteret]
    avertissements: list[str] = field(default_factory=list)


def _points_vers_tableaux(points) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    lat = np.array([p.latitude for p in points], dtype=float)
    lon = np.array([p.longitude for p in points], dtype=float)
    eles = [p.elevation for p in points]
    ele = None if any(e is None for e in eles) else np.array(eles, dtype=float)
    return lat, lon, ele


def nettoyer(lat, lon, ele, doublon_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, int]:
    """Supprime les doublons consécutifs (points plus proches que ``doublon_m``)."""
    garder = np.ones(len(lat), dtype=bool)
    if len(lat) >= 2:
        _, dist = segments(lat, lon)
        dernier = 0
        # un point est un doublon s'il est trop proche du dernier point *gardé*
        for i in range(1, len(lat)):
            d = dist[i - 1] if dernier == i - 1 else segments(lat[[dernier, i]], lon[[dernier, i]])[1][0]
            if d < doublon_m:
                garder[i] = False
            else:
                dernier = i
        # on garde toujours le dernier point (fin exacte de la trace)
        if not garder[-1]:
            garder[dernier] = False
            garder[-1] = True
    retires = int((~garder).sum())
    return lat[garder], lon[garder], (ele[garder] if ele is not None else None), retires


def charger_gpx(chemin: str | Path, cfg: dict) -> DonneesGPX:
    with open(chemin, encoding="utf-8") as f:
        try:
            gpx = gpxpy.parse(f)
        except gpxpy.gpx.GPXException as exc:
            raise ValueError(f"{Path(chemin).name} : fichier GPX illisible ({exc})") from exc
    cal = cfg["calcul"]
    avert: list[str] = []
    brutes: list[tuple[str, list]] = []

    for i, trk in enumerate(gpx.tracks, start=1):
        segs = [seg.points for seg in trk.segments if seg.points]
        if not segs:
            continue
        points = []
        for j, seg in enumerate(segs):
            if points:
                _, d = segments(
                    np.array([points[-1].latitude, seg[0].latitude]),
                    np.array([points[-1].longitude, seg[0].longitude]),
                )
                if d[0] > cal["saut_max_m"]:
                    avert.append(
                        f"Trace « {trk.name or i} » : {d[0] / 1000:.2f} km entre les segments {j} et {j + 1}"
                        " (relié en ligne droite)"
                    )
            points.extend(seg)
        brutes.append((trk.name or f"Étape {i}", points))

    if not brutes:
        for i, rte in enumerate(gpx.routes, start=1):
            if rte.points:
                brutes.append((rte.name or f"Étape {i}", rte.points))
    elif gpx.routes:
        avert.append(f"{len(gpx.routes)} route(s) <rte> ignorée(s) : le fichier contient déjà des traces <trk>")

    if not brutes:
        raise ValueError(f"{chemin} : aucune trace ni route exploitable")

    traces: list[TraceBrute] = []
    for nom, points in brutes:
        lat, lon, ele = _points_vers_tableaux(points)
        if ele is None and any(p.elevation is not None for p in points):
            avert.append(f"Trace « {nom} » : altitude manquante sur une partie des points, ignorée")
        lat, lon, ele, retires = nettoyer(lat, lon, ele, cal["doublon_m"])
        if retires:
            avert.append(f"Trace « {nom} » : {retires} point(s) en doublon supprimé(s)")
        if len(lat) < 2:
            avert.append(f"Trace « {nom} » : moins de 2 points, ignorée")
            continue
        _, dist = segments(lat, lon)
        sauts = int((dist > cal["saut_max_m"]).sum())
        if sauts:
            avert.append(
                f"Trace « {nom} » : {sauts} saut(s) de plus de {cal['saut_max_m']:.0f} m entre deux points"
                " (trace incomplète ?)"
            )
        traces.append(TraceBrute(nom, lat, lon, ele))

    if cfg["epreuve"]["decoupage_etapes"] == "unique" and len(traces) > 1:
        ele = None if any(t.ele is None for t in traces) else np.concatenate([t.ele for t in traces])
        traces = [
            TraceBrute(
                cfg["epreuve"]["nom"],
                np.concatenate([t.lat for t in traces]),
                np.concatenate([t.lon for t in traces]),
                ele,
            )
        ]

    noms = cfg["epreuve"].get("noms_etapes") or []
    for t, nom in zip(traces, noms):
        t.nom = nom

    waypoints = [
        depuis_waypoint(w.name or "", w.latitude, w.longitude, w.description or w.comment or "", w.type, w.symbol)
        for w in gpx.waypoints
    ]
    return DonneesGPX(traces, waypoints, avert)
