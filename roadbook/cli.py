"""Interface en ligne de commande.

    roadbook genere trace.gpx --config config.yaml -o roadbook.pdf
    roadbook instructions trace.gpx --config config.yaml
    roadbook config-defaut > config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__
from .config import DEFAUTS, ErreurConfig, charger_config
from .export import exporter_csv, rapport, table_texte
from .gpx_loader import charger_gpx
from .instructions import analyser
from .poi import charger_csv


def _preparer(args):
    cfg, avert = charger_config(args.config)
    if getattr(args, "format", None):
        cfg["affichage"]["format"] = args.format
    donnees = charger_gpx(args.gpx, cfg)
    avert += donnees.avertissements
    pois = list(donnees.waypoints)
    for chemin in args.poi or []:
        extra, a = charger_csv(chemin)
        pois += extra
        avert += a
    etapes, instructions, a = analyser(donnees.traces, pois, cfg)
    return cfg, etapes, instructions, avert + a


def cmd_genere(args) -> int:
    from .render_pdf import generer_pdf

    cfg, etapes, instructions, avert = _preparer(args)
    sortie = Path(args.sortie or Path(args.gpx).with_suffix(".pdf"))
    nb_pages, a = generer_pdf(etapes, instructions, cfg, sortie)
    avert += a
    print(f"PDF : {sortie} ({nb_pages} pages, {len(instructions)} cases)")
    if args.csv:
        exporter_csv(instructions, args.csv, cfg)
        print(f"CSV : {args.csv}")
    texte = rapport(avert, instructions, etapes, cfg)
    chemin_rapport = Path(args.rapport) if args.rapport else sortie.with_suffix(".rapport.txt")
    chemin_rapport.write_text(texte, encoding="utf-8")
    print(f"Rapport : {chemin_rapport}")
    if not args.silencieux:
        print()
        print(texte)
    return 0


def cmd_instructions(args) -> int:
    cfg, etapes, instructions, avert = _preparer(args)
    print(table_texte(instructions, cfg))
    print()
    print(rapport(avert, instructions, etapes, cfg))
    if args.csv:
        exporter_csv(instructions, args.csv, cfg)
    return 0


def cmd_config(args) -> int:
    sys.stdout.write(yaml.safe_dump(DEFAUTS, allow_unicode=True, sort_keys=False))
    return 0


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roadbook", description="Génère un road book PDF à partir d'une trace GPX.")
    p.add_argument("--version", action="version", version=f"roadbook {__version__}")
    sous = p.add_subparsers(dest="commande", required=True)

    def communs(sp):
        sp.add_argument("gpx", help="fichier GPX (traces <trk> ou routes <rte>, waypoints facultatifs)")
        sp.add_argument("-c", "--config", help="fichier de configuration YAML")
        sp.add_argument("-p", "--poi", action="append", help="CSV de points d'intérêt (option répétable)")
        sp.add_argument("--csv", help="exporte aussi les instructions en CSV")

    g = sous.add_parser("genere", help="génère le PDF")
    communs(g)
    g.add_argument("-o", "--sortie", help="fichier PDF (défaut : nom du GPX en .pdf)")
    g.add_argument("-f", "--format", choices=["a5", "a4", "rouleau"], help="remplace affichage.format")
    g.add_argument("--rapport", help="fichier du rapport (défaut : <sortie>.rapport.txt)")
    g.add_argument("-q", "--silencieux", action="store_true", help="n'affiche pas le rapport")
    g.set_defaults(func=cmd_genere)

    i = sous.add_parser("instructions", help="affiche le tableau des instructions (sans PDF)")
    communs(i)
    i.set_defaults(func=cmd_instructions)

    d = sous.add_parser("config-defaut", help="affiche la configuration par défaut (YAML)")
    d.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    # console Windows : forcer l'UTF-8 pour les accents
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            try:
                flux.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    args = construire_parseur().parse_args(argv)
    try:
        return args.func(args)
    except (ErreurConfig, FileNotFoundError, ValueError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
