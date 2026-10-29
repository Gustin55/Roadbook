"""Génère la trace d'exemple ``exemple.gpx`` (2 étapes synthétiques, sud marocain).

Usage : python examples/generer_exemple.py
La trace est artificielle (bruit GPS simulé de 1 m) : elle sert de jeu de
non-régression et de démonstration, pas de parcours réel.
"""

from pathlib import Path

import numpy as np

from roadbook.synthetique import Tortue, ecrire_gpx

ICI = Path(__file__).parent
LAT0, LON0 = 31.43, -4.23  # environs d'Erfoud


def etape1() -> Tortue:
    t = Tortue(cap_deg=170, pas_m=8)
    t.droit(1800)
    t.arc(400, 25)            # grande courbe : pas une instruction
    t.droit(1200)
    t.arc(8, 90)              # AD franc au carrefour
    t.droit(2600)
    t.rond_point(15, 0)       # rond-point, tout droit
    t.droit(900)
    t.arc(10, -35)            # légèrement à gauche
    t.droit(3200)
    t.arc(8, -95)             # AG
    t.droit(400)
    t.arc(8, 110)             # AD fort
    t.droit(5200)             # longue ligne droite (rappel)
    t.rond_point(14, 90)      # rond-point, sortie à droite
    t.droit(1500)
    t.arc(6, -150)            # épingle à gauche
    t.droit(1100)
    t.arc(12, 60)
    t.droit(2000)
    return t


def etape2() -> Tortue:
    t = Tortue(cap_deg=200, pas_m=8)
    t.droit(1500)
    t.arc(9, -80)
    t.droit(2200)
    t.arc(250, -30)           # courbe douce
    t.droit(900)
    t.rond_point(16, -90)     # rond-point, sortie à gauche
    t.droit(3000)
    t.arc(8, 45)
    t.droit(800)
    t.arc(5, 175)             # demi-tour
    t.droit(300)
    t.arc(8, 90)
    t.droit(2500)
    return t


def main() -> None:
    t1, t2 = etape1(), etape2()
    lat1, lon1 = t1.latlon(LAT0, LON0, bruit_m=1.0, graine=1)
    # l'étape 2 part de l'arrivée de l'étape 1
    lat2, lon2 = t2.latlon(float(lat1[-1]), float(lon1[-1]), bruit_m=1.0, graine=2)
    ele1 = 850 + 60 * np.sin(np.linspace(0, 3, len(lat1)))
    ele2 = 900 + 120 * np.sin(np.linspace(0, 2, len(lat2)))

    def sur(lat, lon, i):
        return float(lat[i]), float(lon[i])

    n1, n2 = len(lat1), len(lat2)
    waypoints = [
        ("CS1", *sur(lat1, lon1, int(n1 * 0.30)), "Tampon équipage", "controle"),
        ("DZ !!!", *sur(lat1, lon1, int(n1 * 0.55)), "Oued, passage cassant", "danger"),
        ("CS2", *sur(lat1, lon1, int(n1 * 0.85)), "", "controle"),
        ("CP3", *sur(lat2, lon2, int(n2 * 0.50)), "Contrôle de passage", "controle"),
    ]
    ecrire_gpx(
        ICI / "exemple.gpx",
        [("E1 - Erfoud boucle nord", lat1, lon1, ele1), ("E2 - Liaison sud", lat2, lon2, ele2)],
        waypoints,
    )

    # POI supplémentaires au format CSV (séparateur « ; », pratique sous Excel)
    lignes = ["lat;lon;type;description;code;niveau;km;etape"]
    la, lo = sur(lat1, lon1, int(n1 * 0.12))
    lignes.append(f"{la:.6f};{lo:.6f};info;Village : ralentir, enfants;;;;")
    la, lo = sur(lat1, lon1, int(n1 * 0.68))
    lignes.append(f"{la:.6f};{lo:.6f};ravitaillement;Station Ziz, dernier carburant avant 120 km;;;;")
    la, lo = sur(lat2, lon2, int(n2 * 0.20))
    lignes.append(f"{la:.6f};{lo:.6f};passage_niveau;Voie ferrée;;;;")
    lignes.append(";;danger;Bourbier après pluie, rester sur la piste principale;;3;9,30;E2 - Liaison sud")
    (ICI / "poi.csv").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print("exemple.gpx et poi.csv écrits dans", ICI)


if __name__ == "__main__":
    main()
