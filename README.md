# roadbook — road book PDF à partir d'une trace GPX

Génère un road book de navigation de style rallye-raid / 4L Trophy (cases
« km Total / Partiel | Schéma | Commentaires ») à partir d'une trace GPX.

```
roadbook genere trace.gpx --config config.yaml -o roadbook.pdf
```

Exemple : [`examples/exemple_a5.pdf`](examples/exemple_a5.pdf) (et
[`exemple_rouleau.pdf`](examples/exemple_rouleau.pdf)), produit à partir de
[`examples/exemple.gpx`](examples/exemple.gpx), [`poi.csv`](examples/poi.csv)
et [`config.yaml`](examples/config.yaml).

## Installation (Windows, macOS, Linux)

Python 3.11 ou plus récent. Toutes les dépendances existent en paquets
précompilés pour Windows (pas de compilateur ni de bibliothèque système).

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (source .venv/bin/activate sous macOS/Linux)
pip install -e ".[dev]"
```

## Interface graphique

```bash
roadbook interface
```

Sous Windows, double-cliquez simplement sur **`Lancer roadbook.bat`** : il
installe l'outil au premier lancement puis ouvre l'interface dans le
navigateur (Python 3.11+ requis).

L'interface tourne en local (rien n'est envoyé sur Internet, sauf les
requêtes OpenStreetMap si vous les activez) :

* **fichiers** : glisser-déposer n'importe où dans la fenêtre (le type est
  reconnu : .gpx, .csv, .osm/.bz2, projet .json, config .yaml), ou bouton
  « Essayer avec l'exemple » ; le dernier travail est **restauré** à la
  réouverture ;
* **options** : toutes les options de mise en page, textes, numérotation,
  détection et OpenStreetMap, avec aide, **recherche**, repère des valeurs
  modifiées et retour à la valeur par défaut option par option ;
  **modèles** en un clic (Carnet A5, A4 confort, Rouleau, Noir et blanc) ;
* **aperçu en direct** : les pages s'affichent en images nettes, sans
  clignotement et sans perdre la page en cours ; zoom (largeur, page entière,
  pourcentage), navigation par page ;
* **annuler / rétablir** toutes les modifications (Ctrl+Z, Ctrl+Maj+Z) ;
* onglet **Cases** : correction des textes, dangers (! à !!!), codes de
  contrôle, suppression ou ajout de case, « voir dans le PDF », carte de
  l'étape ;
* onglet **Rapport** : distance, durée, contrôles, cases à vérifier avec
  accès direct à la case ;
* **Projet** : enregistrer / rouvrir (`.roadbook.json`, Ctrl+S), exporter la
  configuration en `config.yaml` ; téléchargement du PDF (Ctrl+D), du CSV et
  du rapport ; thème clair ou sombre.

## Utilisation en ligne de commande

```bash
roadbook genere trace.gpx -c config.yaml -p balises.csv -o roadbook.pdf --csv instructions.csv
roadbook genere trace.gpx -f rouleau          # format : a5 (défaut) | a4 | rouleau
roadbook instructions trace.gpx -c config.yaml  # tableau texte, sans PDF (pour vérifier)
roadbook config-defaut > config.yaml            # toutes les options, avec leurs valeurs par défaut
```

`python -m roadbook ...` fonctionne aussi si le script `roadbook` n'est pas dans le PATH.

Chaque génération produit :

* le **PDF** : page de légende, puis par étape une page de garde (distance,
  durée estimée, contrôles, dangers, carte du tracé) et les pages de cases ;
  signets par étape et par page ;
* un **rapport** `<sortie>.rapport.txt` : points en doublon, trous dans la
  trace, trace bruitée, POI hors trace ou ambigus, POI sans description,
  virages douteux, textes abrégés/tronqués ;
* en option un **CSV** des instructions (séparateur `;`, virgule décimale,
  UTF-8 avec BOM : s'ouvre directement dans Excel en français), avec heure
  de passage estimée.

## Mode route : carrefours OpenStreetMap

Sur route, la forme de la trace ne suffit pas : il faut savoir où sont les
carrefours. Avec `--osm`, l'outil télécharge le réseau routier le long de la
trace (API Overpass, couloir de 40 m) et en déduit :

* **les carrefours empruntés**, avec l'angle exact et **les autres routes du
  carrefour dessinées en trait fin** sur le schéma ;
* **le numéro de sortie des rond-points** (« RP 3E SORTIE »), en comptant les
  sorties autorisées : une branche à sens unique qui ne fait qu'entrer sur
  l'anneau n'est pas comptée ;
* **la route prise** (« SUR D12 », numéro ou à défaut nom de rue) et le panneau
  de direction quand OSM le connaît (« DIR. VALENCE ») ;
* **les feux** (« FEUX »), et en cases automatiques les **stops**, **passages à
  niveau** et **stations-service** proches de la trace.

```bash
roadbook genere trace.gpx -c config.yaml --osm -o roadbook.pdf
```

Les réponses Overpass sont gardées en cache (`%LOCALAPPDATA%\roadbook\osm`
sous Windows, `~/.cache/roadbook/osm` ailleurs) : une fois téléchargé, le road
book se regénère sans connexion. On peut aussi travailler entièrement hors
ligne avec un export du réseau : `--osm-fichier zone.osm` (bouton « Exporter »
d'openstreetmap.org, JOSM, ou réponse Overpass `.json` ; `.bz2`/`.gz` acceptés).

Quels carrefours ont une case (`osm.carrefours_td`) :

* `importants` (défaut) : quand on tourne, quand on croise une route plus
  importante que la sienne, ou quand une autre branche part dans une direction
  proche (risque de confusion). On n'a pas de case quand on suit simplement
  sa route et que les rues croisées sont plus petites ;
* `tous` : chaque carrefour où l'on a le choix ;
* `aucun` : seulement quand on change de direction.

Sur les portions couvertes par OSM, les virages déduits de la seule forme de
la trace (courbes, lacets sans carrefour) sont retirés
(`osm.virages_hors_carrefour: true` pour les garder). Hors réseau (pistes non
cartographiées), le calcul à partir de la trace reprend la main, dans le même
road book. Les deux modes se mélangent donc naturellement sur un rallye
route + piste.

Le PDF porte la mention « Routes © contributeurs OpenStreetMap (ODbL) »
exigée par la licence des données.

## Entrées

**GPX** : chaque `<trk>` est une étape (ou toutes bout à bout avec
`decoupage_etapes: unique`) ; à défaut, les `<rte>`. Les segments d'une
trace sont mis bout à bout.

**Points d'intérêt** — waypoints du GPX et/ou CSV, projetés sur la trace :

| colonne | contenu |
|---|---|
| `lat`, `lon` | coordonnées (facultatives si `km` est rempli) |
| `type` | `controle`, `danger`, `ravitaillement`, `passage_niveau`, `stop`, `carrefour`, `info`, `depart`, `arrivee` (synonymes acceptés : CP, DZ, essence...) |
| `description` | texte affiché dans la case |
| `code` | ex. `CS10`, affiché cerclé sur le schéma |
| `niveau` | dangers : 1 à 3 (`!` à `!!!`) |
| `km`, `etape` | position imposée (utile quand la trace repasse au même endroit) |

Pour les waypoints GPX, le type est lu dans `<type>` ou `<sym>`, sinon
deviné d'après le nom (`CS1`, `CP3` = contrôle, `DZ !!!` = danger...).
Un POI à moins de `poi_fusion_m` (50 m) d'une manœuvre est ajouté à sa case,
sinon il crée une case « TD ».

## Comment les instructions sont calculées

1. Trace nettoyée (doublons consécutifs supprimés), rééchantillonnée tous les
   5 m ; distances géodésiques sur l'ellipsoïde WGS84 (pyproj).
2. Cap lissé ; la variation de cap est mesurée sur une fenêtre de 30 m. Une
   zone qui dépasse 20° est un virage candidat ; son angle est la différence
   entre le cap stable avant et après (30 m de chaque côté). Les courbes
   douces (grand rayon) ne déclenchent rien, le bruit GPS non plus.
3. Virages de même sens à moins de 25 m : fusionnés. Petit décalage
   gauche-droite qui s'annule : ignoré.
4. Rond-point : tronçon tourné dans le sens de circulation, de rayon ≤ 35 m,
   sur au moins 45°, encadré de déflexions opposées en entrée et en sortie.
5. Classes d'angle (configurables) : ≤ 45° « LÉG. », ≤ 105° normal,
   ≤ 150° « FORT », au-delà « ÉPINGLE » ; ≥ 165° « DEMI-TOUR ».
6. Cap de sortie (« C.235 ») : cap de la trace sur les 100 m qui suivent la manœuvre.

## Choix de mise en page (à valider)

Je ne connais pas de règle FIA qui impose ces détails ; voici les choix faits
et pourquoi :

* **3 colonnes comme le carnet 4L Trophy** plutôt que 5 (TC | TP | Schéma |
  Description | Notes) : distances regroupées dans une seule colonne, et
  description, notes des POI et cap dans une même zone « Commentaires » qui
  laisse de la place pour écrire à la main.
* **Total en gros dans un cartouche gris, partiel en bas à droite, n° de case
  en petit** : comme sur la photo de référence.
* **2 décimales sur le total, 1 sur le partiel** (configurable) ; virgule décimale.
* **Total remis à zéro à chaque étape** (`remise_a_zero: epreuve` pour un cumul).
* **A5 : 7 cases par page**, A4 : 10 cases. La hauteur de case (25 mm) se
  règle avec `hauteur_case_mm` ou `lignes_par_page`. 40 à 60 lignes par page
  ne seraient pas lisibles à 30 cm.
* **Rouleau** : bande de 148 mm de large dont la longueur suit le nombre de
  cases (coupée tous les 3 m au maximum), lue de haut en bas.
* **Schémas** : on arrive par le bas (point noir), le haut de la case est
  « tout droit » et non le nord ; l'angle dessiné est l'angle mesuré.
* **Mise en évidence** : contrôles encadrés en bleu, dangers en rouge (en
  noir et gris avec `couleurs: false`, pour une impression monochrome).
* **Textes en capitales** (`majuscules`), libellés abrégés (`AD`, `AG`, `TD`,
  `RP`...) ou complets (`textes: complet`). Un texte trop long est d'abord
  coupé en lignes, puis abrégé avec le dictionnaire `abreviations`, puis
  écrit plus petit (75 % au minimum), et en dernier recours tronqué avec « … »
  (signalé dans le rapport).
* **Mini-carte** (`mini_carte: true`) : tracé vectoriel de l'étape sous les
  cases, portion de la page en gras. Pas de fond de carte.

## Limites connues

* Sans `--osm`, seuls les **changements de direction** sont détectés :
  un carrefour traversé tout droit, un nom de route ou un numéro de sortie de
  rond-point doivent venir du CSV de POI.
* Avec `--osm`, la qualité dépend de la carte : route manquante, sens unique
  ou rond-point mal saisi dans OSM donnent une case fausse ou absente. Le
  rapport indique combien de carrefours OSM ont été retenus par étape.
* Si la trace GPX est décalée de plus de 12 m de la route (trace dessinée à la
  main, GPS imprécis), les carrefours ne sont pas reconnus : augmenter
  `osm.tolerance_m`.
* La **1re sortie à droite** d'un rond-point à entrée évasée ne parcourt
  presque pas l'anneau : elle apparaît comme un simple « AD ».
* Une chicane très serrée (rayon < 35 m, droite-gauche-droite) est vue comme
  un petit rond-point traversé tout droit.
* Une trace très bruitée (enregistrement GPS) est plus longue que la route
  réelle : le rapport le signale si l'écart dépasse 2 %. Pensez à recaler le
  trip au départ de chaque étape.

## Organisation du code

| module | rôle |
|---|---|
| `roadbook/gpx_loader.py` | lecture et nettoyage du GPX |
| `roadbook/poi.py` | points d'intérêt (waypoints, CSV) |
| `roadbook/geometry.py` | distances, caps, rééchantillonnage, projection |
| `roadbook/instructions.py` | détection des virages/rond-points, génération des instructions |
| `roadbook/osm.py` | réseau OpenStreetMap : Overpass, cache, fichiers .osm/.json |
| `roadbook/carrefours.py` | carrefours et rond-points OSM empruntés par la trace |
| `roadbook/libelles.py` | textes français |
| `roadbook/symbols.py` | pictogrammes vectoriels |
| `roadbook/layout.py` | formats et pagination |
| `roadbook/render_pdf.py` | rendu PDF (ReportLab) |
| `roadbook/export.py` | tableau texte, CSV, rapport |
| `roadbook/cli.py` | ligne de commande |
| `roadbook/serveur.py`, `roadbook/web/index.html` | interface graphique (serveur local + page web) |
| `roadbook/options.py` | description des options affichées dans l'interface |
| `roadbook/modifications.py` | corrections manuelles des cases |

Tests : `pytest` (ligne droite, carré, rond-points synthétiques, distance
géodésique, PDF et CLI sur la trace d'exemple, carrefours OSM sur un réseau
synthétique et sur un extrait OSM réel). La trace d'exemple se
régénère avec `python examples/generer_exemple.py`.
