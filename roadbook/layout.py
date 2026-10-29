"""Mise en page : gabarit (dimensions) et pagination des cases.

Formats proposés :

* ``a5`` : A5 portrait, ~7 cases par page, comme les carnets 4L Trophy ;
* ``a4`` : A4 portrait, ~10 cases par page, cases plus larges ;
* ``rouleau`` : bande de largeur fixe (148 mm par défaut) dont la longueur
  suit le nombre de cases, pour imprimante à rouleau ou impression en bandes
  à recoller. Une étape trop longue est coupée en plusieurs bandes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.lib.units import mm

from .instructions import Etape, Instruction

FORMATS_MM = {"a5": (148.0, 210.0), "a4": (210.0, 297.0)}


@dataclass
class Gabarit:
    format: str
    largeur: float  # pt
    marge: float
    entete: float  # bandeau titre
    titres_colonnes: float  # bandeau « km / schéma / commentaires »
    pied: float
    hauteur_case: float
    colonnes: tuple[float, float, float]  # largeurs (pt)
    mini_carte: float  # hauteur réservée (0 si pas de mini-carte)
    echelle_police: float

    @property
    def largeur_utile(self) -> float:
        return self.largeur - 2 * self.marge

    def hauteur_page(self, nb_cases: int) -> float:
        return (2 * self.marge + self.entete + self.titres_colonnes + self.pied
                + nb_cases * self.hauteur_case + self.mini_carte)


@dataclass
class Page:
    type: str  # legende | garde | cases
    largeur: float
    hauteur: float
    etape: Etape | None = None
    cases: list[Instruction] = field(default_factory=list)
    numero_dans_etape: int = 0
    pages_etape: int = 0
    numero: int = 0  # numéro global, rempli à la fin


def construire_gabarit(cfg: dict) -> tuple[Gabarit, int]:
    """Retourne le gabarit et le nombre de cases par page."""
    aff = cfg["affichage"]
    fmt = aff["format"]
    if fmt == "rouleau":
        largeur_mm = float(aff["largeur_rouleau_mm"])
        hauteur_mm = float(aff["longueur_max_rouleau_mm"])
    else:
        largeur_mm, hauteur_mm = FORMATS_MM[fmt]
    marge = (6 if fmt != "a4" else 8) * mm
    entete = (11 if fmt != "a4" else 13) * mm
    titres = 5 * mm
    pied = (6 if fmt != "rouleau" else 4) * mm
    mini = aff["mini_carte_hauteur_mm"] * mm if aff["mini_carte"] and fmt != "rouleau" else 0.0
    largeur = largeur_mm * mm
    disponible = hauteur_mm * mm - 2 * marge - entete - titres - pied - mini
    if aff["lignes_par_page"] and fmt != "rouleau":
        par_page = int(aff["lignes_par_page"])
        hauteur_case = disponible / par_page
    else:
        hauteur_case = aff["hauteur_case_mm"] * mm
        par_page = max(1, int(disponible // hauteur_case))
        if fmt != "rouleau":
            # on répartit la place restante pour que la page soit pleine
            hauteur_case = disponible / par_page
    pct = aff["colonnes_pct"]
    utile = largeur - 2 * marge
    colonnes = tuple(utile * p / sum(pct) for p in pct)
    # les polices suivent la taille des cases (référence : case A5 de 25 mm)
    echelle = max(0.75, min(1.4, min(hauteur_case / (25 * mm), utile / (136 * mm) * 1.1)))
    return Gabarit(fmt, largeur, marge, entete, titres, pied, hauteur_case, colonnes, mini, echelle), par_page


def paginer(etapes: list[Etape], instructions: list[Instruction], cfg: dict) -> tuple[Gabarit, list[Page]]:
    gab, par_page = construire_gabarit(cfg)
    aff = cfg["affichage"]
    hauteur_std = gab.hauteur_page(par_page)
    if gab.format != "rouleau":
        hauteur_std = FORMATS_MM[gab.format][1] * mm
    # en rouleau, les pages de garde et de légende ont la hauteur d'un A5
    hauteur_annexe = hauteur_std if gab.format != "rouleau" else 210 * mm
    pages: list[Page] = []
    if aff["page_legende"]:
        pages.append(Page("legende", gab.largeur, hauteur_annexe))
    for etape in etapes:
        cases = [i for i in instructions if i.etape == etape.nom]
        if aff["page_garde"]:
            pages.append(Page("garde", gab.largeur, hauteur_annexe, etape=etape))
        morceaux = [cases[k : k + par_page] for k in range(0, len(cases), par_page)] or [[]]
        for n, morceau in enumerate(morceaux, start=1):
            h = gab.hauteur_page(len(morceau)) if gab.format == "rouleau" else hauteur_std
            pages.append(Page("cases", gab.largeur, h, etape=etape, cases=morceau,
                              numero_dans_etape=n, pages_etape=len(morceaux)))
    for i, p in enumerate(pages, start=1):
        p.numero = i
    return gab, pages
