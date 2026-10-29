"""Outils de test : itinéraire le plus court sur un réseau OSM, trace GPS simulée."""

import heapq
import math

import numpy as np

from roadbook.geometry import depuis_plan_local, vers_plan_local


def graphe(reseau):
    aretes = {}
    for v in reseau.voies:
        for a, b in zip(v.noeuds, v.noeuds[1:]):
            la, lo = reseau.coord(a)
            lb, lob = reseau.coord(b)
            x, y = vers_plan_local(lb, lob, la, lo)
            d = float(math.hypot(x, y))
            if v.sens_unique in (0, 1):
                aretes.setdefault(a, []).append((b, d))
            if v.sens_unique in (0, -1):
                aretes.setdefault(b, []).append((a, d))
    return aretes


def plus_court_chemin(reseau, depart, arrivee, passage=None):
    aretes = graphe(reseau)

    def dijkstra(a, b):
        dist, prec, file = {a: 0.0}, {}, [(0.0, a)]
        while file:
            d, n = heapq.heappop(file)
            if n == b:
                break
            if d > dist[n]:
                continue
            for m, l in aretes.get(n, ()):
                if d + l < dist.get(m, math.inf):
                    dist[m], prec[m] = d + l, n
                    heapq.heappush(file, (d + l, m))
        chemin = [b]
        while chemin[-1] != a:
            chemin.append(prec[chemin[-1]])
        return chemin[::-1]

    if passage is None:
        return dijkstra(depart, arrivee)
    return dijkstra(depart, passage)[:-1] + dijkstra(passage, arrivee)


def trace_simulee(reseau, chemin, pas_m=8.0, bruit_m=1.5, graine=0):
    """Points tous les ``pas_m`` le long du chemin, avec bruit GPS gaussien."""
    lat0, lon0 = reseau.coord(chemin[0])
    pts = np.array([vers_plan_local(*reseau.coord(n), lat0, lon0) for n in chemin], dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    cibles = np.arange(0, s[-1], pas_m)
    x = np.interp(cibles, s, pts[:, 0])
    y = np.interp(cibles, s, pts[:, 1])
    rng = np.random.default_rng(graine)
    x, y = x + rng.normal(0, bruit_m, len(x)), y + rng.normal(0, bruit_m, len(y))
    return depuis_plan_local(x, y, lat0, lon0)
