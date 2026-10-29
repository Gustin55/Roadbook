"""Carrefours OpenStreetMap : réseau synthétique et extrait réel (West Oakland)."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from roadbook.config import config_par_defaut
from roadbook.geometry import depuis_plan_local
from roadbook.gpx_loader import TraceBrute
from roadbook.instructions import analyser
from roadbook.osm import charger_fichier, depuis_overpass_json, requetes_overpass
from roadbook.geometry import reechantillonner

sys.path.insert(0, str(Path(__file__).parent))
from reseau_util import plus_court_chemin, trace_simulee  # noqa: E402

LAT0, LON0 = 45.0, 4.0
DONNEES = Path(__file__).parent / "donnees"


class Construction:
    """Petit réseau OSM écrit en coordonnées planes (m)."""

    def __init__(self):
        self.noeuds, self.voies, self.tags_noeuds = {}, [], {}

    def noeud(self, n, x, y, **tags):
        self.noeuds[n] = (x, y)
        if tags:
            self.tags_noeuds[n] = tags
        return n

    def voie(self, noeuds, **tags):
        self.voies.append((noeuds, tags))

    def reseau(self):
        elements = []
        for n, (x, y) in self.noeuds.items():
            lat, lon = depuis_plan_local(x, y, LAT0, LON0)
            el = {"type": "node", "id": n, "lat": float(lat), "lon": float(lon)}
            if n in self.tags_noeuds:
                el["tags"] = self.tags_noeuds[n]
            elements.append(el)
        for k, (noeuds, tags) in enumerate(self.voies, start=1):
            elements.append({"type": "way", "id": 1000 + k, "nodes": noeuds, "tags": tags})
        return depuis_overpass_json(json.loads(json.dumps({"elements": elements})))


def reseau_rond_point():
    """Rond-point (rayon 20 m) à 4 branches + une entrée à sens unique au nord-est.

    Sortie ouest -> route vers un T : la D99 part au nord, la route continue à l'ouest.
    """
    b = Construction()
    anneau = []
    for k in range(8):  # sens antihoraire = sens de circulation
        a = math.radians(-90 + 45 * k)
        anneau.append(b.noeud(10 + k, 20 * math.cos(a), 20 * math.sin(a)))
    b.voie(anneau + [anneau[0]], highway="primary", junction="roundabout")
    # branches : sud (entrée), est, nord-est (entrée seule), nord, ouest
    b.voie([b.noeud(1, 0, -400), b.noeud(2, 0, -200), 10], highway="primary", ref="N7")
    b.voie([12, b.noeud(30, 300, 0)], highway="secondary", ref="D1")
    b.voie([b.noeud(31, 250, 250), 13], highway="tertiary", oneway="yes")
    b.voie([14, b.noeud(32, 0, 300)], highway="secondary", ref="D2")
    # vers l'ouest : traverse une petite rue, puis un T
    b.voie([16, b.noeud(40, -300, 0), b.noeud(41, -500, 0), b.noeud(42, -800, 0)],
           highway="tertiary", ref="D3", destination="Valence;Crest")
    b.voie([b.noeud(50, -300, -150), 40, b.noeud(51, -300, 150)], highway="residential", name="Rue basse")
    b.noeud(61, -500, 200, railway="level_crossing")
    b.voie([41, 61, b.noeud(60, -500, 400)], highway="secondary", ref="D99", destination="Die")
    return b.reseau()


def analyser_chemin(reseau, chemin, cfg=None, graine=1):
    cfg = cfg or config_par_defaut()
    lat, lon = trace_simulee(reseau, chemin, pas_m=6, bruit_m=1.0, graine=graine)
    etapes, instructions, _ = analyser([TraceBrute("T", lat, lon, None)], [], cfg, reseau)
    return [i for i in instructions if i.type not in ("depart", "arrivee")], etapes[0]


def test_rond_point_numero_de_sortie_et_route_suivante():
    r = reseau_rond_point()
    chemin = [1, 2, 10, 11, 12, 13, 14, 15, 16, 40, 41, 61, 60]
    cases, _ = analyser_chemin(r, chemin)
    assert [c.description for c in cases[:2]] == ["RP 3E SORTIE", "AD"]
    rp, t = cases[0], cases[1]
    # est = 1re, nord-est à sens unique (entrée seule) non comptée, nord = 2e, ouest = 3e
    assert rp.sortie_num == 3
    assert rp.angle == pytest.approx(-90, abs=8)
    assert "SUR D3" in rp.notes and "DIR. Valence / Crest" in rp.notes
    assert len(rp.branches) >= 3  # autres branches dessinées autour de l'anneau
    # la petite rue croisée tout droit n'a pas de case ; le T vers la D99 en a une
    assert "SUR D99" in t.notes and "DIR. Die" in t.notes
    assert t.branches and abs(t.branches[0]) < 20  # la D3 continue tout droit
    # passage à niveau ajouté automatiquement
    assert any(p.type == "passage_niveau" for c in cases for p in c.pois)


@pytest.mark.parametrize("sortie, numero", [(12, 1), (14, 2), (16, 3)])
def test_rond_point_toutes_sorties(sortie, numero):
    r = reseau_rond_point()
    anneau = [10, 11, 12, 13, 14, 15, 16]
    suite = {12: [30], 14: [32], 16: [40]}[sortie]
    chemin = [1, 2] + anneau[: anneau.index(sortie) + 1] + suite
    cases, _ = analyser_chemin(r, chemin)
    assert cases[0].type == "rond_point" and cases[0].sortie_num == numero


def test_croisement_route_plus_importante_en_td():
    b = Construction()
    b.voie([b.noeud(1, 0, -500), b.noeud(2, 0, 0), b.noeud(3, 0, 500)], highway="residential", name="Chemin")
    b.voie([b.noeud(4, -500, 0), 2, b.noeud(5, 500, 0)], highway="primary", ref="N86")
    r = b.reseau()
    cases, _ = analyser_chemin(r, [1, 2, 3])
    assert [c.description for c in cases] == ["TD"]
    assert sorted(round(a / 10) * 10 for a in cases[0].branches) == [-90, 90]
    cfg = config_par_defaut()
    cfg["osm"]["carrefours_td"] = "aucun"
    assert analyser_chemin(r, [1, 2, 3], cfg)[0] == []


def test_virage_sans_carrefour_ignore_sur_route():
    b = Construction()
    # route coudée à 90° sans autre route : pas une décision de navigation
    b.voie([b.noeud(1, 0, -500), b.noeud(2, 0, 0), b.noeud(3, 500, 0)], highway="tertiary")
    r = b.reseau()
    cases, etape = analyser_chemin(r, [1, 2, 3])
    assert cases == []
    cfg = config_par_defaut()
    cfg["osm"]["virages_hors_carrefour"] = True
    assert [c.description for c in analyser_chemin(r, [1, 2, 3], cfg)[0]] == ["AD"]


def test_requetes_overpass_suivent_la_trace():
    lat, lon = depuis_plan_local(np.linspace(0, 20000, 2000), np.zeros(2000), LAT0, LON0)
    tr = reechantillonner(lat, lon, None, 5)
    requetes = requetes_overpass(tr, 40)
    assert len(requetes) == 1  # ligne droite : 2 points suffisent
    assert "way(around:40," in requetes[0] and "level_crossing" in requetes[0]


def test_extrait_reel_west_oakland():
    """Itinéraire sur un vrai extrait OSM (© contributeurs OpenStreetMap, ODbL)."""
    cfg = config_par_defaut()
    r = charger_fichier(DONNEES / "West-Oakland.osm.bz2").filtrer(cfg["osm"]["types_ignores"],
                                                                  cfg["osm"]["services_ignores"])
    chemin = plus_court_chemin(r, 429454715, 420944486)
    cases, _ = analyser_chemin(r, chemin, cfg, graine=3)
    assert [(c.description, c.notes[0]) for c in cases] == [
        ("AD", "SUR 8th Street"), ("AG", "SUR Wood Street"), ("AD FORT", "SUR 7th Street")]
    assert "FEUX" in cases[2].notes


def test_overpass_cache_et_repli(monkeypatch, tmp_path):
    """Premier serveur en panne -> second serveur ; la réponse est ensuite lue dans le cache."""
    import io
    import urllib.error

    from roadbook import osm

    appels = []
    reponse = {"elements": [{"type": "node", "id": 1, "lat": 45.0, "lon": 4.0}]}

    def faux_urlopen(req, timeout):
        appels.append(req.full_url)
        if "panne" in req.full_url:
            raise urllib.error.URLError("hors service")
        return io.BytesIO(json.dumps(reponse).encode())

    monkeypatch.setattr(osm.urllib.request, "urlopen", faux_urlopen)
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)
    serveurs = ["https://panne.example/api", "https://ok.example/api"]
    assert osm.interroger_overpass("requete", serveurs, tmp_path, journal=lambda m: None) == reponse
    assert appels == serveurs
    assert osm.interroger_overpass("requete", serveurs, tmp_path, journal=lambda m: None) == reponse
    assert len(appels) == 2  # servi par le cache


def test_cli_osm_fichier(tmp_path):
    from roadbook.cli import main
    from roadbook.synthetique import ecrire_gpx

    r = reseau_rond_point()
    lat, lon = trace_simulee(r, [1, 2, 10, 11, 12, 13, 14, 15, 16, 40, 41, 61, 60], pas_m=6, bruit_m=1, graine=1)
    gpx = tmp_path / "t.gpx"
    ecrire_gpx(gpx, [("T", lat, lon, None)])
    elements = [{"type": "node", "id": n, "lat": la, "lon": lo, **({"tags": r.tags_noeuds[n]}
                 if n in r.tags_noeuds else {})} for n, (la, lo) in r.noeuds.items()]
    elements += [{"type": "way", "id": v.id, "nodes": v.noeuds, "tags": v.tags} for v in r.voies]
    reseau_json = tmp_path / "reseau.json"
    reseau_json.write_text(json.dumps({"elements": elements}))
    csv = tmp_path / "i.csv"
    assert main(["genere", str(gpx), "--osm-fichier", str(reseau_json), "-o", str(tmp_path / "rb.pdf"),
                 "--csv", str(csv), "-q"]) == 0
    assert "RP 3E SORTIE" in csv.read_text(encoding="utf-8-sig")
