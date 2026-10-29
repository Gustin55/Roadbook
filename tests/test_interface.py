"""Serveur de l'interface graphique et corrections manuelles des cases."""

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from roadbook.serveur import creer_serveur

EXEMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def url():
    serveur = creer_serveur(0)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()
    serveur.server_close()


def appel(url, chemin, corps=None):
    donnees = None if corps is None else json.dumps(corps).encode()
    req = urllib.request.Request(url + chemin, data=donnees, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            brut = r.read()
            est_json = r.headers.get("Content-Type", "").startswith("application/json")
            return r.status, (json.loads(brut) if est_json else brut)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def fichiers():
    return {
        "gpx": {"nom": "exemple.gpx", "texte": (EXEMPLES / "exemple.gpx").read_text(encoding="utf-8")},
        "pois": [{"nom": "poi.csv", "texte": (EXEMPLES / "poi.csv").read_text(encoding="utf-8")}],
    }


def test_page_et_options(url):
    code, page = appel(url, "/")
    assert code == 200 and b"Roadbook Studio" in page
    code, d = appel(url, "/api/options")
    chemins = [c["chemin"] for s in d["sections"] for c in s["champs"]]
    assert "affichage.format" in chemins and "osm.carrefours_td" in chemins
    assert d["defauts"]["affichage"]["format"] == "a5"


def test_analyse_rendu_et_corrections(url):
    code, d = appel(url, "/api/analyser", {**fichiers(), "config": {}})
    assert code == 200, d
    assert len(d["etapes"]) == 2 and d["pages"] == 7
    assert [p["titre"] for p in d["liste_pages"]][:3] == [
        "Légende", "E1 - Erfoud boucle nord · page de garde", "E1 - Erfoud boucle nord · 1/2 · cases 1–7"]
    # PDF et images des pages servis à part (pas de PDF en base64 dans le JSON)
    assert "pdf" not in d
    code, pdf = appel(url, f"/pdf?session={d['session']}&rev={d['revision']}".replace("/pdf", "/api/pdf"))
    assert code == 200 and pdf[:4] == b"%PDF"
    code, png = appel(url, f"/api/page?session={d['session']}&rev={d['revision']}&n=3&largeur=600")
    assert code == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
    cases = d["cases"]
    virage = next(c for c in cases if c["type"] == "virage")
    poi = next(c for c in cases if c["type"] == "poi")
    modifs = {
        "cases": {virage["id"]: {"description": "AD SUR PP", "danger": 3}, poi["id"]: {"supprime": True}},
        "ajouts": [{"etape": cases[0]["etape"], "km": 1.5, "description": "TD PONT", "notes": ["Étroit"]}],
    }
    code, r = appel(url, "/api/rendu", {"session": d["session"], "config": {"affichage": {"format": "a4"}},
                                       "modifications": modifs})
    assert code == 200, r
    assert r["pages"] == 6 and not r["analyse_perimee"] and r["revision"] == d["revision"] + 1
    par_id = {c["id"]: c for c in r["cases"]}
    assert par_id[virage["id"]]["description"] == "AD SUR PP" and par_id[virage["id"]]["danger"] == 3
    assert poi["id"] not in par_id
    ajout = next(c for c in r["cases"] if c["manuel"])
    assert ajout["description"] == "TD PONT" and ajout["notes"] == ["Étroit"]
    # numéros et partiels recalculés
    e1 = [c for c in r["cases"] if c["etape"] == cases[0]["etape"]]
    assert [c["numero"] for c in e1] == list(range(1, len(e1) + 1))
    assert sum(c["km_partiel"] for c in e1) == pytest.approx(e1[-1]["km_total"])
    # une option de détection modifiée signale qu'il faut réanalyser
    code, r = appel(url, "/api/rendu", {"session": d["session"], "config": {"calcul": {"seuil_virage_deg": 35}},
                                       "pdf": False, "csv": True})
    assert r["analyse_perimee"] and "pdf" not in r and r["csv"].startswith("numero;")


def test_exemple_integre(url):
    code, d = appel(url, "/api/exemple")
    assert code == 200 and d["gpx"]["texte"].startswith("<?xml") and d["config"]["epreuve"]["nom"]


def test_config_yaml_aller_retour(url):
    code, d = appel(url, "/api/config-yaml", {"config": {"epreuve": {"nom": "Raid"}}})
    assert code == 200 and "Raid" in d["yaml"]
    code, r = appel(url, "/api/lire-config", {"texte": d["yaml"]})
    assert r["config"]["epreuve"]["nom"] == "Raid"


def test_erreurs_lisibles(url):
    code, d = appel(url, "/api/rendu", {"session": "inconnue"})
    assert code == 400 and "session" in d["erreur"]
    code, d = appel(url, "/api/analyser", {"gpx": {"nom": "x.gpx", "texte": "pas du gpx"}})
    assert code == 400 and "GPX illisible" in d["erreur"]
    code, d = appel(url, "/api/analyser", {**fichiers(), "config": {"affichage": {"format": "a3"}}})
    assert code == 400 and "format" in d["erreur"]


def test_checkpoints_poses_sur_la_carte(url):
    code, d = appel(url, "/api/analyser", {**fichiers(), "config": {}})
    assert code == 200
    e1 = d["etapes"][0]
    lat, lon = e1["latlon"][len(e1["latlon"]) // 3]
    # un clic à ~50 m de la trace s'accroche dessus
    code, a = appel(url, "/api/accrocher", {"session": d["session"], "lat": lat + 0.0004, "lon": lon})
    assert code == 200 and a["etape"] == e1["nom"] and a["ecart_m"] < 60
    points = [
        {"id": "a1", "type": "controle", "code": "cp9", "description": "Tampon", **a},
        {"id": "a2", "type": "danger", "niveau": 3, "description": "Ornière", "lat": a["lat"], "lon": a["lon"],
         "etape": a["etape"], "km": a["km"] + 1.0},
    ]
    code, r = appel(url, "/api/rendu", {"session": d["session"], "modifications": {"points": points}})
    assert code == 200, r
    cp = next(c for c in r["cases"] if "CP9" in c["controle"])
    assert "Tampon" in cp["notes"]
    dz = next(c for c in r["cases"] if "Ornière" in c["notes"])
    assert dz["danger"] == 3
    assert [p["km"] for p in r["points"]] == pytest.approx([a["km"], a["km"] + 1.0], abs=0.001)
    # la session d'origine n'est pas modifiée : sans les points, ils disparaissent
    code, r2 = appel(url, "/api/rendu", {"session": d["session"], "pdf": False})
    assert not any("CP9" in c["controle"] for c in r2["cases"])
    # export GPX : trace + points
    code, g = appel(url, "/api/gpx", {"session": d["session"], "modifications": {"points": points}})
    assert code == 200 and g["gpx"].count("<trk>") == 2 and "<name>CP9</name>" in g["gpx"]
    # trop loin de la trace
    code, err = appel(url, "/api/accrocher", {"session": d["session"], "lat": lat + 1, "lon": lon})
    assert code == 400 and "trop loin" in err["erreur"]


def test_bibliotheques_livrees(url):
    code, js = appel(url, "/vendor/leaflet/leaflet.js")
    assert code == 200 and b"Leaflet" in js[:500]
    code, _ = appel(url, "/vendor/leaflet/images/layers.png")
    assert code == 200
    code, _ = appel(url, "/vendor/../serveur.py")
    assert code == 404
