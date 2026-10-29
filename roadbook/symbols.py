"""Pictogrammes vectoriels du road book (« tulipes »), dessinés avec ReportLab.

Convention (inspirée des road books de rallye-raid) : on arrive par le bas de
la case (point de départ marqué d'un rond plein), on rejoint le centre de la
manœuvre, et la flèche indique la direction à prendre. Le haut de la case est
« tout droit », pas le nord. Tout est tracé en primitives vectorielles.
"""

from __future__ import annotations

import math

from reportlab.lib.colors import Color, black, white

GRIS = Color(0.55, 0.55, 0.55)


class Boite:
    """Zone de dessin : centre du carrefour et longueur des branches."""

    def __init__(self, x: float, y: float, w: float, h: float):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.cx = x + w / 2
        self.cy = y + h * 0.46
        self.L = min(w * 0.45, h * 0.42)
        self.trait = max(1.6, self.L * 0.12)

    def point(self, angle_deg: float, rayon: float) -> tuple[float, float]:
        """Point à ``rayon`` du centre, dans la direction ``angle_deg`` (0 = haut, + = droite)."""
        a = math.radians(angle_deg)
        return self.cx + rayon * math.sin(a), self.cy + rayon * math.cos(a)


def _fleche(c, x1, y1, x2, y2, trait: float, couleur=black) -> None:
    """Segment épais terminé par une pointe triangulaire pleine."""
    ang = math.atan2(y2 - y1, x2 - x1)
    tete = trait * 2.8
    # le trait s'arrête sous la pointe pour qu'elle reste nette
    bx, by = x2 - tete * 0.8 * math.cos(ang), y2 - tete * 0.8 * math.sin(ang)
    c.setStrokeColor(couleur)
    c.setFillColor(couleur)
    c.setLineWidth(trait)
    c.setLineCap(1)
    c.line(x1, y1, bx, by)
    _pointe(c, x2, y2, ang, tete)


def _pointe(c, x, y, ang, tete) -> None:
    p = c.beginPath()
    p.moveTo(x, y)
    p.lineTo(x - tete * math.cos(ang - 0.42), y - tete * math.sin(ang - 0.42))
    p.lineTo(x - tete * math.cos(ang + 0.42), y - tete * math.sin(ang + 0.42))
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def _entree(c, b: Boite, jusqu_a: float = 0.0) -> None:
    """Branche d'arrivée : du bas de la case jusqu'à ``jusqu_a`` sous le centre."""
    x0, y0 = b.cx, b.cy - b.L
    c.setStrokeColor(black)
    c.setFillColor(black)
    c.setLineWidth(b.trait)
    c.setLineCap(1)
    c.line(x0, y0, b.cx, b.cy - jusqu_a)
    c.circle(x0, y0, b.trait * 1.1, stroke=0, fill=1)


def virage(c, b: Boite, angle: float) -> None:
    _entree(c, b)
    if abs(angle) > 150:
        # épingle très fermée : la sortie longe l'entrée, on la décale un peu
        angle = math.copysign(150, angle)
    x2, y2 = b.point(angle, b.L)
    c.setLineJoin(1)
    _fleche(c, b.cx, b.cy, x2, y2, b.trait)


def tout_droit(c, b: Boite) -> None:
    _entree(c, b)
    _fleche(c, b.cx, b.cy, *b.point(0, b.L), b.trait)


def demi_tour(c, b: Boite, angle: float) -> None:
    """U complet, tourné du côté du virage."""
    s = 1 if angle >= 0 else -1
    r = b.L * 0.38
    x0, y0 = b.cx - s * r, b.cy - b.L
    c.setStrokeColor(black)
    c.setFillColor(black)
    c.setLineWidth(b.trait)
    c.setLineCap(1)
    c.circle(x0, y0, b.trait * 1.1, stroke=0, fill=1)
    haut = b.cy + b.L * 0.35
    c.line(x0, y0, x0, haut)
    p = c.beginPath()
    p.arc(b.cx - r, haut - r, b.cx + r, haut + r, startAng=180 if s > 0 else 0, extent=-180 * s)
    c.drawPath(p, stroke=1, fill=0)
    _fleche(c, b.cx + s * r, haut, b.cx + s * r, b.cy - b.L * 0.55, b.trait)


def rond_point(c, b: Boite, angle: float, sens_circulation: str = "droite") -> None:
    r = b.L * 0.38
    # anneau complet en trait fin
    c.setStrokeColor(black)
    c.setLineWidth(max(0.8, b.trait * 0.35))
    c.circle(b.cx, b.cy, r, stroke=1, fill=0)
    _entree(c, b, jusqu_a=r)
    # chemin parcouru sur l'anneau (angles ReportLab : degrés, antihoraire depuis +x)
    phi = 90 - angle
    if sens_circulation == "droite":
        etendue = 180 - angle
        if etendue < 20:
            etendue += 360
        if etendue > 345:
            etendue = 345
    else:
        etendue = -(180 + angle)
        if etendue > -20:
            etendue -= 360
        if etendue < -345:
            etendue = -345
    c.setLineWidth(b.trait)
    p = c.beginPath()
    p.arc(b.cx - r, b.cy - r, b.cx + r, b.cy + r, startAng=-90, extent=etendue)
    c.drawPath(p, stroke=1, fill=0)
    fin = math.radians(-90 + etendue)
    xs, ys = b.cx + r * math.cos(fin), b.cy + r * math.sin(fin)
    # sortie radiale vers l'extérieur
    _fleche(c, xs, ys, b.cx + b.L * math.cos(math.radians(phi)), b.cy + b.L * math.sin(math.radians(phi)),
            b.trait)


def depart(c, b: Boite) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(b.trait * 1.4)
    c.line(b.cx - b.L * 0.6, b.cy - b.L, b.cx + b.L * 0.6, b.cy - b.L)
    _fleche(c, b.cx, b.cy - b.L, b.cx, b.cy + b.L, b.trait)


def arrivee(c, b: Boite) -> None:
    _entree(c, b)
    c.setLineWidth(b.trait)
    c.line(b.cx, b.cy - b.L, b.cx, b.cy + b.L * 0.2)
    # drapeau à damier
    n, cote = 4, b.L * 0.22
    x0, y0 = b.cx - 2 * cote, b.cy + b.L * 0.2
    c.setLineWidth(0.6)
    for i in range(n):
        for j in range(3):
            c.setFillColor(black if (i + j) % 2 == 0 else white)
            c.rect(x0 + i * cote, y0 + j * cote, cote, cote, stroke=1, fill=1)


# --------------------------------------------------------------------------
# Éléments ajoutés selon les points d'intérêt
# --------------------------------------------------------------------------


def route_croisee(c, b: Boite) -> None:
    """Route transversale (carrefour) en trait fin."""
    c.setStrokeColor(black)
    c.setLineWidth(max(0.8, b.trait * 0.4))
    c.line(b.cx - b.L, b.cy, b.cx + b.L, b.cy)


def voie_ferree(c, b: Boite) -> None:
    y = b.cy - b.L * 0.45
    c.setStrokeColor(black)
    c.setLineWidth(0.9)
    for dy in (-b.L * 0.07, b.L * 0.07):
        c.line(b.x + b.w * 0.08, y + dy, b.x + b.w * 0.92, y + dy)
    pas = b.L * 0.16
    x = b.x + b.w * 0.1
    while x < b.x + b.w * 0.9:
        c.line(x, y - b.L * 0.13, x, y + b.L * 0.13)
        x += pas


def pastille_code(c, b: Boite, texte: str, couleur=black) -> None:
    """Code de contrôle cerclé (ex. « CS10 ») en haut à gauche."""
    taille = max(6.5, b.L * 0.26)
    c.setFont("Helvetica-Bold", taille)
    largeur = c.stringWidth(texte, "Helvetica-Bold", taille)
    w, h = largeur + taille * 0.9, taille * 1.5
    x, y = b.x + 2, b.y + b.h - h - 2
    c.setStrokeColor(couleur)
    c.setFillColor(white)
    c.setLineWidth(1.4)
    c.roundRect(x, y, w, h, h / 2, stroke=1, fill=1)
    c.setFillColor(couleur)
    c.drawCentredString(x + w / 2, y + h * 0.3, texte)


def danger(c, b: Boite, niveau: int, decale: bool = False, couleur=black) -> None:
    """« ! », « !! » ou « !!! » en haut (à gauche, ou à droite si une pastille y est)."""
    taille = max(9, b.L * 0.5)
    texte = "!" * max(1, min(3, niveau))
    c.setFont("Helvetica-Bold", taille)
    c.setFillColor(couleur)
    y = b.y + b.h - taille * 0.85
    if decale:
        c.drawRightString(b.x + b.w - 3, y, texte)
    else:
        c.drawString(b.x + 3, y, texte)


def pompe(c, b: Boite) -> None:
    """Petite pompe à carburant en haut à droite."""
    u = max(1.2, b.L * 0.045)
    x, y = b.x + b.w - 9 * u, b.y + b.h - 12 * u
    c.setFillColor(black)
    c.setStrokeColor(black)
    c.rect(x, y, 5 * u, 8 * u, stroke=0, fill=1)
    c.setFillColor(white)
    c.rect(x + u, y + 4.5 * u, 3 * u, 2.5 * u, stroke=0, fill=1)
    c.setLineWidth(u * 0.8)
    c.line(x + 5 * u, y + 6 * u, x + 7 * u, y + 5 * u)
    c.line(x + 7 * u, y + 5 * u, x + 7 * u, y + 1.5 * u)


def panneau_stop(c, b: Boite) -> None:
    r = max(5, b.L * 0.2)
    x0, y0 = b.x + b.w - r - 3, b.y + b.h - r - 3
    p = c.beginPath()
    for k in range(8):
        a = math.radians(22.5 + 45 * k)
        (p.moveTo if k == 0 else p.lineTo)(x0 + r * math.cos(a), y0 + r * math.sin(a))
    p.close()
    c.setFillColor(black)
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", r * 0.62)
    c.drawCentredString(x0, y0 - r * 0.22, "STOP")


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------


def dessiner_schema(c, x, y, w, h, type_: str, angle: float | None = None, pois=(),
                    sens_circulation: str = "droite", couleur_controle=black, couleur_danger=black) -> None:
    """Dessine le schéma complet d'une case dans le rectangle (x, y, w, h)."""
    b = Boite(x, y, w, h)
    types_poi = {p.type for p in pois}
    c.saveState()
    if "passage_niveau" in types_poi:
        voie_ferree(c, b)
    if "carrefour" in types_poi:
        route_croisee(c, b)
    if type_ == "virage":
        virage(c, b, angle or 0.0)
    elif type_ == "demi_tour":
        demi_tour(c, b, angle or 180.0)
    elif type_ == "rond_point":
        rond_point(c, b, angle or 0.0, sens_circulation)
    elif type_ == "depart":
        depart(c, b)
    elif type_ == "arrivee":
        arrivee(c, b)
    else:
        tout_droit(c, b)

    codes = [p.code or "CP" for p in pois if p.type == "controle"]
    if codes:
        pastille_code(c, b, codes[0], couleur_controle)
    niveau = max((p.niveau for p in pois if p.type == "danger"), default=0)
    if niveau:
        danger(c, b, niveau, decale=bool(codes), couleur=couleur_danger)
    if "ravitaillement" in types_poi and not (niveau and codes):
        pompe(c, b)
    elif "stop" in types_poi and not (niveau and codes):
        panneau_stop(c, b)
    c.restoreState()
