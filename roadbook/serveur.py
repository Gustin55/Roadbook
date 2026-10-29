"""Interface graphique : petit serveur web local (bibliothèque standard uniquement).

    roadbook interface            # ouvre http://127.0.0.1:8765 dans le navigateur

Le serveur n'écoute que sur la machine locale. Les fichiers envoyés restent en
mémoire (et dans un dossier temporaire le temps de la lecture).
"""

from __future__ import annotations

import base64
import io
import json
import math
import tempfile
import threading
import traceback
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

from . import __version__
from .config import DEFAUTS, ErreurConfig, depuis_dict
from .export import exporter_csv, rapport
from .geometry import vers_plan_local
from .gpx_loader import charger_gpx
from .geometry import projeter_sur_trace
from .instructions import (Etape, Instruction, analyser, generer_instructions, rattacher_pois,
                           reechantillonner_traces)
from .modifications import appliquer, identifiant_case
from .options import SECTIONS, empreinte_analyse
from .osm import ErreurOSM, charger_reseau
from .poi import PointInteret, charger_csv
from .layout import paginer
from .render_pdf import generer_pdf

try:  # aperçu des pages en images (facultatif : sinon le navigateur affiche le PDF)
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

TAILLE_MAX = 300 * 1024 * 1024
SESSIONS_MAX = 6
RENDUS_GARDES = 3
IMAGES_GARDEES = 300
VERROU_PDFIUM = threading.Lock()  # pdfium n'est pas réentrant


@dataclass
class Session:
    id: str
    etapes: list[Etape]
    avertissements: list[str]
    osm: bool
    empreinte: str
    journal: list[str] = field(default_factory=list)
    rendus: dict[int, bytes] = field(default_factory=dict)  # révision -> PDF
    images: dict[tuple, bytes] = field(default_factory=dict)  # (révision, page, largeur) -> PNG
    revision: int = 0

    def garder_pdf(self, pdf: bytes) -> int:
        self.revision += 1
        self.rendus[self.revision] = pdf
        for ancienne in sorted(self.rendus)[:-RENDUS_GARDES]:
            del self.rendus[ancienne]
        self.images = {k: v for k, v in self.images.items() if k[0] in self.rendus}
        return self.revision

    def image(self, revision: int, numero: int, largeur: int) -> bytes:
        cle = (revision, numero, largeur)
        if cle not in self.images:
            pdf = self.rendus.get(revision)
            if pdf is None:
                raise ErreurRequete("aperçu périmé")
            with VERROU_PDFIUM:
                doc = pdfium.PdfDocument(pdf)
                try:
                    if not 1 <= numero <= len(doc):
                        raise ErreurRequete("page inexistante")
                    page = doc[numero - 1]
                    echelle = largeur / page.get_width()
                    tampon = io.BytesIO()
                    page.render(scale=echelle).to_pil().save(tampon, format="PNG", optimize=False)
                finally:
                    doc.close()
            if len(self.images) > IMAGES_GARDEES:
                self.images.clear()
            self.images[cle] = tampon.getvalue()
        return self.images[cle]


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
            "points": [[round(float(a), 1), round(float(b), 1)] for a, b in zip(x, y)],
            "latlon": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(tr.lat[idx], tr.lon[idx])]}


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
        "lat": round(i.lat, 6), "lon": round(i.lon, 6),
        "manuel": getattr(i, "manuel", False),
    }


def _page_info(p) -> dict:
    if p.type == "legende":
        titre = "Légende"
    elif p.type == "garde":
        titre = f"{p.etape.nom} · page de garde"
    else:
        titre = f"{p.etape.nom} · {p.numero_dans_etape}/{p.pages_etape}"
        if p.cases:
            titre += f" · cases {p.cases[0].numero}–{p.cases[-1].numero}"
    return {"numero": p.numero, "titre": titre, "largeur": round(p.largeur, 2), "hauteur": round(p.hauteur, 2),
            "cases": [identifiant_case(i) for i in p.cases]}


def _exemple() -> dict:
    dossier = resources.files("roadbook").joinpath("web/exemple")
    config = yaml.safe_load(dossier.joinpath("config.yaml").read_text(encoding="utf-8"))
    return {
        "gpx": {"nom": "exemple.gpx", "texte": dossier.joinpath("exemple.gpx").read_text(encoding="utf-8")},
        "pois": [{"nom": "poi.csv", "texte": dossier.joinpath("poi.csv").read_text(encoding="utf-8")}],
        "config": config,
    }


TYPES_POINTS = {"controle", "danger", "ravitaillement", "passage_niveau", "stop", "carrefour", "info"}


def points_carte(modifications: dict | None) -> list[PointInteret]:
    """Points (checkpoints, dangers…) posés sur la carte de l'interface."""
    resultat = []
    for pt in (modifications or {}).get("points") or []:
        try:
            lat, lon = float(pt["lat"]), float(pt["lon"])
            km = float(pt["km"]) if pt.get("km") is not None else None
        except (KeyError, TypeError, ValueError):
            continue
        type_ = pt.get("type") if pt.get("type") in TYPES_POINTS else "info"
        resultat.append(PointInteret(
            lat, lon, type_, str(pt.get("description") or "").strip(),
            code=str(pt.get("code") or "").strip().upper() if type_ == "controle" else "",
            niveau=max(0, min(3, int(pt.get("niveau") or (2 if type_ == "danger" else 0)))),
            km=km, etape=pt.get("etape") or None, source=f"carte:{pt.get('id', '')}"))
    return resultat


def _avec_points(session: Session, points: list[PointInteret], cfg: dict) -> tuple[list[Etape], list[str]]:
    if not points:
        return session.etapes, []
    etapes = [Etape(e.nom, e.trace, e.manoeuvres, pois=list(e.pois), remarques=e.remarques)
              for e in session.etapes]
    return etapes, rattacher_pois(etapes, points, cfg["calcul"])


def accrocher(requete: dict) -> dict:
    """Point de la trace le plus proche d'un clic sur la carte."""
    session = ETAT.sessions.get(requete.get("session", ""))
    if session is None:
        raise ErreurRequete("session expirée : relancez l'analyse")
    lat, lon = float(requete["lat"]), float(requete["lon"])
    meilleur = None
    for e in session.etapes:
        for s, ecart in projeter_sur_trace(lat, lon, e.trace, 3000.0):
            if meilleur is None or ecart < meilleur[2]:
                meilleur = (e, s, ecart)
    if meilleur is None:
        raise ErreurRequete("trop loin de la trace (plus de 3 km)")
    e, s, ecart = meilleur
    plat, plon = e.trace.position(s)
    return {"etape": e.nom, "km": round(s / 1000, 4), "lat": round(plat, 7), "lon": round(plon, 7),
            "ecart_m": round(ecart, 1)}


def exporter_gpx(requete: dict) -> str:
    """Trace et points de contrôle en GPX (pour un GPS de bord)."""
    import gpxpy.gpx

    session = ETAT.sessions.get(requete.get("session", ""))
    if session is None:
        raise ErreurRequete("session expirée : relancez l'analyse")
    cfg, _ = _config(requete.get("config"))
    etapes, _ = _avec_points(session, points_carte(requete.get("modifications")), cfg)
    gpx = gpxpy.gpx.GPX()
    gpx.creator = f"roadbook {__version__}"
    gpx.name = cfg["epreuve"]["nom"]
    for e in etapes:
        trk = gpxpy.gpx.GPXTrack(name=e.nom)
        seg = gpxpy.gpx.GPXTrackSegment()
        tr = e.trace
        for la, lo in zip(tr.lat_originaux, tr.lon_originaux):
            seg.points.append(gpxpy.gpx.GPXTrackPoint(round(float(la), 7), round(float(lo), 7)))
        trk.segments.append(seg)
        gpx.tracks.append(trk)
        for p in sorted(e.pois, key=lambda p: p.s_m or 0):
            if p.s_m is None or p.source.startswith("OSM:"):
                continue
            la, lo = tr.position(p.s_m)
            nom = p.code or {"danger": "DZ" + "!" * max(1, p.niveau)}.get(p.type, p.type.upper())
            w = gpxpy.gpx.GPXWaypoint(round(la, 7), round(lo, 7), name=nom,
                                      description=p.description or None, comment=f"{e.nom} km {p.s_m / 1000:.2f}")
            w.type = p.type
            gpx.waypoints.append(w)
    return gpx.to_xml()


def rendre(requete: dict) -> dict:
    session = ETAT.sessions.get(requete.get("session", ""))
    if session is None:
        raise ErreurRequete("session expirée : relancez l'analyse")
    cfg, avert = _config(requete.get("config"))
    points = points_carte(requete.get("modifications"))
    etapes, a = _avec_points(session, points, cfg)
    avert += a
    instructions = generer_instructions(etapes, cfg)
    instructions, ignorees = appliquer(instructions, etapes, requete.get("modifications"), cfg)
    origines = {e.nom: (float(e.trace.lat.mean()), float(e.trace.lon.mean())) for e in etapes}
    resultat = {
        "analyse_perimee": empreinte_analyse(cfg) != session.empreinte,
        "cases": [_case(i, origines) for i in instructions],
        "points": [{"id": p.source.split(":", 1)[1], "etape": p.etape if p.s_m is None else
                    next(e.nom for e in etapes if p in e.pois),
                    "km": None if p.s_m is None else round(p.s_m / 1000, 3)} for p in points],
    }
    if requete.get("pdf", True):
        _, pages = paginer(etapes, instructions, cfg)
        with tempfile.TemporaryDirectory(prefix="roadbook_") as tmp:
            chemin = Path(tmp) / "roadbook.pdf"
            attribution = "Routes © contributeurs OpenStreetMap (ODbL)" if session.osm else ""
            nb_pages, a = generer_pdf(etapes, instructions, cfg, chemin, attribution)
            resultat["revision"] = session.garder_pdf(chemin.read_bytes())
        resultat["pages"] = nb_pages
        resultat["apercu_images"] = pdfium is not None
        resultat["liste_pages"] = [_page_info(p) for p in pages]
        avert += a
    tous = session.avertissements + avert + ignorees
    resultat["avertissements"] = tous
    resultat["rapport"] = rapport(tous, instructions, etapes, cfg)
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

    def _envoyer(self, code: int, corps: bytes, type_: str, entetes: dict | None = None) -> None:
        entetes = {"Cache-Control": "no-store", **(entetes or {})}
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        for k, v in entetes.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, code: int, donnees) -> None:
        self._envoyer(code, json.dumps(donnees, ensure_ascii=False, default=str).encode("utf-8"),
                      "application/json; charset=utf-8")

    TYPES_STATIQUES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                       ".png": "image/png"}

    def _statique(self, chemin: str) -> None:
        """Bibliothèques livrées avec l'interface (Leaflet), sans accès à Internet."""
        morceaux = [m for m in chemin.split("/") if m]
        type_ = self.TYPES_STATIQUES.get(Path(chemin).suffix)
        if type_ is None or any(m in ("..", ".") or "\\" in m for m in morceaux):
            self._json(404, {"erreur": "introuvable"})
            return
        fichier = resources.files("roadbook").joinpath("web", *morceaux)
        if not fichier.is_file():
            self._json(404, {"erreur": "introuvable"})
            return
        self._envoyer(200, fichier.read_bytes(), type_, {"Cache-Control": "public, max-age=86400"})

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                self._envoyer(200, _page(), "text/html; charset=utf-8")
            elif url.path == "/api/options":
                self._json(200, {"sections": SECTIONS, "defauts": DEFAUTS, "version": __version__,
                                 "apercu_images": pdfium is not None})
            elif url.path == "/api/exemple":
                self._json(200, _exemple())
            elif url.path.startswith("/vendor/"):
                self._statique(url.path)
            elif url.path in ("/api/pdf", "/api/page"):
                session = ETAT.sessions.get(params.get("session", ""))
                if session is None:
                    raise ErreurRequete("session expirée")
                revision = int(params.get("rev", session.revision))
                if url.path == "/api/pdf":
                    pdf = session.rendus.get(revision)
                    if pdf is None:
                        raise ErreurRequete("PDF périmé : regénérez")
                    nom = params.get("nom", "roadbook.pdf").replace('"', "")
                    disposition = "attachment" if params.get("telecharger") else "inline"
                    self._envoyer(200, pdf, "application/pdf", {
                        "Content-Disposition": f'{disposition}; filename="{nom}"'})
                else:
                    if pdfium is None:
                        raise ErreurRequete("aperçu en images indisponible (pypdfium2 absent)")
                    largeur = max(200, min(3000, int(params.get("largeur", 900))))
                    png = session.image(revision, int(params.get("n", 1)), largeur)
                    self._envoyer(200, png, "image/png", {"Cache-Control": "private, max-age=3600"})
            else:
                self._json(404, {"erreur": "introuvable"})
        except (ErreurRequete, ValueError) as exc:
            self._json(400, {"erreur": str(exc)})

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
                elif self.path == "/api/accrocher":
                    reponse = accrocher(requete)
                elif self.path == "/api/gpx":
                    reponse = {"gpx": exporter_gpx(requete)}
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
