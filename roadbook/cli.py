"""Interface en ligne de commande.

    roadbook genere trace.gpx --config config.yaml -o roadbook.pdf
    roadbook instructions trace.gpx --config config.yaml
    roadbook config-defaut > config.yaml
    roadbook interface
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
from .instructions import analyser, reechantillonner_traces
from .osm import ErreurOSM, charger_reseau
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
    echantillons = reechantillonner_traces(donnees.traces, cfg)
    reseau = None
    fichiers_osm = list(cfg["osm"]["fichiers"]) + list(args.osm_fichier or [])
    en_ligne = bool(args.osm or cfg["osm"]["actif"])
    if en_ligne or fichiers_osm:
        cache = Path(args.osm_cache) if args.osm_cache else None
        reseau = charger_reseau(echantillons, cfg, fichiers_osm, en_ligne, cache, journal=print)
        print(f"OpenStreetMap : {len(reseau.voies)} voies chargées")
    etapes, instructions, a = analyser(donnees.traces, pois, cfg, reseau, echantillons)
    return cfg, etapes, instructions, avert + a, reseau is not None


def cmd_genere(args) -> int:
    from .render_pdf import generer_pdf

    cfg, etapes, instructions, avert, osm = _preparer(args)
    sortie = Path(args.sortie or Path(args.gpx).with_suffix(".pdf"))
    attribution = "Routes © contributeurs OpenStreetMap (ODbL)" if osm else ""
    nb_pages, a = generer_pdf(etapes, instructions, cfg, sortie, attribution)
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
    cfg, etapes, instructions, avert, _ = _preparer(args)
    print(table_texte(instructions, cfg))
    print()
    print(rapport(avert, instructions, etapes, cfg))
    if args.csv:
        exporter_csv(instructions, args.csv, cfg)
    return 0


def cmd_config(args) -> int:
    sys.stdout.write(yaml.safe_dump(DEFAUTS, allow_unicode=True, sort_keys=False))
    return 0


def cmd_interface(args) -> int:
    from .serveur import lancer

    lancer(args.port, navigateur=not args.sans_navigateur)
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
        sp.add_argument("--osm", action="store_true",
                        help="carrefours, rond-points et noms de routes depuis OpenStreetMap (Overpass, en ligne)")
        sp.add_argument("--osm-fichier", action="append",
                        help="réseau OSM hors ligne : .osm, .osm.bz2 ou Overpass .json (option répétable)")
        sp.add_argument("--osm-cache", help="dossier du cache Overpass (défaut : cache utilisateur)")

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

    ui = sous.add_parser("interface", help="ouvre l'interface graphique dans le navigateur")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    ui.set_defaults(func=cmd_interface)

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
    except ErreurOSM as exc:
        print(f"Erreur OpenStreetMap : {exc}\nSans connexion, utilisez --osm-fichier avec un export .osm.",
              file=sys.stderr)
        return 3
    except (ErreurConfig, FileNotFoundError, ValueError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
