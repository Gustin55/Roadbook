"""Corrections manuelles des cases (saisies dans l'interface ou un fichier projet).

Format (dictionnaire JSON) ::

    {
      "cases": {
        "<identifiant>": {"description": "AG SUR D12", "notes": ["Village"], "supprime": false,
                          "danger": 2, "controle": "CS4"}
      },
      "ajouts": [
        {"etape": "E1", "km": 4.25, "description": "TD", "notes": ["Pont étroit"], "danger": 1}
      ]
    }

L'identifiant d'une case (``identifiant_case``) dépend de son étape, de son
type et de sa position arrondie au mètre : il reste valable quand on change
la mise en page, et le plus souvent après une nouvelle analyse.
"""

from __future__ import annotations

import copy

from .instructions import Etape, Instruction
from .poi import PointInteret


def identifiant_case(i: Instruction) -> str:
    return f"{i.etape}|{i.type}|{round(i.s_m)}"


def _appliquer_marques(instr: Instruction, danger, controle) -> None:
    if danger is not None:
        instr.pois = [p for p in instr.pois if p.type != "danger"]
        if int(danger) > 0:
            instr.pois.append(PointInteret(instr.lat, instr.lon, "danger", "", niveau=int(danger),
                                           source="manuel"))
    if controle is not None:
        instr.pois = [p for p in instr.pois if p.type != "controle"]
        if str(controle).strip():
            instr.pois.append(PointInteret(instr.lat, instr.lon, "controle", "", code=str(controle).strip().upper(),
                                           source="manuel"))


def renumeroter(instructions: list[Instruction], etapes: list[Etape], cfg: dict) -> list[Instruction]:
    """Recalcule numéros, distances partielles et distance à la case suivante."""
    aff = cfg["affichage"]
    ordre = {e.nom: k for k, e in enumerate(etapes)}
    instructions = sorted(instructions, key=lambda i: (ordre.get(i.etape, 0), i.s_m, i.type != "depart"))
    numero = 0
    etape_courante = None
    precedente = None
    for i in instructions:
        if i.etape != etape_courante:
            etape_courante = i.etape
            precedente = None
            if aff["numerotation"] == "etape":
                numero = 0
        numero += aff["numerotation_pas"]
        i.numero = numero
        i.km_partiel = 0.0 if precedente is None else (i.s_m - precedente.s_m) / 1000.0
        if precedente is not None:
            precedente.km_suivante = i.km_partiel
        i.km_suivante = None
        precedente = i
    return instructions


def appliquer(instructions: list[Instruction], etapes: list[Etape], modifs: dict | None,
              cfg: dict) -> tuple[list[Instruction], list[str]]:
    """Retourne une copie corrigée des instructions et la liste des corrections ignorées."""
    if not modifs:
        return instructions, []
    ignorees: list[str] = []
    resultat: list[Instruction] = []
    cases = dict(modifs.get("cases") or {})
    for i in instructions:
        m = cases.pop(identifiant_case(i), None)
        if m is None:
            resultat.append(i)
            continue
        if m.get("supprime"):
            continue
        i = copy.copy(i)
        i.pois = list(i.pois)
        if m.get("description") is not None:
            i.description = str(m["description"])
        if m.get("notes") is not None:
            i.notes = [str(n) for n in m["notes"] if str(n).strip()]
        _appliquer_marques(i, m.get("danger"), m.get("controle"))
        resultat.append(i)
    ignorees += [f"correction de la case {k} : case introuvable (nouvelle analyse ?)" for k in cases]

    par_nom = {e.nom: e for e in etapes}
    decalages = {}
    for i in instructions:
        decalages.setdefault(i.etape, i.km_total - i.s_m / 1000.0)
    for a in modifs.get("ajouts") or []:
        etape = par_nom.get(a.get("etape"))
        try:
            s = float(a.get("km")) * 1000.0
        except (TypeError, ValueError):
            s = -1
        if etape is None or not 0 <= s <= etape.trace.longueur:
            ignorees.append(f"case ajoutée ignorée : étape ou km invalide ({a.get('etape')}, {a.get('km')})")
            continue
        lat, lon = etape.trace.position(s)
        i = Instruction(
            numero=0, etape=etape.nom, type="poi", s_m=s,
            km_total=decalages.get(etape.nom, 0.0) + s / 1000.0, km_partiel=0.0, km_suivante=None,
            description=str(a.get("description") or "TD"),
            notes=[str(n) for n in a.get("notes") or [] if str(n).strip()],
            cap_sortie=etape.trace.cap_entre(s, s + cfg["calcul"]["cap_distance_m"]),
            lat=lat, lon=lon, ele=etape.trace.altitude(s),
        )
        _appliquer_marques(i, a.get("danger"), a.get("controle"))
        i.manuel = True  # case saisie à la main (repérée par l'interface)
        resultat.append(i)
    return renumeroter(resultat, etapes, cfg), ignorees
