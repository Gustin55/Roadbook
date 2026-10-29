"""Interface graphique : petit serveur web local (bibliothèque standard uniquement).

    roadbook interface            # ouvre http://127.0.0.1:8765 dans le navigateur

Le serveur n'écoute que sur la machine locale. Les fichiers envoyés restent en
mémoire (et dans un dossier temporaire le temps de la lecture).
"""

from __future__ import annotations

import base64
import json
import math
import tempfile
import threading
import traceback
import uuid
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

from . import __version__
from .config import DEFAUTS, ErreurConfig, depuis_dict
from .export import exporter_csv, rapport
from .geometry import vers_plan_local
from .gpx_loader import charger_gpx
from .instructions import Etape, Instruction, analyser, generer_instructions, reechantillonner_traces
from .modifications import appliquer, identifiant_case
from .options import SECTIONS, empreinte_analyse
from .osm import ErreurOSM, charger_reseau
from .poi import charger_csv
from .render_pdf import generer_pdf

TAILLE_MAX = 300 * 1024 * 1024
SESSIONS_MAX = 6


@dataclass
class Session:
    id: str
    etapes: list[Etape]
    avertissements: list[str]
    osm: bool
    empreinte: str
    journal: list[str] = field(default_factory=list)


class Etat:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.verrou = threading.Lock()

    def ajouter(self, s: Session) -> None:
        self.sessions[s.id] = s
        while len(self.sessions) > SESSIONS_MAX:
            self.sessions.pop(next(iter(self.sessions)))


ETAT = Etat()


class ErreurRequete(ValueError):
    pass


# --------------------------------------------------------------------------
# Traitements
# --------------------------------------------------------------------------


def _config(donnees) -> tuple[dict, list[str]]:
    try:
        return depuis_dict(donnees or {})
    except (ErreurConfig, KeyError, TypeError) as exc:
        raise ErreurRequete(f"configuration invalide : {exc}") from exc


def _ecrire(dossier: Path, fichier: dict, defaut: str) -> Path:
    nom = Path(fichier.get("nom") or defaut).name or defaut
    chemin = dossier / nom
    if "base64" in fichier:
        chemin.write_bytes(base64.b64decode(fichier["base64"]))
    else:
        chemin.write_text(fichier.get("texte", ""), encoding="utf-8")
    return chemin


def analyser_fichiers(requete: dict) -> Session:
    cfg, avert = _config(requete.get("config"))
    if not requete.get("gpx"):
        raise ErreurRequete("aucune trace GPX fournie")
    journal: list[str] = []
    with tempfile.TemporaryDirectory(prefix="roadbook_") as tmp:
        dossier = Path(tmp)
        gpx = _ecrire(dossier, requete["gpx"], "trace.gpx")
        donnees = charger_gpx(gpx, cfg)
        avert += donnees.avertissements
        pois = list(donnees.waypoints)
        for k, f in enumerate(requete.get("pois") or []):
            extra, a = charger_csv(_ecrire(dossier, f, f"poi{k}.csv"))
            pois += extra
            avert += a
        echantillons = reechantillonner_traces(donnees.traces, cfg)
        fichiers_osm = [str(_ecrire(dossier, f, f"reseau{k}.osm")) for k, f in enumerate(requete.get("osm") or [])]
        reseau = None
        if fichiers_osm or cfg["osm"]["actif"]:
            reseau = charger_reseau(echantillons, cfg, fichiers_osm, bool(cfg["osm"]["actif"]),
                                    journal=journal.append)
            journal.append(f"OpenStreetMap : {len(reseau.voies)} voies chargées")
        etapes, _, a = analyser(donnees.traces, pois, cfg, reseau, echantillons)
    return Session(uuid.uuid4().hex[:12], etapes, avert + a, reseau is not None, empreinte_analyse(cfg), journal)


def _carte(etape: Etape, n_max: int = 700) -> dict:
    tr = etape.trace
    lat0, lon0 = float(tr.lat.mean()), float(tr.lon.mean())
    pas = max(1, len(tr.s) // n_max)
    idx = np.unique(np.concatenate([np.arange(0, len(tr.s), pas), [len(tr.s) - 1]]))
    x, y = vers_plan_local(tr.lat[idx], tr.lon[idx], lat0, lon0)
    return {"nom": etape.nom, "longueur_km": round(tr.longueur / 1000, 3), "origine": [lat0, lon0],
            "points": [[round(float(a), 1), round(float(b), 1)] for a, b in zip(x, y)]}


def _case(i: Instruction, origines: dict) -> dict:
    lat0, lon0 = origines[i.etape]
    x, y = vers_plan_local(i.lat, i.lon, lat0, lon0)

    def propre(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

    return {
        "id": identifiant_case(i), "numero": i.numero, "etape": i.etape, "type": i.type,
        "km_total": i.km_total, "km_partiel": i.km_partiel, "description": i.description, "notes": i.notes,
        "angle": propre(i.angle), "cap": propre(i.cap_sortie), "branches": i.branches,
        "position_sortie": propre(i.position_sortie), "sortie_num": i.sortie_num,
        "danger": i.niveau_danger, "controle": " ".join(p.code or "CP" for p in i.pois if p.type == "controle"),
        "pois": [{"type": p.type, "code": p.code, "niveau": p.niveau, "description": p.description}
                 for p in i.pois],
        "remarques": i.remarques, "x": round(float(x), 1), "y": round(float(y), 1),
        "manuel": getattr(i, "manuel", False),
    }


def rendre(requete: dict) -> dict:
    session = ETAT.sessions.get(requete.get("session", ""))
    if session is None:
        raise ErreurRequete("session expirée : relancez l'analyse")
    cfg, avert = _config(requete.get("config"))
    instructions = generer_instructions(session.etapes, cfg)
    instructions, ignorees = appliquer(instructions, session.etapes, requete.get("modifications"), cfg)
    origines = {e.nom: (float(e.trace.lat.mean()), float(e.trace.lon.mean())) for e in session.etapes}
    resultat = {
        "analyse_perimee": empreinte_analyse(cfg) != session.empreinte,
        "cases": [_case(i, origines) for i in instructions],
    }
    if requete.get("pdf", True):
        with tempfile.TemporaryDirectory(prefix="roadbook_") as tmp:
            chemin = Path(tmp) / "roadbook.pdf"
            attribution = "Routes © contributeurs OpenStreetMap (ODbL)" if session.osm else ""
            nb_pages, a = generer_pdf(session.etapes, instructions, cfg, chemin, attribution)
            resultat["pdf"] = base64.b64encode(chemin.read_bytes()).decode("ascii")
            resultat["pages"] = nb_pages
        avert += a
    tous = session.avertissements + avert + ignorees
    resultat["avertissements"] = tous
    resultat["rapport"] = rapport(tous, instructions, session.etapes, cfg)
    if requete.get("csv"):
        with tempfile.TemporaryDirectory(prefix="roadbook_") as tmp:
            chemin = Path(tmp) / "instructions.csv"
            exporter_csv(instructions, chemin, cfg)
            resultat["csv"] = chemin.read_text(encoding="utf-8-sig")
    return resultat


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _page() -> bytes:
    return resources.files("roadbook").joinpath("web/index.html").read_bytes()


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = f"roadbook/{__version__}"

    def log_message(self, fmt, *args):  # console silencieuse
        pass

    def _envoyer(self, code: int, corps: bytes, type_: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, code: int, donnees) -> None:
        self._envoyer(code, json.dumps(donnees, ensure_ascii=False, default=str).encode("utf-8"),
                      "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._envoyer(200, _page(), "text/html; charset=utf-8")
        elif self.path == "/api/options":
            self._json(200, {"sections": SECTIONS, "defauts": DEFAUTS, "version": __version__})
        else:
            self._json(404, {"erreur": "introuvable"})

    def do_POST(self):
        longueur = int(self.headers.get("Content-Length") or 0)
        if longueur > TAILLE_MAX:
            self._json(413, {"erreur": "fichiers trop volumineux"})
            return
        try:
            requete = json.loads(self.rfile.read(longueur) or b"{}")
            with ETAT.verrou:
                if self.path == "/api/analyser":
                    session = analyser_fichiers(requete)
                    ETAT.ajouter(session)
                    reponse = rendre({**requete, "session": session.id})
                    reponse.update(session=session.id, journal=session.journal,
                                   etapes=[_carte(e) for e in session.etapes])
                elif self.path == "/api/rendu":
                    reponse = rendre(requete)
                elif self.path == "/api/config-yaml":
                    cfg, _ = _config(requete.get("config"))
                    reponse = {"yaml": yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)}
                elif self.path == "/api/lire-config":
                    donnees = yaml.safe_load(requete.get("texte") or "") or {}
                    cfg, avert = _config(donnees)
                    reponse = {"config": cfg, "avertissements": avert}
                else:
                    self._json(404, {"erreur": "introuvable"})
                    return
            self._json(200, reponse)
        except (ErreurRequete, ErreurOSM, ValueError, yaml.YAMLError) as exc:
            self._json(400, {"erreur": str(exc)})
        except Exception as exc:  # noqa: BLE001 — l'interface doit toujours recevoir un message
            traceback.print_exc()
            self._json(500, {"erreur": f"erreur interne : {exc}"})


def creer_serveur(port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)


def lancer(port: int = 8765, navigateur: bool = True) -> None:
    try:
        serveur = creer_serveur(port)
    except OSError:
        serveur = creer_serveur(0)  # port occupé : port libre au hasard
    url = f"http://127.0.0.1:{serveur.server_address[1]}/"
    print(f"Interface roadbook : {url}  (Ctrl+C pour arrêter)")
    if navigateur:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        serveur.server_close()
