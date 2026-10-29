"""Détection des virages et rond-points, puis génération des instructions.

Principe (tout est paramétrable dans la section ``calcul`` de la config) :

1. La trace est rééchantillonnée à pas constant et son cap est lissé.
2. **Rond-points** : un anneau est un tronçon parcouru dans le sens de
   circulation (vers la gauche quand on roule à droite), de faible rayon,
   encadré par une déflexion de sens opposé à l'entrée et à la sortie.
3. **Virages** : la variation de cap est mesurée sur une fenêtre glissante
   (``fenetre_virage_m``) ; les zones où elle dépasse le seuil sont des
   candidats. L'angle retenu est la différence entre le cap moyen *stable*
   avant et après la zone (``stabilite_m``), ce qui élimine le bruit GPS.
4. Les virages de même sens trop proches sont fusionnés ; deux petits
   virages opposés qui s'annulent (décalage latéral) sont supprimés.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import libelles
from .geometry import (
    TraceEchantillonnee,
    caps_echantillons,
    distance_cumulee,
    moyenne_glissante,
    projeter_sur_trace,
    reechantillonner,
)
from .poi import PointInteret

TYPES_MANOEUVRE = ("virage", "rond_point", "demi_tour")


@dataclass
class Manoeuvre:
    type: str  # virage | rond_point | demi_tour
    s: float  # position retenue (m depuis le début de l'étape)
    angle: float  # changement de cap net, + = à droite
    s_debut: float
    s_fin: float
    rayon_m: float | None = None
    arc_anneau_deg: float | None = None  # rond-points : angle parcouru sur l'anneau
    # bornes des fenêtres de mesure (manœuvres voisines)
    lim_avant: float = -math.inf
    lim_apres: float = math.inf
    remarques: list[str] = field(default_factory=list)


@dataclass
class Instruction:
    numero: int
    etape: str
    type: str  # depart | virage | rond_point | demi_tour | poi | rappel | arrivee
    s_m: float  # position dans l'étape (m)
    km_total: float  # valeur du compteur TC
    km_partiel: float  # depuis l'instruction précédente
    km_suivante: float | None  # jusqu'à l'instruction suivante
    description: str
    angle: float | None = None
    classe: str | None = None
    cap_sortie: float | None = None
    notes: list[str] = field(default_factory=list)
    pois: list[PointInteret] = field(default_factory=list)
    lat: float = 0.0
    lon: float = 0.0
    ele: float | None = None
    pente_pct: float | None = None
    remarques: list[str] = field(default_factory=list)  # pour le rapport

    @property
    def est_controle(self) -> bool:
        return any(p.type == "controle" for p in self.pois)

    @property
    def niveau_danger(self) -> int:
        return max((p.niveau for p in self.pois if p.type == "danger"), default=0)


# --------------------------------------------------------------------------
# Détection
# --------------------------------------------------------------------------


class _Caps:
    """Cap brut et lissé de la trace, avec quelques mesures utilitaires."""

    def __init__(self, tr: TraceEchantillonnee, cal: dict):
        self.tr = tr
        self.pas = cal["pas_reechantillonnage_m"]
        self.H, self.sm = caps_echantillons(tr)
        n_lissage = max(1, round(cal["lissage_m"] / self.pas))
        self.Hs = moyenne_glissante(self.H, n_lissage)

    def moyen(self, s1: float, s2: float) -> float:
        # fenêtre d'au moins 3 pas : un seul segment est trop sensible au bruit GPS
        if s2 - s1 < 3 * self.pas:
            centre = (s1 + s2) / 2
            s1, s2 = centre - 1.5 * self.pas, centre + 1.5 * self.pas
        masque = (self.sm >= s1) & (self.sm <= s2)
        if not masque.any():
            return float(self.H[int(np.argmin(np.abs(self.sm - (s1 + s2) / 2)))])
        return float(self.H[masque].mean())

    def angle_net(self, s_a: float, s_b: float, stabilite: float,
                  lim_avant: float = -math.inf, lim_apres: float = math.inf) -> float:
        """Cap moyen après la zone moins cap moyen avant, fenêtres bornées par les voisins."""
        return (self.moyen(s_b, min(s_b + stabilite, max(lim_apres, s_b)))
                - self.moyen(max(s_a - stabilite, min(lim_avant, s_a)), s_a))

    def mi_virage(self, s_a: float, s_b: float, angle: float) -> tuple[float, float]:
        """Abscisse où la moitié du changement de cap est atteinte, et rayon estimé."""
        masque = (self.sm >= s_a) & (self.sm <= s_b)
        if masque.sum() < 2 or angle == 0:
            return (s_a + s_b) / 2, float("inf")
        s = self.sm[masque]
        progres = (self.Hs[masque] - self.Hs[masque][0]) / angle
        def franchit(f):
            k = int(np.argmax(progres >= f)) if (progres >= f).any() else len(s) - 1
            return float(s[k])
        s10, s50, s90 = franchit(0.1), franchit(0.5), franchit(0.9)
        rayon = max(s90 - s10, self.pas) / math.radians(0.8 * abs(angle))
        return s50, rayon


def _plages(masque: np.ndarray, trou_max: int = 0) -> list[tuple[int, int]]:
    """Plages [début, fin] d'indices vrais, en tolérant ``trou_max`` faux isolés."""
    plages: list[tuple[int, int]] = []
    i, n = 0, len(masque)
    while i < n:
        if not masque[i]:
            i += 1
            continue
        j = i
        while True:
            k = j + 1
            while k < n and not masque[k] and k - j - 1 < trou_max:
                k += 1
            if k < n and masque[k]:
                j = k
            else:
                break
        plages.append((i, j))
        i = j + 1
    return plages


def _rond_points(c: _Caps, cal: dict) -> list[Manoeuvre]:
    rp = cal["rond_point"]
    if not rp["actif"]:
        return []
    circ = -1.0 if cal["sens_circulation"] == "droite" else 1.0
    pas = c.pas
    inc = np.diff(c.Hs)  # inc[k] situé en tr.s[k + 1]
    if len(inc) < 3:
        return []
    k_min = math.degrees(pas / rp["rayon_max_m"])
    na = max(1, round(rp["approche_m"] / pas))
    trouves: list[Manoeuvre] = []
    for a, b in _plages(inc * circ >= k_min, trou_max=1):
        arc = circ * float(inc[a : b + 1].sum())
        longueur = (b - a + 1) * pas
        if arc < rp["arc_min_deg"] or longueur / math.radians(arc) > rp["rayon_max_m"]:
            continue
        # déflexion nette (sens opposé à la circulation) avant et après l'anneau
        avant = -circ * (c.Hs[a] - c.Hs[max(0, a - na)])
        apres = -circ * (c.Hs[min(len(c.Hs) - 1, b + 1 + na)] - c.Hs[b + 1])
        if avant < rp["deflexion_min_deg"] or apres < rp["deflexion_min_deg"]:
            continue
        s_anneau_debut = float(c.tr.s[a + 1])
        s_debut = max(0.0, s_anneau_debut - rp["approche_m"])
        s_fin = min(c.tr.longueur, float(c.tr.s[b + 1]) + rp["approche_m"])
        angle = c.angle_net(s_debut, s_fin, cal["stabilite_m"])
        trouves.append(
            Manoeuvre(
                "rond_point", s_anneau_debut, angle, s_debut, s_fin,
                rayon_m=longueur / math.radians(arc), arc_anneau_deg=arc,
            )
        )
    return trouves


def _virages(c: _Caps, cal: dict, zones_exclues: list[tuple[float, float]]) -> list[Manoeuvre]:
    pas = c.pas
    w = max(1, round(cal["fenetre_virage_m"] / (2 * pas)))
    n = len(c.Hs)
    if n <= 2 * w + 1:
        return []
    D = np.zeros(n)
    D[w : n - w] = c.Hs[2 * w :] - c.Hs[: n - 2 * w]
    seuil = cal["seuil_virage_deg"]
    # zones où la variation de cap dépasse le seuil : [début, fin] en indices de cap
    zones = []
    for signe in (1, -1):
        for i0, i1 in _plages(D * signe >= seuil):
            zones.append([max(0, i0 - w), min(n - 1, i1 + w), i0, i1])
    zones.sort()

    def hors_rond_point(z):
        s_a, s_b = float(c.sm[z[0]]), float(c.sm[z[1]])
        return not any(s_a < fin and s_b > debut for debut, fin in zones_exclues)

    # 1re passe, fenêtres libres : on écarte le bruit (angle net négligeable)
    zones = [z for z in zones if hors_rond_point(z)
             and abs(c.angle_net(float(c.sm[z[0]]), float(c.sm[z[1]]), cal["stabilite_m"])) >= seuil / 2]
    # deux zones qui se chevauchent (virages enchaînés) sont coupées entre leurs cœurs
    for z, y in zip(zones, zones[1:]):
        if z[1] > y[0]:
            milieu = (z[3] + y[2]) // 2
            z[1], y[0] = milieu, milieu
    # 2e passe : fenêtres de mesure bornées par les virages voisins
    candidats: list[Manoeuvre] = []
    for k, (a, b, _, _) in enumerate(zones):
        lim_avant = float(c.sm[zones[k - 1][1]]) if k > 0 else -math.inf
        lim_apres = float(c.sm[zones[k + 1][0]]) if k + 1 < len(zones) else math.inf
        candidats.append(_mesurer(c, cal, float(c.sm[a]), float(c.sm[b]), lim_avant, lim_apres))
    return candidats


def _mesurer(c: _Caps, cal: dict, s_a: float, s_b: float,
             lim_avant: float = -math.inf, lim_apres: float = math.inf) -> Manoeuvre:
    angle = c.angle_net(s_a, s_b, cal["stabilite_m"], lim_avant, lim_apres)
    s_mid, rayon = c.mi_virage(s_a, s_b, angle)
    # on se cale sur le point GPX d'origine le plus proche du milieu du virage
    so = c.tr.s_originaux
    k = int(np.argmin(np.abs(so - s_mid)))
    if abs(so[k] - s_mid) <= 2 * c.pas:
        s_mid = float(so[k])
    type_ = "demi_tour" if abs(angle) >= cal["demi_tour_deg"] else "virage"
    return Manoeuvre(type_, s_mid, angle, s_a, s_b, rayon_m=rayon, lim_avant=lim_avant, lim_apres=lim_apres)


def _fusionner(c: _Caps, cal: dict, virages: list[Manoeuvre], remarques: list[str]) -> list[Manoeuvre]:
    seuil, dist = cal["seuil_virage_deg"], cal["fusion_virages_m"]
    resultat: list[Manoeuvre] = []
    for m in virages:
        if resultat:
            p = resultat[-1]
            proches = m.s_debut - p.s_fin <= dist or m.s - p.s <= dist
            if proches and math.copysign(1, m.angle) == math.copysign(1, p.angle):
                resultat[-1] = _mesurer(c, cal, p.s_debut, max(p.s_fin, m.s_fin), p.lim_avant, m.lim_apres)
                continue
            # petit décalage latéral (gauche-droite qui s'annulent) : pas une direction à prendre
            if proches and abs(p.angle + m.angle) < seuil and max(abs(p.angle), abs(m.angle)) <= 45:
                remarques.append(
                    f"décalage latéral ignoré à {p.s / 1000:.2f} km ({p.angle:+.0f}° puis {m.angle:+.0f}°)"
                )
                resultat.pop()
                continue
        resultat.append(m)
    return [m for m in resultat if abs(m.angle) >= seuil]


def detecter_manoeuvres(tr: TraceEchantillonnee, cal: dict) -> tuple[list[Manoeuvre], list[str]]:
    """Retourne les manœuvres triées par position et des remarques pour le rapport."""
    remarques: list[str] = []
    c = _Caps(tr, cal)
    rps = _rond_points(c, cal)
    zones = [(m.s_debut, m.s_fin) for m in rps]
    virages = _fusionner(c, cal, _virages(c, cal, zones), remarques)
    for v in virages:
        if abs(abs(v.angle) - cal["seuil_virage_deg"]) < 5:
            v.remarques.append(f"angle {v.angle:+.0f}° proche du seuil de détection")
        if v.rayon_m is not None and v.rayon_m > 80:
            v.remarques.append(f"courbe large (rayon ≈ {v.rayon_m:.0f} m) : carrefour réel ?")
    for r in rps:
        r.remarques.append("n° de sortie non déterminable sans carte : à préciser si besoin")
    tout = sorted(rps + virages, key=lambda m: m.s)
    for a, b in zip(tout, tout[1:]):
        if b.s - a.s < 2 * cal["fusion_virages_m"]:
            b.remarques.append(f"à {b.s - a.s:.0f} m seulement de la manœuvre précédente")
    return tout, remarques


def classe_angle(angle: float, tranches: list[float]) -> str:
    a = abs(angle)
    for borne, nom in zip(tranches, libelles.CLASSES):
        if a <= borne:
            return nom
    return libelles.CLASSES[-1]


# --------------------------------------------------------------------------
# Rattachement des points d'intérêt
# --------------------------------------------------------------------------


@dataclass
class Etape:
    nom: str
    trace: TraceEchantillonnee
    manoeuvres: list[Manoeuvre]
    pois: list[PointInteret] = field(default_factory=list)
    remarques: list[str] = field(default_factory=list)


def rattacher_pois(etapes: list[Etape], pois: list[PointInteret], cal: dict) -> list[str]:
    """Place chaque POI sur une étape (abscisse ``s_m``). Retourne des avertissements."""
    avert: list[str] = []
    tol = cal["poi_tolerance_m"]
    par_nom = {e.nom: e for e in etapes}
    for p in pois:
        nom = p.description or p.code or p.source
        if not p.description and p.type not in ("depart", "arrivee"):
            avert.append(f"POI {p.source} ({libelles.TYPES_POI[p.type]}) sans description")
        if p.km is not None:
            etape = par_nom.get(p.etape) if p.etape else (etapes[0] if len(etapes) == 1 else None)
            if etape is None:
                avert.append(f"POI « {nom} » : km fourni sans étape valide (colonne etape), ignoré")
                continue
            p.s_m = p.km * 1000.0
            if not 0 <= p.s_m <= etape.trace.longueur:
                avert.append(f"POI « {nom} » : km {p.km} hors de l'étape « {etape.nom} », ignoré")
                continue
            etape.pois.append(p)
            continue
        meilleurs: list[tuple[float, Etape, list]] = []
        for e in etapes:
            if p.etape and e.nom != p.etape:
                continue
            cands = projeter_sur_trace(p.lat, p.lon, e.trace, tol)
            if cands:
                meilleurs.append((min(c[1] for c in cands), e, cands))
        if not meilleurs:
            avert.append(f"POI « {nom} » à plus de {tol:.0f} m de la trace, ignoré")
            continue
        _, etape, cands = min(meilleurs, key=lambda t: t[0])
        if len(cands) > 1:
            kms = ", ".join(f"{c[0] / 1000:.2f}" for c in cands)
            avert.append(
                f"POI « {nom} » : la trace passe plusieurs fois à proximité (km {kms}) ;"
                " premier passage retenu (préciser la colonne km pour choisir)"
            )
        p.s_m, p.ecart_m = cands[0]
        etape.pois.append(p)
    return avert


# --------------------------------------------------------------------------
# Génération des instructions
# --------------------------------------------------------------------------


def _description_manoeuvre(m: Manoeuvre, cal: dict, style: str) -> tuple[str, str | None]:
    if m.type == "rond_point":
        return libelles.texte_rond_point(m.angle, style), None
    if m.type == "demi_tour":
        return libelles.texte_demi_tour(style), None
    classe = classe_angle(m.angle, cal["tranches_angle_deg"])
    return libelles.texte_virage(classe, 1 if m.angle > 0 else -1, style), classe


def generer_instructions(etapes: list[Etape], cfg: dict) -> list[Instruction]:
    cal, aff = cfg["calcul"], cfg["affichage"]
    style = aff["textes"]
    resultat: list[Instruction] = []
    decalage_km = 0.0
    numero = 0
    for etape in etapes:
        tr = etape.trace
        if aff["numerotation"] == "etape":
            numero = 0
        # 1. lignes brutes : (s, type, manoeuvre|None)
        lignes: list[dict] = []
        if aff["depart_arrivee"]:
            lignes.append({"s": 0.0, "type": "depart", "m": None})
        for m in etape.manoeuvres:
            lignes.append({"s": m.s, "type": m.type, "m": m})
        if aff["depart_arrivee"]:
            lignes.append({"s": tr.longueur, "type": "arrivee", "m": None})
        for l in lignes:
            l["pois"] = []

        # 2. POI : rattachés à la ligne la plus proche ou nouvelle ligne
        for p in sorted(etape.pois, key=lambda p: p.s_m):
            proche = min(lignes, key=lambda l: abs(l["s"] - p.s_m), default=None)
            cible_type = {"depart": "depart", "arrivee": "arrivee"}.get(p.type)
            if cible_type:
                proche = next((l for l in lignes if l["type"] == cible_type), proche)
            if proche is not None and (cible_type or abs(proche["s"] - p.s_m) <= cal["poi_fusion_m"]):
                proche["pois"].append(p)
            else:
                lignes.append({"s": p.s_m, "type": "poi", "m": None, "pois": [p]})
        lignes.sort(key=lambda l: (l["s"], l["type"] != "depart"))

        # 3. rappels « TD » sur les longues lignes droites
        if cal["rappel_km"] and cal["rappel_km"] > 0:
            pas_r = cal["rappel_km"] * 1000.0
            ajouts = []
            for a, b in zip(lignes, lignes[1:]):
                k = 1
                while b["s"] - (a["s"] + k * pas_r) > pas_r / 4:
                    ajouts.append({"s": a["s"] + k * pas_r, "type": "rappel", "m": None, "pois": []})
                    k += 1
            lignes = sorted(lignes + ajouts, key=lambda l: (l["s"], l["type"] != "depart"))

        # 4. instructions
        precedente_s = 0.0
        instructions_etape: list[Instruction] = []
        for l in lignes:
            m: Manoeuvre | None = l["m"]
            classe = None
            if m is not None:
                description, classe = _description_manoeuvre(m, cal, style)
                fin_manoeuvre = m.s_fin
            else:
                if l["type"] in libelles.TEXTES_FIXES:
                    abr, complet = libelles.TEXTES_FIXES[l["type"]]
                    description = abr if style == "abrege" else complet
                else:
                    description = libelles.texte_tout_droit(style)
                fin_manoeuvre = l["s"]
            cap = None
            if l["type"] != "arrivee":
                cap = tr.cap_entre(fin_manoeuvre, fin_manoeuvre + cal["cap_distance_m"])
            lat, lon = tr.position(l["s"])
            ele = tr.altitude(l["s"])
            pente = None
            if ele is not None and l["s"] - precedente_s > 50:
                pente = 100.0 * (ele - tr.altitude(precedente_s)) / (l["s"] - precedente_s)
            numero += aff["numerotation_pas"]
            instr = Instruction(
                numero=numero,
                etape=etape.nom,
                type=l["type"],
                s_m=l["s"],
                km_total=decalage_km + l["s"] / 1000.0,
                km_partiel=(l["s"] - precedente_s) / 1000.0,
                km_suivante=None,
                description=description,
                angle=m.angle if m else None,
                classe=classe,
                cap_sortie=cap,
                notes=[p.description for p in l["pois"] if p.description],
                pois=l["pois"],
                lat=lat,
                lon=lon,
                ele=ele,
                pente_pct=pente,
                remarques=list(m.remarques) if m else [],
            )
            if pente is not None and abs(pente) >= cal["seuil_pente_pct"] and aff["afficher_pente"]:
                instr.notes.append(f"PENTE {pente:+.0f} %")
            instructions_etape.append(instr)
            precedente_s = l["s"]
        for a, b in zip(instructions_etape, instructions_etape[1:]):
            a.km_suivante = b.km_partiel
        resultat.extend(instructions_etape)
        if aff["remise_a_zero"] == "epreuve":
            decalage_km += tr.longueur / 1000.0
    return resultat


def analyser(traces, pois: list[PointInteret], cfg: dict) -> tuple[list[Etape], list[Instruction], list[str]]:
    """Chaîne complète : traces brutes -> étapes détectées -> instructions."""
    cal = cfg["calcul"]
    avert: list[str] = []
    etapes: list[Etape] = []
    for t in traces:
        tr = reechantillonner(t.lat, t.lon, t.ele, cal["pas_reechantillonnage_m"])
        manoeuvres, remarques = detecter_manoeuvres(tr, cal)
        etapes.append(Etape(t.nom, tr, manoeuvres, remarques=remarques))
        # trace bruitée : la longueur brute dépasse nettement la longueur lissée
        lisse = moyenne_glissante(tr.lat, 5), moyenne_glissante(tr.lon, 5)
        l_lisse = distance_cumulee(*lisse)[-1]
        if l_lisse > 0 and tr.longueur / l_lisse > 1.02:
            avert.append(
                f"Étape « {t.nom} » : trace bruitée (longueur brute {100 * (tr.longueur / l_lisse - 1):.1f} %"
                " au-dessus de la longueur lissée) ; le compteur peut dériver par rapport au trip"
            )
    avert += rattacher_pois(etapes, pois, cal)
    instructions = generer_instructions(etapes, cfg)
    return etapes, instructions, avert
