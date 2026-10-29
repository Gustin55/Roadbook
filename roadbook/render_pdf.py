"""Rendu PDF vectoriel avec ReportLab."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import numpy as np
from reportlab.lib.colors import Color, black, white
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from . import __version__, libelles
from .export import formater_km, heure_depart
from .geometry import vers_plan_local
from .instructions import Instruction
from .layout import Gabarit, Page, paginer
from .poi import PointInteret
from .symbols import dessiner_schema

GRIS_TC = Color(0.84, 0.84, 0.84)
GRIS_BANDEAU = Color(0.35, 0.35, 0.35)
GRIS_ALTERNE = Color(0.95, 0.95, 0.95)
GRIS_TRACE = Color(0.7, 0.7, 0.7)

POLICE = "Helvetica"
GRAS = "Helvetica-Bold"


class Couleurs:
    def __init__(self, actives: bool):
        if actives:
            self.controle = Color(0.05, 0.25, 0.65)
            self.fond_controle = Color(0.88, 0.92, 1.0)
            self.danger = Color(0.75, 0.05, 0.05)
            self.fond_danger = Color(1.0, 0.88, 0.88)
        else:
            self.controle = self.danger = black
            self.fond_controle = Color(0.86, 0.86, 0.86)
            self.fond_danger = Color(0.93, 0.93, 0.93)


# --------------------------------------------------------------------------
# Texte
# --------------------------------------------------------------------------


def abreger(texte: str, abreviations: dict[str, str]) -> str:
    for long, court in sorted(abreviations.items(), key=lambda kv: -len(kv[0])):
        texte = re.sub(rf"(?<!\w){re.escape(long)}(?!\w)", court, texte, flags=re.IGNORECASE)
    return texte


def ajuster_texte(blocs: list[tuple[str, str, float]], largeur: float, hauteur: float,
                  abreviations: dict[str, str], majuscules: bool) -> tuple[list[tuple[str, str, float]], str]:
    """Coupe les textes en lignes qui tiennent dans le cadre.

    Ordre des tentatives : retour à la ligne, puis abréviations, puis police
    réduite (jusqu'à 75 %), puis troncature avec « … ».
    Retourne les lignes (texte, police, taille) et un éventuel motif d'alerte.
    """
    def couper(blocs_, echelle):
        lignes = []
        for texte, police, taille in blocs_:
            t = taille * echelle
            for morceau in texte.split("\n"):
                for ligne in simpleSplit(morceau, police, t, largeur) or [""]:
                    lignes.append((ligne, police, t))
        return lignes

    def hauteur_de(lignes):
        return sum(t * 1.18 for _, _, t in lignes)

    maj = (lambda s: s.upper()) if majuscules else (lambda s: s)
    essai = [(maj(t), p, s) for t, p, s in blocs if t]
    lignes = couper(essai, 1.0)
    if hauteur_de(lignes) <= hauteur:
        return lignes, ""
    essai = [(maj(abreger(t, abreviations)), p, s) for t, p, s in blocs if t]
    for echelle in (1.0, 0.92, 0.84, 0.75):
        lignes = couper(essai, echelle)
        if hauteur_de(lignes) <= hauteur:
            return lignes, "abrégé" if echelle == 1.0 else "abrégé et police réduite"
    gardees = []
    for l in lignes:
        if hauteur_de(gardees + [l]) > hauteur:
            break
        gardees.append(l)
    if gardees:
        texte, police, taille = gardees[-1]
        while texte and simpleSplit(texte + "…", police, taille, largeur)[1:]:
            texte = texte[:-1]
        gardees[-1] = (texte.rstrip() + "…", police, taille)
    return gardees, "texte tronqué"


# --------------------------------------------------------------------------
# Rendu
# --------------------------------------------------------------------------


class RenduPDF:
    def __init__(self, cfg: dict, gab: Gabarit, pages: list[Page]):
        self.cfg = cfg
        self.aff = cfg["affichage"]
        self.gab = gab
        self.pages = pages
        self.couleurs = Couleurs(self.aff["couleurs"])
        self.avertissements: list[str] = []
        self.e = gab.echelle_police

    # -- utilitaires -------------------------------------------------------

    def km(self, v: float, total: bool = True) -> str:
        d = self.aff["decimales_total"] if total else self.aff["decimales_partiel"]
        return formater_km(v, d, self.aff["separateur_decimal"])

    def texte(self, c, x, y, s, police=POLICE, taille=9, couleur=black, align="g"):
        c.setFont(police, taille)
        c.setFillColor(couleur)
        {"g": c.drawString, "d": c.drawRightString, "c": c.drawCentredString}[align](x, y, s)

    # -- page --------------------------------------------------------------

    def generer(self, chemin: str | Path) -> None:
        c = Canvas(str(chemin), pagesize=(self.pages[0].largeur, self.pages[0].hauteur))
        ep = self.cfg["epreuve"]
        c.setTitle(f"Road book – {ep['nom']}")
        c.setAuthor(ep.get("equipage") or "")
        c.setCreator(f"roadbook {__version__}")
        c.setSubject("Road book généré à partir d'une trace GPX")
        etape_signee = None
        for page in self.pages:
            c.setPageSize((page.largeur, page.hauteur))
            if page.type == "legende":
                c.bookmarkPage("legende")
                c.addOutlineEntry("Légende", "legende", level=0)
                self.page_legende(c, page)
            else:
                if page.etape is not etape_signee:
                    etape_signee = page.etape
                    cle = f"etape{page.numero}"
                    c.bookmarkPage(cle)
                    c.addOutlineEntry(page.etape.nom, cle, level=0)
                if page.type == "garde":
                    self.page_garde(c, page)
                else:
                    if page.cases:
                        cle = f"p{page.numero}"
                        c.bookmarkPage(cle)
                        premier, dernier = page.cases[0], page.cases[-1]
                        c.addOutlineEntry(
                            f"Cases {premier.numero}–{dernier.numero} (km {self.km(premier.km_total)}"
                            f" – {self.km(dernier.km_total)})", cle, level=1)
                    self.page_cases(c, page)
            c.showPage()
        c.save()

    def entete(self, c, page: Page, titre_droite: str | None = None) -> float:
        """Bandeau d'en-tête ; retourne l'ordonnée sous le bandeau."""
        g, e = self.gab, self.e
        ep = self.cfg["epreuve"]
        haut = page.hauteur - g.marge
        x0, x1 = g.marge, page.largeur - g.marge
        nom_etape = page.etape.nom if page.etape else "Légende"
        self.texte(c, x0, haut - 9 * e, f"RB : {nom_etape}", GRAS, 9 * e)
        infos = []
        if page.etape is not None:
            longueur = page.etape.trace.longueur / 1000
            infos.append(f"RB km {formater_km(longueur, 1, self.aff['separateur_decimal'])}")
            if page.type == "cases":
                infos.append(f"p {page.numero_dans_etape} / {page.pages_etape}")
        depart = heure_depart(self.cfg)
        if depart:
            infos.append(f"départ prévu {depart.strftime('%H:%M')}")
        self.texte(c, x0, haut - 18 * e, "  ·  ".join(infos), POLICE, 7.5 * e)
        nom = titre_droite or ep["nom"]
        taille = 13 * e
        while c.stringWidth(nom, GRAS, taille) > (x1 - x0) * 0.5 and taille > 7:
            taille -= 0.5
        self.texte(c, x1, haut - 11 * e, nom, GRAS, taille, align="d")
        if ep.get("equipage"):
            self.texte(c, x1, haut - 19 * e, ep["equipage"], POLICE, 7 * e, align="d")
        y = page.hauteur - g.marge - g.entete
        c.setStrokeColor(black)
        c.setLineWidth(1.2)
        c.line(x0, y + 1.5 * mm, x1, y + 1.5 * mm)
        return y

    def pied(self, c, page: Page) -> None:
        g = self.gab
        y = g.marge
        self.texte(c, page.largeur / 2, y, str(page.numero), GRAS, 10 * self.e, align="c")
        self.texte(c, g.marge, y, f"roadbook {__version__}", POLICE, 6, Color(0.5, 0.5, 0.5))

    def page_cases(self, c, page: Page) -> None:
        g, e = self.gab, self.e
        y = self.entete(c, page)
        x0 = g.marge
        c1, c2, c3 = g.colonnes
        # bandeau de titres des colonnes
        y -= g.titres_colonnes
        c.setFillColor(GRIS_BANDEAU)
        c.rect(x0, y, g.largeur_utile, g.titres_colonnes, stroke=0, fill=1)
        ty = y + g.titres_colonnes * 0.3
        self.texte(c, x0 + 2 * mm, ty, "km Total / Partiel", GRAS, 7.5 * e, white)
        self.texte(c, x0 + c1 + c2 / 2, ty, "Schéma", GRAS, 7.5 * e, white, "c")
        self.texte(c, x0 + c1 + c2 + c3 / 2, ty, "Commentaires", GRAS, 7.5 * e, white, "c")
        for k, instr in enumerate(page.cases):
            y -= g.hauteur_case
            self.case(c, instr, x0, y, k)
        if g.mini_carte and page.etape is not None:
            self.mini_carte(c, page, x0, g.marge + g.pied, g.largeur_utile, g.mini_carte - 3 * mm)
        self.pied(c, page)

    def case(self, c, instr: Instruction, x0: float, y: float, rang: int) -> None:
        g, e = self.gab, self.e
        c1, c2, c3 = g.colonnes
        hc = g.hauteur_case
        coul = self.couleurs
        controle, niveau = instr.est_controle, instr.niveau_danger

        fond = None
        if controle:
            fond = coul.fond_controle
        elif niveau:
            fond = coul.fond_danger
        elif self.aff["lignes_alternees"] and rang % 2 == 1:
            fond = GRIS_ALTERNE
        if fond is not None:
            c.setFillColor(fond)
            c.rect(x0 + c1 + c2, y, c3, hc, stroke=0, fill=1)

        # grille
        c.setStrokeColor(black)
        c.setLineWidth(0.9)
        c.rect(x0, y, c1 + c2 + c3, hc, stroke=1, fill=0)
        c.line(x0 + c1, y, x0 + c1, y + hc)
        c.line(x0 + c1 + c2, y, x0 + c1 + c2, y + hc)

        # distances : TC en grand dans un cartouche gris, partiel en bas à droite
        tc = self.km(instr.km_total)
        taille_tc = 19 * e
        while c.stringWidth(tc, GRAS, taille_tc) > c1 - 4 * mm and taille_tc > 9:
            taille_tc -= 0.5
        hauteur_cartouche = taille_tc * 1.35
        c.setFillColor(GRIS_TC)
        c.rect(x0 + 1.2 * mm, y + hc - hauteur_cartouche - 1.2 * mm, c1 - 2.4 * mm, hauteur_cartouche,
               stroke=0, fill=1)
        self.texte(c, x0 + 2.2 * mm, y + hc - hauteur_cartouche - 1.2 * mm + taille_tc * 0.33, tc, GRAS,
                   taille_tc)
        if instr.type != "depart":
            self.texte(c, x0 + c1 - 1.8 * mm, y + 2 * mm, self.km(instr.km_partiel, total=False), GRAS,
                       14 * e, align="d")
        self.texte(c, x0 + 1.5 * mm, y + 1.5 * mm, str(instr.numero), POLICE, 7 * e)

        # schéma
        dessiner_schema(c, x0 + c1 + 1 * mm, y + 1 * mm, c2 - 2 * mm, hc - 2 * mm, instr.type, instr.angle,
                        instr.pois, self.cfg["calcul"]["sens_circulation"], coul.controle, coul.danger)

        # commentaires
        marge_t = 2 * mm
        largeur_t = c3 - 2 * marge_t
        cap = ""
        if self.aff["afficher_cap"] and instr.cap_sortie is not None and instr.type != "arrivee":
            cap = f"C.{instr.cap_sortie % 360:03.0f}"
        hauteur_cap = 11 * e * 1.3 if cap else 0
        blocs: list[tuple[str, str, float]] = []
        codes = " ".join(p.code for p in instr.pois if p.type == "controle" and p.code)
        if codes:
            blocs.append((codes, GRAS, 12.5 * e))
        blocs.append((instr.description, GRAS, 12.5 * e))
        for note in instr.notes:
            blocs.append((note, POLICE, 10.5 * e))
        lignes, alerte = ajuster_texte(blocs, largeur_t, hc - 2 * marge_t - hauteur_cap,
                                       self.cfg["abreviations"], self.aff["majuscules"])
        if alerte:
            self.avertissements.append(f"Case {instr.numero} ({instr.etape}) : {alerte}")
        ty = y + hc - marge_t
        for ligne, police, taille in lignes:
            ty -= taille * 1.18
            couleur = black
            if police == GRAS and controle:
                couleur = coul.controle
            self.texte(c, x0 + c1 + c2 + marge_t, ty + taille * 0.18, ligne, police, taille, couleur)
        if cap:
            self.texte(c, x0 + c1 + c2 + c3 - marge_t, y + 1.8 * mm, cap, GRAS, 11 * e, align="d")

        # mise en évidence : cadre épais autour de toute la case
        if controle or niveau:
            c.setStrokeColor(coul.controle if controle else coul.danger)
            c.setLineWidth(2.6)
            c.rect(x0 + 1.3, y + 1.3, c1 + c2 + c3 - 2.6, hc - 2.6, stroke=1, fill=0)

    # -- cartes --------------------------------------------------------------

    def trace_plane(self, etape, n_max: int = 1500):
        tr = etape.trace
        pas = max(1, len(tr.s) // n_max)
        lat0, lon0 = float(tr.lat.mean()), float(tr.lon.mean())
        x, y = vers_plan_local(tr.lat[::pas], tr.lon[::pas], lat0, lon0)
        return tr.s[::pas], x, y, (lat0, lon0)

    def dessiner_carte(self, c, etape, x, y, w, h, cases: list[Instruction], s_debut=None, s_fin=None,
                       marquer_pois=False):
        s, px, py, origine = self.trace_plane(etape)
        etendue = max(px.max() - px.min(), py.max() - py.min(), 1.0)
        echelle = min((w - 8 * mm) / max(px.max() - px.min(), 1.0), (h - 8 * mm) / max(py.max() - py.min(), 1.0))
        cx_, cy_ = (px.max() + px.min()) / 2, (py.max() + py.min()) / 2

        def proj(xx, yy):
            return x + w / 2 + (xx - cx_) * echelle, y + h / 2 + (yy - cy_) * echelle

        c.saveState()
        c.setStrokeColor(black)
        c.setLineWidth(0.6)
        c.rect(x, y, w, h, stroke=1, fill=0)
        p = c.beginPath()
        p.rect(x, y, w, h)
        c.clipPath(p, stroke=0, fill=0)

        def polyligne(masque, couleur, epaisseur):
            idx = np.flatnonzero(masque)
            if len(idx) < 2:
                return
            chemin = c.beginPath()
            # coupe la polyligne là où le masque s'interrompt
            debut = True
            for k, i in enumerate(idx):
                if k > 0 and i != idx[k - 1] + 1:
                    debut = True
                X, Y = proj(px[i], py[i])
                chemin.moveTo(X, Y) if debut else chemin.lineTo(X, Y)
                debut = False
            c.setStrokeColor(couleur)
            c.setLineWidth(epaisseur)
            c.setLineJoin(1)
            c.drawPath(chemin, stroke=1, fill=0)

        polyligne(np.ones(len(s), bool), GRIS_TRACE if s_debut is not None else black, 1.2)
        if s_debut is not None:
            polyligne((s >= s_debut - 1) & (s <= s_fin + 1), black, 2.4)
        tr = etape.trace
        for instr in cases:
            X, Y = proj(*vers_plan_local(*tr.position(instr.s_m), *origine))
            couleur = self.couleurs.controle if instr.est_controle else (
                self.couleurs.danger if instr.niveau_danger else black)
            c.setFillColor(white)
            c.setStrokeColor(couleur)
            c.setLineWidth(0.8)
            c.circle(float(X), float(Y), 1.4 * mm, stroke=1, fill=1)
            self.texte(c, float(X), float(Y) - 0.8 * mm, str(instr.numero), GRAS, 5.5, couleur, "c")
        if marquer_pois:
            for poi in etape.pois:
                if poi.type != "controle" or poi.s_m is None:
                    continue
                X, Y = proj(*vers_plan_local(*tr.position(poi.s_m), *origine))
                self.texte(c, float(X) + 2 * mm, float(Y) + 1.5 * mm, poi.code or "CP", GRAS, 7,
                           self.couleurs.controle)
        # départ (rond « D ») et arrivée (carré « A »)
        for (xx, yy), lettre in ((proj(px[0], py[0]), "D"), (proj(px[-1], py[-1]), "A")):
            r = 2.2 * mm
            c.setFillColor(black)
            if lettre == "D":
                c.circle(float(xx), float(yy), r, stroke=0, fill=1)
            else:
                c.rect(float(xx) - r, float(yy) - r, 2 * r, 2 * r, stroke=0, fill=1)
            self.texte(c, float(xx), float(yy) - 1.1 * mm, lettre, GRAS, 7, white, "c")
        nx, ny = x + w - 5 * mm, y + h - 9 * mm
        c.setStrokeColor(black)
        c.setFillColor(black)
        c.setLineWidth(1)
        c.line(nx, ny, nx, ny + 5 * mm)
        d = c.beginPath()
        d.moveTo(nx, ny + 6 * mm); d.lineTo(nx - 1.2 * mm, ny + 4 * mm); d.lineTo(nx + 1.2 * mm, ny + 4 * mm)
        d.close()
        c.drawPath(d, stroke=0, fill=1)
        self.texte(c, nx, ny - 3 * mm, "N", GRAS, 7, align="c")
        # échelle graphique
        longueur_m = 10 ** np.floor(np.log10(etendue / 4))
        for f in (5, 2):
            if longueur_m * f * echelle < w / 4:
                longueur_m *= f
                break
        ex, ey = x + 3 * mm, y + 3 * mm
        c.setLineWidth(1.2)
        c.line(ex, ey, ex + longueur_m * echelle, ey)
        etiquette = f"{longueur_m / 1000:g} km" if longueur_m >= 1000 else f"{longueur_m:g} m"
        self.texte(c, ex, ey + 1.2 * mm, etiquette, POLICE, 6)
        c.restoreState()

    def mini_carte(self, c, page: Page, x, y, w, h) -> None:
        if not page.cases:
            return
        self.dessiner_carte(c, page.etape, x, y, w, h, page.cases, page.cases[0].s_m, page.cases[-1].s_m)

    # -- pages annexes ----------------------------------------------------------

    def page_garde(self, c, page: Page) -> None:
        g, e = self.gab, self.e
        etape = page.etape
        y = self.entete(c, page)
        x0, w = g.marge, g.largeur_utile
        y -= 12 * mm
        taille = 20 * e
        while c.stringWidth(etape.nom, GRAS, taille) > w and taille > 9:
            taille -= 0.5
        self.texte(c, x0 + w / 2, y, etape.nom, GRAS, taille, align="c")
        cases = [i for i in self._instructions_etape(etape)]
        longueur = etape.trace.longueur / 1000
        vitesse = self.cfg["epreuve"]["vitesse_moyenne_kmh"]
        lignes = [
            ("Distance", f"{formater_km(longueur, 2, self.aff['separateur_decimal'])} km"),
            ("Cases", str(len(cases))),
        ]
        if vitesse:
            duree = timedelta(hours=longueur / vitesse)
            h_, m_ = divmod(round(duree.total_seconds() / 60), 60)
            lignes.append(("Durée estimée", f"{h_} h {m_:02d} (à {vitesse:g} km/h de moyenne)"))
            depart = heure_depart(self.cfg)
            if depart:
                lignes.append(("Départ / arrivée prévus",
                               f"{depart.strftime('%H:%M')} / {(depart + duree).strftime('%H:%M')}"))
        if etape.trace.ele is not None:
            d = np.diff(etape.trace.ele)
            lignes.append(("Dénivelé", f"+{d[d > 0].sum():.0f} m / {d[d < 0].sum():.0f} m"))
        controles = [i for i in cases if i.est_controle]
        if controles:
            lignes.append(("Contrôles", ", ".join(
                f"{' '.join(p.code or 'CP' for p in i.pois if p.type == 'controle')} (km {self.km(i.km_total)})"
                for i in controles)))
        dangers = [i for i in cases if i.niveau_danger]
        if dangers:
            lignes.append(("Dangers", ", ".join(f"case {i.numero} (km {self.km(i.km_total)})" for i in dangers)))
        y -= 10 * mm
        largeur_lib = 38 * mm * e
        for lib, val in lignes:
            morceaux = simpleSplit(val, POLICE, 10 * e, w - largeur_lib)
            self.texte(c, x0, y, lib, GRAS, 10 * e)
            for m in morceaux:
                self.texte(c, x0 + largeur_lib, y, m, POLICE, 10 * e)
                y -= 12 * e
            y -= 2 * e
        bas = g.marge + g.pied
        if y - bas > 40 * mm:
            self.dessiner_carte(c, etape, x0, bas, w, y - bas - 4 * mm, [], marquer_pois=True)
        self.pied(c, page)

    def _instructions_etape(self, etape):
        for p in self.pages:
            if p.etape is etape and p.type == "cases":
                yield from p.cases

    def page_legende(self, c, page: Page) -> None:
        g, e = self.gab, self.e
        y = self.entete(c, page, titre_droite=self.cfg["epreuve"]["nom"])
        x0, w = g.marge, g.largeur_utile
        y -= 8 * mm
        self.texte(c, x0, y, "Légende des schémas", GRAS, 12 * e)

        def poi(type_, **kw):
            return PointInteret(0, 0, type_, **kw)

        exemples = [
            ("TD", "rappel", 0, []), ("LÉG. AD", "virage", 30, []), ("AD", "virage", 90, []),
            ("AG FORT", "virage", -120, []), ("ÉPINGLE AG", "virage", -160, []),
            ("DEMI-TOUR", "demi_tour", 180, []), ("RP SORTIE TD", "rond_point", 0, []),
            ("RP SORTIE AD", "rond_point", 90, []), ("RP SORTIE AG", "rond_point", -90, []),
            ("DÉPART", "depart", 0, []), ("ARRIVÉE", "arrivee", 0, []),
            ("CONTRÔLE", "rappel", 0, [poi("controle", code="CS1")]),
            ("DANGER !!!", "rappel", 0, [poi("danger", niveau=3)]),
            ("CARBURANT", "rappel", 0, [poi("ravitaillement")]),
            ("PASSAGE À NIVEAU", "rappel", 0, [poi("passage_niveau")]),
            ("CARREFOUR", "rappel", 0, [poi("carrefour")]),
        ]
        colonnes = 6 if w < 180 * mm else 7
        cote = w / colonnes
        legende_h = 4.5 * mm
        y -= 3 * mm
        sens = self.cfg["calcul"]["sens_circulation"]
        for k, (lib, type_, angle, pois) in enumerate(exemples):
            col, rang = k % colonnes, k // colonnes
            bx = x0 + col * cote
            by = y - (rang + 1) * (cote + legende_h) + legende_h
            c.setStrokeColor(Color(0.6, 0.6, 0.6))
            c.setLineWidth(0.5)
            c.rect(bx + 0.5 * mm, by, cote - 1 * mm, cote - 1 * mm, stroke=1, fill=0)
            dessiner_schema(c, bx + 1 * mm, by + 0.5 * mm, cote - 2 * mm, cote - 2 * mm, type_, angle, pois, sens,
                            self.couleurs.controle, self.couleurs.danger)
            self.texte(c, bx + cote / 2, by - 3.2 * mm, lib, GRAS, 6.5 * e, align="c")
        rangs = -(-len(exemples) // colonnes)
        y -= rangs * (cote + legende_h) + 6 * mm
        self.texte(c, x0, y, "Abréviations", GRAS, 12 * e)
        y -= 6 * mm
        for abr, sens_ in libelles.legende_abreviations(self.cfg["calcul"]["tranches_angle_deg"]):
            self.texte(c, x0, y, abr, GRAS, 8.5 * e)
            self.texte(c, x0 + 24 * mm, y, sens_, POLICE, 8.5 * e)
            y -= 4.3 * mm * max(1.0, e * 0.9)
        y -= 2 * mm
        note = ("Schémas : on arrive par le bas (point noir), le haut de la case est « tout droit » et non le nord. "
                "Distances en km depuis le départ de l'étape (Total) et depuis la case précédente (Partiel). "
                "Rond-points : sens de circulation "
                + ("antihoraire (circulation à droite)." if sens == "droite" else "horaire (circulation à gauche)."))
        for ligne in simpleSplit(note, POLICE, 7.5 * e, w):
            if y < g.marge + g.pied + 2 * mm:
                break
            self.texte(c, x0, y, ligne, POLICE, 7.5 * e)
            y -= 9.5 * e
        self.pied(c, page)


def generer_pdf(etapes, instructions, cfg: dict, chemin: str | Path) -> tuple[int, list[str]]:
    """Écrit le PDF ; retourne (nombre de pages, avertissements de mise en page)."""
    gab, pages = paginer(etapes, instructions, cfg)
    rendu = RenduPDF(cfg, gab, pages)
    rendu.generer(chemin)
    return len(pages), rendu.avertissements

