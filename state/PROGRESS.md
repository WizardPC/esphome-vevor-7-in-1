### 03/10 (suite 10) — DÉFAUT EN PRODUCTION : pics de pluie à 7 634,5 mm, et la borne qui manquait

Signalé par l'utilisateur, relevé Home Assistant : deux pics de **7 634,5 mm** dans l'après-midi sous
un ciel dégagé, la valeur restant à 59,2 mm avant et après. L'historique HA donne la chronologie
exacte : **59,18 → 29,36 mm à 11:51:44 UTC** (une division par deux, soit **exactement −128 ticks** :
254 → 126, un seul bit faux), puis les pics.

**La cause du fait que ça passe : la porte de plausibilité ne contrôlait PAS la pluie.** Elle vérifie
direction, humidité, température, vent et UV — jamais la pluie. Une trame cohérente portant
n'importe quelle valeur de pluie était donc publiée telle quelle.

**Correctif livré** (`pluie_plausible` dans `vevor_protocol.h`, appliqué à TOUTES les trames dans le
composant) : la pluie ne peut pas MONTER de plus de 5 mm entre deux rafales. La borne porte sur la
hausse seulement, et c'est délibéré : le protocole documente un recul légitime de 256 ticks (la
station lit son compteur pendant un report) et la station peut remettre son compteur à zéro — un
contrôle qui refuserait une BAISSE rejetterait ensuite toutes les trames, indéfiniment. Une hausse,
elle, est toujours physiquement bornée, donc ce contrôle ne peut jamais bloquer une réception saine.
Le message de refus journalise les **octets bruts** de la trame : sans eux on bloquerait le défaut
sans comprendre pourquoi. Compteur `pluie_refusee=N` dans le journal périodique.

**Tests : 408 vérifications, 0 échec.** Le test démontre le défaut au niveau de la trame : construite
avec les octets `80 FF`, la trame au pic (7 634,5 mm) **franchit en-tête, somme, compteur et toute la
porte de plausibilité du protocole** — et c'est bien le nouveau contrôle qui l'arrête. Contre-épreuve
incluse : la division par deux observée en production et la remise à zéro du compteur restent
ACCEPTÉES.

**Hypothèse réfutée par la mesure, à ne pas rouvrir** : les réparations du décodeur ne fabriquent pas
de trame. Sur **3 000 charges utiles aléatoires** (synchronisation et en-tête justes, soit ~1 million
de tentatives de réparation) le décodeur ne publie **rien**. Le test à 200 charges d'hier était trop
petit pour conclure quoi que ce soit : le porter à 3 000.

**Mécanisme restant à élucider** : la division par deux est un −128 propre dans l'octet bas, et la
trame a passé le checksum — donc la trame était COHÉRENTE, ce qui oriente vers l'émetteur ou vers une
erreur systématique, pas vers un décalage de notre extraction. Trancher exige les octets bruts du
prochain pic : binaire de campagne `fab3ce97` (968 624 octets, niveau DEBUG) flashé, ligne
`V7IN1 RAW` et motifs de rejet actifs, capture de 60 min lancée à 19h00.

**Leçon outillage** : ESPHome refuse un niveau par tag plus verbeux que le niveau GLOBAL (« must not
be less severe »). La recette de campagne est donc `esphome -s niveau_journal DEBUG compile …`, la
substitution portant sur `logger: level:` lui-même. Un `logs: {v7in1: DEBUG}` avec `level: INFO` fait
échouer la validation — la compétence disait le contraire, elle est corrigée.

### 03/10 (suite 9) — PREUVE SUR LA CARTE : 45 trames sur 45 émissions, une seule réparation

Fenêtre de 15 min avec le firmware de l'étape 1 (binaire `ec0a270c`, 958 688 octets). **45 trames
publiées pour 45 émissions attendues** — la meilleure fenêtre jamais mesurée sur ce montage.

| mesure | valeur |
|---|---|
| trames publiées | **45** (44 intervalles, **tous exactement à 20,0 s**, aucun trou) |
| compteurs TX distincts | **45** — aucun doublon de livraison (artefact de recollage écarté) |
| trames réparées | **1** (dont **0** refusée par le garde-fou), contre 4 réparations sur 5 rafales du dump |
| candidats rejetés | **1** — contre **125** sur 12 min avec la grille fixe à 90 µs |
| puce présente | **oui** — 0 ligne `Chip ID: 0xFFFF` sur toute la fenêtre |
| forme du flux | rafales complètes, 178 à 184 impulsions, capture la plus longue 502 |
| valeurs publiées | 19,3 °C, 65-66 %, direction 90°, lux 26 730, compteur TX avançant de +39/émission |

**Validation indépendante par le compteur TX** (sans passer par le firmware) : sur les 44 intervalles,
l'écart du compteur correspond au temps écoulé (dt × 1,95 tick/s) avec un **écart relatif médian de
1,000**, et **0 trame hors tolérance**. Les trames sont donc cohérentes avec elles-mêmes ET avec
l'horloge — c'est une validation trame par trame, pas un compte.

**Un trou dans la chaîne de preuve, trouvé et corrigé ici même :** `tools/eval_frames.py` rend
**FAIL** (« 45 trames publiées mais aucune ligne RAW exploitable ») parce que la ligne `V7IN1 RAW`
(les 21 octets bruts) est en **DEBUG**, donc retirée du binaire en production (niveau INFO) — c'est
une conséquence directe de l'allègement du YAML. Le niveau des tags du projet est désormais
**substituable** : `esphome -s niveau_v7in1 DEBUG …` le remonte pour une campagne sans toucher au
YAML de production. La réception de cette fenêtre n'est pas en cause (le FAIL le dit lui-même).

**Comparaison honnête** : l'ancienne mesure de référence (12 trames en 12 min) avait été prise avec
la puce en état A (muette sur le SPI, 0xFFFF) — les deux fenêtres ne comparent pas le même état.
Ce qui se compare, c'est le travail du décodeur : 125 rejets et 4 réparations nécessaires sur 5
rafales, contre **1 rejet et 1 réparation sur 45 trames** — l'estimateur de rythme mesuré fait
décoder directement ce que la grille fixe à 90 µs ratait.

### 03/10 (suite 8) — Étape 1 livrée : période MESURÉE + réparations bornées, 5/6 sur les rafales réelles

Consigne : « essaie la piste de l'horloge », avec une contrainte de production structurante —
**un nouvel utilisateur ne fera que flasher**, le code doit rendre sa station fonctionnelle sans
analyse, et donc **jamais dépendre d'une constante propre à une station**.

**Livré dans le firmware** (`esphome/includes/vevor_protocol.h`), avec tests hôtes :

* `estimer_periode_x10()` : la période bit est **mesurée sur chaque rafale reçue** (médiane de la
  fenêtre protocolaire 45-115 µs, puis consolidation par `d / round(d/T)` sur les impulsions > 0,55·T).
  Aucune constante de station. La grille `PERIOD_CANDIDATES` ne sert plus que de repli.
* `reparer_par_insertion()` : réparation bornée d'un bit **manquant** (le mécanisme prouvé : une
  impulsion de deux bits lue comme un seul), après la tolérance d'un bit d'en-tête déjà en place.
  Toutes validées par en-tête + somme + compteur + porte de plausibilité.
* `continuite_ok()` côté composant : une trame **réparée** doit être cohérente avec la précédente
  (même station, ±1 °C, ±5 %). Mesuré : 0 fabrication sur 200 charges aléatoires — c'est une
  précaution à coût nul, pas une nécessité mesurée, et c'est documenté comme telle.
* Le journal périodique publie désormais `réparées=N (dont M refusées)` : la mesure sur la carte doit
  montrer ce que les réparations apportent réellement.

**Chiffres mesurés :**

| quoi | résultat |
|---|---|
| estimateur, sur rafales synthétiques 88/89/87/90 µs | 87,8 / 88,7 / 86,9 / 90,2 µs |
| **rafales RÉELLES du dump rejouées dans le C++** | **5 sur 6** (critère d'acceptation fixé le matin) |
| les 5 décodées | même mesure de la station (préfixe de 11 octets identique), périodes 88,2-89,1 µs |
| impulsion de 2 bits raccourcie à 1 bit | réparée à l'identique |
| 200 charges utiles aléatoires (synchro juste) | **0 publiée** |
| suite de tests du projet | **397 vérifications, 0 échec** |

**Deux corrections structurelles** ont été nécessaires pour que la réparation fonctionne, toutes deux
trouvées par la mesure et non par le raisonnement : (1) la trame ne « rentre » plus dans la fenêtre de
recherche dès qu'un bit manque — `find_frame_candidate` accepte maintenant une charge utile à un bit
près ; (2) les bits entre deux frontières appartiennent au segment **précédent**, pas au suivant —
ma première implémentation était décalée d'un segment entier, d'où 0/6.

**Vecteur de régression versionné** : `tests/data/captures_reelles.txt` (les 6 rafales du dump) est
rejoué par `test_captures_reelles()` — c'est le seul test du projet qui porte sur du signal réel.

**Reste ouvert** : la 6e rafale (au moins deux corrections nécessaires), et la récupération d'horloge
au sens strict (étape 2), qui reste du domaine de la recherche. Firmware flashé (`a444b9a0`,
958 688 octets) ; mesure de 15 min en cours.

### 03/10 (suite 7) — Piste de l'horloge : rythme MESURÉ sur la rafale (5/6), et ce qui ne marche pas

Consigne reçue : écarter le cycle d'alimentation (l'utilisateur le fait à la main après un flash) et
essayer la piste de l'horloge. Contrainte de conception rappelée et désormais structurante : **un
nouvel utilisateur ne fera que flasher** — le code doit rendre sa station fonctionnelle sans analyse,
et **jamais** dépendre d'une constante propre à une station.

**Ce qui marche (et qui sert directement la contrainte) :**

* **Estimateur de rythme bit auto-adaptatif** — aucune constante de station. Sur les six rafales du dump
  il sort **88,5-88,9 µs**, soit les **88,3 µs** mesurés par le projet de référence. Méthode : médiane
  des durées de la fenêtre 45-115 µs, puis consolidation par la médiane de `d / round(d/T)` sur les
  impulsions > 0,55·T, quatre fois. Le bug de classe « 90 µs codé en dur » disparaît : chaque carte est
  MESURÉE, pas supposée.
* **Mécanisme de panne prouvé** : **un bit manquant**, pas un bit en trop. Insérer un seul bit répare
  les rafales 0 et 3 (positions 151 et 187 du flux) ; en supprimer un ne réparait rien.
* **Combinaison à 5/6**, critère d'acceptation fixé le matin même : 1 directe + 2 par le filet d'un bit
  d'en-tête + **2 par insertion d'un bit dans la charge**, toutes portant la même charge utile. Coût de
  l'insertion sur la cible : ~67 k opérations au pire, < 1 ms à 160 MHz, et seulement quand une synchro
  est trouvée mais la trame invalide (~125 fois / 12 min). Négligeable.

**Ce qui ne marche pas (à ne pas refaire) :**

* **Horloge verrouillée en phase : trois implémentations, aucune meilleure que l'arrondi simple.** Les
  deux premières donnaient 0/6 et ne reproduisaient même pas la rafale décodable — donc elles étaient
  fausses, pas l'approche.
* **L'arrondi de position cumulée est PIRE** : égal à l'arrondi isolé au bon rythme, mais **0/6 dès +1 %
  d'erreur de période**, quand l'arrondi isolé tient 3/6 jusqu'à ±2 %. Il cumule l'erreur sur 350 bits ;
  l'arrondi isolé non. **Pour un produit qui doit marcher sur la carte d'un inconnu, l'arrondi isolé sur
  période mesurée est le choix robuste.**
* **Seuil de parasites** (écarter et fusionner les impulsions < α·T), testé de 0,5·T à 0,8·T : aucun gain,
  et dégrade le filet au-delà de 0,7·T. Les parasites de 45-50 µs sont une histoire plausible, pas le
  mécanisme.

**Statut honnête :** la récupération d'horloge au sens strict **n'est pas obtenue**. Ce qui est obtenu,
c'est un rythme auto-adaptatif + des réparations bornées validées par somme/compteur/porte → 5/6. La
rafale 2 reste inexpliquée (il lui faut au moins deux corrections). Suite : implémenter l'étape 1 du plan
(`docs/bit-jitter-analysis.md` §6) en C++ avec les tests hôtes, puis mesurer sur la carte.

### 03/10 (suite 6) — État mesuré en fin de journée, et les deux vrais chantiers restants

**Mesure de 12 minutes avec le firmware flashé** (tolérance d'un bit sur l'en-tête) :

```
TRAMES : 12 sur 36 émissions attendues (33 %)
rejets : 125       dernières impulsions = 177 (rafale complète)   plus longue = 530
écritures : « les 8 registres surveillés sont conformes »
calibration VCO : FSCAL1=0x17 (valide), MARCSTATE=0x0D (en RX)
V7IN1 OK {"id":33995,"temp_c":17.6,"humidity":74,"wind_dir_deg":107,"lux":17640,"tx_counter":152}
```

Valeurs cohérentes, et compteur TX avançant de +39 par émission — la cadence documentée.

**Mais la fenêtre de référence juste avant (25 min, interrompue) montrait l'état A** : `Chip ID:
0xFFFF`, `status 0xFF`, `CHIP_RDYn HAUT = alimentation ou quartz pas prêts`, pendant plus de dix
minutes, avec redémarrage du garde-fou. Dans cet état la puce n'est pas sur le bus et **aucune
correction logicielle ne peut rien** — ni l'interruption GDO0, ni la tolérance, ni la grille de
périodes. C'est pourquoi la référence a donné 0 trame et la fenêtre suivante 12.

**Chantier 1 — récupération d'horloge (le vrai correctif de décodeur).** Les 125 rejets sont les
trames dont le décalage commence à l'octet 9 ou 11 : la tolérance d'un bit ne les rattrape pas, et
c'est mesuré. L'approche de rtl_433 (alignement sur le préambule `AA AA AA` puis reconstruction de
l'horloge bit) est la bonne ; elle exige une vraie implémentation avec tests hôtes sur des rafales
synthétiques. Le prototype jetable a donné 0/6 : ne pas recommencer par là. Détail et références :
`docs/bit-jitter-analysis.md`.

**Chantier 2 — rendre le module cyclable en alimentation par le firmware.** L'état A est une panne
d'ALIMENTATION/quartz (`CHIP_RDYn` haut = la puce l'annonce elle-même), seul un vrai cycle
d'alimentation la rétablit — un `reset` logiciel ne redémarre pas l'oscillateur. Un transistor (ou un
interrupteur de charge) entre le 3,3 V et le VCC du module, piloté par un GPIO, permettrait au
garde-fou de faire ce cycle au lieu de redémarrer l'ESP32 en espérant. C'est la piste « transistor »
déjà notée dans le projet, et elle devient la priorité matérielle.

**Correction du 03/10 (l'utilisateur a raison de reprendre) :** un **10 µF** est DÉJÀ monté entre VCC et
GND du module. Un 100 nF fait un autre travail (les fronts rapides, à souder au plus court sur les
broches ; un 10 µF voit son impédance remonter au-dessus de ~1 MHz), mais **son absence n'a jamais été
mesurée comme cause sur cette carte** : elle vient de la note du projet, pas d'une mesure. Ne plus le
présenter comme LE levier manquant. Ce que la puce dit elle-même (`CHIP_RDYn` haut = alimentation ou
quartz pas prêts) désigne un problème de DÉMARRAGE, dont le levier actionnable est un cycle
d'alimentation (bouton dans le fil VCC, transistor pour l'automatiser).

---

### 03/10 (suite 5) — Pourquoi le rendement est bas : cinq rafales propres sur six ont un contenu corrompu

Analyse hors ligne des 6 rafales « propres » du dump (162-167 impulsions, impulsion courte médiane à
90 µs, toutes d'apparence identique), en balayant période, polarité et alignement de bit :

| capture | impulsions | décodage |
|---|---|---|
| 12 | 162 | aucune trame (le sync apparaît, la somme ne tombe pas) |
| 13 | 165 | aucune trame (sync trouvé, en-tête absent) |
| 16 | 166 | aucune trame (sync trouvé, en-tête absent) |
| 17 | 167 | aucune trame (sync trouvé, somme fausse) |
| 20 | 167 | aucune trame (sync trouvé, en-tête absent) |
| 21 | 167 | **TRAME VALIDE** (`aa 00 84 cb …` = température 15,6 °C, 80 %, 289°) |

Autrement dit : dans cinq cas, le mot de synchronisation est un hasard et la trame réelle n'est pas
là. Ce ne sont ni la fréquence (vérifiée), ni la période de bit, ni la grille du firmware, ni le
pilote : c'est le **flux démodulé** qui contient des erreurs de bit, et un seul front perdu au milieu
d'une rafale suffit à ruiner la trame — le piège déjà documenté dans `vevor_protocol.h`.

**Troisième erreur d'analyse du jour, consignée pour mémoire** : un script de diagnostic a conclu que
la capture 21 ne se décodait qu'à 85,4 µs et que la grille du firmware (87-90) la manquait. Faux : ce
script utilisait `round()` de Python (arrondi bancaire), alors que le firmware fait
`(durée + période/2) / période` (arrondi au plus proche). Avec la règle du firmware, la capture
décode à 86, 87, 88, 89, 90 ET 91 µs. Leçon : rejouer un diagnostic avec la règle de l'implémentation
qu'on accuse, avant de l'accuser.

**Leviers restants, côté qualité de démodulation** (et non plus décodeur) :
1. **100 nF** céramique au plus près du VCC du module — le seul des trois gestes matériels non monté ;
2. test à UNE variable sur la **bande passante du filtre** : 100 kHz pour 70 kHz de déviation est juste
   au sens de Carson (~150 kHz requis) — à mesurer, pas à supposer.

---

### 03/10 (suite 4) — LA RÉCEPTION EST REVENUE

Après les trois correctifs du jour, la carte décode à nouveau de vraies trames. Preuve, dans la
fenêtre même où le dump des durées a été pris :

```
[I][v7in1:242]: V7IN1 OK {"id":33995,"temp_c":15.6,"humidity":80,"wind_dir_deg":289,
                          "rain_mm":59.2,"uv_index":1,"lux":12510,...}
captures=50 (+3), trames=2, rejets=45
```

Le décodage hors ligne de la même rafale donne exactement les mêmes valeurs (température 15,6 °C,
humidité 80 %, direction 289°), et une réplique fidèle du décodeur C++ retrouve la trame aux périodes
90, 88 et 89 µs. La chaîne radio → RMT → bits → trame → entité est donc de nouveau complète.

**Les trois correctifs qui l'ont permise, dans l'ordre des mesures :**
1. l'interruption GDO0 attachée avant tout retour anticipé (le chemin de secours la sautait) ;
2. la vérification des écritures qui ne contrôle plus les registres de calibration du synthétiseur —
   c'est ce qui a rendu le démodulateur propre (captures de 171 impulsions au lieu d'un silence ou
   d'un continuum de bruit) ;
3. les deux passages du CC1101 en IDLE rétablis (avant arrêt propre et pendant l'OTA).

**Ce qui reste à mesurer** : le rendement de cette fenêtre est faible (2 trames publiées pour ~13
émissions attendues) et le compteur de rejets est élevé (~50 candidats écartés — des flux de bits qui
passent en-tête + somme + compteur mais que la porte de plausibilité physique refuse, exactement le
faux positif que `vevor_protocol.h` documente). La référence du 01/10 était à 98,8 % : l'état de la
puce pèse encore. Une mesure longue à état contrôlé est à refaire, sans flash au milieu.

**Deux erreurs d'analyse à ne pas répéter** (elles ont chacune coûté un aller-retour) : le décompte
des octets d'une trame décodée hors ligne a été fait de tête et faux, ce qui a fait déclarer « faux
positif » une trame parfaitement saine ; et le journal de `tools/ab_cycle.py` est en AJOUT, donc un
dépouillement qui ne filtre pas par horodatage relit les runs précédents. Lire le journal d'un outil
avant d'en dépouiller le contenu.

---

### 03/10 (suite 3) — YAML de production allégé, explications déplacées dans la documentation

Demande du propriétaire : le fichier destiné à ESPHome Builder n'a pas besoin d'autant de détail, et
les lambda de journalisation doivent être en debug pour ne pas charger l'ESP32.

- `esphome/vevor-7in1.yaml` : **486 → 330 lignes**. Les blocs de justification sont remplacés par des
  renvois d'une ligne vers `docs/firmware-design-notes.md`. Vérifié par un diff des lignes
  fonctionnelles (commentaires YAML **et** C++ retirés) : trois écarts seulement, tous voulus — niveau
  de log, forme du log OTA, libellé d'un message. Entités, identifiants, valeurs, scripts et
  intervalles inchangés.
- Journalisation : tout le périodique passe en `DEBUG`, `logger: level` passe à **INFO**. Le binaire
  passe de **966 896 à 957 008 octets** : ESPHome retire du firmware les chaînes de journalisation
  debug, ce n'est donc pas cosmétique. Seule exception, documentée dans le YAML et dans les notes :
  la ligne `V7IN1 OK {...}` reste en INFO, parce que c'est le produit de la carte et que les outils de
  mesure la lisent.
- `docs/firmware-design-notes.md` (anglais) : dix sections qui reprennent les mesures justifiant
  chaque réglage (câblage, paramètres radio, framework, règle du seul périphérique SPI, pilote local
  — piège de l'interruption GDO0 et faux positifs des registres de calibration —, état de la puce à
  travers un redémarrage, voie asynchrone, garde-fou, journalisation, ce qui reste dans le YAML).

**Conséquence à connaître pour les campagnes de mesure** : la ligne de santé `SANTE radio=…` n'existe
plus qu'en DEBUG. Les compteurs restent lisibles comme entités (c'est ce dont les outils se servent),
mais pour suivre le comportement du garde-fou pendant une mesure, remonter le niveau ou ajouter
`logs: {v7in1: DEBUG}` le temps de la campagne.

---

### 03/10 (suite 2) — Notre contrôle d'écriture criait au loup sur les registres de calibration

Le relevé de **quels** registres échouaient — jamais fait jusqu'ici — explique 70 % des alertes de la
journée :

| registre | adresse | alertes | verdict |
|---|---|---|---|
| FSCAL2 | 0x24 | 21 | FAUX POSITIF du contrôle |
| AGCCTRL0 | 0x1D | 5 | perte réelle |
| FSCAL1 | 0x25 | 2 | FAUX POSITIF du contrôle |
| MCSM0 | 0x18 | 1 | perte réelle |
| FREQ0 | 0x0F | 1 | perte réelle |

FSCAL3/FSCAL2/FSCAL1/FSCAL0 sont les registres de **calibration du synthétiseur, que la puce réécrit
elle-même** pendant sa calibration VCO. Preuve directe dans le journal : nous écrivons `0x2C` dans
FSCAL2 et la calibration y laisse `0x0C`. Notre boucle « écrire → relire → réécrire jusqu'à ce que ça
prenne » ne pouvait donc JAMAIS réussir sur ces registres : elle les réécrivait quatre fois à chaque
configuration et comptait ces échecs comme des pertes de liaison. Deux conséquences : des diagnostics
trompeurs (le « lien qui lâche en permanence ») et du trafic SPI inutile ajouté juste avant la
calibration.

Correction : ces quatre registres sont désormais écrits UNE fois, sans vérification (comme TEST0/1/2),
et la valeur écrite reste celle que recommande la datasheet pour accélérer la calibration.

Ce qui reste, et qui est réel : **FREQ0, AGCCTRL0 et MCSM0** — eux ne sont pas réécrits par la puce.
Une seule perte de FREQ0 (mot de fréquence) suffit à rendre la puce sourde à toute fréquence, quelle
que soit sa sensibilité : c'est la cause du « 0 trame alors que les registres se relisent conformes »
relevé par l'autre session le 02/10 au soir.

---

### 03/10 (suite) — Les deux passages du CC1101 en IDLE étaient désactivés depuis un test

Signalé par le propriétaire, qui ne les trouvait plus dans notre YAML alors que le projet de référence
les porte. Vérification faite : ils y étaient, mais **commentés** sous l'étiquette « VARIANTE D
(test) » — désactivés pendant une campagne de tests, jamais remis en service.

- `on_shutdown:` (priorité 600) → `cc1101.set_idle:` : le CC1101 est un composant SÉPARÉ, il reste
  alimenté et **garde ses registres** pendant que l'ESP32 redémarre. Or au démarrage de l'ESP32 les
  broches du bus (CSN, SCLK, MOSI) sont en haute impédance : un front parasite sur CSN est lu comme le
  début d'une transaction SPI et peut corrompre ses registres — d'autant plus si la puce était restée
  en RX ou en pleine calibration. La mettre en IDLE avant l'arrêt lui donne un état CONNU pour le
  démarrage suivant. C'est la même fenêtre que traite le pull-up externe de 10 kΩ sur CSN.
- `ota: on_begin:` → `cc1101.set_idle:` : même chose pendant toute la durée de la mise à jour.

Rétablis, compilés, flashés (966 880 octets, `2c64b292`). Le commentaire de test est remplacé par
l'explication du mécanisme : c'est exactement le genre de reste de campagne de tests qui fait
ressembler un montage à une panne matérielle.

---

## 03/10 — Cause du « sourd un démarrage sur deux » : un défaut de NOTRE pilote

Ce n'était pas la loterie du matériel, c'était un bug de la copie locale du pilote `cc1101`.

**Le mécanisme.** `loop()` du composant est piloté par INTERRUPTION : il commence par
`disable_loop()`, et seul `gpio_intr()` (front sur GDO0) le relance via
`enable_loop_soon_any_context()`. Notre chemin de secours « la puce ne répond pas du premier coup,
je relis toutes les 250 ms » **sortait de `setup()` en `return` AVANT le bloc `defer()` qui attache
cette interruption**. Conséquence : la relecture finissait par réussir, `configure()` entrait bien en
RX, la puce remplissait son FIFO, GDO0 montait — et plus personne ne lisait, définitivement. Le
pilote d'origine, qui n'a pas ce retour anticipé, n'a jamais ce défaut : d'où l'impression mesurée
qu'il « décode mieux » (bissect à état égal du 02/10 : 12 trames contre 3-4).

**Pourquoi ça ressemblait à une loterie matérielle.** Le chemin de secours n'est pris que si la puce
ne répond pas au premier essai, ce qui dépend de la vitesse de stabilisation de son alimentation et
de son quartz. Un démarrage favorable passait à côté du bug, un démarrage défavorable tombait
dedans, définitivement. Cela explique aussi le « sourd après OTA » (un OTA redémarre l'ESP32 sans
couper le module, donc la puce est plus souvent lente) et le fait qu'un ré-armement ne récupérait
pas toujours.

**Correctif appliqué.** L'interruption GDO0 est attachée **avant tout retour anticipé**
(`attacher_interruption_gdo0_()`), et `reset()` la détache/rattache pour qu'un ré-armement récupère
vraiment.

**Ce que ça NE règle pas, mesuré dans la foulée.** Le blocage actuel est ailleurs : dans la même
fenêtre, le contrôle des écritures rapporte `1 registre définitivement non pris` neuf fois, `2` une
fois, contre `0` cinq fois — la configuration de la puce reste partiellement aux valeurs d'usine
(`FSCAL1=0x19` valide et `MARCSTATE=0x0D` par ailleurs : la puce est en RX, la PLL est bonne, elle
ne démodule simplement pas). C'est le défaut de LIEN, celui que le pull-up et le 10 µF ont atténué
sans le supprimer → **l'alimentation du module reste l'intervention à faire**.

**Deux mesures du jour, et leur portée.** (a) A/B interleavé `origine` contre notre pilote d'avant
correctif, 6 tours chacun, 100 s par tour : **0 trame partout** — tirage confondu, aucune conclusion
possible sur les pilotes ; seul écart reproductible, la longueur des captures (90-93 impulsions chez
nous contre 22-41 chez l'origine), ce qui recoupe le bissect. (b) Le binaire corrigé, flashé : le
chemin de secours a bien été pris (`CC1101 trouvé après 1 relecture(s)` à chaque cycle) — donc le
correctif s'exerce — mais toujours 0 trame, à cause des écritures perdues ci-dessus.

**Garde-fou : à calmer.** Le seuil actuel (`muettes <= 30`) ré-arme **toutes les 20 s pendant 10
minutes**. Chaque ré-armement relance une configuration complète, dont ~2 sur 3 perdent un registre
sur ce lien : sur une liaison marginale, le garde-fou **entretient** le défaut au lieu de le réparer.
Proposition : n'armer qu'après un silence franc (2-3 min, soit 6-9 muettes) et plafonner l'insistance
à quelques tentatives, puis redémarrer.

---

> **RETIRÉ le 03/10** — cette itération portait la prévision embarquée, démontée à la demande du propriétaire (la station ne transmet pas la pression). Les règles survivent hors du firmware : `docs/forecast-rules.md`.

## 03/10 — PARTIE PRÉVISION RETIRÉE (demande du propriétaire)

L'itération du 02/10 au soir avait ajouté **dans le firmware** une estimation locale de prévision
météo : un modèle C++ (`esphome/includes/vevor_forecast.h`, ~320 lignes), une horloge SNTP, le
composant `sun` (élévation solaire), les substitutions latitude/longitude/fuseau, et quatre entités
(Prévision, Alerte verglas, Taux de pluie, Élévation du soleil). **Retiré intégralement le 03/10**,
à la demande du propriétaire du montage, pour deux raisons :

1. **La station ne fournit pas l'information.** L'icône de la console vient de SON baromètre
   (manuel YT60309 p.20) ; le capteur extérieur ne mesure ni ne transmet la pression. Reproduire une
   prévision à partir d'autres grandeurs, c'est produire une valeur que la station n'a pas donnée.
2. **Des dépendances ajoutées sans prévenir** (horloge NTP, position du soleil, géolocalisation dans
   les substitutions) : ce n'est pas au récepteur de les introduire.

Le firmware ne publie donc plus que des **grandeurs mesurées**. Les règles, elles, sont conservées —
hors de la carte — sous forme de tableaux dans `docs/forecast-rules.md` (seuils et leurs sources,
fenêtre de pluie, référence de ciel clair, anti-battement), à appliquer **dans Home Assistant** avec
l'intégration `sun` et les entités Vevor. `README.md` §1.4 explique le fait et renvoie à ce document.

Retiré : `esphome/includes/vevor_forecast.h`, les entités de prévision, `time: sntp`, `sun:`, les
substitutions géographiques, l'inclusion dans le YAML, l'accesseur dans `vevor_7in1.h`, et les tests
correspondants (la suite repasse de 430 à 377 vérifications, 0 échec).

---

# État du projet — récepteur Vevor 7-en-1

Format : on ajoute une entrée en haut à chaque itération. Jamais de réécriture de l'historique.




## 2026-10-02 22:0x-22:5x UTC — Itération 17 (session interactive) : DOCUMENTATION EN ANGLAIS, SCHEMA DE CABLAGE, TABLE DES ENTITES, PREVISION LOCALE

**Demande utilisateur.** Basculer la documentation en anglais ; ajouter un schéma de câblage ;
séparer nettement la **production** (YAML ESPHome + composants C++, intégration HA simple) de la
partie **tests / validation / outillage** ; ajouter un tableau des entités exposées (plage min/max,
unité, signification) ; et, l'écran de la station estimant 6 météos possibles, vérifier le manuel
et exposer cette entité en développant le calcul.

**MANUEL — ce qu'il dit exactement** (Vevor YT60309, p. 20) : la prévision est calculée par la
**console**, à partir de **son propre baromètre** (« The built-in barometer can notice atmospheric
pressure changes… There are 6 weather icons --- Sunny, Partly Cloudy, Cloudy, Rainy, Stormy and
Snowy. NOTE: The accuracy of a general pressure-based forecast is about 65-70%. »). Alerte verglas,
même page : « When outdoor temperature is lower than 1°C/33.8°F, the snowflake icon will appear ».
Le capteur extérieur ne mesure ni ne transmet la pression (« Weather data: temperature, humidity,
wind speed, wind direction, rainfall, UVI and light intensity ») et la trame de 21 octets n'a
**aucun champ de pression**. **Fait, à ne pas contourner : la prévision propre de la station n'est
pas recevable par ce montage.** (Manuel récupéré hors dépôt, non redistribué ; seules de courtes
citations sont reprises.)

**Ce qui a été implémenté à la place** — dit franchement comme une **estimation locale**, jamais
comme l'icône de la console :
- `esphome/includes/vevor_forecast.h` (C++ pur, testable hors carte) : pluie cumulée différenciée sur
  une **fenêtre glissante de 20 min** (16 échantillons à 75 s, span minimal 5 min sinon « pas de
  pluie ») → `snowy` (< 1 °C, seuil du manuel), `stormy` (≥ 7,6 mm/h WMO « forte pluie » ou rafale
  ≥ 40 km/h), `rainy` ; sinon ciel clair : `lux` mesuré / modèle de ciel clair de Kittler/CIE
  (133 800 × sin(elev)^1,15) → `sunny` (≥ 0,70), `partly_cloudy` (≥ 0,35), `cloudy` ; `unknown` la
  nuit (élévation < 3°), sans horloge, ou sans historique de pluie. Anti-battement : 10 min (1 min
  pour la première publication).
- Entités ajoutées : `Prévision (estimation locale)` (text_sensor, 7 valeurs),
  `Alerte verglas` (binary_sensor `cold`, `temp < 1 °C` — fidèle au manuel),
  `Taux de pluie (estimation)` (sensor diagnostic, mm/h, la grandeur intermédiaire du calcul).
- Horloge : **SNTP** (`time: platform: sntp`, fuseau en substitution) et composant `sun:` (lat/lon en
  substitutions). SNTP plutôt que l'heure Home Assistant : l'estimation doit vivre même sans client
  HA connecté.
- L'estimateur vit **dans le composant** `vevor_7in1` (un `globals:` ESPHome n'accepte pas une classe
  C++ libre — premier build échoué là-dessus, 3 erreurs de compilation, corrigé).

**Documentation.** `README.md` réécrit **en anglais** et restructuré en deux parties explicites :
**PART 1 — PRODUCTION** (matériel, câblage, **tableau des entités avec plage/unité/signification**,
prévision, installation, notes HA) et **PART 2 — TESTS/VALIDATION/OUTILLAGE** (suite hors carte,
décodeur indépendant, outils terrain, preuves versionnées, méthode), plus les 7 pièges. Traduits
aussi : `references/PROTOCOL.md`, `tools/README.md`, `evidence/README.md`. Les journaux internes
(`state/*`) restent en français — c'est dit dans le README.

**Schéma de câblage.** `docs/wiring.svg` (+ `docs/wiring.png`) : ESP32-C3 ↔ CC1101 fil par fil,
pull-up 10 kΩ CSN, condensateur 10 µF, antenne λ/4, encadré des règles. Rendu avec le Chromium du
conteneur puis **contrôlé visuellement** : la première version avait des textes qui se
chevauchaient, elle a été refaite (trois panneaux séparés : détail A, détail B, règles).

**Preuves de cette itération.**
- Suite hors matériel : **430 vérifications, 0 échec** (377 avant ; +53 sur la prévision : seuils aux
  bornes, fenêtre de pluie, remise à zéro du compteur, anti-battement, nuit, horloge non réglée).
- `BUILD OK`, **1 005 616 octets** (`build/last_status.txt`).
- **Flash OTA effectué** (`FLASH OK cible=172.16.0.205`), et les 3 nouvelles entités sont bien
  présentes sur la carte (`tools/read_state.py` : `Alerte verglas = False`,
  `Prévision (estimation locale)`, `Taux de pluie (estimation)`).
- **Horloge vérifiée sur la carte** : `sntp: Synchronized time: 2026-10-03 00:23:30` (heure de Paris).
- **Position du soleil vérifiée sur la carte et recoupée** : nouvelle entité `Élévation du soleil
  (estimation)` publiée aussi par l'intervalle de 20 s (elle reste donc observable radio muette).
  Lue sur la carte : **−42,119°** puis **−42,250°** ; un calcul indépendant (algorithme solaire NOAA,
  lat/lon de la maison) donne respectivement −42,24° et −42,56° aux instants de lecture — accord à
  ~0,1-0,3°, largement suffisant pour un partage de ciel. Vérifié aussi dans le code d'ESPHome que
  `sun` travaille bien en **UTC** (`time_->utcnow()`) : aucun décalage de fuseau, et il renvoie NaN
  si l'heure n'est pas réglée.
- **Rejeu sur données réelles** de l'estimateur (fenêtre validée `logs/verif_garde_fou_60min.log`,
  180 trames réelles du 01/10 14:58→15:58 UTC, latitude/longitude de la maison) : élévation solaire
  calculée de 26,2° à 17,9°, rapport `lux mesuré / lux ciel clair` entre **0,55 et 0,73** → 61 trames
  classées `sunny`, 119 `partly_cloudy`, **0 `cloudy`** (jamais d'inversion absurde) ; pas de pluie et
  rafale ≤ 16,8 km/h dans la fenêtre, donc aucun état de précipitation — cohérent. Ce n'est pas une
  validation de l'icône de la console (irrecevable), c'est le contrôle que le proxy de ciel ne
  raconte pas n'importe quoi sur de vraies mesures.

**Ce qui n'a PAS pu être vérifié sur la carte, et pourquoi (dit franchement).** Aucune trame n'a été
décodée pendant les fenêtres de capture de cette itération. La cause est **mesurée** et **antérieure**
à cette itération (aucun changement radio n'a été fait) : le lien SPI continue de perdre des
écritures de registres par intermittence — relevé du 02/10 22:45:04 :
`ECRITURE NON PRISE FREQ0 : ecrit 0xE8, relu 0xEC` puis
`controle des ecritures : 1 registre(s) NON pris — la configuration radio n'est pas celle demandee`
(plus 1 ou 2 registres non pris à chaque cycle sur 0x24/0x1D/0x0F). La puce répond pourtant
normalement (Chip ID 0x0014) et reste en RX (MARCSTATE=0x0D), mais sa configuration n'est pas celle
demandée : les captures RMT sont alors du bruit (2 à 5 impulsions), avec une seule capture de 159
impulsions en 6 min. La chaîne `V7IN1 PREV` n'a donc **pas** été observée ce soir. Ce n'est pas la
logique de prévision qui est en cause (elle est couverte par 53 vérifications hors carte et par le
rejeu sur données réelles ci-dessus) : c'est le lien SPI. Pistes déjà documentées et non montées :
alimentation dédiée du module par LDO + 100 nF au plus près du VCC, ou coupure d'alimentation par
P-MOSFET (README §1.2). À reprendre par la boucle radio quand elle sera autorisée à tourner.

## 2026-10-02 — REVUE DE LA DOCUMENTATION LONGUE ET NETTOYAGE (commit 9693dbe)

**Objet.** Revue de cohérence demandée le 02/10 : documentation longue/archivée, chiffres périmés,
affirmations réfutées. Cette entrée est **ajoutée en tête** conformément à la règle du fichier ;
**aucun texte passé n'est réécrit** — les entrées concernées reçoivent seulement un bandeau de tête.

**Anomalie de structure à connaître.** Les dernières itérations (15 et 16 du 01/10) puis les sections
du **02/10** (intervention matérielle, cause racine SPI 200 kHz, validation de 30 min) ont été
écrites **en bas** de ce fichier, après les entrées du 30/09 et du début du 01/10, contrairement à la
règle « une entrée en haut ». On ne réécrit pas l'historique : la présente entrée est la plus récente
en **tête**, mais la **chronologie vraie se termine en fin de fichier** (sections « 02/10 — … »).

**Chiffres remis à jour.** La suite hors matériel compte désormais **377 vérifications, 0 échec**
(`README.md:24`, `build/message_commit4.txt`, relancée le 02/10). Les mentions historiques « 128 »
(section PAUSE du 30/09), « 173 » (it. 7) et « 204 » (`state/DONE.md`, état du 01/10) sont des **états
antérieurs** : ne pas les lire comme le total courant. Un bandeau a été posé sur la section PAUSE, où
« 128 » est annoncé.

**Firmware.** Recompilé `BUILD OK`, **966 400 octets** (`build/last_status.txt`). Ce binaire **n'est
PAS flashé** : la carte tourne encore l'ancien firmware ; aucun flash n'a été fait pour cette revue.

**Nettoyage d'outillage (02/10).**
- `tools/_common.py` créé : **une seule** version de `key_from_yaml`, de `maybe_await`, **une seule**
  table `VARIANTS`, écritures **atomiques** (`os.replace`) et chemins relatifs résolus par rapport à
  la **racine** du projet (jamais au CWD). La duplication signalée par `state/DONE.md:104-105` est
  supprimée (vérifié : plus qu'une seule définition de chaque).
- **Échecs silencieux supprimés** : une mesure nulle sort désormais **code 3** (`RC_MESURE_NULLE`), une
  absence de trame **code 0** — contrats distingués (`tools/_common.py`, `tools/count_probe.py`,
  `tools/eval_frames.py`).
- Sauvegarde d'ancienne production `esphome/vevor-7in1.yaml.bak-20261001` **supprimée**.
- **En attente de décision utilisateur** : les **13 outils morts/doublons** recensés par la revue
  round 2 (`reviews/round2/02-outillage-preuves.md` §1.7) ne sont **pas encore supprimés**.

**Affirmations réfutées, désormais bannérisées.**
- It. **11septies** (« la station n'émet que par fenêtres de quelques minutes ») et it. **11nonies**
  (« la station émet par bouffées ») : **FAUX**. `state/DONE.md` §3 établit que les fenêtres vides
  étaient des « carte sourde » ; la station émet **en continu toutes les 20 s**. Chaque entrée porte
  un bandeau de tête.
- La **cause racine** des « 0 trame » n'était ni la station, ni l'environnement de build, ni le
  quartz : c'est la **cadence SPI de 200 kHz** que le pilote avait été réglé à utiliser (correctif du
  02/10, SPI rétabli à 1 MHz). Voir les sections « 02/10 — CAUSE RACINE » et « 02/10 — VALIDATION »
  en fin de fichier.

**Notes de nuit archivées.** `state/NUIT.md` et `state/BILAN_NUIT_20261002.md` (rédigées avant la
cause racine) sont **déplacées** en `state/archive/2026-10-01_NUIT.md` et
`state/archive/2026-10-02_BILAN_NUIT.md`, chacune avec un bandeau disant ce qui est réfuté et où lire
l'état vrai. Contenu intégralement conservé (journal de diagnostic).

**Références contrôlées.** `evidence/README.md` : cohérent avec `evidence/` et les outils (aucune
correction nécessaire). `references/PROTOCOL.md`, `references/EXTERNAL_CONTEXT_WIZARDPC.md` et
`references/HOME_ASSISTANT.md` : bandeaux de statut ajoutés (valeurs radio rtl_433 ≠ config livrée ;
table « Nous » du 30/09 périmée ; API HA non joignable sur :8123). Le projet `WizardPC` reste
**externe**, jamais recopié.

## 2026-10-01 09:32:43-09:42:23 UTC — Itération 11nonies (session interactive) : VALIDATION 10 MIN — 60/60 TRAMES VALIDÉES, CADENCE 20,0 s, VERDICT `PASS` → objectif de MISSION.md ATTEINT

> **BANDEAU (ajouté le 02/10, commit 9693dbe) — entrée partiellement réfutée.** La phrase de fin
> « la station émet par bouffées (contrôle physique de l'unité extérieure recommandé) » est **fausse** :
> `state/DONE.md` §3 établit que les fenêtres vides étaient des « carte sourde » ; la station émet
> **en continu toutes les 20 s**. L'état vrai et la cause racine (cadence SPI 200 kHz, corrigée le
> 02/10) sont dans `state/DONE.md` et dans les entrées du 02/10 en fin de ce fichier.

**Fenêtre** : `logs/validation_prod_20261001.log` (600 s pleines), firmware de production corrigé
(config sans second périphérique SPI, binaire `build/variants/nous_prod.ota.bin`).

**Mesuré**
- **60 trames décodées, 60 valides** : `checksum_fail=0`, `counter_fail=0`, `V7IN1 REJ=0`,
  30 doublons de livraison RMT ignorés. Le **décodeur Python indépendant**
  (`tools/eval_frames.py` → `logs/validation_prod_rapport.json`) retrouve les mêmes 60 trames et
  conclut **`verdict: PASS`** — les deux implémentations concordent trame par trame.
- **Cadence : 20,0 s pile** (médiane = min = max des intervalles entre émissions, sur 30 rafales).
  La station a émis pendant les 10 minutes entières (plus de 1 h 40 d'émission continue au total).
- **Cohérence** : T 17,5-17,7 °C ; H 66-74 % ; vent et rafale variables (rafale ≥ vent) ;
  direction 273-299° ; **pluie monotone 59,2 mm** ; UV 2-3 ; lux 11 520-29 970 ; un seul `id`
  (33995 = 0x84CB) ; toutes les valeurs dans les plages physiques ; aucun problème signalé.
- **Recoupement indépendant** : le firmware **témoin** (dépôt `WizardPC/esphome-vevor-7in1`,
  compilé et flashé par nous) lisait la même station au même moment : T 17,5 °C, H 70-71 %,
  pluie 59,2 mm, lux 18 810-19 080 à 09:19 UTC (et 6 trames/60 s à 09:28).

**Ce qui a produit le résultat** (détail en itération 11octies) : suppression du second périphérique
SPI de notre composant + de la ré-armature radio au boot. Justification de la ré-armature, désormais
caduque : elle avait été ajoutée pour un mutisme post-OTA qui était en réalité causé par ce
périphérique SPI (chaque reboot re-déclarait ce dernier).

**Écriture de fin de mission** : `state/DONE.md` (statut, preuves, suites). Boucle planifiée
`5fe5aac7bcf4` **laissée en pause** ; l'utilisateur a été prévenu avec les preuves.

**Reste ouvert (non bloquant, dit franchement)** : le mécanisme exact par lequel un second
périphérique SPI (CS sur une broche libre, GPIO10) rend la puce muette n'est pas expliqué au niveau
du pilote — la cause est établie empiriquement par alternance dans les mêmes fenêtres. Et la station
émet par bouffées (contrôle physique de l'unité extérieure recommandé).

## 2026-10-01 08:50-09:32 UTC — Itération 11octies (session interactive) : CAUSE TROUVÉE ET CORRIGÉE — notre SECOND PÉRIPHÉRIQUE SPI (instrument de registres, GPIO10) cassait la réception

**La preuve, par alternance témoin / nous dans les MÊMES fenêtres d'émission** (`tools/ab_cycle.py` :
flash du binaire figé, 12 s de démarrage, 60 s de capture, résultat en JSONL) :

| Créneau (UTC) | Firmware mesuré | Trames décodées | Captures RMT | Taille des rafales |
|---|---|---|---|---|
| 08:53:49 | témoin | **6** | 9-15 | jusqu'à 501 impulsions |
| 08:55:09 | nous V0 (actuel, instrument GPIO10) | 0 | 2 | — |
| 08:56:30 | nous V1 (sans ré-armature boot) | 0 | **0** | — |
| 08:57:51 → 09:13:55 | témoin (3 créneaux) | **6, 6, 6** | 9-15 | 498-529 |
| idem | nous V0 / V1 | 0 / 0 | 1-6 / 0 | — |
| 09:24:19 | témoin | 0 (fenêtre de silence de la station) | 0 | — |
| **09:25:38** | **nous V2 = V1 SANS le périphérique SPI GPIO10** | **5** | **9** | **176 impulsions** |
| 09:26:59 | nous V1 (avec le périphérique) | 0 | 0 | — |
| 09:28:20 | témoin | 6 | 9 | 176 |
| **09:29:39** | **nous V2** | **5** | **9** | **178 impulsions** |

Trames de V2, décodées par NOTRE code, station 0x84CB (33995) :
`aa 00 84 cb 16 02 a2 49 01 15 03 02 14 01 ff 04 6d 49 b9 9e ba` →
`{"temp_c":17.4,"humidity":73,"wind_kmh":2.4,"gust_kmh":2.4,"wind_dir_deg":275,
"rain_mm":59.2,"uv_index":3,"lux":27720}` puis `wind_kmh:7.4, gust 8.0, dir 286, lux 20700`.
Durées brutes : `93 -83 92 -84 91 -85 …` (période bit 90 µs, polarité normale) — la même forme que
les `x[0]=93, x[1]=-85` du témoin au même moment (T 17.5 °C / H 70-71 % / pluie 59.2 mm chez lui).

**Conclusion** : le firmware témoin et le nôtre décodent tous les deux la station, à la même minute,
sur la même carte — la différence n'était ni le code, ni l'environnement de build de l'agent (testé :
témoin compilé par nous avec esphome 2026.9.0 ET 2026.9.1, les deux décodent), ni la version
d'ESPHome, ni la ré-armature radio au boot (V1 sans elle = toujours 0). C'était **le second
périphérique SPI** que notre composant déclarait sur le bus du cc1101 (broche CS GPIO10) : il suffit
à rendre le cc1101 muet (0 capture RMT, donc aucune donnée n'arrive même au décodeur). Le témoin n'a
qu'un seul périphérique sur ce bus — c'était là toute la différence.

**Correction appliquée à la configuration de production** (`esphome/vevor-7in1.yaml`, sauvegarde
`vevor-7in1.yaml.bak-20261001`) :
1. `cs_pin` du composant `vevor_7in1` **retiré** (plus de second périphérique SPI) ;
2. ré-armature radio du boot **retirée** : elle contournait un mutisme dont on connaît maintenant la
   cause, et elle injectait elle-même des trains de bruit + des échecs de verrouillage PLL ;
3. `cs_pin` rendu facultatif dans le schéma du composant
   (`spi.spi_device_schema(cs_pin_required=False)`) — le composant gérait déjà ce cas.
Conséquence assumée : plus d'inventaire de registres ni de RSSI/MARCSTATE lus par SPI (ces entités
restent vides). Le balayage de fréquence reste possible : il passe par le composant `cc1101`.

Binaire de production reconstruit (`build/variants/nous_prod.ota.bin`, 968 704 o) et flashé
(`OTA successful`), puis validation de 10 min lancée (`logs/validation_prod_20261001.log` +
`tools/eval_frames.py`). Variante de test conservée : `esphome/vevor-7in1-v2.yaml`.

**Ce qui n'est PAS prouvé** : le mécanisme exact (le périphérique SPI sur GPIO10 empêche-t-il
l'enregistrement du device du cc1101 auprès du bus IDF, ou le fait-il passer en échec au boot ?) —
la cause est établie empiriquement, pas expliquée au niveau du pilote. Et la station émet toujours
par fenêtres (voir itération 11septies) : toute mesure de « 0 trame » doit être validée par un
créneau témoin dans la même fenêtre.

## 2026-10-01 07:40-08:45 UTC — Itération 11septies (session interactive) : LE CODE TÉMOIN, CONSTRUIT ET FLASHÉ PAR L'AGENT, DÉCODE — l'environnement de build est innocenté ; la station n'ÉMET QUE PAR FENÊTRES

> **BANDEAU (ajouté le 02/10, commit 9693dbe) — entrée partiellement réfutée.** La « Découverte : la
> station n'émet que par fenêtres de quelques minutes » est **fausse** : `state/DONE.md` §3 établit que
> les fenêtres vides correspondaient à des « carte sourde », la station émettant **en continu toutes
> les 20 s**. Le titre et la section restent comme trace de l'hypothèse, mais ne pas s'en servir comme
> fait. État vrai : `state/DONE.md` ; cause racine : entrées du 02/10 en fin de ce fichier.

**Ce qui a été fait (et qui n'avait jamais été fait)**
- Dépôt témoin récupéré par nos soins (`git clone https://github.com/WizardPC/esphome-vevor-7in1`, commit
  `6ff19a4` « 3.2 »), dans `/home/hermes/projets/_temoins/` — **hors du projet**, jamais importé chez nous.
  Le composant effectivement compilé est identique au dépôt (`diff -r` : seul `__pycache__` diffère).
- YAML du témoin : celui fourni par l'utilisateur, **repris tel quel** (seules les fins de ligne CRLF→LF
  changent, `diff` = identique). Un `secrets.yaml` local mappe ses 3 noms de secrets
  (`wifi_ssid`, `wifi_password`, `esp32_weather__encryption_key`) sur notre Wi-Fi et **notre clé API** —
  c'est ce qui rend la carte lisible par notre outillage (API native 6053) une fois son firmware en place.
- Compilé par nous (esphome **2026.9.1**, puis séparément **2026.9.0**), flashé par nous en OTA
  (`INFO OTA successful`, 5,2 s), mesuré par nous.

**Résultat : le témoin décode, construit et flashé par l'agent**
- `logs/witness090_boot_20261001.log` (08:04:23→08:06:00) : 5 trames / 25 rafales — `[84CB] T=16.7°C
  H=78% wind=0.0 (gust 0.0) km/h dir=299° rain=59.2mm UV=0 lux=8505`.
- `logs/AB_20261001_A_esphome20260901.log` (08:06:43→08:09:31) : **18 trames / 32 rafales**, même station,
  `T=17.0°C H=76% rain=59.2mm lux=10080`. Rafales de 70 à 519 impulsions, recollage `96+82 (extra=-180 us)`.
- **Hypothèse « c'est l'environnement de build de l'agent » : MORTE.** Le MÊME YAML témoin, compilé par
  nous avec **2026.9.0** *et* avec **2026.9.1**, décode (essais faits dans la même fenêtre d'émission à
  2 min d'intervalle, `md5` des binaires différents : `c6a3f7d3…` / `b0490a04…`). La version d'ESPHome
  n'est donc pas le facteur.

**Découverte : la station n'émet que par fenêtres de quelques minutes**
| Fenêtre (UTC) | Firmware sur la carte | Ce qui est reçu |
|---|---|---|
| 07:48→08:03 | témoin | 0 rafale, 0 trame (15 min) |
| **08:04:23→08:09:23** | témoin (2 boots) | **23 trames**, cadence 20 s |
| 08:10:07→08:15:00 | **nous (V0)** | 0 trame, `captures=4` |
| 08:15:38→08:18:08 | témoin | 0 rafale |
| 08:18:31→08:38:31 | témoin (M1, 20 min sans reboot) | 0 rafale, 0 trame |
| 08:38:44→08:40:24 | témoin | 0 rafale |
| **08:40:54→08:42:30** | **nous (V0)** | **+5/+6 captures toutes les 20 s**, `dernières impulsions=76-82`,
  `plus longue=519`, **0 trame décodée** |
| 08:42:30→08:45+ | nous (V0) | 0 capture nouvelle |

Lectures : (1) la station émet ~2 à 6 min par ~30 min — 20 s pile pendant la fenêtre, puis silence
total ; son ID reste `0x84CB` et sa pluie monte normalement (57,8 → 59,2 mm), donc l'ISS n'est pas
retombée sous tension : à confirmer par un contrôle physique (afficheur intérieur : se met-il à jour
en continu ou par bouffées ?). (2) Les fenêtres ON/OFF ne suivent **ni** le firmware, **ni** le
nombre de reboots, **ni** la version d'ESPHome — elles suivent l'heure. (3) La fenêtre 08:10, où nous
n'avons rien reçu, était une fenêtre de **silence de la station** : elle ne prouve rien sur notre code.

**Ce qui reste ouvert (une seule question, mesurable)**
Dans la fenêtre 08:40:54→08:42:30, **notre** firmware reçoit les rafales (compteur +5/+6 toutes les
20 s, 76-82 impulsions) mais n'en décode aucune, là où le témoin décodait 23 trames une demi-heure
plus tôt. Il faut donc : (a) les **durées brutes** de nos captures pendant une fenêtre d'émission
(bouton « Dump impulsions » armé, fenêtre longue en cours : `logs/fenetre_suivante_dump_20261001.log`),
et (b) la comparaison **témoin / nous dans la MÊME fenêtre** — outil écrit pour ça :
`tools/ab_cycle.py` (alterne les binaires figés dans `build/variants/`, mesure 100 s chacun,
résultats en JSONL dans `logs/ab_cycle.jsonl`).

**Outils ajoutés** : `tools/ab_cycle.py` (cycle A/B interleavé), `esphome/vevor-7in1-v1.yaml`
(variante sans ré-armature radio au boot), binaires figés `build/variants/nous_v0.ota.bin` (actuel) et
`nous_v1.ota.bin` (sans ré-armature). Boucle planifiée `5fe5aac7bcf4` **laissée en pause** pendant ces
essais (elle reflasherait notre firmware au milieu d'une mesure).

## 2026-10-01 06:00-06:11 UTC — Itération 11sexies (réveil dédié, 08:00 locales) : AUCUN SIGNAL au lever du jour — 0 capture, 0 trame en 10 min, carte saine, compteur RMT figé à 48

**Pourquoi cette étape** : réveil programmé par l'utilisateur (job faec92db373d, 06:00 UTC = 08:00 locales) pour tester l'hypothèse « la station solaire redémarre le matin, donc le signal revient ». Mesure passive de 10 min, aucun appui radio, aucun flash, state/PHASE non modifié.

**Vérifié (preuves)**
- **Fenêtre 06:00:56 → 06:10:54 UTC, 600 s pleines** (tools/capture_logs.py --host 172.16.0.205 --seconds 600 --out logs/retry_0800.log, 493 lignes) : « trame extraite » = **0**, « V7IN1 OK » = **0**, « V7IN1 RAW » = **0**, « rafale capturée » = **0**.
- **Aucune capture du tout** — pas même des miettes ni des trains de bruit : le compteur est resté **figé à captures=48** sur les 120 battements de cœur de la fenêtre (grep -oE captures=[0-9]+ | sort -u → une seule valeur, 48). Même valeur qu'à 00:09 (it. 11quinquies) : la carte n'a pas redémarré et n'a rien entendu pendant 10 min.
- **Carte saine** : « récepteur opérationnel (is_failed=false) » 10 fois (06:01:01 → 06:10:02), 0 ligne « PLL », aucun redémarrage, aucune erreur fatale ; le mute 0xFFFF ne s'est pas reproduit.
- **C'est bien la version alignée sur le témoin qui tourne** : esphome/vevor-7in1.yaml (21:58:48) < build/last_status.txt = BUILD OK 969 280 o < logs/last_flash_status.txt = FLASH OK cible=172.16.0.205 → binaire esp-idf, bus SPI propre, instrument de registres sur GPIO10.
- **Instrument de registres (GPIO10) toujours muet** : VERSION=0x00, « lecture SPI suspecte », plancher n=2948 moy=-74.0 min=-74.0 max=-74.0 (constante = pas une mesure). À ignorer, comme documenté en 11ter.

**Hypothèse du lever du soleil : NON confirmée à 08:00 locales** — la station n'émet toujours pas, et le récepteur ne capte même plus le bruit de fond (4 à 10 captures / 300 s) observé le 30/09 au soir.

**Prochaine action** : demander à l'utilisateur une **coupure d'alimentation de 10 s** de la carte (seul remède connu), puis re-mesurer 10 min ; en parallèle, contrôle physique de la station (unité extérieure solaire : affichage intérieur, pile). state/PHASE laissé **volontairement inchangé** pour que la boucle 15 min reste silencieuse (pas de seconde capture en parallèle).


## 2026-10-01 00:09-00:16 UTC — Itération 11quinquies (boucle) : fenêtre de nuit — aucun signal, et le compteur de captures N'EST PAS figé (46 → 48 sans aucune action)

**Pourquoi cette étape** : réveil de contrôle de la boucle (changement de « bucket » à 00:00 UTC). Une seule action, non invasive : une fenêtre de mesure de nuit sur la version en cours (esp-idf, bus SPI propre, sonde retirée) pour établir la **ligne de base de bruit** qui servira à juger la mesure de 06:00. Aucun appui radio, aucun flash, `state/PHASE` non modifié.

**Vérifié (preuves)**
- **Fenêtre 00:09:27 → 00:16:23 UTC (6 min 56 s, `logs/night_baseline_0009.log`)** : `récepteur opérationnel (is_failed=false)`, battement de cœur `aucune rafale depuis 5 s (captures=48, trames=0) — normal` sur toute la fenêtre, **0 trame** (`grep -c "V7IN1 RAW\|V7IN1 OK"` = 0), **aucune ligne « PLL »**, aucune ligne de démarrage.
- **Le compteur de captures n'est pas figé** : il vaut **46** à 22:28 (fin de `logs/night_after_bench_150s.log`) et **48** dès la connexion à 00:09:27, **sans aucun appui de notre part ni redémarrage** → ~2 captures spontanées en ~1 h 40 de nuit. **Correction de lecture** : à l'itération 11quater, le « compteur figé » servait de preuve d'absence de reboot ; cette inférence est plus faible qu'annoncée (le compteur bouge seul, lentement). La preuve de bonne santé de la carte reste la fenêtre live (`is_failed=false`, battement de cœur toutes les 5 s).
- **Conséquence directe pour le jugement de 06:00** : un compteur qui a bougé de quelques unités **n'est pas** une preuve de signal. Ligne de base de nuit mesurée : 0 capture / 7 min sur la fenêtre, ~2 captures / 100 min en tout, **toutes sans rafale**. Une émission utile se reconnaît à la TAILLE (`dernières impulsions` 94+70 ou 161-178, plus plusieurs dizaines de captures en 10 min), jamais au seul compteur.
- **C'est bien la version alignée témoin qui tourne** : `esphome/vevor-7in1.yaml` mtime 21:58:48 < binaire 21:59:05 < flash 21:59:15 (`build/last_status.txt` = BUILD OK 969 280 o, `logs/last_flash_status.txt` = FLASH OK) → le binaire flashé contient bien l'état actuel du YAML (esp-idf, sonde retirée, instrument de registres sur GPIO10).
- **Réveil dédié toujours armé** : `hermes cron list` → `faec92db373d` [active], `Next run 2026-10-01T06:00:00+00:00`, livraison #esphome.

**Pas de signal** : 0 trame, 0 capture nouvelle sur la fenêtre — cohérent avec la nuit (dernière trame décodée : `logs/validation_5min_20260930.log` à 19:28:43 UTC).

**Prochaine action** : inchangée — mesure de 06:00 UTC par le job dédié (10 min dans `logs/retry_0800.log`), jugée sur la taille des captures. `state/PHASE` laissé **volontairement inchangé** : l'empreinte du moniteur reste stable, la boucle 15 min reste donc silencieuse jusqu'au changement de « bucket » de 06:00 (aucun réveil intermédiaire, aucune capture en parallèle du job dédié). **Toujours pas de reflash d'ici là.**

## 2026-09-30 22:46-22:47 UTC — Itération 11quater (boucle) : pré-vol du réveil de 06:00 — carte joignable, stable, silencieuse ; rien d'autre à faire cette nuit

**Pourquoi cette étape** : la boucle s'est réveillée sur changement de `state/PHASE` (plan de reprise à 06:00). Il fait nuit, la station n'émet pas : le seul risque réel du plan avant l'aube est un imprévu (carte tombée du réseau, reboot, redémarrage de la chaîne de décodage). Cette itération le vérifie — et ne fait **rien** d'autre : pas de reflash, pas d'appui radio, pas de capture longue.

**Vérifié (preuves)**
- **Carte joignable** : API native 6053 ouverte, connexion établie `# connecté à 172.16.0.205:6053 — vevor-7in1 / esp32-c3-devkitm-1 / esphome 2026.9.1` ; `tools/find_esp32.py` → `172.16.0.205`. Preuve : `logs/night_linkcheck_2248.log` (45 s).
- **Aucun reboot depuis la veille de 22:28** : le compteur reste figé à `captures=46` sur toute la fenêtre (même valeur qu'à 22:28:21, fin de `logs/night_after_bench_150s.log`) ; la boucle de décodage tourne (`aucune rafale depuis 5 s (captures=46, trames=0) — normal`) ; **aucune ligne « PLL »**, aucune capture parasite.
- **C'est bien la version mesurée qui tourne** : `build/last_status.txt` = BUILD OK (esp-idf, binaire 969 280 o), `logs/last_flash_status.txt` = FLASH OK cible=172.16.0.205.
- **Réveil dédié toujours armé** : `hermes cron list` → job `faec92db373d` [active], `once at 2026-10-01 06:00`, Next run `2026-10-01T06:00:00+00:00`.
- **Instrument de registres (GPIO10) toujours muet**, comme documenté à l'itération 11ter : `VERSION=0x00`, `lecture SPI suspecte : VERSION=0x00 (attendu 0x14)`, `plancher n=287 moy=-74.0 min=-74.0 max=-74.0` (valeur constante = pas une mesure, la broche CS n'est pas câblée). À ignorer, ne pas le remettre sur GPIO7.

**Pas de signal** : 0 capture, 0 trame sur la fenêtre — attendu (nuit, station alimentée par le soleil), ce n'est pas un défaut de la chaîne de réception.

**Prochaine action** : inchangée — job `faec92db373d` à 06:00 UTC (10 min dans `logs/retry_0800.log`, jugement sur la TAILLE des captures). `state/PHASE` laissé **volontairement inchangé** : l'empreinte du moniteur reste identique, la boucle 15 min reste donc silencieuse jusqu'au changement de « bucket » de 06:00 (aucun réveil parasite, aucune seconde capture en parallèle du job dédié). **Ne pas reflasher d'ici là.**

## 2026-09-30 22:23-22:28 UTC — Itération 11ter (boucle) : VEILLE DE NUIT — la puce répond 6/6 fois `Chip ID 0x0014` (le « mute 0xFFFF » venait de notre instrumentation sur le bus SPI), et chaque ré-armature déverrouille la PLL en injectant des trains de bruit

**Pourquoi cette étape** : la boucle s'est réveillée sur changement de `state/PHASE` (plan de reprise à 06:00 UTC). Nuit à Plougastel : la station n'émet plus, aucune trame n'est attendue avant l'aube — mais deux choses restaient mesurables sans signal : l'état réel de la puce et l'effet de nos propres outils sur la chaîne de réception.

**1. Le « mute » (tous registres `0xFF`) ne se reproduit plus avec le bus propre — 6 appuis, 6 fois `0x0014`**
- Protocole : 6 appuis du bouton « Réappliquer la config radio » (chaque appui = `cc1101.reset` + réécriture complète de la config + `begin_rx`, donc une lecture PARTNUM/VERSION faite par le pilote ESPHome lui-même), fenêtre de 18 s par appui : `logs/night_bench_1..6.log` (appuis à 22:23:08, 22:23:32, 22:23:56, 22:24:19, 22:24:43, 22:25:06 UTC).
- Résultat : `[D][cc1101:148]: CC1101 found! Chip ID: 0x0014` **6 fois sur 6** ; aucun `Failed to verify CC1101`, aucun `cc1101 was marked as failed`.
- Comparaison directe, MÊME bouton, version précédente (instrument de registres partageant GPIO7) : `logs/iter11_rearm_2128.log` → `Chip ID: 0xFFFF` + `Failed to verify CC1101.` + `cc1101 was marked as failed`. La seule différence entre les deux versions est le bus SPI (instrument déplacé sur GPIO10).
- **Lecture** : le mute aléatoire observé hier soir dans cette forme était lié à notre instrumentation sur le bus, pas à la puce. Conséquence pratique : plus besoin de couper l'alimentation ni de contrôler l'antenne pour ce symptôme ; il ne reste que la question « la station émet-elle de nouveau ? ».

**2. Notre ré-armature déverrouille la PLL et injecte des captures de bruit (mesuré)**
- 5 appuis sur 6 produisent `[W][cc1101:317]: PLL lock failed, retrying calibration` (9 avertissements au total : 3/2/2/0/1/1 par appui). Le pilote relance la calibration et **finit par se verrouiller** : l'erreur fatale `PLL lock failed after retries` n'apparaît jamais (0 occurrence sur les 6 fichiers).
- Pendant ces fenêtres : **3 captures en 23 min avant tout appui → +43 captures en ~2 min d'appuis** (compteur 3 → 46), chaque relevé portant `plus longue=511` ou `547` (tampon PLEIN = train de bruit), dernières captures de 22, 86, 486, 90, 5, 20 impulsions.
- Contrôle immédiat, 150 s **sans aucune action** : `logs/night_after_bench_150s.log` → **0 capture nouvelle** (compteur figé à 46), aucune ligne PLL. Le bruit suit donc les appuis, il n'est pas ambiant.
- **Hypothèse ouverte pour demain** : l'anomalie historique « captures de ~500 impulsions (bruit) ou miettes de 2-7 selon le boot » et la quantification en multiples de 11,25 µs sont au moins partiellement produites par NOTRE ré-armature — chaque `cc1101.reset` fait passer la PLL par un état non verrouillé, et GDO0 sort alors du bruit. Test à faire avec signal : comparer les captures de la 1re minute après boot (ré-armature) et 5 min plus tard.

**3. Ce qui n'a pas pu être mesuré (dit franchement)**
- **Pas de signal** : 0 capture hors appuis, 0 trame. Nuit, station solaire : cohérent, ce n'est pas un défaut de la chaîne de réception.
- L'instrument de registres (déplacé sur GPIO10) ne lit plus rien : l'entité publie « PUCE MUETTE (bus SPI) » et ses valeurs (`RSSI −74 dBm`, `SLEEP`, `0,00000 MHz`) sont du bruit — **à ignorer**.

**Prochaine action** : réveil programmé (job `faec92db373d`, 2026-10-01 06:00 UTC = 08:00 locales) → 10 min de mesure dans `logs/retry_0800.log`, jugée sur la TAILLE des captures. **Ne pas reflasher avant cette mesure** : un flash = reboot = ré-armature = trains de bruit pendant la recalibration de PLL. Si la boucle 15 min se réveille à 06:00 par changement de « bucket », ne rien lancer et laisser la main au job dédié.

## 2026-09-30 22:00-22:10 UTC — Itération 11bis (session interactive) : PARITÉ AVEC LE TÉMOIN (framework esp-idf, AGC 42 dB, bus SPI propre) — flashé, mais intestable tant que le signal n'arrive pas

**Ce que le YAML du témoin m'a appris (fichier fourni par l'utilisateur, code + config)**
Comparaison champ par champ de son YAML avec le nôtre — trois différences réelles, toutes traitées :
1. **`framework: type: esp-idf`** chez lui, `arduino` chez nous. C'est la différence de fond (ESPHome
   fait d'esp-idf le framework par défaut des ESP32 depuis 2026.1 ; leur guide de migration parle
   explicitement d'opérations « sensibles au timing » à réajuster). **Bascule faite** : le build
   esp-idf passe sans difficulté dans ce conteneur (969 280 o contre 1 001 536 o en arduino), le
   blocage d'origine (« Can't create Python virtual environment for ESP-IDF ») étant résolu depuis
   par le CPython autonome de `.venv` ; toolchain IDF déjà en cache (2,8 Go).
2. **`magn_target`** : nous le forcions à **33 dB**, le défaut ESPHome (et donc le témoin) est
   **42 dB** — soit ~9 dB de gain AGC en moins de notre côté, sur un signal faible. **Retiré** (avec
   `num_preamble: 4`, sans effet en réception). Nos deux blocs `cc1101` sont désormais identiques.
3. **Bus SPI** : notre instrument de diagnostic (lecture des registres) déclarait un **second
   périphérique sur la même broche CS (GPIO7)** que le `cc1101`, et sous esp-idf toutes ses lectures
   revenaient à `0xFF` (VERSION comprise) — signe que les transactions de la puce pouvaient être
   perturbées. **Déplacé sur GPIO10** (non câblée) : le `cc1101` redevient le seul maître du bus,
   comme chez le témoin. `allow_other_uses` retiré des deux côtés.

**Résultats mesurés avec cette version (300 s, `logs/idf_300s.log` et `logs/idf_cleanbus_300s.log`)**
57 captures en 300 s (le rythme du témoin) mais **4 à 5 impulsions par capture**, **0 trame**, et
l'instrument déplacé lit `0x00` (normal : plus de puce en face) — donc plus aucune mesure de registre
possible depuis notre composant. **Ces fenêtres ne prouvent rien sur la parité de configuration :
elle est simplement intestable tant que le signal n'arrive pas.**

**Fait établi par l'itération 11 de la boucle, qui change la lecture de la soirée** : inventaire
complet des registres → la puce **est** correctement configurée (11108 bauds, DRATE_E=8, MDMCFG3=192,
868,34985 MHz) et **en état sain elle ne détecte aucune porteuse** (RSSI plat −112,5 dBm, `CS=0`),
alors que le témoin, sur la **même carte**, décodait 44 rafales / 39 trames en 300 s à 20:31-20:36
UTC. La dégradation est donc **progressive et physique** : 44 rafales/300 s (20:31) → 4-10 captures
/300 s (20:40-20:52) → rien (21:30+). Les hypothèses « démodulateur 8× trop rapide », « clone de
CC1101 » et « configuration fausse » sont **mortes** (registres lus).

**Prochaine action (physique, demandée à l'utilisateur)** : revisser/revérifier l'antenne 868 MHz et
son connecteur sur le module ; vérifier que la station émet encore (afficheur intérieur : mise à jour
toutes les ~20 s ? icône de pile faible ?). Le contrôle est lisible en une commande (entité
« Inventaire registres CC1101 » ou toute capture : `CS` qui bascule et plancher qui remonte vers
−100 dBm = le signal est revenu). Dès qu'il revient, rejouer une fenêtre de 10 min avec la version
esp-idf + config alignée (c'est le test de parité qui reste à faire).

## 2026-09-30 21:18-21:50 UTC — Itération 11 (boucle) : inventaire complet des registres → la puce est CORRECTEMENT configurée, l'hypothèse « démodulateur 8× trop rapide » et celle du clone sont MORTES ; en état sain la puce n'entend AUCUNE porteuse (RSSI −112,5 dBm plat, CS=0) → le signal n'arrive plus

**1. Nouvel instrument : inventaire des registres (bouton + entité + log au démarrage)**
- `Vevor7in1::log_register_inventory()` lit les 47 registres de configuration (0x00-0x2E, adresse
  seule, **sans** le bit de rafale réservé aux registres d'état) + PARTNUM/VERSION/RSSI/MARCSTATE/
  PKTSTATUS, calcule le débit, la bande, la déviation RÉELLEMENT actifs, et **publie le résultat en
  entité** : « Inventaire registres CC1101 » (`inventory_sensor`). La valeur survit à la fenêtre de
  logs (l'API la relit à chaque connexion) → plus besoin de capturer au démarrage.
- Appelable par le bouton « Relire l'inventaire registres CC1101 » et rejoué au boot
  (`on_boot`, après la ré-armature). Builds : `BUILD OK code=0` (1 012 496 o) ; flashes :
  `FLASH OK code=0` ×4. Léger échantillonnage RADIO rétabli (3 registres d'état / 10 s) car le test
  « sans instrumentation » du 20:52 n'avait rien changé.

**2. La puce est configurée EXACTEMENT comme voulu — deux hypothèses ferment** (`logs/iter11_inv2_2132.log`)
- `PARTNUM=0x00 VERSION=0x14 (relu 0x14)` → CC1101 d'origine, bus SPI sain (pas de clone).
- `11108 baud (DRATE_E=8, MDMCFG3=192) | 868.34985 MHz | dev 69.8 kHz | BW 101562 Hz |
  mod 0x0 (2-FSK) sync 0x2 (16/16) | pktctrl0=0x32 (PKT_FORMAT=3 = série asynchrone) |
  iocfg0=0x0D (GDO0 = données série) | MDMCFG4..0=C8 C0 02 42 F8 | DEVIATN=53`, `MARCSTATE=0x0D RX`.
- **Donc : pas d'erreur de débit ×8** (le débit écrit est bien 11 108 bauds, pas 88 800) : la
  quantification des impulsions en multiples de 11,25 µs **n'est pas** un démodulateur trop rapide.
  Et ce n'est pas un clone. Ces deux pistes sont closes par mesure, plus par supposition.

**3. La panne « puce muette » (tous registres 0xFF) est ALÉATOIRE À CHAQUE REDÉMARRAGE**
- Séquence mesurée ce soir : OTA 21:24 → muette (inventaire 21:26 : `PARTNUM=0xFF VERSION=0xFF`,
  47 registres 0xFF) ; OTA 21:29 → **vivante** ; OTA 21:36 → muette ; OTA 21:44 → **vivante**.
  Donc ~1 redémarrage sur 2 laisse la puce muette, et un **simple redémarrage (pas seulement une
  coupure d'alimentation) peut la réveiller** — c'est nouveau et ça change la procédure de secours.
- Preuve indépendante que ce n'est PAS notre instrumentation : ESPHome's own driver voit la même
  chose — `logs/iter11_rearm_2125.log` : `[D][cc1101:148]: CC1101 found! Chip ID: 0xFFFF` puis
  `[E][cc1101:150]: Failed to verify CC1101.` puis `[E][component:204]: cc1101 was marked as failed`,
  et `Failed to enter RX state!`.
- En état muet, GDO0 ne livre que des miettes (2-5 impulsions, tampon plein de bruit à 497) :
  `logs/iter11_window_2137.log` (222 s, captures +1 toutes les 5-10 s).

**4. EN ÉTAT SAIN, LA PUCE N'ENTEND PLUS RIEN — mesure directe, 27 échantillons / 4 min**
(`logs/iter11_alive_window_2145.log`, 21:45-21:49, après l'OTA 21:44)
- `MARCSTATE=0x0D RX` **27/27**, `VERSION=0x14 27/27`, `FREQ=868.34985 MHz` : la puce écoute, bien
  configurée, à la bonne fréquence.
- **`RSSI=-112,5 dBm` plat 27/27 et `CS=0` sur 23/23 échantillons** (PKTSTATUS 0xA8/0xAD).
- Référence sur cette MÊME carte, ce soir : plancher −106,2 dBm (mode packet), −104,0 dBm à
  20:36-20:41 **avec CS=1 sur 4/60** (donc porteuse vue), puis −109,0 dBm après la ré-armature de
  20:47. Aujourd'hui : **−112,5 dBm et plus aucune porteuse détectée**.
- Lecture : le plancher a chuté de ~8 dB **et** aucune porteuse n'est détectée → **aucun signal
  n'atteint la puce** (antenne/découplage du chemin RF ou station arrêtée). `captures RMT=5` figé,
  0 trame : cohérent. L'innocentation du chemin RF de l'itération 9 ne tient donc plus à l'instant
  présent — c'est une mesure, pas une impression (et elle est postérieure).

**5. Ce qui reste impossible à trancher d'ici (dit franchement)**
- « Antenne/chemin RF » contre « station arrêtée » : nous n'avons **pas** de second récepteur. Le
  témoin (qui décodait 39 trames/300 s à 20:31) n'est pas dans ce dépôt (aucun binaire : le flash
  du témoin est fait par la session interactive). Sans ce contrôle, les deux causes restent
  possibles ; le plancher 8 dB plus bas penche pour le chemin d'antenne.

**Demande physique (l'utilisateur connaît la RF)** : vérifier/revisser l'antenne 868 MHz (et son
connecteur au module), rapprocher la carte de la station en vue directe si possible, et confirmer
que la station émet encore (affichage intérieur qui se met à jour, icône pile). Ensuite, l'état sain
se lit en une commande : bouton « Relire l'inventaire registres CC1101 » (ou l'entité
« Inventaire registres CC1101 ») → si `CS` bascule et que le plancher remonte vers −100 dBm, le
signal est revenu et l'on mesure alors les impulsions brutes (bouton « Dump impulsions »).

**Prochaine action (itération 12)**
1. Au premier état sain : fenêtre de 15 min avec l'échantillonnage 10 s (CS/plancher) pour voir si la
   porteuse revient, + un « Dump impulsions » pour la question de la quantification (11,25 µs).
2. Si la puce est muette : **un redémarrage** suffit maintenant (mesuré 4 fois ce soir) — pas besoin
   de solliciter l'utilisateur pour une coupure d'alimentation.
3. Ne pas refaire : débit (11 108 bauds lus dans la puce), fréquence (868,34985 MHz lue), identité
   (0x00/0x14), réglages de réception (identiques au témoin), « clone » et « débit ×8 » (closes).

## 2026-09-30 — Itération 10 (session interactive) : POURQUOI LES RAFALES ARRIVENT CASSÉES (et pourquoi c'est structurel sur ESP32-C3)

**Question posée par l'utilisateur : pourquoi les trames sont-elles cassées, et que faire ?**

**Réponse, avec la source dans la puce** (`soc_caps.h` de l'ESP32-C3, IDF 5.5.5 installé) :
`SOC_RMT_MEM_WORDS_PER_CHANNEL = 48`, `SOC_RMT_RX_CANDIDATES_PER_GROUP = 2`,
`SOC_RMT_SUPPORT_RX_PINGPONG = 1`, **pas de `SOC_RMT_SUPPORT_DMA`**. ESPHome affecte cette mémoire
au canal RX avec `channel.mem_block_symbols = rmt_symbols` (96 par défaut, mesuré dans le dump du
décodeur). Une réception **se termine mécaniquement quand la mémoire du canal est pleine**, c'est-à-dire
après ~94 impulsions (`receive_symbols: 512` ne change que la taille du tampon de destination, pas
la mémoire matérielle). Le pilote relance aussitôt une réception pour la suite, et ESPHome remet
**chaque réception séparément** au décodeur (`call_listeners_dumpers_()` par événement).

Conséquence mesurée chez le témoin, mêmes réglages, même carte (relevé de 140 s,
`logs/witness_cross_test_20260930.log`) : sur 23 salves reçues, **7 sont arrivées en deux morceaux**
(94+70, 95+76, 95+72, 92+66, 97+71, 96+72…) et il les a décodées **en recollant les fragments**
(« Trame coupee reconstruite avec succes (94 + 70 impulsions, extra=-180 us) ») : 16 trames en
140 s, soit une par salve. **Sans recollage, une rafale sur deux est perdue.**

**Ce que ça implique pour nous, concrètement**
- Le recollage n'est pas un pansement : c'est **nécessaire** et c'est ce qui explique nos fenêtres
  « 1 trame toutes les 2 minutes » alors que le témoin décode une salve sur une. Il est rétabli
  dans notre composant (`build_stitched_`, avec la soudure des deux moitiés quand la coupure tombe
  au milieu d'une impulsion — le « extra=-180 us » du témoin).
- **Aucun réglage ne peut supprimer la coupure** : pas de DMA sur le C3 et 48 mots par canal.
  Monter `rmt_symbols` au-delà de 96 n'est pas possible (la puce refuserait l'allocation :
  « out of RMT symbol memory »). La seule alternative structurelle serait d'abandonner le RMT et de
  dater les fronts de GDO0 par interruption GPIO dans notre composant — à garder comme plan B, pas
  comme première intention (plus de code dans l'ISR, plus de RAM).

**Mesures de la même session (notre firmware, notre carte)**
- Instrument SPI de la boucle (registres lus par notre composant) : **VERSION=0x14**,
  **MARCSTATE=0x0D (RX)**, **FREQ=868,34985 MHz** (FREQ2:1:0 = 21 65 E8), **RSSI −104 dBm** au
  plancher avec des excursions à **−87 dBm** et `CS` (carrier sense) qui bascule → **la chaîne RF
  est intacte et la station est bien reçue**. Notre config de réception est identique au témoin,
  vérifié par le dump re-journalisé (`logs/receiver_dump2.log`) : clock 1 MHz, RMT symbols 96,
  receive symbols 512, tolérance 25 %, filtre 45 µs, idle 1100 µs, GPIO3, et
  `is_failed()=false`.
- **Mais** nos captures restent anormales : trains de 496 impulsions puis miettes de 2 à 7 selon
  le boot, et **les impulsions sont quantifiées en multiples de 11,25 µs = 90/8** (relevé
  `logs/dump_after_stitching.log` : 45, 56, 67, 78, 90, 101, 113… µs) alors que celles du témoin
  tombent à ~1 µs près (92, 84, 269 µs). **11,25 µs = une période bit divisée par 8** : signature
  d'un démodulateur qui travaille ~8× trop vite, ce qui explique aussi que le filtre à 45 µs ne
  laisse presque rien passer.
- Les registres du démodulateur (0x10 → 0x15 : MDMCFG4..0, DEVIATN) se lisent **0xFF** depuis notre
  composant, alors que VERSION/MARCSTATE/FREQ2 se lisent correctement : lecture à creuser (lecture
  registre par registre au lieu du bloc de 6, et contrôle PARTNUM/PARTVERSION pour écarter un clone
  de CC1101).

**Hypothèse principale à tester en priorité (itération 11) : c'est NOTRE séquence de ré-armature
radio au boot qui laisse la puce mal configurée.** Elle enchaîne `cc1101.reset` (remise à zéro SANS
réécriture des registres) puis des setters un par un ; la configuration qui décodait (18:50 UTC,
13 salves en 5 min) n'avait **ni** cette séquence **ni** de lecture SPI. À tester : boot sans
ré-armature radio (et sans instrumentation SPI), lecture des registres du démodulateur, et
comparaison directe des impulsions brutes avec celles du témoin. Instrumentation ajoutée pour ça :
le composant **re-journalise le dump du `remote_receiver`** toutes les 60 s (l'API ne peut pas lire
celui du démarrage) ; l'ancien message « GDO0 STATIQUE » ne s'affiche plus quand la sonde est absente.

**État** : notre firmware est sur la carte (recollage actif, ré-armature active, instrumentation SPI
désactivée le temps du test). Étoile polaire inchangée : reproduire les 13 salves décodées en 5 min
du 30/09 18:50 UTC.

## 2026-09-30 — Itération 9 (boucle) : instrumentation RSSI/MARCSTATE/FREQ en service ; le chemin RF est innocenté par un contrôle témoin positif → le déficit est dans l'état de démodulation de la puce

**1. Instrumentation déployée (nouvelle capacité de mesure, pas un réglage radio)**
- `esphome/components/vevor_7in1/` est maintenant **second périphérique du même bus SPI** que le
  CC1101 (même `cs_pin`, `spi_device_schema`), uniquement pour **LIRE** (aucune écriture) :
  RSSI (0x34), MARCSTATE (0x35), PKTSTATUS (0x38, bits CS/SFD), FREQ2/1/0 (0x0D-0x0F), VERSION
  (0x31). Publié : capteur « RSSI » (dBm) + nouvelle entité texte « État radio CC1101 »
  (`RX | CS=0 SFD=1 | 868.34985 MHz`) ; journalisé : une ligne `RADIO …` toutes les 5 s avec le
  cumul de fenêtre (n / moy / min / max).
- **Piège de schéma rencontré** : ESPHome refuse deux `cs_pin` sur la même broche
  (`Pin 7 is used in multiple places`) → il faut `allow_other_uses: true` sur **les deux**
  (celui du `cc1101` et le nôtre). `BUILD OK code=0` (1 006 544 o au lieu de 1 004 288 : +2,2 ko).
- Nouveaux outils : `tools/analyze_radio_log.py` (statistiques des lignes `RADIO`),
  `tools/witness_probe.py` / `tools/witness_summary.py` / `tools/witness_fetch.py` (relevé du
  serveur web non authentifié du firmware témoin — la seule mesure possible **sans toucher à la
  carte** quand elle tourne le témoin, son API étant chiffrée avec une autre clé).

**2. Le flash OTA a été refusé (et n'a rien écrit) : la carte tournait le témoin**
- 20:26 : `tools/flash.sh 172.16.0.205` → `ERROR Device rejected the handshake; is the OTA
  encryption key correct?` / `FLASH FAIL code=1` (`logs/last_flash.log`). Vérification à l'API :
  `InvalidEncryptionKeyAPIError … received_name=vevor-weather-station, received_mac=7ce8b1d1d85c`
  → c'est bien **notre carte**, mais elle exécutait le **firmware témoin** (uptime 12 s à 20:27).
  Aucun octet n'a été écrit ; la boucle a appliqué la règle « ne pas reflasher par-dessus le
  témoin » et n'a rien forcé. La version instrumentée s'est retrouvée sur la carte par la
  **session interactive** (rebuild à 20:35:10) et tourne depuis.

**3. Contrôle témoin — gratuit, 300 s, 20:31-20:36 UTC (`logs/witness_probe_300s_20260930.log`)**
- **44 rafales RF, 39 trames décodées** : `[84CB] T=12.8-12.9 °C H=89-90 % wind 0.0 (gust 0.0-1.6)
  dir=271° rain=58.2mm UV=0 lux=0`. La station émet, la puce reçoit, l'antenne et le chemin RF
  sont bons **sur cette carte, à cet endroit, maintenant**.
- **L'hypothèse « atténuation du chemin RF / antenne » de l'itération 8 est donc close** (elle
  reposait sur la sonde GDO0, qui n'est décidément pas un détecteur de signal).
- Réserve mesurée, elle sera utile : les rafales arrivent **coupées** — 96 puis 72 impulsions
  (rafale utile : 166-178), 1re durée `x[0]=-1327 µs`, trou interne `x[1]=-350 µs`, et le témoin
  les **recolles** : `Trame coupee reconstruite avec succes (96 + 72 impulsions, extra=-180 us)`
  ×13. Nos captures « une rafale par capture » (itération 7) ne survivent pas à ce régime.

**4. Notre firmware instrumenté, mêmes instants, autre fenêtre (`logs/iter9_rssi_300s_20260930.log`)**
- 300 s (20:36-20:41), 60 échantillons : **MARCSTATE=RX 60/60**, **FREQ=868.34985 MHz**,
  **VERSION=0x14 60/60** (les lectures SPI atteignent bien la puce), **RSSI plat à −104,0 dBm**
  (référence carte : plancher −106,2 dBm en mode packet), CS=1 4/60, SFD=1 60/60,
  **captures RMT 4 → 10 (+6), 0 trame**.
- Puis 300 s avec le bouton « Dump impulsions » armé (20:46-20:51) : **0 capture** alors que la
  sonde voit 40-45 transitions/3 ms. Contraste net avec les 44 captures du témoin, minutes avant.
- → **ni la fréquence, ni le niveau RF, ni la présence/joignabilité de la puce ne sont en cause** :
  ce qui manque est un **flux démodulé exploitable** (la puce est en RX à la bonne fréquence, mais
  ce qu'elle sort donne 0-6 captures au lieu de ~44).

**5. Ré-armature à chaud (bouton « Réappliquer la config radio », 20:47:05) — ne répare pas**
- Immédiatement après : `[W][cc1101:317]: PLL lock failed, retrying calibration` **×2**
  (`logs/iter9_rearm_20260930.log`) = l'échec de verrouillage PLL est **reproduit à volonté**, ce
  n'est plus une hypothèse.
- Fenêtre suivante de 165 s (`logs/iter9_after_rearm_20260930.log`) : plancher **−109,0 dBm**
  (33/33, soit 5 dB sous la mesure d'avant l'appui), captures **20 → 62 (+42)**, plus longue 529
  impulsions, mais **24/33 échantillons avec « GDO0 STATIQUE »** et **0 trame**.
- Lecture : après recalibrage, la puce « capture » (bruit, tampon plein) mais **ne démodule plus**
  — le flux GDO0 n'est plus le train NRZ attendu. Le remède documenté de l'itération 7 n'est donc
  pas fiable dans ce régime.

**6. NOUVEAU, à 20:50-20:52 : la puce ne répond PLUS du tout au SPI**
- Le journal montre `[I][app:271]: Rebooting safely` (fin de la fenêtre 20:46-20:51) : la carte a
  redémarré vers 20:50:5x, et le compteur de captures est reparti de zéro (62 → 9).
- Depuis, **toutes** les lectures renvoient `0xFF` : `RADIO RSSI=-74.5 dBm (brut 0xFF) |
  MARCSTATE=0xFF ? | PKTSTATUS=0xFF | FREQ=6655.99951 MHz (FREQ2:1:0=FF FF FF) | VERSION=0xFF`
  (`logs/iter9_check_2051.log`, 7 échantillons consécutifs). Le garde-fou ajouté ce soir le dit
  explicitement : `lecture SPI suspecte : VERSION=0xFF (attendu 0x14) — valeurs ci-dessus non
  fiables`. Autrement dit : plus de `Chip ID 0x0014`, le CC1101 **ne répond plus** (MISO figé haut,
  bus muet, ou puce sans alimentation). Les capteur/entité « RSSI » et « État radio CC1101 »
  continuent de publier : ils publient cette absence de réponse, il ne faut pas les lire comme des
  mesures radio.
- Conséquence : **aucune mesure n'est possible sur la puce dans cet état**, et un redémarrage
  logiciel ne peut pas la récupérer (le strobe de reset passe par le SPI, qui est muet). Il faut
  une **coupure d'alimentation** de la carte (action physique, demandée à l'utilisateur).
- Bilan honnête de la journée sur ce matériel : la puce décode avec le témoin (39 trames/300 s à
  20:31), puis **PLL lock failed à chaque recalibrage**, plancher qui saute de 5 dB, GDO0 tantôt
  « 40 transitions/3 ms » tantôt « statique », et maintenant **plus de réponse SPI du tout**. La
  puce elle-même (ou son alimentation) est désormais un suspect de premier plan, à côté de l'état
  de configuration.

**Changement de stratégie (règle MISSION : 3 itérations sans amélioration)**
On arrête de chercher côté « signal reçu » (fréquence, antenne, niveau, protocole : tous mesurés
sains) et on passe côté **état interne de la puce + matériel** — d'où aussi la demande faite à
l'utilisateur (alimentation/découplage du CC1101, module de rechange).

**Prochaine action (itération 10)**
1. **Inventaire complet des registres** (la capacité existe maintenant) : dumper les registres de
   configuration et de statut de la puce en mode asynchrone (IOCFG0/IOCFG2, FIFOTHR, AGCCTRL2/1/0,
   MDMCFG4/3/2/1, DEVIATN, PKTCTRL0, MCSM, FSCAL, VCO_VC_DAC) et les comparer aux valeurs
   attendues — c'est la seule façon de voir si l'état réel de la puce est celui qu'on croit.
2. **Piste matérielle, à demander à l'utilisateur** (il connaît la RF) : alimentation du CC1101
   (3V3 pris sur la SuperMini, longueur des fils), condensateur de découplage au plus près du
   module, et si possible **un second module CC1101** pour trancher entre puce marginale et
   configuration.

## 2026-09-30 — Itération 8 (boucle) : A/B de l'état de la puce — ni la fréquence ni une ré-armature radio complète ne rétablissent la réception ; deux bugs d'outillage corrigés

**But de l'itération** : trancher, sans flash, entre « l'état de la puce est fautif » (hypothèse 1 de
l'itération 7 : séquence de boot, hooks `set_idle` d'OTA) et « le chemin RF a changé » (hypothèse 2),
en mesurant sonde + captures + trames sur des fenêtres avant/après intervention.

**1. Fréquence — anomalie trouvée, et commande qui ne faisait RIEN**
- `tools/read_state.py` (nouveau) : l'entité « Fréquence CC1101 » valait **868,5 MHz**, pas 868,35 —
  valeur **restaurée** (`restore_value: true`) après le balayage de 19:07. Preuve : `logs/state_pre_ab.json`.
- En la réglant : **aucun effet** (0 trame / 180 s, sonde méd. 46/3 ms → `logs/ab_freq_only_20260930.log`).
  Cause trouvée : `tools/scan_freq.py` cherchait l'entité avec le motif **non ancré** `fr[ée]quence`,
  qui matche aussi « Offset fréquence » (un **capteur**), et `key_of()` prend le premier nom venu. Un
  `number_command` envoyé à la clé d'un capteur est **silencieusement ignoré** par l'appareil : toutes
  les commandes de fréquence passées par ce chemin (et donc les balayages de `scan()`) ne changeaient
  rien, tout en affichant « fréquence réglée ». Corrigé : motif ancré (`^\s*fr[ée]quence`) **et**
  relecture de l'entité après écriture. Vérifié : après `--set 868.35`, l'entité relit **868.35**
  (`logs/state_final_iter8.json`) — et la préférence est aussitôt réécrite (`preferences: Writing 1 items`
  à 19:44:44), donc les prochains boots restaureront la bonne valeur.

**2. Ré-armature radio complète à chaud (bouton « Réappliquer la config radio »), deux fois**
- 19:36:06 → 240 s : **0 trame extraite**, sonde 32-55 transitions/3 ms (méd. 43), captures 477-536
  impulsions (tampon plein par du bruit) — `logs/ab_rearm_B_20260930.log`.
- 19:46:12 → 240 s : **1 trame** (`aa 00 84 cb 16 02 7a 58 01 01 02 02 14 01 fb 01 01 01 48 44 49` →
  13,4 °C, 88 %, pluie 58,2 mm, **compteur TX 72**) — `logs/ab_rearm_C_20260930.log`. La station émet
  donc toujours ; le récepteur décode **par intermittence** (~1 trame / 4 min contre ~13 trames
  distinctes / 300 s à 18:50).
- Preuve que l'action a bien été exécutée (elle ne journalise rien par elle-même) :
  `[D][cc1101:148]: CC1101 found! Chip ID: 0x0014` en tête des deux fenêtres = `configure()` rejoué
  (reset + écriture de **tous** les registres depuis la config YAML, donc **868,35 MHz** + recalibration).
- Lecture : la puce est bien à 868,35 MHz, fraîchement configurée et recalibrée, et elle décode encore
  (rarement). **Ce n'est donc ni la fréquence ni la configuration radio.**

**3. Le flux démodulé lui-même, mis en clair**
- Bouton « Dump impulsions » dans cet état — `logs/dump_pulses_1941.log`, capture #254 :
  `535 impulsions, de 45 us à 1100 us`, 64 premières durées **étalées en continu de 45 à 360 µs**
  (45, 56, 67, 79, 90, 101, 113, 124, 135, 146, 158, 169, 191, 203, 213, 225, 236, 247, 259, 270,
  281, 292, 349, 360), **sans groupement autour de 90 µs**. Le montage témoin qui décode mesure des
  rafales à **+92 / −84 µs** : ici la sortie du démodulateur n'est plus un train NRZ propre.
- Contraste instrumental, **même firmware** : `logs/ours_first_20260930.log` (18:50, 26 extractions /
  300 s) → sonde **220-330** transitions/3 ms ; fenêtres 19:33-19:50 (~1 trame / 4 min) → **32-56**.
  Révision de la conclusion de l'itération 6 : la sonde GDO0 *sépare* bien les deux régimes — les
  deux mesures de l'itération 6 (868,05 et 868,30) étaient simplement prises **toutes les deux dans
  l'état dégradé**. Elle reste inutilisable comme *détecteur de fréquence*, mais c'est un bon
  indicateur d'état, à croiser avec les trames extraites.

**4. Piège nouveau, mesuré : changer la fréquence par l'entité peut rendre la puce MUETTE**
- Après le `--set 868.35` vérifié, le journal affiche en boucle
  `GDO0 STATIQUE (0 transition) — puce pas en écoute` et les captures se figent à 259
  (`logs/ab_freq_verified_20260930.log`). Mécanisme (source ESPHome 2026.9.1, `cc1101.cpp:460`) :
  `set_frequency()` fait `enter_idle_()` → écriture `FREQ2/1/0` → `enter_rx_()`, et c'est la
  recalibration (`enter_calibrated_`) qui échoue. Le bouton « Réappliquer la config radio » répare
  (constaté : sonde 35-54/3 ms après l'appui). **Règle : après toute écriture de fréquence à chaud,
  vérifier la sonde ; si elle est statique, ré-armer.**

**Outillage**
- `tools/read_state.py` (nouveau) : valeur de **toutes** les entités par l'API — c'est lui qui a révélé
  « Fréquence CC1101 = 868,5 ». `tools/press_button.py` (nouveau) : appuie sur n'importe quel bouton
  nommé et capture la fenêtre qui suit, horodatage de l'appui en tête de fichier (le bouton de
  ré-armature ne journalise rien de lui-même).
- `tools/scan_freq.py` : motif ancré + contrôle de relecture après écriture (cf. §1).

**Prochaine action (itération 9 — hypothèse unique : le NIVEAU, mesuré en dB et non en transitions)**
1. Ajouter au composant une **lecture périodique du registre `RSSI`** (valide en RX même en mode série
   asynchrone) publiée comme entité, flasher en OTA, et comparer le plancher de bruit au
   **−106,2 / −105,7 dBm** mesuré le 30/09 en mode packet sur **cette même carte**
   (`logs/stream_nominal_restore.log`, `logs/bw100_86830_analysis.json`). Plancher effondré de ~10 dB
   ⇒ atténuation du chemin RF (antenne / connecteur / position de la carte) ; plancher inchangé ⇒ la
   puce amplifie normalement et le déficit est ailleurs (interférence locale, ou émission de la station).
2. En parallèle, **sans attendre la boucle** : vérification physique par l'utilisateur (antenne 868 MHz
   bien vissée et droite sur le CC1101, carte non déplacée depuis son passage en USB, afficheur intérieur
   de la station montrant encore des données extérieures). C'est le seul point que le logiciel ne peut
   plus trancher : fréquence, configuration de la puce et protocole sont hors de cause (§2 et §3).

## 2026-09-30 — Itération 7 (session interactive) : TEST TÉMOIN POSITIF — la station est entendue ; le défaut est chez nous, sur la capture et la polarité

**Réponse à la question que l'itération 6 laissait en suspens : OUI, le projet de référence décode.**
L'environnement (position, câblage, station, fréquence) est donc hors de cause : c'est notre
configuration de capture et/ou notre décodeur qui étaient fautifs.

**Preuves (pas des déductions)**
- Le firmware témoin tourne depuis 18:31 UTC sur la carte et décode en continu. Son **serveur web
  (port 80, sans authentification)** diffuse l'état et les logs : relevé direct de notre côté le
  30/09 18:36–18:37 UTC (`logs/reference_witness_events.log`) — `Outside Temperature` 14,2 → 14,1 °C,
  `Wind Speed` 9,8 / 6,2 / 7,9 / 3,8 / 3,0 km/h (variable), `Rain Total` 57,784 mm stable,
  `Illuminance` 0 lx, `uptime` 228 → 371 s. Mise à jour toutes les ~20 s : c'est exactement la
  cadence du protocole. La station émet, sur cette carte, à cet endroit, aujourd'hui.
- Le log fourni par l'utilisateur (`vevor_decoder`, `rf_raw`) confirme des **rafales de 166 à 178
  impulsions** captées d'un seul bloc, décodées (`[84CB] T=14.2°C H=86% wind=11.2 (gust 12.8)
  km/h dir=283° rain=57.8mm UV=0 lux=0`), trois rafales d'affilée.

**Comparaison champ par champ — leur configuration fonctionnelle vs la nôtre (avant cette itération)**

| Paramètre | Témoin (fonctionne) | Nous (0 trame) | Verdict |
|---|---|---|---|
| Fréquence | **868 349 824 Hz** (868,35) | 868,05 par défaut | **écart — corrigé** |
| Déviation / bande | 70 kHz / 100 kHz | 70 kHz / 100 kHz | **identiques — suspects écartés** |
| Débit symbole | 11 108 bauds (11 111 demandés) | 11 111 | identiques |
| `remote_receiver` filtre | **45 µs** | 10 µs | **écart — corrigé** |
| `remote_receiver` idle | **1100 µs** | 10 ms | **écart — corrigé** |
| Période bit | **90 µs** (fixe) | 88/87/89/86 | élargi à 90/88/89/87 |
| Polarité | **les deux essayées** | une seule (`invert` jamais activé) | **écart — corrigé** |
| Motif cherché | **CA 54** (2 octets) à tous les alignements | préambule entier AA AA CA CA 54 (5 octets) | **écart — corrigé** |
| Niveau tenu > 64 périodes | **sauté** (la trame peut suivre le trou) | capture entière abandonnée | **écart — corrigé** |
| Recollage inter-captures | inutile | en place | supprimé (voir plus bas) |
| GPIO | GDO0 → **GPIO3** (idem nous) | GPIO3 | identiques |

Correction d'une note périmée : le témoin n'est **pas** sur GPIO12 comme on l'avait écrit depuis
`references/EXTERNAL_CONTEXT_WIZARDPC.md` (son `remote_receiver` est sur **GPIO3**, comme nous).

**Mesures réelles de la rafale, prises directement chez le témoin** (son `/events` diffuse aussi
les lignes de log : `logs/reference_witness_events.log`, relevé de 70 s)
- 5 trames décodées en 70 s ; **rafales de 168 à 174 impulsions**, captées **d'un seul bloc**
  (confirme `receive_symbols: 512` et rend le recollage inutile).
- Durées mesurées : **marks +92 à +94 µs**, **espaces −83 à −85 µs** → une impulsion = un bit,
  erreur de −7 à +4 µs autour de 90 µs. C'est exactement dans la tolérance de notre arrondi par
  impulsion (±45 µs, soit une demi-période) : **rien à corriger de ce côté**, et cela tranche la
  question du rythme en faveur de **90 µs** (nos 88 µs et l'ajustement à 88,3 µs étaient une
  fausse piste sur ce montage).
- La rafale commence par un **mark** (+92) : le RMT démarre au premier front de la rafale, donc
  exiger le préambule entier (AA AA CA CA 54) était bien une cause d'échec — d'où la recherche du
  seul mot de synchronisation **CA 54** à tous les alignements.
- Avec ces durées, chaque rafale mesurée ici passe nos scénarios hors matériel : période 90 µs,
  biais absolu −7/+4 µs, capture tronquée, polarité inconnue.

**Ce qu'on a changé (notre code, pas une reprise)**
1. `esphome/vevor-7in1.yaml` : fréquence de boot **868,35 MHz**, `filter: 45us`, `idle: 1100us`,
   `bit_period: 90us`. La fréquence n'est plus une hypothèse : elle est mesurée chez le seul
   récepteur qui entend la station.
2. `includes/vevor_protocol.h` : la chaîne impulsions → trame y est désormais **entière** (avant,
   seules les 21 octets l'étaient) — `timings_to_bits()`, `find_frame_candidate()`,
   `decode_timings()`. Trois corrections : recherche du mot de synchronisation **CA 54 à tous les
   alignements** (une capture peut commencer au milieu du préambule), **les deux polarités
   essayées** (la polarité de GDO0 dépend du module : ne pas la supposer), et un niveau tenu plus
   de 64 périodes est **sauté** au lieu d'invalider la capture.
3. `components/vevor_7in1/` : le recollage inter-captures est **supprimé**. Il existait parce qu'on
   croyait le RMT du C3 limité à 96 symboles ; `receive_symbols: 512` livre la rafale entière
   (166-178 impulsions mesurées chez le témoin). Il ne faisait que coller le bruit d'une capture
   devant la suivante. L'option `invert` disparaît (les deux polarités sont testées).
   Les captures n° 1 à 3 journalisent maintenant **les 16 premières durées en clair** : c'est la
   seule façon d'analyser une rafale hors de la carte, l'API ne livrant que des logs.
4. `tests/` : la chaîne complète est testable hors matériel. `tests/frames.py --pulses` fabrique des
   scénarios d'impulsions (préambule + trame, NRZ, durées signées) que `test_decoder.cpp` rejoue :
   nominal, polarité inversée, période 88 µs, capture tronquée au milieu du préambule, trou
   inter-rafales, gigue ±2 %, biais absolu ±30 µs, capture trop courte, checksum corrompu, bruit ×3.
   → **173 vérifications, 0 échec** (128 auparavant). `BUILD OK code=0` (1 001 536 o OTA).
   Note de méthode : un scénario à ±8 % de gigue **échoue** et c'est normal — l'arrondi par
   impulsion tolère ±45 µs en ABSOLU (une demi-période), donc une erreur proportionnelle ne peut
   pas dépasser ~5 % sur la plus longue série (10 bits ici). Le scénario a été remplacé par ±2 %
   plus un biais absolu, qui est la forme d'erreur réellement mesurée sur ce montage (86 et 267 µs
   au lieu de 90 et 270).

**Bloqué (et c'est la seule chose qui manque pour conclure) : flasher notre firmware**
- `172.16.0.205:6053` **répond** mais la clé du firmware témoin n'est pas la nôtre : mesure faite ce
  soir → `InvalidEncryptionKeyAPIError ... received_name=vevor-weather-station` avec notre clé. Donc
  **pas d'OTA possible tant que le témoin tourne** (son OTA est en `Encryption: required`), et son
  serveur web a `ota: false` : aucun chemin de flash à distance.
- Port série toujours hors service dans le conteneur : `/dev/ttyACM0` = **`c--------- nobody
  nogroup`** (mode 000) et `/dev/serial/by-id/` absent → ni console ni flash USB depuis ici.
- Notre firmware est prêt et compilé : `firmware.ota.bin` et `firmware.factory.bin` dans
  `esphome/.esphome/build/vevor-7in1/build/`.

**Prochaine action** : demander à l'utilisateur UN déblocage matériel, au choix —
(a) `pct exec 101 -- chmod 666 /dev/ttyACM0` (ou `pct reboot 101` côté hôte) pour nous rendre le
port série : on flashe et on lit ensuite tout seuls ; ou (b) flasher lui-même
`firmware.factory.bin` en USB. Puis, dès que notre firmware tourne : capture de 5 min via l'API,
lecture des « V7IN1 RAW »/« V7IN1 OK » et de la période/polarité gagnantes, et resserrement.
`state/PHASE` = `waiting_flash_usb`. La boucle (job `5fe5aac7bcf4`) **reste en pause** pour ne pas
reflasher par-dessus le témoin.

### Suite de l'itération 7 — NOTRE FIRMWARE DÉCODE (premières trames de l'histoire du projet)

**Déblocage du flash, sans port série.** Le port USB reste hors service, mais la carte a été
rendue flashable en Wi-Fi : l'utilisateur a reflashé le témoin **sans chiffrement OTA**. Détail qui
compte : `esphome upload` échoue si la configuration utilisée pour téléverser déclare
`encryption:` sous `ota:` (elle propose alors une poignée de main chiffrée qu'une carte sans clé
refuse). D'où `esphome/flash-plain.yaml`, fichier d'appoint **sans `encryption:`**, utilisé avec
`--file <firmware.ota.bin>` : téléversement en clair réussi du premier coup. Notre propre
`vevor-7in1.yaml` garde `encryption: {}` et fonctionne en OTA depuis que notre firmware tourne
(mesuré : `FLASH OK code=0`, upload 5,7 s).

**Résultat mesuré — notre décodeur, notre firmware, notre carte**
`logs/ours_first_20260930.log` (300 s, 18:50:34 → 18:55:34) : **26 extractions, 13 contenus
distincts, 26 trames validées et publiées**, période **90 µs** et **polarité normale** à chaque
fois, rafales de **162 à 178 impulsions**. Exemple brut :
`aa 00 84 cb 16 02 7e 56 01 01 02 02 0f 01 f9 01 01 01 fe f5 ff` →
`id=33995 (0x84CB — la station du témoin)`, `T=13,8 °C`, `H=86 %`, `vent 0,0`, `rafale 1,6`,
`dir 270°`, `pluie 57,8 mm`, `batterie OK`. Le suivi sur 5 min est cohérent (vent qui varie,
pluie stable, T 13,7-13,8 °C) et **recoupe les valeurs du témoin** (14,0-14,2 °C, pluie 57,8 mm).
Un doublon de livraison par rafale a été identifié (le RMT livre deux fois la même trame) :
déduplication par comparaison des 21 octets sur une fenêtre de 5 s, compteur « Doublons ignorés ».

**Deux corrections d'instrumentation issues de ces mesures**
- Le message « aucune impulsion depuis 5 s : la sortie GDO0 ne bouge pas » était **faux** quand la
  sonde voit la broche bouger (cas normal entre deux rafales, la station émettant toutes les 20 s) :
  il est maintenant en DEBUG quand la sonde a vu des transitions, et l'alerte WARN est réservée au
  cas réellement muet (0 transition) ; elle dit alors « GDO0 STATIQUE ».
- Nouveaux instruments, utilisés pour le diagnostic ci-dessous : `tools/dump_pulses.py` (appuie
  sur le bouton « Dump impulsions » et ramène les 64 premières durées brutes), `tools/scan_async.py`
  (balayage jugé sur les compteurs valides/rejetées), `tools/boot_dump.sh` (enchaîne des captures
  pendant un redémarrage pour attraper un `dump_config()`), et deux entités de diagnostic
  (« Captures RMT », « Doublons ignorés ») publiées par un `interval`.

**Piège MAJEUR trouvé, mesuré, et contourné : le CC1101 reste sans verrouillage de PLL après un OTA**
- Symptôme : après un OTA de NOTRE firmware, `captures=0` pendant 55 s alors que la sonde voit la
  broche bouger (37-53 transitions/3 ms) et que le même firmware décodait parfaitement 10 minutes
  plus tôt. Balayage 868,10 → 868,50 MHz (6 paliers de 40 s, `logs/scan_async_1907.json`) :
  **0 trame partout** — donc ni la fréquence ni le décodeur.
- Cause identifiée par A/B : le récepteur revient **immédiatement** quand on réécrit la
  configuration radio complète à chaud (`cc1101.reset` + setters + `begin_rx`). Preuve
  `logs/dump_pulses.log` : avant l'appui, sonde 46 trans/3 ms et `captures=0` ; après, le journal
  affiche `PLL lock failed, retrying calibration`, puis `captures=25` et une trame décodée
  (pluie passée à 58,2 mm — il a plu).
- Correctif appliqué : la même séquence est rejouée **au boot** (`esphome: on_boot: priority: -100`,
  donc après le setup de tous les composants). Vérifié : après un OTA, **3 trames décodées sans
  toucher à rien** (`logs/ours_after_rearm_fix_20260930.log`).

**Question ouverte, à traiter en priorité par la boucle (honnête : ce n'est pas résolu)**
- Sur 300 s (19:23-19:28, `logs/validation_5min_20260930.log`, `logs/validation_5min.json`) :
  **2 trames seulement** (1 toutes les 150 s) alors que la station émet toutes les ~20 s et que le
  témoin en décodait 5 en 70 s. `captures=108` mais seule une minorité contient une rafale propre.
- Le régime radio a changé entre les deux fenêtres : le 18:50 la sonde mesurait **295 transitions
  /3 ms** (min 220, max 330) et la plus longue capture faisait **178 impulsions** ; depuis, **44
  transitions/3 ms** (min 32, max 59) et des captures de **jusqu'à 548 impulsions** (tampon plein).
  Autrement dit : bien moins d'énergie démodulée, et un régime de bruit très différent.
- Hypothèses à départager par la boucle, dans cet ordre : (1) la séquence de ré-armature du boot
  laisse le CC1101 dans un état d'AGC/calibration différent de `configure()` seul — test A/B :
  boot avec la séquence / sans la séquence / sans les hooks `set_idle` d'OTA, en mesurant à chaque
  fois sonde + captures + trames sur ≥ 15 min ; (2) l'environnement radio ou le chemin RF a changé
  (antenne 868 MHz desserrée, carte déplacée — l'utilisateur a manipulé la carte pour la reflasher
  en USB). Le point (2) se vérifie en 30 s par l'utilisateur : antenne bien vissée, et l'afficheur
  intérieur de la station montre-t-il encore des données extérieures ?
- À NE PAS refaire : chercher la fréquence (balayage fait : rien), ni suspecter le protocole (trames
  décodées), ni le filtre/l'idle (réglages du témoin repris tels quels).

**État final de cette itération** : notre firmware est sur la carte, il décode, l'OTA fonctionne
avec notre clé. `state/PHASE` = `decoded_our_firmware`. La boucle est réactivée pour traiter la
question ouverte ci-dessus.


## 2026-09-30 — Itération 6 (boucle) : les deux balayages sont clos (0 extraction) et le flux GDO0 ne dépend pas de la fréquence ; carte passée au firmware témoin → pause respectée

**Fait (mesures seulement — aucune écriture radio, aucun flash)**
- **Balayage 1** (firmware du 18:07:52, filtre 65 µs) : 867,80 → 868,60 MHz, 25 s/palier → **gelé** dans `logs/sweep1_frozen/` (17 paliers, 18:09→18:17), résumé vérifié dans `logs/sweep1_summary.json` : **11 captures RMT** au total, présentes sur **8 des 17 paliers** (234 à 288 impulsions, `imp.max` identique sur des paliers voisins), et **0 trame extraite**.
- **Balayage 2** (firmware du 18:20:53, filtre 10 µs) : 867,50 → 868,00 MHz par pas de 25 kHz, interrompu à 18:29 (dernier fichier `logs/sweepas_868.00.log`) ; `captures=18 → 20`, `plus longue=1025` impulsions, **0 trame extraite**.
- **Recherche exhaustive** : `grep -rl "trame extraite" logs/` → **aucun fichier**. Depuis la mise en service de la voie asynchrone (filtre 65 µs puis 10 µs), pas une seule trame n'a été extraite, à aucune fréquence balayée.
- **Nouvel outil** `tools/gdo0_rate_vs_freq.py` (+ `logs/gdo0_rate_vs_freq.json`) : le débit de transitions de GDO0 est **indépendant de la fréquence** — 868,05 MHz : moyenne **15 167 tr/s** (13 333-17 333, 6 sondes) ; 868,30 MHz : **15 500 tr/s** (2 sondes) ; soit ~65 µs par impulsion en moyenne, **pas des bits à 88 µs**. Conclusion : cette sortie **ne peut pas servir de détecteur de signal** (elle bascule pareil partout, y compris sur un palier sans émetteur attendu). Le palier témoin 867,00 MHz n'a pas pu être mesuré (voir ci-dessous).

**Collision constatée, sans dégât**
- À **18:31:10**, pendant notre capture à 868,30 MHz, la carte a été reflashée par le **firmware témoin de l'utilisateur** : l'API a répondu `received_name=vevor-weather-station, received_mac=7ce8b1d1d85c` puis `InvalidEncryptionKeyAPIError` (capture 868,30 tronquée après 6 s ; `logs/gdo0_freq_867.00.log` vide).
- Nos deux écritures de fréquence (18:30:32 et 18:31:04, sur **notre** firmware) n'ont pas touché le firmware témoin ; la commande suivante (`--set 867.00` puis remise à 868,30) a échoué sur la clé — **rien n'a été écrit sur la carte témoin**. La pause documentée ci-dessous **reste en vigueur**.
- Port série toujours hors service : `/dev/ttyACM0` en `c--------- nobody nogroup` et pas de `/dev/serial/by-id` → ni console de boot ni flash USB, quoi qu'il arrive.

**Prochaine action** : ne rien faire sur la carte ; **demander à l'utilisateur le résultat du test témoin** (le projet de référence décode-t-il encore, oui ou non ?). Oui → comparer sa configuration champ par champ ; non → l'environnement (position, câblage, station) est en cause. `state/PHASE` = `waiting_user_control_test` pour que la boucle ne réveille pas un flash sur le firmware témoin.

## 2026-09-30 — PAUSE : flash du projet de référence par l'utilisateur (test témoin)

> **BANDEAU (ajouté le 02/10, commit 9693dbe) — chiffre remplacé.** Le décompte « **128 vérifications**
> hors matériel » cité en fin de section (« tests/ + tools/run_tests.sh ») est un état du 30/09 ; la
> suite en compte désormais **377, 0 échec** (`README.md:24`). Ne pas lire 128 comme le total courant.

**À lire en premier si on reprend ce projet dans une nouvelle session.**

- **La boucle planifiée est EN PAUSE** (job `5fe5aac7bcf4`, raison : ne pas reflasher notre
  firmware par-dessus celui que l'utilisateur installe). **La relancer avec `resume` après le
  test.** Un balayage en cours a été interrompu volontairement pour la même raison.
- **Test témoin décidé par l'utilisateur** : il flashe le projet de référence
  (`github.com/WizardPC/esphome-vevor-7in1`), qui a **fonctionné sur cette même carte**, pour
  vérifier qu'il décode encore aujourd'hui et à la position actuelle. **Demander le résultat en
  premier à la reprise** : s'il décode → notre configuration ou notre code est fautif ; s'il ne
  décode pas → l'environnement a changé (position, câblage, station).

### État réel du projet (sans enjolivement)

**Nous n'avons jamais décodé une seule trame.** Établi, preuves à l'appui :

- **Carte et CC1101 fonctionnels** : `Chip ID 0x0014`, registres corrects (868,04992 MHz, 2-FSK,
  11 108 bauds, bande 101,562 kHz), `remote_receiver` sur GPIO3.
- **GDO0 bascule en permanence** (sonde intégrée, mesure directe sur la carte) : ~7,5 kHz par
  moments, jusqu'à ~55 kHz. **C'est un flux rapide, pas des bits à 88 µs.**
- **Piège n°1 (majeur)** : avec `filter: 65us` et des impulsions mesurées à 26-50 µs,
  `remote_receiver` **jetait tout** → `captures=0` permanent. Le filtre présupposait un débit de
  88 µs jamais vérifié. Passé à `filter: 10us` : on ne présuppose plus, le décodeur trie sur le
  contenu (préambule + checksum).
- **Piège n°2** : sur **ESP32-C3**, le bloc mémoire RMT matériel fait **96 symboles** (192 sur
  ESP32 classique) → une trame (~211 bits) ne tient pas dans une capture. `receive_symbols`
  (tampon **logiciel**, 512 accepté sans erreur au démarrage) est la piste ; un **recollage des
  fragments** est implémenté en filet de sécurité.
- **Piège n°3** : le message contient des **trous internes** (rtl_433 : `reset_limit = 9000`)
  → avec `idle: 2000us` il était coupé. Passé à `idle: 10ms`.
- **Balayages** 867,5 → 868,7 MHz par pas de 25-50 kHz, jugés sur les trames réellement
  extraites (critère fort : le bruit ne fabrique pas un checksum valide) → **0 extraction**.
- Le pic à 868,05 MHz (+18 dB au-dessus du bruit) reste inexpliqué : `freq_offset` instables →
  probablement un **brouilleur** voisin, pas la station.
- Notre dernier firmware est sur la carte (filtre 10 µs) ; le flash de l'utilisateur l'écrasera.

### Architecture (notre implémentation, pas une reprise de code)

- `esphome/components/vevor_7in1/` : **notre** composant — impulsions → octets, trame remise au
  YAML via `on_frame`. Aucune logique de protocole dedans ; il sert aussi d'instrumentation
  (battement de cœur 5 s, sonde de broche, compteurs) — c'est ce qui a permis de sortir des
  devinettes, à garder et étendre.
- `esphome/includes/vevor_protocol.h` : le décodeur, pur C++, testable hors matériel.
  **Ne pas le renommer `vevor_7in1.h`** (collision avec l'en-tête du composant).
- Le `id:` YAML du composant génère une **variable C++** de même nom : `id: vevor` masquait le
  namespace `vevor::` → l'instance s'appelle `vevor_rx`.
- `tests/` + `tools/run_tests.sh` : **128 vérifications hors matériel**, avec un encodeur Python
  indépendant qui reproduit la trame de rtl_433 octet pour octet. C'est ce qui protège le
  décodeur pendant qu'on tâtonne sur la radio.

### Reprise, selon le résultat du test témoin

- **S'il décode** → comparer SA configuration à la nôtre champ par champ (fréquence, bande,
  filtre, `bit_period`, polarité, et son **câblage** : chez lui `remote_receiver` est sur
  GPIO12). Chercher ce qui **diffère**, pas ce qui manque.
- **S'il ne décode pas** → l'environnement a changé : vérifier le **câblage** (GDO0 → GPIO3,
  alimentation du module, antenne) et la **position**.

## 2026-09-30 — Itération 5 (boucle) : bw 100 kHz testé → aucun gain ; le point faible était l'outillage de mesure (reboots)

**Hypothèse testée (une seule) : la sensibilité.** `bw_khz` 200 → 100 kHz (~3 dB de SNR attendus).
Compilation + flash OK : `build/last_status.txt` = `BUILD OK code=0` (987 024 o) ; `logs/last_flash_status.txt` = `FLASH OK code=0 cible=172.16.0.205`.
Registre réellement écrit, vérifié indépendamment (`tools/verify_radio_config.py`, `logs/radio_config_check.json`) : 100 kHz demandé → **101,56 kHz** (CHANBW_E=3 M=0, MDMCFG4=0xC8) ; `(déviation + débit/2)/(BW/2) = 0,86 < 1` → pas d'écrêtage des bits.
Même flash : plage de l'entité « Fréquence CC1101 » élargie 866–870 → **430–930 MHz** (changement de *capacité* de l'outillage, pas une hypothèse radio : il rend 433,92 / 915,0 MHz testables sans recompiler).

**Résultat mesuré : aucun gain.**
- 868,30 MHz, 60 s (`logs/bw100_86830.log` → `logs/bw100_86830_analysis.json`) : 86 paquets, RSSI **min -110,5 / moy -106,2 / max -103,0 dBm**, 0 paquet ≥ -95 dBm, **0 préambule, 0 candidate `AA 00`, 0 trame valide**.
- 868,30 MHz, 120 s (`logs/stability_120s.log` → `logs/stability_120s_analysis.json`) : **211 paquets**, RSSI min -111,5 / moy -106,3 / max -95,5, 0 préambule, 1 candidate `AA 00` au checksum invalide (hasard : ~0,1 candidate attendue sur 211 paquets).
- Comparaison directe des planchers : **-106,2 dBm à 100 kHz** contre **-105,7 dBm à 200 kHz** (itération 4, `logs/stream_nominal_restore.log`) ; cadence de faux verrous du même ordre (1,3-1,8/s). → le gain attendu n'apparaît pas, **la bande passante n'est pas le verrou**. Hypothèse fermée.

**Le vrai défaut trouvé ce tick n'est pas radio, c'est la mesure.**
- Fenêtre 17:34 → 17:39 : **4 captures d'affilée sans aucune ligne** (dont une `Connection reset by peer`), alors que des captures identiques juste avant (17:32, 86 paquets) et juste après (17:40, 50 paquets) marchent.
- Premier réflexe (faux) : « régler la fréquence tue la réception ». **Démenti par A/B** : `--set 868.35` → capture = **76 paquets** (`logs/ab_A_86835.log`) ; `--set 868.305` → **81 paquets** ; `--set 868.05` → 0 ligne mais compteurs vivants.
- Explication mesurée : la carte devient **injoignable / redémarre par intermittence**. Preuve : à 17:47 la capture échoue sur `[Errno 113] Connect call failed ('172.16.0.205', 6053)` puis, 60 s plus tard, le compteur « Trames rejetées » repart à **9** (compteurs non restaurés = la carte venait de rebooter). Corrélat dans les logs : `[W][cc1101:317]: PLL lock failed, retrying calibration` et `cc1101 took a long time for an operation (110 ms) (max is 50 ms)`.
- **Conséquence de méthode (à appliquer partout désormais)** : une capture sans ligne `V7IN1 RAW` **ne prouve pas** l'absence de paquets — le flux de logs meurt avec la session, les compteurs d'état non. Nouveau `tools/count_probe.py` (lit « Trames valides / Trames rejetées » par l'API ; attend la livraison de l'état, sinon le premier relevé vaut 0 et le delta vaut le compteur absolu — piège déjà rencontré).
- **Croisement fait** : capture 120 s = 211 lignes `V7IN1 RAW` ↔ sonde 20 s = 26 paquets (1,3/s) ↔ sonde 25 s = 40 paquets (1,6/s) → les deux instruments concordent (1,3-1,8 paquet/s de bruit), chaîne RX **vivante et mesurable**.

**Bande 433,92 / 915,0 MHz (reconnaissance, capacité nouvelle)**
- 433,92 MHz, 60 s (`logs/band_43392.log` → `logs/band_43392_analysis.json`) : 89 paquets, moyenne -105,9 dBm, **1 paquet à -91,5 dBm** dont le contenu est du bruit (`...f0 f0 f0 e2 e2 e2`, pas de préambule) → un peu d'énergie à 433,92 (émetteur voisin probable), rien de décodable.
- 915,0 MHz, 60 s (`logs/band_915.log` → `logs/band_915_analysis.json`) : 111 paquets, moyenne -105,9 dBm, max -95,5 → rien.
- **Leçon instrumentale** : la cadence de paquets (faux verrous de sync sur le bruit) est **la même partout** (1,5/s à 433,92 comme à 868,30) → elle ne discrimine pas la présence d'un signal. Seuls comptent le **RSSI**, la recherche de **préambule** et le **checksum**. À ne plus utiliser comme critère de balayage.

**Changement de stratégie (règle MISSION : après 3 itérations sans amélioration) — acté**
1. Toute mesure = capture **plus** `tools/count_probe.py` (sinon on ne sait pas si on a réellement mesuré).
2. Fini le balayage à chaud par l'entité comme méthode principale : le **chemin de boot est la seule initialisation prouvée** du CC1101 (chaque flash OTA est immédiatement suivi de paquets). Itération 6 : reflasher avec `freq_mhz: "868.35"` (fréquence du projet de référence, **jamais testée au boot** — tous nos essais à 868,35 passaient par l'entité), puis capture longue (~5 min) validée aux compteurs.
3. Action physique (hors boucle, à demander à l'utilisateur) : **batterie neuve** dans la station, station à **< 2 m en vue directe**, antenne 868 MHz bien **vissée**. C'est le point 5 de l'ordre de diagnostic, et plus rien de logiciel ne peut le trancher.

**Compléments 17:52 → 18:00 (même itération) — la carte est restée MUETTE et le port série est tombé**

- **CC1101 muet depuis 17:52.** Après le flash de la session interactive (17:52:42), 4 sondes successives (17:53 → 17:56, à 868,05 puis 868,35) donnent **compteurs figés à 0/0 (valides et rejetées), RSSI jamais publié**, alors que **18 états d'entités sont bien reçus** (donc l'API livre : ce n'est pas une mesure nulle). Preuves : `logs/count_probe_final.json`, `logs/count_probe_final2.json`, `logs/count_probe_rearm1/2.json`, `logs/count_probe_statecheck.json` (avec le nouveau champ `entites_recues`).
  → Un **redémarrage par OTA n'a rien changé** : `logs/reboot_fix_flash.stdout` = `FLASH OK code=0 cible=172.16.0.205`, puis `logs/count_probe_after_reboot.json` = **0 paquet / 30 s, 18 états reçus**. C'est nouveau et important : au 17:37:54, le même remède avait réveillé la réception.
- **Port série hors service** (raison pour laquelle le log de boot n'a pas pu être lu) : `ls -l /dev/ttyACM0` → **`c--------- 0 nobody nogroup 166, 0`** (aucun droit) et **`/dev/serial/by-id/` a disparu** ; la règle udev `99-esp32.rules` n'est donc plus appliquée. `tools/serial_log.py` échoue sur `[Errno 13] Permission denied`. **Conséquence : aucun flash USB ni capture console possible tant que le port n'est pas repassé dans le LXC (`pct reboot 101` côté hôte).**
- **Collision entre les deux agents, confirmée par les horodatages** : mes captures de 17:47 → 17:52 tournaient pendant que la session interactive compilait et flashait (`build/last_status.txt` réécrit à **17:52:32**, `logs/last_flash_status.txt` à **17:52:42**) — un flash reboute la carte et coupe net toute capture en cours. Le verrou `build/.build_flash.lock` protège le *dossier de build*, **pas l'appareil** : la boucle doit vérifier qu'aucun `esphome` ne tourne (`ps`) et qu'un flash n'a pas eu lieu dans les 2 dernières minutes avant de mesurer.
- **Prochaine action (itération 6)** : d'abord **requalifier la réception** — reflasher la configuration nominale (déviation 37, `sync 16/16`, bw 100, 868,30) puis lire le log de boot CC1101 (`CC1101 found! Chip ID: 0x0014` attendu ; son absence = SPI/câblage) sur un port série réparé ; ensuite seulement reprendre la piste radio. **Tant que la carte ne renvoie pas de paquets de bruit, aucune conclusion radio n'est valide.**


## 2026-09-30 — Itération 4bis (session interactive) : 868,05 MHz = brouilleur, PAS la station

Mesure du pic détecté au balayage, cette fois dans des conditions radio corrigées (bande 100 kHz,
déviation 70 kHz, fréquence forcée à 868,05 MHz) : capture de 150 s via l'API →
**264 paquets, 0 trame valide**, 263 échecs de checksum. Preuve : `logs/capture_20260930_174045.log`,
`logs/eval_params.json`.

- `freq_offset` **éparpillés et sans cohérence** : `0` ×120, puis −1587, −3174, −9521, −15869,
  +1587… → signature de bruit, pas d'un émetteur cohérent (un vrai signal donnerait un offset
  stable, ce qui permettrait de recaler la fréquence).
- Le taux de faux verrous est de **1,76 paquet/s, soit ~10× celui mesuré à 868,30 MHz**
  (0,128/s). Cohérent avec le plancher relevé de ~18 dB à 868,05 : il y a bien de l'énergie à
  cette fréquence, mais **elle n'est pas démodulable en 2-FSK** → c'est un **brouilleur**
  (autre émetteur 868 MHz du voisinage), pas la station Vevor.
- **Conclusion : la station n'a toujours pas été entendue une seule fois.** Cumulé au test de la
  boucle (aucun bit du protocole dans le flux démodulé, syncword désactivé), le diagnostic est
  **physique** : le signal n'arrive pas au récepteur.

Actions décidées :
1. **Déplacer l'antenne** (accord de l'utilisateur) — rapprocher de la station, vue directe,
   antenne verticale et dégagée, alimentation par chargeur USB dédié.
2. **Vérifier côté station que l'unité extérieure émet réellement** (piles de l'ISS, indicateur
   de liaison radio sur l'écran intérieur). Une ISS sans pile n'émet rien : aucune quantité
   d'antenne ni de réglage n'y changera quoi que ce soit, et c'est vérifiable en 30 secondes.
3. Hypothèse à garder en réserve : **la référence YT60309 n'est peut-être pas en 2-FSK**
   (rtl_433 ne documente que YT60231/YT60234 ; l'OOK/ASK est courant sur ces stations). Si après
   déplacement on voit de l'énergie mais toujours aucun décodage, tester ASK/OOK — un seul flash.

## 2026-09-30 — Itération 4 (boucle) : le syncword n'est pas la cause — **aucun bit de la station dans le flux démodulé**

**Hypothèse testée (radio, une seule) : le cadrage.** `sync_mode: "None"` + `carrier_sense_above_threshold: true`
(au lieu de `16/16` + `CA 54`) : le moteur paquet du CC1101 démarre sur **seuil d'énergie**, la FIFO
remonte donc le flux de bits démodulé **sans dépendre du syncword, de la polarité ni de l'alignement
bit à bit**. Nouvel outil d'analyse : `tools/analyze_stream.py` (cherche le préambule `AA AA CA CA 54`
à tous les alignements, puis son **complément binaire**, puis toute candidate `AA 00` avec
checksum + compteur).

**Résultat mesuré : rien de la station** — preuves `logs/stream_analysis.json` et `logs/stream86805_analysis.json`
- 868,30 MHz, 70 s (`logs/stream1.log`) : 9 paquets, RSSI −97…−108 dBm → **0 préambule, 0 complément,
  0 candidate `AA 00`, 0 trame valide**.
- 868,05 MHz, 68 s (`logs/stream_86805.log`) : 7 paquets, RSSI −96…−105,5 dBm → mêmes zéros. Le
  « pic » à −84,5 dBm vu au balayage était donc **transitoire**, pas une porteuse.
- Conséquence : le syncword n'est pas le verrou. Le flux démodulé **ne contient aucun bit du
  protocole** → le problème n'est plus logiciel mais physique : le signal n'arrive pas au récepteur
  (antenne / portée / station muette — point 5 de l'ordre de diagnostic de MISSION).

**Raisonnement à réutiliser (corrige une piste du projet de référence)** : sur CC1101, `DEVIATN`
(déviation) ne sert qu'à l'**émission** ; en réception c'est la **bande** (`MDMCFG4`) qui compte.
« Déviation 37 → 70 kHz » ne peut donc **pas** expliquer une absence totale de réception : c'est un
faux suspect pour notre sensibilité (à ne tester que si on émet un jour).

**Point positif à garder** : la puce est bien accordée sur 868 MHz (des paquets de bruit arrivent
aussi bien à 868,30 qu'à 868,05 → PLL verrouillé, module très probablement en version 868 MHz).

**Retour à la configuration nominale (sous verrou, aucun run concurrent)**
- `sync_mode: 16/16` + `sync1/0 = CA 54` restaurés. `build/last_status.txt` = `BUILD OK code=0`
  (987 024 o) ; `logs/last_flash_status.txt` = `FLASH OK code=0 cible=172.16.0.205` ; fréquence de
  l'entité remise à 868,30 MHz (`tools/scan_freq.py --set 868.30`).
- Contrôle nominal : `logs/stream_nominal_restore.log` → **64 paquets en 45 s (1,46/s), 0 valide,
  0 `AA 00`, 0 `V7IN1 OK`** → la chaîne RX est vivante en mode nominal : elle ne reçoit que du bruit.

**Prochaine action (itération 5) — hypothèse unique : la sensibilité**
1. `filter_bandwidth: 100 kHz` (au lieu de 200 → ~3 dB de SNR en plus), `sync_mode` inchangé.
2. Puis **balayage fin** 868,25 → 868,45 MHz par pas de **10 kHz** (25 s/palier) : un signal faible
   peut être à quelques dizaines de kHz du nominal.
3. Repli peu coûteux si toujours rien (à noter, pas à faire en même temps) : la famille existe aussi
   en **915 MHz** (YT60234) et le CC1101 couvre 779–928 MHz → élargir la plage de l'entité
   « Fréquence CC1101 » (866–870 → 866–928) et tester 915,0–915,2 MHz.
4. En parallèle (action humaine, hors boucle) : rapprocher la station (< 5 m, vue directe) et vérifier
   que l'antenne vissée est bien une **868 MHz** — c'est le suspect n°1 d'après les mesures ci-dessus.

## 2026-09-30 — Itération 3 (session interactive) : contexte vérifié — la carte EST joignable

**Fait**
- USB passé dans le conteneur 101. Confirmé : `/dev/ttyACM0` + `by-id/usb-Espressif_USB_JTAG_serial_debug_unit_7C:E8:B1:D1:D8:5C-if00`, droits lecture+écriture OK.
  ⚠️ `/dev/ttyUSB0` existe **aussi** dans le conteneur : ne jamais s'y fier, la carte est sur
  `ttyACM0`. Toujours vérifier avant un flash.
- **Premier flash USB réussi** : `FLASH OK code=0`, « Hash of data verified », 1 050 992 octets @ 0x0.
- **La carte reçoit déjà des paquets RF** à 868,30 MHz (console série) :
  `V7IN1 RAW df ea 60 af b2 86 be b0 f2 e5 b4 2f 3b 1c 17 34 ab bc bc bc 73  rssi=-99.0 freq_offset=0 lqi=127`
  → `V7IN1 REJ en-tete`.
  Interprétation : SPI + CC1101 + mode packet + chaîne de validation fonctionnent. Mais
  `-99 dBm` = plancher de bruit → ce n'est **pas** la station, la fréquence reste à trouver.
- Carte joignable sur le réseau : **172.16.0.205:6053 ouvert** (Wi-Fi sur `172.16.0.0/24`, routé
  depuis `192.168.2.0/24`). Le mDNS ne traverse pas la passerelle → toujours viser l'IP.
- Options Wi-Fi demandées par l'utilisateur intégrées et validées : `output_power: 8.5dB`,
  `use_address: 172.16.0.205`, plus `on_shutdown` et `ota: on_begin` → `cc1101.set_idle`
  (l'utilisateur avait constaté un CC1101 indisponible après certains OTA).
- `tools/find_esp32.py` balaie maintenant `192.168.2.0/24` **et** `172.16.0.0/24` : l'ancien
  scan d'un seul sous-réseau concluait à tort « pas de carte ». Cache : `state/DEVICE_IP`.

**Piège constaté (important pour l'auto-évaluation)**
- Les logs via USB CDC **tronquent les lignes longues** (observé : `90 f33c 30 02 02 rffset=0`).
  Les logs servant de preuve doivent venir de l'**API native (port 6053)**, pas de l'USB.

**Corrections apportées à l'itération 2 — la carte EST joignable**
- L'itération 2 doutait de `172.16.0.205` : c'est **tranché par la preuve**. Sans clé, l'API
  répondait `Connection requires encryption` ; après correction de la résolution `!secret`, la
  capture donne : `connecté à 172.16.0.205:6053 — vevor-7in1 / esp32-c3-devkitm-1 / esphome
  2026.9.1`. Le Wi-Fi fonctionne et le sous-réseau est routé depuis ce conteneur via la
  passerelle (`ip route get 172.16.0.205` → `via 192.168.2.1`).
- Deux bugs d'outillage corrigés, qui menaient à tort à « carte absente » :
  1. `tools/find_esp32.py` ne balayait que `192.168.2.0/24` → il balaie désormais aussi
     `172.16.0.0/24` ; cache `state/DEVICE_IP` = `172.16.0.205` ;
  2. le motif de la clé API était `key:\s*(\S+)` : sur `key: !secret api_key` il ne capturait
     que `!secret`, donc la clé valait `None`. Motif corrigé dans `capture_logs.py` et
     `scan_freq.py` (la piste `!secret` de l'itération 2 était bonne, la capture était juste
     incomplète). `subscribe_logs` n'est pas une coroutine → plus de `await` dessus.
- Le « run frère » de 16:38, c'était **la session interactive** (l'humain), pas un doublon de la
  boucle : `wifi.output_power`, `wifi.use_address` et `ota.encryption` venaient d'une demande
  explicite de l'utilisateur (sa carte était rejetée par son DNS, et le CC1101 devenait
  indisponible après OTA). Validées par le schéma ESPHome installé (`output_power` =
  `cv.decibel`, min 8,5 ; `use_address` = `cv.string_strict` ; `ota.encryption` reconnu).
  **Ne pas les retirer.**
- Un verrou `build/.build_flash.lock` (flock) protège désormais `build.sh` et `flash.sh` : deux
  exécutions simultanées ne peuvent plus se marcher dessus sur le même dossier de build.
- Contre-relevé API (45 s, `logs/capture_api.log`) : 11 trames de 21 octets, RSSI −105…−108,5
  dBm, LQI=127, **toutes rejetées** → confirme « bruit de fond à 868,30 MHz ». Signature de
  bruit bien visible : octets finaux répétés (`26 26 26…`, `87 87 87`, `43 43 43`).

**Prochaine action, désormais possible** : le balayage via l'API, qui était bloqué faute d'accès
réseau → `tools/scan_freq.py --host 172.16.0.205 --start 867.8 --stop 868.6 --step 0.05 --dwell 25`

**Prochaine action**
- Balayage `867,8 → 868,6 MHz` par pas de 50 kHz, 25 s par palier
  (`tools/scan_freq.py --host 172.16.0.205 --start 867.8 --stop 868.6 --step 0.05 --dwell 25`),
  puis reflash avec la fréquence trouvée.

## 2026-09-30 — Itération 0.5 : accès matériel et boucle armée

**Le port série est enfin là (après `pct reboot 101`)**
- Empreinte du moniteur : `serie=[/dev/ttyACM0,/dev/ttyUSB0,] byid=[usb-Espressif_USB_JTAG_serial_debug_unit_7C:E8:B1:D1:D8:5C-if00]` ; `uptime` = 5 min au premier tick (conteneur redémarré, le port est donc bien passé dans le LXC).
- `/dev/ttyACM0` = USB-Serial-JTAG de l'ESP32-C3, `crw-rw-rw-` → utilisable. `/dev/ttyUSB0` est présent mais en `---------- root root` (inutilisable) : tout passe par ttyACM0.
- Flash USB réussi : `logs/last_flash_status.txt` = `FLASH OK code=0 cible=/dev/ttyACM0`, log de flash terminé par « Hash of data verified. / Successfully uploaded program. ».

**Preuve matérielle n°1 : le CC1101 répond, et la FIFO remonte bien des paquets**
- Capture série `logs/serial_20260930_163519.log` (80 s, `esphome logs --device /dev/ttyACM0`) :
  - `[D][cc1101:148]: CC1101 found! Chip ID: 0x0014` → SPI, câblage CS/SCK/MOSI/MISO **validés**.
  - 11 lignes `V7IN1 RAW` de **21 octets exactement**, toutes rejetées (`V7IN1 REJ en-tete`).
- **Suspect n°1 de l'itération 1 écarté** : `cc1101.cpp` d'ESPHome 2026.9.1 (l. 742-747) met en mode packet `GDO0_CFG=0x01` (« FIFO status : seuil OU fin de paquet ») et `FIFO_THR=15` ; l'interruption se déclenche donc sur de vraies fins de paquet, pas sur un seuil de FIFO inatteignable. Les paquets arrivent — ils sont juste illisibles.

**Analyse mesurée : du bruit, pas la station** — `tools/analyze_noise.py` → `logs/noise_analysis.json` (verdict `BRUIT_SEUL`), trames brutes dans `logs/raw_frames.jsonl` (11 lignes)
- 0/11 paquets avec l'en-tête attendu `AA 00` (règle du décodeur : `in[0]!=0xAA || in[1]!=0x00` → « en-tete »), 0 trame valide, 0 checksum OK.
- Cadence observée **0,128 paquet/s** sur 78,2 s ↔ faux verrou d'un syncword **16 bits** = 11 505/2^16 = **0,176/s** (sync 32 bits : 2,7e-6/s, négligeable) → les 11 paquets sont des verrous de sync sur le bruit de fond.
- RSSI −94,5…−107,5 dBm (moyenne −101,0) et LQI=127 constant = plancher de bruit ; 231 octets, entropie 6,97/8 et 146 valeurs distinctes (≈152 attendues pour de l'uniforme) → contenu aléatoire.
- Conclusion honnête : **pas de signal Vevor sur 868,30 MHz** (station hors de portée, éteinte, ou sur un autre canal). Le problème n'est plus « on ne reçoit rien » mais « on reçoit du bruit ».

**Prochaine hypothèse (une seule à la fois) : la fréquence** → balayage 867,5–869,0 MHz.
- Voie nominale : `tools/scan_freq.py` sur l'entité « Fréquence CC1101 » (déjà écrite) — mais elle suppose la carte joignable sur le réseau.
- Blocage réseau constaté : **aucune** ligne `Connecting to …` dans les 80 s de log, et `tools/find_esp32.py` → `none` après le flash. La carte n'est donc joignable ni en OTA ni en API depuis ce conteneur ; cause non tranchée.
- Repli sans Wi-Fi : balayage embarqué (l'`interval` change de fréquence et journalise RSSI/nb de paquets par palier) lu par la console série.

**Run frère / prudence** : ce tick a tourné en parallèle d'un **second run du même job** (il a réécrit `esphome/vevor-7in1.yaml` à 16:38:22 : `ota.encryption` + `cc1101.set_idle` sur `on_begin`, `wifi.output_power: 8.5dB`, `wifi.use_address: 172.16.0.205`). Ces deux derniers points ne sont **étayés par aucun log de ce dépôt** : le conteneur n'a qu'une interface `192.168.2.167/24` (`ip route` : aucune route vers 172.16.0.0/24) et aucune capture ne montre d'IP obtenue en 172.16.0.x. À confirmer par la prochaine capture série. Corollaire : **ne jamais lancer build/flash en même temps qu'un autre run** (même dossier de build → collision).

**Déverrouillage majeur (même tick) : l'API native est joignable — la carte est en Wi-Fi**
- `tools/net_scan.py --subnet 172.16.0 --ports 6053,6052,80 --timeout 1.0` → **`172.16.0.205 -> 6053 (ESP32 ESPHome — API native)`** (+ 8 hôtes HTTP sur ce /24). La carte est donc connectée à un réseau Wi-Fi **172.16.0.0/24** et joignable depuis ce conteneur (`ip route get 172.16.0.205` → via la passerelle 192.168.2.1). Le mDNS ne traverse pas, mais l'IP directe suffit : plus besoin de reflasher pour les logs.
- **Stabilité mesurée** (nouveau `tools/tcp_probe.py`) : 15/15 connexions OK en 60 s (« lien STABLE »). Les 3 échecs `EHOSTUNREACH` du premier lancement correspondaient à la fenêtre de reboot du flash USB du run frère (le lien est instable seulement pendant le boot de la carte).

**Trois bugs d'outillage corrigés (chacun bloquait l'autonomie)**
1. `aioesphomeapi` attend la clé de chiffrement en paramètre **nommé** `noise_psk=` (la 3e position = ancien mot de passe en clair) → les deux outils répondaient « Connection requires encryption ». Corrigé dans `tools/scan_freq.py` et `tools/capture_logs.py`, dont le `key_from_yaml()` résout maintenant `key: !secret api_key` via `esphome/secrets.yaml` (avant, il renvoyait littéralement `!secret api_key`).
2. Motif d'entité `f[ée]quence` (le `r` manquait) → « entité « Fréquence CC1101 » introuvable » alors que `--list` la voyait. Corrigé en `fr[ée]quence`.
3. `int(NaN)` → `ValueError: cannot convert float NaN to integer` dès qu'un palier lisait un capteur jamais publié (« Trames valides » vaut NaN avant la 1re trame). Les compteurs NaN sont maintenant traités comme 0 (et le RSSI NaN ignoré).
- Preuve que le chemin scan marche : `logs/scan_smoke.json` → `868.300 MHz trames=0 rssi_max=-105.5` (palier de 6 s, cohérent avec le plancher de bruit).

**Balayage de fréquence en cours (hypothèse unique)**
- `logs/scan_sweep1.log` + `logs/scan_sweep1.json` : **867,80 → 868,60 MHz, pas de 0,05, 25 s par palier** (~7,5 min, lancé à 16:48:30 UTC, PID 10915 détaché, `persist_on_release`).
- Lecture au tick suivant : par palier `valid` (trames conformes) et `rssi_max` — le total `frames`/`rejected` inclut les faux verrous de bruit présents **sur tous** les paliers, donc il ne discrimine pas.
- **Ne pas relancer de balayage ni toucher à l'entité « Fréquence CC1101 » tant que `logs/scan_sweep1.json` n'existe pas**, et ne pas lancer de build pendant qu'un autre run compile (même dossier de build).

**À vérifier au prochain flash OTA** : le run frère a ajouté `on_begin: cc1101.set_idle` (pour rester joignable pendant l'OTA). Si rien ne remet le CC1101 en RX après un OTA, le récepteur peut rester muet — à confirmer par une capture post-OTA (composant `cc1101.cpp` : `set_idle()` à la ligne 288, `begin_rx()` à la 271).

## 2026-09-30 — Itération 1 : vérification hors matériel de la config radio (aucun flash)

**Matériel toujours absent (vérifié, pas supposé)**
- `ls /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/` → rien ; aucun `/dev/ttyS*` non plus.
  Donc **pas de flash USB possible** et aucune trame captée : « pas de signal », littéralement.
- `tools/net_scan.py` (ports 6052/6053/8123 sur tout le /24) → « rien trouvé » ; `tools/find_esp32.py`
  → `none`. Aucun ESP32 joignable, donc ni OTA ni capture de logs par l'API native.
- Empreinte du moniteur : `serie=[aucun] byid=[aucun] esp32=none phase=waiting_hardware step=0`.

**Fait (utile sans matériel) : le CC1101 serait-il réellement programmé comme la spec l'exige ?**
- Nouveau `tools/verify_radio_config.py` : rejoue **ligne à ligne** les calculs du composant
  `cc1101` d'ESPHome (`.venv/.../components/cc1101/cc1101.cpp` : `split_float()`,
  `set_frequency`, `set_filter_bandwidth`, `set_fsk_deviation`, `set_symbol_rate`) sur les
  substitutions du YAML, puis reconvertit en grandeurs physiques avec les formules du datasheet
  utilisées par `dump_config()`. Rapport : `logs/radio_config_check.json` (VERDICT OK, exit 0).
- Résultat mesuré (registres réellement écrits) :
  - fréquence 868,300 MHz demandée → **868,299866 MHz** (FREQ=0x21 0x65 0x6A, erreur **-134 Hz**) ;
  - déviation 37 kHz demandée → **38,09 kHz** (DEVIATN=0x44, E=4 M=4 — quantification du chip) ;
  - bande passante 200 kHz → **203,12 kHz** (CHANBW_E=2 M=0, MDMCFG4=0x88) ;
  - débit 11 494 demandé → **11 505 bauds** (DRATE_E=8 DRATE_M=208).
- Contrôle anti-repliement : `(déviation + débit/2) / (bande/2) = 0,43 < 1` → les bits ne sont pas
  écrêtés par le filtre (règle CC1101, source d'un « pas de paquet » classique).
- Autres contrôles OK : `sync_mode 16/16` avec sync1=0xCA/sync0=0x54 (= motif rtl_433 `…CA CA 54`),
  `whitening=false`, `manchester=false`, `crc_enable=false`, `packet_mode=true` + `packet_length=21`
  en **longueur fixe** (le composant met `APPEND_STATUS=0` dans ce mode : la FIFO contient bien
  21 octets, pas 23 → pas de rejet « taille » systématique).

**Point à surveiller sur la 1re capture (hypothèse non prouvée, à trancher par le log)**
- En mode packet, ESPHome met `GDO0_CFG=0x01` (IOCFG0) et `FIFO_THR=15` (= seuil 64 octets, donc
  jamais atteint par une trame de 21 octets) : la lecture de la FIFO ne peut donc se déclencher que
  sur la **fin de paquet**. Si la première capture montre `CC1101 found!` mais **zéro** ligne
  `V7IN1 RAW`, c'est le premier suspect (avant la fréquence) : ne pas chercher à rebalayer la bande.
  Repli prévu : `GDO0_CFG` sur « end of packet » explicite (0x06/CRC désactivé) ou retour au mode
  *async serial* avec décodage bit à bit depuis GDO0.

**Prochaine action (itération 2)** — inchangée, elle dépend de l'utilisateur
1. Passer le port série USB dans le LXC 101 (snippet PVE : `cgroup2 188:*`/`166:*` + bind
   `/dev/serial/by-id`) puis `pct reboot 101`.
2. Vrai SSID/mot de passe Wi-Fi dans `esphome/secrets.yaml` (valeurs factices actuelles :
   elles empêcheraient toute connexion → ni OTA ni logs).
3. `tools/flash.sh /dev/ttyUSB0`, puis `tools/scan_freq.py --host <IP> --start 867.8 --stop 868.6
   --step 0.05 --dwell 25`.

**Pourquoi `state/PHASE` n'est pas modifié par cette itération** : l'empreinte du moniteur est
identique (aucun port série, aucun ESP32, même phase) → la boucle reste au repos et ne publie rien
d'inutile. `PHASE` repassera à `phase=scanning_frequency step=…` dès qu'une carte sera joignable.

## 2026-09-30 — Itération 0.5 : accès matériel et boucle armée

**Diagnostic réseau (le token HA ne sert à rien pour l'instant)**
- `192.168.2.104` = bien `homeassistant.local` (mDNS) mais **aucun service sur 8123** :
  seuls 80 et **4357** (observateur HAOS) répondent. Donc HA Core est arrêté ou n'écoute plus.
  Le `.ha_token` est en place et testable dès qu'il revient. Preuve : `tools/net_scan.py`.
- Piège corrigé dans l'outillage : un timeout de 0,4 s sur le scan /24 donnait des **faux
  négatifs** (il ratait même le port 80 de HA, pourtant ouvert). Défaut porté à 1,0 s.

**Accès matériel**
- L'ESP32 est branché sur l'**hôte Proxmox**, pas sur la machine HA → l'add-on ESPHome de HA
  ne peut pas le voir. Il faut passer le port série USB dans **ce conteneur (ID 101)**.
  Snippet PVE fourni à l'utilisateur (cgroup2 188:* et 166:* + bind de /dev/serial/by-id).
- Aucun `/dev/ttyUSB*` ni `/dev/ttyACM*` visible pour l'instant : normal, pas encore passé.

**Boucle autonome armée**
- Tâche planifiée Hermes `5fe5aac7bcf4`, toutes les 15 min, sortie dans le salon Discord
  #esphome (`1554880841325482104`), `continuity` activé.
- Elle est **pilotée par une empreinte d'état** (`tools/loop_monitor.sh`, via
  `~/.hermes/scripts/vevor_loop_monitor.sh`) : porte série, IP de l'ESP32, phase du projet,
  dernier statut de build/flash. Empreinte identique → l'agent n'est même pas lancé (aucun
  message, aucun coût) ; empreinte différente → l'agent fait une itération.
- Vérifié : deux ticks consécutifs donnent une empreinte identique, et un changement de
  `state/PHASE` est bien détecté comme un réveil.
- `state/PHASE` est donc le **levier d'avancement** : si l'agent ne le met pas à jour, la
  boucle s'endort. C'est documenté dans son prompt.

**Prochaine action (itération 1)**
1. Passer le USB dans le conteneur 101 (snippet PVE) puis `pct reboot 101`
   (`hermes-gateway.service` est `enabled`, donc l'agent revient seul).
2. Renseigner le **vrai Wi-Fi** dans `esphome/secrets.yaml` (sinon la carte flashée ne se
   connectera pas : ni OTA, ni logs).
3. `tools/flash.sh /dev/ttyUSB0` (ou `/dev/ttyACM0`), puis
   `tools/scan_freq.py --host <IP> --start 867.8 --stop 868.6 --step 0.05 --dwell 25`.

## 2026-09-30 — Itération 0 : mise en place (agent, sans matériel)

**Fait**
- Récupéré la source de vérité du protocole : `references/vevor_7in1.c` (rtl_433) → synthèse
  dans `references/PROTOCOL.md` (2-FSK, 87 µs/bit ≈ 11 494 bauds, ±37 kHz, trame de 21 octets,
  checksum = somme(b[0..18]) & 0xFF, b[20] = b[18]+1, rafale toutes les 20 s).
- Décodeur C++ `esphome/includes/vevor_7in1.h` (portage fidèle, avec les -1 sur les octets
  8,9,11,12,13,14,16,17 appliqués APRÈS validation du checksum).
- Firmware `esphome/vevor-7in1.yaml` : cc1101 en mode packet, sync `CA 54`, 21 octets,
  publication de tous les capteurs + entités de diagnostic (RSSI, offset fréquence, compteurs
  valides/rejetées, dernière trame brute) + entité `number` « Fréquence CC1101 » permettant de
  balayer la bande **sans reflasher**.
- Outillage : `tools/build.sh`, `tools/flash.sh`, `tools/capture_logs.sh` (logs via l'API
  native, port 6053), `tools/eval_frames.py` (décodeur Python **indépendant** + critères
  d'auto-évaluation), `tools/scan_freq.py` (balayage de fréquence piloté par l'API).
- ESPHome 2026.9.1 installé dans `.venv` (pip, pas d'apt : pas de sudo sur le conteneur).
- `esphome config` : **valide** (0 erreur).

**Vérifié pour de vrai**
- **Le firmware compile** : `tools/build.sh` → « Successfully compiled program »
  (`firmware.ota.bin` 985 456 octets, RAM 33,5 %, flash 53,7 %). Le binaire contient bien
  les chaînes du décodeur C++ (`V7IN1 RAW`, `V7IN1 OK`, `V7IN1 REJ`) — le C++ est donc
  réellement intégré, pas seulement présent dans le YAML. Preuve : `build/last_compile.log`.
- Le décodeur Python a été testé sur la trame de référence de rtl_433
  (`aa 00 f8 f7 9d 02 e3 32 01 0e 03 02 0b 01 38 02 39 7a 86 e0 87`) :
  checksum OK, compteur OK → **23,9 °C / 50 % / vent 1,6 km/h / rafale 2,4 km/h / 266° /
  12,8 mm / UV 1 / 14 457 lx**. Une trame volontairement corrompue est bien rejetée
  (checksum KO). Preuve : `logs/selftest.log` + `logs/selftest_report.json`.

**Incident résolu (à ne pas refaire)**
- Le framework `esp-idf` (et même `arduino`, qui l'utilise en interne depuis ESPHome 2025+)
  plantait sur `Can't create Python virtual environment for ESP-IDF 5.5.5` : le Python de
  Debian 13 du conteneur est privé d'`ensurepip` (paquet `python3-venv`, non installable
  sans sudo). Corrigé par `tools/fix_python_env.sh` : venv du projet reconstruit sur un
  CPython autonome (python-build-standalone via `uv`) qui embarque `ensurepip`. Ne pas
  revenir au Python système pour ce venv.

**Bloqué par**
- Pas de matériel accessible depuis le conteneur : aucun `/dev/ttyUSB*` visible
  (le CC1101/ESP32 n'est pas encore branché, et le port série n'est pas passé dans le LXC).
- `secrets.yaml` contient des valeurs factices : il faut le vrai SSID/mot de passe Wi-Fi.
- Câblage non confirmé (hypothèse : SCK=GPIO4, MISO=GPIO5, MOSI=GPIO6, CSN=GPIO7, GDO0=GPIO3).

**Prochaine action (itération 1)**
1. Confirmer le câblage + renseigner `secrets.yaml` avec le vrai Wi-Fi.
2. Flasher en USB (première fois) une fois le port série accessible :
   `tools/flash.sh /dev/ttyUSB0`.
3. `tools/scan_freq.py --host <IP> --start 867.8 --stop 868.6 --step 0.05 --dwell 25`
   et serrer la fréquence sur le meilleur palier.
4. Si aucun paquet : déviation (37 kHz ±), bande passante (100→300 kHz), puis `packet_length`
   et syncword ; journaliser chaque essai ici.

**Hypothèses à vérifier (non prouvées)**
- La référence YT60309 utilise le même protocole que YT60231/YT60234 (famille Fujian Youtong) —
  à confirmer par la capture réelle.
- Fréquence de départ 868,30 MHz = simple point de départ pour le balayage, pas une mesure.
- `symbol_rate: 11494` : déduit de la période bit de 87 µs de rtl_433.

## Itération 12 — fenêtre d'une heure réelle, et le défaut qu'elle a révélé (01/10/2026)

**Contexte.** La fenêtre de 11:36→12:36 était vide (0 capture, 3600 s). Vérifié : ce n'était pas le
firmware. Test interleavé (2 tours × 60 s, témoin / firmware corrigé / binaire d'avant la revue,
`logs/ab_cycle.jsonl`) : le témoin et le binaire d'avant la revue ne reçoivent RIEN (le second
affiche ses propres lectures SPI : `VERSION=0x00`, `MARCSTATE=0x00 SLEEP`, « valeurs non fiables »),
le firmware corrigé reçoit 3 trames/60 s aux deux tours. Le binaire d'avant la revue, qui décodait
216 trames à 11:28, est donc muet **dans la même fenêtre** : l'accès SPI depuis ce composant est
bien ce qui tue la réception. La station, elle, émettait par phases (silence 11:28→12:42).

**Fenêtre d'une heure conditionnelle** (`build/fenetre_1h_conditionnelle.sh`, flash → sonde 60 s →
heure longue si la station émet) : détectée active dès la première sonde (4 trames/60 s), fenêtre
12:51:00→13:51:00 UTC, `logs/fenetre_1h_cond_20261001.log`.

**Résultats** (`evidence/rapport_fenetre_1h_decalage.json`) : **181 trames, 181 valides, 0 échec de
checksum, 0 échec de compteur, 179/179 intervalles à 20 s, accord champ par champ C++/Python sur les
181**. Compteurs carte : captures=558, trames=185, doublons ignorés=116+, rejets=178.

**Défaut trouvé par le verdict** : 2 trames sur 181 (1,6 %) sont **fausses tout en passant en-tête,
checksum et compteur** — décalage d'un bit à l'extraction, ce qui double les octets de valeur :
direction 779° et 835°, pluie 178,2 mm au lieu de 59,2, vent 34,2 km/h, UV 10-12. Elles venaient de
captures **d'un seul bloc** (piste du recollage écartée par vérification : les 2 trames recollées de
la fenêtre sont, elles, correctes). Piste retenue : la rafale livrée deux fois par le RMT produit
une fois un décodage décalé d'un bit, une fois le bon — la déduplication ne peut pas l'écarter
(trames différentes octet pour octet).

**Correctif** : porte de plausibilité dans `includes/vevor_protocol.h` (direction > 359°, humidité
> 100 %, température hors −40..60 °C, vent/rafale > 180 km/h, UV hors 0..16 → refus motivé, compté
dans les rejets) + test `test_plausibility` avec **les deux trames réelles fautives** (elles doivent
être refusées) et la trame saine encadrante (elle doit passer).

**Corrigé aussi** : `tools/summarize_window.py` affichait « AUCUNE trame décodée » sur une fenêtre de
181 trames — ESPHome colore ses lignes, et les motifs ancrés en fin de ligne ne correspondaient
jamais à cause des séquences ANSI. Nettoyage ANSI ajouté avant analyse.

## Itération 13 — le vrai défaut : un démarrage sur deux lève la puce absente du bus SPI (01/10/2026)

**Point de départ.** L'utilisateur a contesté mon explication « la station est en phase de silence » :
« il n'y a pas de raison que la station arrête d'émettre juste pendant les tests, c'est que la sonde
ne capte plus rien après un OTA. Peut-être forcer un reboot pour la récupérer. » Il avait raison.

**Preuve que ma conclusion était fausse.** La sonde du 13:53:38 comptait les trames dans un fichier
ouvert en AJOUT : elle a compté les 4 trames laissées par la sonde de 12:50 et conclu « station
active ». La capture d'une heure qui a suivi affichait `captures=0` dès sa première seconde : aucune
livraison du RMT, donc ni décodage ni rejet — la carte, pas la station.

**Mesure du taux (6 cycles flash → 5 min de capture, même binaire d8e6152d)** : sourd / sain /
sourd / sain / sourd / sain — **alternance stricte, 3 cycles sur 3**, 0 trame contre 15 trames.
Ce n'est pas aléatoire : chaque démarrage inverse l'état de la puce (elle garde ses registres quand
l'ESP32 redémarre).

**Cause, lue dans le journal embarqué** (ré-armement automatique déclenché par le firmware) :
```
[D][cc1101:148]: CC1101 found! Chip ID: 0xFFFF
[E][cc1101:150]: Failed to verify CC1101.
[W][cc1101:279]: Failed to enter RX state!
```
`0xFFFF` = **toutes les lectures SPI à 0xFF : la puce ne répond pas sur le bus**. Elle n'est donc
jamais configurée, reste en IDLE d'usine, et GDO0 ne sort rien. Ni PLL, ni RMT, ni station.

**Ce qui répare, ce qui ne répare pas (mesuré)**
- ré-armement à chaud (`reset` + réglages + `begin_rx`) : **inefficace** (3 tentatives, 3 fois
  « Failed to verify ») ;
- redémarrage : **efficace** — c'est lui qui inverse l'état (sourd → sain à chaque fois).

**Correctif (firmware, autonome)** : état radio journalisé chaque minute (`SANTE radio=ok|EN ECHEC
captures=N muet depuis M min`), ré-armement automatique à 3 min, **redémarrage automatique à 8 min
si et seulement si la radio s'avoue en échec** (jamais si la station est simplement à l'arrêt, sinon
les captures longues seraient sabotées), plus un bouton « Redémarrer la carte » pour ne plus dépendre
d'un reflash.

**Corrigé au passage** : `capture_logs.py` écrivait en AJOUT (une fenêtre vide relue sur la
précédente s'est fait passer pour un résultat) → écrasement par défaut ; `summarize_window.py` ne
voyait aucune trame à cause des séquences ANSI d'ESPHome → nettoyage ; et le garde-fou de
plausibilité, vérifié par une fenêtre d'une heure complète : 180 trames, 180 valides, 0 échec de
checksum, 0 désaccord C++/Python, pluie monotone, `verdict: PASS`.

## Itération 14 — la station émet en continu : le garde-fou devient inconditionnel (01/10/2026)

**Information donnée par l'utilisateur** : « la station émet en continu toutes les 20 s jour et nuit ».
Elle lève l'ambiguïté qui bridait le garde-fou : un silence de plus de quelques minutes n'est jamais
un arrêt de la station, c'est toujours une panne du récepteur. Il n'y a donc plus de raison de
repousser le redémarrage à 20 min « au cas où la station serait à l'arrêt ».

**Garde-fou final** (`esphome/vevor-7in1.yaml`) : état journalisé toutes les 20 s, 9 tentatives
d'initialisation sur 3 min (gratuites, recommandées par le fil TI pour un quartz lent), puis
redémarrage automatique — 4 fois de suite, puis un par 30 min sans jamais renoncer. Le compteur de
tentatives est persistant et remis à zéro dès qu'une trame passe. La distinction « radio EN ECHEC »
(puce muette sur le SPI) contre « radio ok » (chaîne RF/RMT) reste journalisée : elle sert à savoir
ce qu'on répare, plus à décider s'il faut redémarrer.

**Mesures intermédiaires qui ont mené là** (toutes consignées dans `logs/`) :
- v2 (seuil 8 min sur les CAPTURES) : redémarrage déclenché 3/3 mais jamais là où il fallait — en
  état sourd, quelques captures parasites remettaient le compteur à zéro (9 min, 7 lignes EN ECHEC,
  0 redémarrage). Critère changé pour les TRAMES publiées.
- v3 : 8 tentatives d'initialisation en 3 min, 0 redémarrage en phase A (seuil resté à 20 min) ;
  les deux cycles sont restés sourds 21 min → confirme que les tentatives d'initialisation ne
  récupèrent pas, seul le redémarrage le fait.
- Un second mode de panne a été observé au passage : « radio=ok, captures=0 » pendant 10 min — la
  puce répond au SPI, est configurée, et rien n'arrive au RMT. Il est traité par la même règle.

## Itération 15 — auto-guérison mesurée de bout en bout (01/10/2026, binaire 6706e62f)

Deux cycles `flash → 5 min → 12 min`, avec le garde-fou final :

- **essai 1 — démarrage sourd, récupéré sans intervention** : phase A = 0 trame, 8 tentatives
  d'initialisation, **1 redémarrage automatique à 3 min**. Phase B : 10 tentatives puis un second
  redémarrage, puis **21 trames**. La carte est donc revenue seule en deux redémarrages, sans
  personne et sans reflash — c'est exactement ce que demandait l'utilisateur (« forcer un reboot
  pour la récupérer »), automatisé.
- **essai 2 — démarrage sain** : phase A = 15 trames, phase B = 36 trames, aucun redémarrage,
  aucune tentative d'initialisation. Cadence normale (3 trames/minute = une tous les 20 s).

Total de la séquence : 72 trames reçues pendant les 34 minutes de l'expérience, dont aucune perdue
après récupération. Le binaire mesuré (6706e62f) est celui flashé sur la carte.

## Itération 16 — deux états de panne, et la piste du quartz (01/10/2026, nuit)

**Constat de la soirée** : vers 21:16, la carte est passée dans un état où elle ne reçoit plus, et
depuis elle n'en est plus sortie — alors que la même carte avait tourné une heure entière à 180
trames l'après-midi (18:48→19:06).

**Deux états mesurés, jamais un troisième qui reçoive** :

| État | Signature au journal | Interprétation |
|---|---|---|
| A | `CC1101 found! Chip ID: 0xFFFF`, `SANTE radio=EN ECHEC` | la puce ne répond pas sur le SPI (MISO reste haut) : elle n'est jamais configurée |
| B | `Chip ID: 0x0014` mais `PLL lock failed, retrying calibration`, `SANTE radio=ok`, `captures` qui montent, `trames=0` | la puce répond, entre en RX sans se caler, ne démodule rien d'utilisable |

**Ce qui ne répare rien (mesuré)** : ré-armement à chaud jusqu'à 9 fois d'affilée (échec à chaque
fois) ; **coupure d'alimentation 5 s** (donne l'état B) ; **coupure de 30 s** (même état B — la durée
ne change rien) ; redémarrage à chaud (renvoie en état A). Le seul remède connu reste le redémarrage,
et ce soir il n'atteint plus l'état sain.

**Hypothèse retenue** : le quartz 26 MHz du module ne repart pas de façon fiable après une
perturbation d'alimentation — et le démarrage de l'ESP32-C3 lui-même suffit à la provoquer (la
réception fonctionne quand le quartz a survécu au redémarrage de l'ESP32, elle meurt quand il
s'arrête). Cohérent avec le fil TI E2E « CC1101 not responding to SPI » (des 1 partout, quartz qui
n'oscille pas au départ) et avec le fait que le composant ESPHome lit `PARTNUM`/`VERSION` une seule
fois puis se déclare en échec.

**Pistes matérielles à contrôler sur place** (ordre de probabilité) : liaisons SPI Dupont (CLK/MOSI/
MISO/CS + masse) à refaire en soudé ; découplage du module (100 nF + 10 µF) ; alimentation du module
et sa tenue pendant le démarrage de l'ESP32 (oscilloscope) ; remplacement du module si le quartz est
en cause.

**Veille en place** : 60 fenêtres de 55 s classant l'état (A / B / C-sain) pour savoir si la carte
retombe d'elle-même sur l'état sain (malchance) ou reste bloquée (matériel).

## 02/10 — intervention matérielle de l'utilisateur (matin)

- **Pull-up sur CS (GPIO7) : 10 kΩ** au 3,3 V, soudé — exactement la valeur de la carte de
  référence ESP32-C3 + CC1101. (L'utilisateur a d'abord annoncé 100 kΩ, puis corrigé : c'est bien
  10 kΩ.)
- **Condensateur : 10 µF** — la valeur attendue pour le découplage du module.
- Mesure d'après-soudure : redémarrage à froid **sans reflash** (pour exercer réellement un démarrage
  avec le nouveau câblage), puis fenêtre d'écoute de 8 min → `logs/apres_soudure.log`.

## 02/10 après-midi — après les soudures (pull-up 10 kΩ sur CS + 10 µF)

**Ce qui est réglé :** le lien SPI en écriture. Mesure : « configuration : 1/4/0/2 registre(s) repris
apres relecture, **0 definitivement non pris** » sur quatre cycles consécutifs — hier soir `MDMCFG4`,
`MDMCFG3` et `FREQ0` restaient figés à leur valeur d'usine. La puce est donc réellement configurée.

**Ce qui reste, et le mécanisme identifié :**

1. Le firmware témoin (composant d'ORIGINE d'ESPHome) a décodé **12 trames** le 02/10 à 12h30 sur ce
   même matériel, même YAML (les blocs `cc1101` et `remote_receiver` sont identiques champ pour
   champ, à `id: radio` près). Le nôtre : 0. La configuration YAML est donc hors de cause.
2. Au démarrage, notre build REÇOIT la station : le compteur de captures avance de +3 toutes les 20 s
   exactement (puis se fige) — la cadence de la station. Le flux arrive donc bien.
3. Le garde-fou ré-arme toutes les 20 s tant qu'aucune trame n'est publiée (9 tentatives), et chaque
   ré-armement échoue à entrer en RX : « Failed to enter RX state! » (4 fois mesuré). Or dans le
   pilote, un échec d'entrée en RX appelle `mark_failed()` — **la session entière est condamnée**.
   D'où le motif : réception correcte ~2 min, puis sourde jusqu'au redémarrage suivant.

**Correctif appliqué (pilote local, `cc1101.cpp`) :**
- `enter_calibrated_()` ne fait plus `return false` sur un dépassement d'attente : il réessaie
  (attente portée à 250 ms, pause de 10 ms, retour en IDLE, nouvel essai) — la datasheet §22.1 demande
  de recalibrer en boucle jusqu'au verrouillage ;
- délai de stabilisation de 20 ms avant l'entrée en RX (le démarrage à froid réussissait, le
  ré-armement à chaud non) ;
- journalisation explicite de « Failed to enter RX state! » au point d'appel de `configure()`.

**Test en cours :** ce pilote + le garde-fou laissé actif — si le ré-armement réussit désormais, les
sessions survivent et les trames doivent revenir (`logs/test_reessais_rx.log`).

**À faire si ça ne suffit pas :** comparer les impulsions BRUTES (bouton « Dump impulsions ») à ce
que décode le décodeur Python — pour savoir si le flux est bon et que c'est l'assembleur qui rate, ou
si c'est la réception elle-même. Le témoin reste le contrôle de référence, sur plusieurs fenêtres.


## 02/10 — CAUSE RACINE TROUVÉE : la cadence SPI que J'AVAIS abaissée à 200 kHz

**Ce qui était cassé :** le 01/10 au soir, pour compenser des écritures de registres perdues, j'avais
abaissé la cadence SPI du pilote CC1101 de 1 MHz à **200 kHz** (`cc1101.h`, `DATA_RATE_200KHZ`).
Les soudures du matin (pull-up 10 kΩ sur CS + 10 µF) ont réglé les écritures perdues — mais la
béquille, elle, **rendait la puce sourde** : elle sortait un flux de bruit au lieu du signal.

**Preuve, à état de puce identique** (puce qui répond, PLL verrouillée, `MARCSTATE=0x0D`) :

| configuration | longueur des captures | durées | trames décodées |
|---|---|---|---|
| pilote modifié, SPI 200 kHz | 437 à 510 impulsions | continuum de 45 à 1100 µs | 0 |
| pilote d'origine, SPI 1 MHz | 166 à 182 impulsions | rythme 2:1 (≈113 µs / ≈57 µs) | 12 |
| pilote modifié, SPI 1 MHz | 498 à 531 impulsions | signal | **3, 4 puis 4** |

Et le point qui rend la démonstration solide : sur six démarrages d'affilée avec le SPI à 1 MHz, les
**trois** démarrages où la puce répondait ont décodé des trames (3, 4, 4 — soit la totalité des
rafales émises dans la fenêtre), les trois où elle ne répondait pas (état A, `Chip ID 0xFFFF`) n'en
ont décodé aucune. La cadence de 1 MHz est donc rétablie et le récepteur fonctionne.

**Leçon de méthode :** deux fois aujourd'hui j'ai conclu sur une comparaison polluée par la loterie
des démarrages (un démarrage sur deux lève une puce muette). Toute comparaison « avant/après » doit
être faite **à état égal** — c'est le script `build/bissect_1mhz.sh` qui rejoue les démarrages
jusqu'à obtenir un état B avant de mesurer.

**Autre cause, corrigée le même jour :** le garde-fou enchaînait sept actions `cc1101.set_*`, chacune
déclenchant sa propre reconfiguration (voir `set_frequency` dans le composant) — sept cycles toutes
les 20 s tant qu'aucune trame n'arrivait. Il ne se déclenchait jamais pendant les périodes saines, ce
qui l'a rendu invisible. Un seul `cc1101.reset` suffit.


## 02/10 — VALIDATION APRÈS CORRECTIF (30 minutes, à état de puce contrôlé)

Mesure de 14h37 à 15h07 (heure de Paris), binaire `d4b03646` : pilote local, **SPI 1 MHz**, garde-fou
corrigé (un seul `cc1101.reset`), pull-up 10 kΩ sur CS + 10 µF soudés par l'utilisateur.

- **86 trames décodées en 30 minutes** (la station émet toutes les 20 s ⇒ 90 attendues) ;
- **84 intervalles sur 85 à exactement 20,0 s**, le seul autre à 40 s ⇒ **98,8 % des émissions
  décodées** ;
- valeurs cohérentes : température 21,1-21,3 °C, humidité 57 %, vent 6-10 km/h, direction 278-279°,
  pluie 59,2 mm (stable), ID station 33995 ;
- **le garde-fou n'a pas déclenché une seule fois** : il ne se déclenche que sur silence, donc le
  flux n'a jamais été interrompu ;
- le seul intervalle raté coïncide avec un ré-armement où le registre `FSCAL2` (0x24) n'a pas pris du
  premier coup (`ECRITURE NON PRISE`, reprise au 2e essai, calibration `FSCAL1=0x19` valide derrière).
  Reste à gratter ~1 %, côté lien SPI, pas côté code.

**Rappel de la méthode, sans laquelle cette mesure ne vaut rien :** la validation n'a été lancée
qu'après obtention d'un **état B** (puce qui répond) — un démarrage sur deux lève une puce muette
sur ce montage, et une fenêtre de 40 minutes tombée en état A avait déjà donné « 0 trame » sans rien
dire du correctif (`build/valider_etat_b.sh`).
