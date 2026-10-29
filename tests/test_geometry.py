import numpy as np
import pytest

from roadbook.geometry import (
    GEOD,
    diff_cap,
    distance_cumulee,
    projeter_sur_trace,
    reechantillonner,
)
from roadbook.synthetique import Tortue


def test_diff_cap_normalisee():
    assert diff_cap(350, 10) == pytest.approx(20)
    assert diff_cap(10, 350) == pytest.approx(-20)
    assert diff_cap(0, 180) == pytest.approx(180)
    assert diff_cap(90, 270) == pytest.approx(180)


def test_distance_meridien_a_un_pour_cent():
    # 1° de latitude à l'équateur ≈ 110 574 m (référence géodésique WGS84)
    lat = np.linspace(0.0, 1.0, 101)
    lon = np.zeros_like(lat)
    assert distance_cumulee(lat, lon)[-1] == pytest.approx(110_574, rel=0.01)


def test_distance_cumulee_egale_geodesique_apres_reechantillonnage():
    t = Tortue(cap_deg=30).droit(800).arc(60, 90).droit(500).arc(40, -120).droit(1200)
    lat, lon = t.latlon(31.4, -4.2, bruit_m=1.0, graine=3)
    reference = GEOD.line_length(lon, lat)
    tr = reechantillonner(lat, lon, None, 10.0)
    assert tr.longueur == pytest.approx(reference, rel=0.01)
    assert np.all(np.diff(tr.s) <= 10.0 + 1e-6)


def test_reechantillonnage_sans_bruit_conserve_la_longueur():
    t = Tortue(cap_deg=30).droit(800).arc(60, 90).droit(500).arc(40, -120).droit(1200)
    lat, lon = t.latlon(31.4, -4.2)
    tr = reechantillonner(lat, lon, None, 10.0)
    # les points rééchantillonnés sont sur la trace : la polyligne qu'ils forment
    # coupe un peu les courbes, mais reste à moins de 1 % de la longueur réelle
    assert GEOD.line_length(tr.lon, tr.lat) == pytest.approx(GEOD.line_length(lon, lat), rel=0.01)


def test_projection_et_double_passage():
    # aller-retour : un point au milieu est croisé deux fois
    t = Tortue(cap_deg=0).droit(1000).arc(20, 180).droit(1000)
    lat, lon = t.latlon(45.0, 5.0)
    tr = reechantillonner(lat, lon, None, 5.0)
    plat, plon = tr.position(500)
    candidats = projeter_sur_trace(plat, plon, tr, tolerance_m=60)
    assert len(candidats) == 2
    assert candidats[0][0] == pytest.approx(500, abs=2)
