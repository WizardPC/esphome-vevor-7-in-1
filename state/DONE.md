# État final — récepteur Vevor 7-en-1 868 MHz (ESP32-C3 SuperMini + CC1101, ESPHome)

**Statut : objectif de `MISSION.md` atteint**, puis **corrigé et rendu auto-réparant** après deux
séries de vérifications indépendantes le 01/10/2026. Ce document dit ce qui est prouvé, et par quoi
— y compris ce que j'ai affirmé à tort en cours de route.

## 1. Ce qui a été corrigé, et sur quelle preuve

**a) Comptage de trames doublé.** La première validation annonçait « 60 trames en 10 min » : c'étaient
**30 mesures publiées deux fois** (chaque compteur TX exactement 2×). Le recollage inter-captures
s'appliquait à *toute* capture, y compris complète, et faisait relire la rafale PRÉCÉDENTE.
Corrigé : décodage direct d'abord, recollage **uniquement entre deux morceaux** de rafale
(`MAX_FRAGMENT_TIMINGS = 160` ; une rafale utile en fait 176 à 184).

**b) Instrumentation SPI supprimée.** `sample_radio_()` était appelée dans `loop()` alors que son
commentaire la disait désactivée, et comme `SPIDelegate::is_ready()` renvoie `true` même sans broche
CS, elle publiait toutes les 10 s un faux `RSSI=-74.0 dBm (brut 0x00)`, `SLEEP`, `0 MHz`. Tout accès
SPI depuis ce composant a été supprimé (composant, schéma, YAML).

**c) Filet de tests et outillage.** Ancrage externe rtl_433 complété (vent, rafale, pluie, lux
calculés à la main depuis la source), période et polarité désormais **assertées**, recollage couvert
(**204 vérifications, 0 échec**). Contre-épreuve : la même erreur d'échelle de vent injectée dans
l'encodeur Python **et** dans le C++ fait échouer la suite. `eval_frames.py` compare **trame par
trame** le C++ et un décodeur Python indépendant ; `capture_logs.py` **écrase désormais** son fichier
de sortie au lieu d'y ajouter (le mode AJOUT avait fait relire une fenêtre vidée comme si c'était la
nouvelle — voir §3) ; `summarize_window.py` ne voyait aucune trame à cause des séquences ANSI.

**d) Trames fausses mais bien formées.** Sur une fenêtre d'une heure, **2 trames sur 181** passaient
en-tête + checksum + compteur et étaient pourtant fausses : décalage d'un bit à l'extraction, qui
double les octets de valeur (direction 779°, pluie 178,2 mm au lieu de 59,2). Ajout d'une **porte de
plausibilité** dans `vevor_protocol.h` (direction > 359°, humidité > 100 %, température hors −40..60,
vent/rafale > 180 km/h, UV hors 0..16) → refus motivé, compté dans les rejets. Le test
`test_plausibility` embarque **les deux trames fautives réelles**.

## 2. Le défaut principal : un démarrage sur deux lève la puce absente du bus SPI

Mesuré sur **6 cycles** flash → 5 min, avec le même binaire : **sourd / sain / sourd / sain / sourd /
sain** (0 trame contre 15). Dans les démarrages sourds, le composant relit `Chip ID: 0xFFFF` — **toutes
les lectures SPI à 0xFF** : la puce ne répond pas sur le bus, n'est donc jamais configurée, reste en
IDLE et ne produit rien sur GDO0.

- **Ré-armement à chaud** (`reset` + réglages + `begin_rx`) : **inefficace** (répété 9 fois, 9 échecs).
- **Redémarrage** : **récupère** — l'état de la puce s'inverse d'un démarrage à l'autre, car elle
  garde ses registres pendant que l'ESP32 redémarre.
- La littérature TI décrit le même symptôme (« CC1101 not responding to SPI » : des 1 partout, la
  puce finit par répondre si on insiste, quartz qui démarre tardivement) ; le composant ESPHome, lui,
  lit `PARTNUM`/`VERSION` **une seule fois** puis se déclare en échec — il amplifie donc une condition
  matérielle marginale en une session entièrement sourde.

**Correctif embarqué** (`esphome/vevor-7in1.yaml`) : état radio journalisé toutes les 20 s
(`SANTE radio=ok|EN ECHEC trames=N captures=N`), 9 tentatives d'initialisation sur 3 min, puis
**redémarrage automatique** — la station émettant **en continu toutes les 20 s, jour et nuit**
(confirmé par l'utilisateur), tout silence prolongé est une panne du récepteur, sans ambiguïté. Après
4 redémarrages rapprochés, la carte continue d'essayer à raison d'un par 30 min : elle ne renonce
jamais, sans passer son temps à redémarrer. Bouton « Redémarrer la carte » ajouté.

## 3. Ce que j'ai affirmé à tort (et la règle qui en découle)

- **« La station émet par bouffées, avec des phases de silence »** : FAUX. Les fenêtres vides de
  11:36→12:36 et 13:53→14:53 étaient des **carte sourde**, pas des silences de la station (qui émet
  en continu). Aggravant : la sonde du 13:53 comptait les trames d'un fichier ouvert en AJOUT (4
  trames laissées par la sonde de 12:50) et a déclaré « station active » sur une carte déjà sourde.
- **« Le binaire d'avant revue est muet parce qu'il touche au SPI »** : non concluant. Mesurer une
  seule fenêtre par binaire ne vaut rien quand un démarrage sur deux est sourd — l'appariement
  témoin/nous n'est fiable que sur **plusieurs tours** (l'effet « second périphérique SPI » des
  mesures du matin reste établi, lui, par 6 tours alternés).
- **Règle retenue** : ne jamais juger l'état d'un récepteur sur un seul démarrage ; soit le comparer
  dans la MÊME fenêtre d'émission sur plusieurs tours, soit lire l'état embarqué (`SANTE radio=`).

## 4. Ce qui est vérifié aujourd'hui, et par quoi

| Preuve | Résultat |
|---|---|
| Fenêtre d'une heure, garde-fou actif (`evidence/rapport_fenetre_1h.json`) | **180 trames, 180 valides**, 0 échec de checksum, 0 échec de compteur, **verdict `PASS`** |
| Accord C++ / décodeur Python indépendant | champ par champ sur les 180 trames, 0 désaccord |
| Cadence et continuité | 179/179 intervalles entre 15 et 25 s (médiane 20,0 s), aucun trou > 30 s |
| Compteur TX | avance conforme au temps écoulé : 0 doublon, 0 rafale manquée |
| Plausibilité | pluie monotone (59,2 → 59,2 mm), aucune valeur impossible publiée |
| Décodeur hors matériel | 204 vérifications, 0 échec, dont l'ancrage rtl_433 et le recollage |
| Auto-guérison | essai 1 (démarrage sourd) : **0 trame** puis redémarrage automatique à 3 min, encore sourd, second redémarrage, et **21 trames retrouvées sans intervention** ; essai 2 (démarrage sain) : 15 puis 36 trames, cadence normale |

## 5. Fichiers

- Firmware : `esphome/vevor-7in1.yaml` (+ `components/vevor_7in1/`, `includes/vevor_protocol.h`).
- Preuves versionnées : `evidence/` — rapport de la fenêtre validée, rapport de la fenêtre **fautive**
  conservé à part (`rapport_fenetre_1h_decalage.json`), comparaison A/B (`ab_cycle.jsonl`).
- Outils : `tools/` (capture, évaluation, synthèse, balayage, A/B) et `build/` (scénarios de mesure).
- Journal complet des itérations : `state/PROGRESS.md`.

## 6. Suites ouvertes (dites franchement)

1. **La panne de fin de journée n'est PAS résolue et n'est plus logicielle.** Mesuré le 01/10 au
   soir : deux états alternent, aucun ne reçoit — **A** `Chip ID: 0xFFFF` (puce absente du bus SPI,
   `radio EN ECHEC`) et **B** `Chip ID: 0x0014` mais `PLL lock failed, retrying calibration`
   (`radio=ok`, des `captures`, **0 trame**). Ce qui a été testé sans succès : ré-armement à chaud
   (9 tentatives), **coupure d'alimentation 5 s**, **coupure 30 s** (la durée ne change rien),
   redémarrage à chaud (renvoie en A). Hypothèse soutenue par les mesures : le **quartz 26 MHz du
   module** ne repart pas de façon fiable après une perturbation d'alimentation, et le démarrage de
   l'ESP32-C3 suffit à la provoquer — quand le quartz survit (une heure entière à 180 trames cet
   après-midi), tout fonctionne. À contrôler sur place, dans l'ordre : liaisons SPI (fils Dupont
    CLK/MOSI/MISO/CS + masse) à refaire en soudé, découplage du module (100 nF + 10 µF), tenue de son
   alimentation pendant le démarrage de l'ESP32, remplacement du module. Le garde-fou logiciel reste
   utile (il récupère quand un démarrage atteint l'état sain) mais il ne fabrique pas l'état sain.
2. **Duplication d'outillage** : `key_from_yaml()` existe encore en plusieurs copies (sans bug connu
   après vérification), et `maybe_await` en trois exemplaires — à factoriser dans `tools/_common.py`.
3. Les variantes de diagnostic `vevor-7in1-v1/v2/v3.yaml` ont été **supprimées** (obsolètes, et v1/v3
   contenaient encore le second périphérique SPI — mauvais exemple à laisser dans le dépôt).
