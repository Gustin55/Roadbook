"""Non-régression sur la trace d'exemple : instructions, PDF et CLI."""

from pathlib import Path

import pytest
from pypdf import PdfReader

from roadbook.cli import main
from roadbook.config import charger_config
from roadbook.gpx_loader import charger_gpx
from roadbook.instructions import analyser
from roadbook.layout import paginer
from roadbook.poi import charger_csv
from roadbook.render_pdf import abreger, ajuster_texte, generer_pdf

EXEMPLES = Path(__file__).parent.parent / "examples"
GPX = EXEMPLES / "exemple.gpx"
POI = EXEMPLES / "poi.csv"


@pytest.fixture(scope="module")
def exemple():
    cfg, _ = charger_config(EXEMPLES / "config.yaml")
    donnees = charger_gpx(GPX, cfg)
    pois, _ = charger_csv(POI)
    etapes, instructions, avert = analyser(donnees.traces, donnees.waypoints + pois, cfg)
    return cfg, etapes, instructions, avert


def test_instructions_exemple(exemple):
    _, etapes, instructions, _ = exemple
    assert [e.nom for e in etapes] == ["E1 - Erfoud boucle nord", "E2 - Liaison sud"]
    e1 = [i for i in instructions if i.etape == etapes[0].nom]
    manoeuvres = [i.description for i in e1 if i.type in ("virage", "rond_point", "demi_tour")]
    # 1re sortie à droite d'un rond-point à entrée évasée : vue comme un « AD » (limite connue)
    assert manoeuvres == ["AD", "RP SORTIE TD", "LÉG. AG", "AG", "AD FORT", "AD", "ÉPINGLE AG", "AD"]
    e2 = [i.description for i in instructions if i.etape == etapes[1].nom
          and i.type in ("virage", "rond_point", "demi_tour")]
    assert e2 == ["AG", "RP SORTIE AG", "LÉG. AD", "DEMI-TOUR", "AD"]
    # compteur remis à zéro à chaque étape, partiels cohérents
    for etape in etapes:
        cases = [i for i in instructions if i.etape == etape.nom]
        assert cases[0].km_total == 0 and cases[0].type == "depart"
        assert cases[-1].km_total == pytest.approx(etape.trace.longueur / 1000)
        assert sum(i.km_partiel for i in cases) == pytest.approx(cases[-1].km_total)
    # contrôles et dangers rattachés
    assert sum(i.est_controle for i in instructions) == 3
    assert sum(1 for i in instructions if i.niveau_danger) == 2


@pytest.mark.parametrize("fmt", ["a5", "a4", "rouleau"])
def test_pdf_nombre_de_pages(exemple, fmt, tmp_path):
    cfg, etapes, instructions, _ = exemple
    cfg = {**cfg, "affichage": {**cfg["affichage"], "format": fmt}}
    _, pages = paginer(etapes, instructions, cfg)
    sortie = tmp_path / f"rb_{fmt}.pdf"
    nb, _ = generer_pdf(etapes, instructions, cfg, sortie)
    lecteur = PdfReader(sortie)
    assert len(lecteur.pages) == nb == len(pages)
    # légende + (garde + cases) par étape
    cases_par_page = {"a5": 7, "a4": 10}.get(fmt)
    if cases_par_page:
        attendu = 1 + sum(1 + -(-sum(1 for i in instructions if i.etape == e.nom) // cases_par_page)
                          for e in etapes)
        assert nb == attendu
    # signets : légende puis une entrée par étape
    titres = [o.title for o in lecteur.outline if not isinstance(o, list)]
    assert titres == ["Légende"] + [e.nom for e in etapes]
    texte = lecteur.pages[2].extract_text()
    assert "0,00" in texte and "DÉPART" in texte


def test_texte_trop_long_abrege_puis_tronque():
    lignes, alerte = ajuster_texte([("Suivre la piste principale tout droit", "Helvetica", 12)],
                                   60, 30, {"piste principale": "PP", "tout droit": "TD", "suivre": "SVE"}, True)
    assert alerte.startswith("abrégé")
    assert "PP" in " ".join(l[0] for l in lignes)
    lignes, alerte = ajuster_texte([("x " * 200, "Helvetica", 12)], 60, 30, {}, True)
    assert alerte == "texte tronqué" and lignes[-1][0].endswith("…")


def test_abreger_mots_entiers():
    assert abreger("Suivre la piste principale", {"piste principale": "PP", "suivre": "SVE"}) == "SVE la PP"
    assert abreger("poursuivre", {"suivre": "SVE"}) == "poursuivre"


def test_cli_genere(tmp_path, capsys):
    sortie = tmp_path / "rb.pdf"
    csv = tmp_path / "rb.csv"
    code = main(["genere", str(GPX), "-c", str(EXEMPLES / "config.yaml"), "-p", str(POI),
                 "-o", str(sortie), "--csv", str(csv), "-q"])
    assert code == 0
    assert sortie.exists() and csv.exists() and sortie.with_suffix(".rapport.txt").exists()
    assert csv.read_text(encoding="utf-8-sig").startswith("numero;etape;type")


def test_cli_erreur_fichier_absent(capsys):
    assert main(["genere", "absent.gpx"]) == 2
