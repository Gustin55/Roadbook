"""Exports texte : tableau console, CSV des instructions, rapport de génération."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from .instructions import Instruction


def formater_km(valeur: float, decimales: int, separateur: str = ",") -> str:
    return f"{valeur:.{decimales}f}".replace(".", separateur)


def heure_depart(cfg: dict) -> datetime | None:
    brut = cfg["epreuve"].get("depart_prevu")
    if not brut:
        return None
    if isinstance(brut, datetime):
        return brut
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%H:%M"):
        try:
            return datetime.strptime(str(brut), fmt)
        except ValueError:
            pass
    return None


def table_texte(instructions: list[Instruction], cfg: dict) -> str:
    aff = cfg["affichage"]
    dt, dp, sep = aff["decimales_total"], aff["decimales_partiel"], aff["separateur_decimal"]
    lignes = [f"{'N°':>4} {'TC km':>8} {'TP km':>6}  {'Type':<10} {'Angle':>6} {'Cap':>5}  Description / notes"]
    etape = None
    for i in instructions:
        if i.etape != etape:
            etape = i.etape
            lignes.append(f"--- {etape} ---")
        angle = f"{i.angle:+.0f}°" if i.angle is not None else ""
        cap = f"{i.cap_sortie:03.0f}" if i.cap_sortie is not None else ""
        texte = i.description
        if i.pois:
            marques = " ".join(p.code or p.type.upper() for p in i.pois)
            texte += f"  [{marques}]"
        if i.notes:
            texte += " | " + " / ".join(i.notes)
        lignes.append(
            f"{i.numero:>4} {formater_km(i.km_total, dt, sep):>8} {formater_km(i.km_partiel, dp, sep):>6}"
            f"  {i.type:<10} {angle:>6} {cap:>5}  {texte}"
        )
    return "\n".join(lignes)


def exporter_csv(instructions: list[Instruction], chemin: str | Path, cfg: dict) -> None:
    """CSV « ; » en UTF-8 avec BOM : s'ouvre directement dans Excel (Windows, réglages FR)."""
    aff = cfg["affichage"]
    sep = aff["separateur_decimal"]
    depart = heure_depart(cfg)
    vitesse = cfg["epreuve"]["vitesse_moyenne_kmh"]
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "numero", "etape", "type", "km_total", "km_partiel", "km_suivante", "description", "angle_deg",
            "classe", "cap_sortie_deg", "notes", "poi", "lat", "lon", "altitude_m", "pente_pct",
            "heure_estimee", "remarques",
        ])
        for i in instructions:
            heure = ""
            if depart and vitesse:
                heure = (depart + timedelta(hours=i.s_m / 1000.0 / vitesse)).strftime("%H:%M")
            w.writerow([
                i.numero, i.etape, i.type,
                formater_km(i.km_total, 3, sep), formater_km(i.km_partiel, 3, sep),
                "" if i.km_suivante is None else formater_km(i.km_suivante, 3, sep),
                i.description,
                "" if i.angle is None else f"{i.angle:.0f}",
                i.classe or "",
                "" if i.cap_sortie is None else f"{i.cap_sortie:.0f}",
                " / ".join(i.notes),
                " ".join(f"{p.type}:{p.code}" if p.code else p.type for p in i.pois),
                f"{i.lat:.6f}".replace(".", sep), f"{i.lon:.6f}".replace(".", sep),
                "" if i.ele is None else f"{i.ele:.0f}",
                "" if i.pente_pct is None else f"{i.pente_pct:.1f}".replace(".", sep),
                heure,
                " ; ".join(i.remarques),
            ])


def rapport(avertissements: list[str], instructions: list[Instruction], etapes, cfg: dict) -> str:
    lignes = [f"Rapport de génération — {cfg['epreuve']['nom']}", ""]
    for e in etapes:
        n = sum(1 for i in instructions if i.etape == e.nom)
        types = {}
        for m in e.manoeuvres:
            types[m.type] = types.get(m.type, 0) + 1
        detail = ", ".join(f"{v} {k.replace('_', '-')}" for k, v in sorted(types.items())) or "aucune manœuvre"
        lignes.append(f"Étape « {e.nom} » : {e.trace.longueur / 1000:.2f} km, {n} cases ({detail}), "
                      f"{len(e.pois)} POI")
    lignes.append("")
    douteux = [i for i in instructions if i.remarques]
    lignes.append(f"Avertissements ({len(avertissements)}) :")
    lignes += [f"  - {a}" for a in avertissements] or ["  (aucun)"]
    lignes.append("")
    lignes.append(f"Cases à vérifier ({len(douteux)}) :")
    for i in douteux:
        lignes.append(f"  - case {i.numero} ({i.etape}, km {i.km_total:.2f}, {i.description}) : "
                      + " ; ".join(i.remarques))
    if not douteux:
        lignes.append("  (aucune)")
    for e in etapes:
        for r in e.remarques:
            lignes.append(f"  - {e.nom} : {r}")
    return "\n".join(lignes) + "\n"
