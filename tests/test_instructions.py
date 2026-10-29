import pytest

from roadbook.config import config_par_defaut
from roadbook.geometry import reechantillonner
from roadbook.instructions import detecter_manoeuvres
from roadbook.synthetique import Tortue

LAT0, LON0 = 46.5, 2.5


def manoeuvres(tortue, bruit_m=0.0, graine=0, avec_trace=False):
    cfg = config_par_defaut()
    lat, lon = tortue.latlon(LAT0, LON0, bruit_m=bruit_m, graine=graine)
    tr = reechantillonner(lat, lon, None, cfg["calcul"]["pas_reechantillonnage_m"])
    m = detecter_manoeuvres(tr, cfg["calcul"])[0]
    return (m, tr) if avec_trace else m


@pytest.mark.parametrize("bruit", [0.0, 1.5])
def test_ligne_droite_sans_instruction(bruit):
    assert manoeuvres(Tortue(cap_deg=37, pas_m=8).droit(5000), bruit) == []


@pytest.mark.parametrize("sens", [1, -1])
@pytest.mark.parametrize("bruit", [0.0, 1.0])
def test_carre_quatre_virages_a_90(sens, bruit):
    # départ au milieu d'un côté pour que les 4 coins soient des virages
    t = Tortue(cap_deg=0, pas_m=10).droit(250)
    for _ in range(3):
        t.coin(90 * sens).droit(500)
    t.coin(90 * sens).droit(250)
    m, tr = manoeuvres(t, bruit, graine=4, avec_trace=True)
    assert [x.type for x in m] == ["virage"] * 4
    # le bruit GPS allonge un peu la trace : positions attendues à l'échelle
    echelle = tr.longueur / 2000.0
    for x, attendu in zip(m, [250, 750, 1250, 1750]):
        assert x.angle == pytest.approx(90 * sens, abs=5)
        assert x.s == pytest.approx(attendu * echelle, abs=10)


def test_courbe_douce_ignoree():
    t = Tortue(cap_deg=0).droit(500).arc(400, 40).droit(500)
    assert manoeuvres(t) == []


def test_classes_et_demi_tour():
    t = Tortue(cap_deg=0).droit(400).arc(8, 30).droit(400).arc(8, -120).droit(400).arc(5, 178).droit(400)
    m = manoeuvres(t)
    assert [x.type for x in m] == ["virage", "virage", "demi_tour"]
    assert m[0].angle == pytest.approx(30, abs=4)
    assert m[1].angle == pytest.approx(-120, abs=4)


def test_virages_proches_fusionnes():
    # deux coudes de 45° à 10 m d'écart = un seul virage de 90°
    t = Tortue(cap_deg=0, pas_m=5).droit(400).coin(45).droit(10).coin(45).droit(400)
    m = manoeuvres(t)
    assert len(m) == 1 and m[0].angle == pytest.approx(90, abs=5)


@pytest.mark.parametrize(
    "sortie, deflexion",
    # déflexion 90° = entrée radiale ; 65° = entrée évasée. Une 1re sortie à
    # droite avec entrée évasée ne parcourt que ~40° d'anneau : elle est vue
    # comme un simple virage à droite (limite assumée, cf. README).
    [(90, 90), (0, 90), (-90, 90), (180, 90), (0, 65), (-90, 65), (180, 65)],
)
def test_rond_point_synthetique(sortie, deflexion):
    t = Tortue(cap_deg=20, pas_m=6).droit(600).rond_point(15, sortie, deflexion=deflexion).droit(600)
    m = manoeuvres(t, bruit_m=0.5, graine=7)
    assert [x.type for x in m] == ["rond_point"]
    assert abs((m[0].angle - sortie + 180) % 360 - 180) <= 10


def test_epingle_isolee_pas_un_rond_point():
    t = Tortue(cap_deg=0).droit(500).arc(12, -160).droit(500)
    m = manoeuvres(t, bruit_m=1.0, graine=2)
    assert [x.type for x in m] == ["virage"]


def test_droite_puis_gauche_rapprochees():
    t = Tortue(cap_deg=0, pas_m=6).droit(500).arc(10, 90).droit(40).arc(10, -90).droit(500)
    m = manoeuvres(t, bruit_m=0.5, graine=1)
    assert [round(x.angle / 10) for x in m] == [9, -9]


def test_decalage_lateral_ignore():
    t = Tortue(cap_deg=0, pas_m=5).droit(500).coin(30).droit(10).coin(-30).droit(500)
    assert manoeuvres(t) == []
