# Récepteur Vevor 7-en-1 868 MHz — ESP32-C3 SuperMini + CC1101 (ESPHome)

Récepteur ESPHome qui **décode** les trames 868 MHz d'une station Vevor 7-en-1 (réf. YT60309,
famille Fujian Youtong) et publie température, humidité, vent (vitesse/rafale/direction), pluie,
UV, luminosité et état de pile — en rejetant les trames invalides (checksum, compteur, plages
physiques).

**Statut : fonctionnel et vérifié** (01/10/2026) — trames décodées avec checksum et compteur TX
validés, **cadence 20,0 s pile**, valeurs plausibles, **accord champ par champ entre le firmware C++
et un décodeur Python indépendant**, et recoupement avec un second récepteur.

> Correction importante : une première validation annonçait « 60 trames en 10 min » ; c'était
> **30 mesures publiées deux fois** (recollage appliqué à tort, voir le piège n° 5). Le défaut est
> corrigé et couvert par les tests hors matériel. Détail et preuves : `state/DONE.md` et `evidence/`.

## Fichiers

| Chemin | Rôle |
|---|---|
| `esphome/vevor-7in1.yaml` | firmware de production (config ESPHome complète) |
| `esphome/components/vevor_7in1/` | composant C++ : écoute `remote_receiver`, impulsions → trame |
| `esphome/includes/vevor_protocol.h` | protocole (durées → bits → octets → valeurs), **testable hors matériel** |
| `esphome/secrets.yaml.example` | modèle à copier en `esphome/secrets.yaml` (non versionné) |
| `tests/` | 377 vérifications hors carte (nominal, polarité inversée, capture tronquée, gigue, biais, bruit, recollage, porte de plausibilité) |
| `tools/` | build, flash, capture de logs, évaluation, balayage de fréquence, synthèse de fenêtre, comparaison A/B |
| `evidence/` | rapports JSON versionnés : résultat d'une fenêtre, comparaison témoin/nous (voir `evidence/README.md`) |
| `requirements.txt` | dépendances de la machine qui pilote la carte (ESPHome, aioesphomeapi) |
| `references/PROTOCOL.md` | description du protocole ; `references/vevor_7in1.c` : source rtl_433 (GPL-2.0) |
| `state/PROGRESS.md` | journal d'itérations complet (ce qui a marché, ce qui a échoué, pourquoi) |
| `state/DONE.md` | état final, preuves, suites |

## Câblage

### Liaisons (c'est le montage qui fonctionne)

| ESP32-C3 SuperMini | CC1101 (module) | Signal |
|---|---|---|
| 3V3 | VCC | alim 3,3 V (**jamais 5 V**) |
| GND | GND | masse |
| GPIO6 | MOSI | SPI |
| GPIO4 | SCLK | SPI |
| GPIO5 | MISO | SPI |
| GPIO7 | CSN | chip select |
| GPIO3 | GDO0 | flux démodulé, consommé par `remote_receiver` |
| — | GDO2 | non connecté |

Antenne : l'antenne spirale fournie suffit à moins de 15 m. Pour de la portée, un brin λ/4
(≈ 8,6 cm pour 868 MHz) soudé sur ANT fonctionne nettement mieux.

### Résistance et condensateur — ce qui est SOUDÉ (02/10/2026)

Symptôme traité : la puce **perdait des écritures de registres de façon intermittente** — un registre
relu à sa **valeur d'usine** (`MDMCFG4` écrit `0xC8` relu `0x8C`, `MDMCFG3` écrit `0xC0` relu
`0x22`), donc une puce jamais configurée qui ne démodulait rien, à aucune fréquence. Les lectures,
elles, restaient fiables : le défaut était bien dans le LIEN, pas dans la puce. Après ces deux
composants, le contrôle embarqué est passé de « 1 registre définitivement non pris » à **« 0 registre
définitivement non pris » sur quatre cycles d'affilée**.

- **Résistance 10 kΩ** entre **CSN (GPIO7)** et **3,3 V**, soudée au plus près de la broche CSN du
  module. Pourquoi : au reset, les GPIO de l'ESP32-C3 sont en **haute impédance** (Table 2-1 du
  datasheet Espressif : IE, sans WPU) — sans pull-up, la ligne CS flotte pendant tout le démarrage,
  la puce peut y voir des sélections parasites et partir dans l'état indéterminé que décrit la
  datasheet (§4.9). 4,7 à 10 kΩ convient ; 10 kΩ est la valeur de la carte de référence ESP32-C3 +
  CC1101. **L'option YAML `cs_pin: mode: {pullup: true}` ne remplace pas cette résistance** : elle
  n'est appliquée qu'au `setup()` de la broche, donc après la fenêtre de démarrage.
- **Condensateur 10 µF** entre **VCC et GND du module** (découplage des appels de courant).

### Recommandé, pas encore monté

- **100 nF** céramique au plus près de la broche VCC du module — c'est lui qui agit sur les fronts
  rapides ; à associer au 10 µF, pas à mettre à la place.
- **Alimentation du module séparée** de la broche 3V3 du SuperMini : LDO 3,3 V dédié (≥ 300 mA)
  alimenté en 5 V, **masse commune obligatoire** (une masse flottante est pire que le défaut). Les
  clones de SuperMini plafonnent autour de 250 mA et leur rail s'effondre sous les pics Wi-Fi.
- **22 Ω en série sur SCLK** (et éventuellement MOSI/CS) si les fils restent longs.
- **Ne rien ajouter sur le quartz** : quartz et capacités de charge sont déjà dans le module, y
  toucher dérègle la fréquence. Rien non plus sur le chemin RF entre la puce et l'antenne.
- Vérifier que **DCOUPL n'est pas relié au 3,3 V** (erreur de schéma relevée par TI). Sur un module
  il n'est normalement pas accessible : à contrôler sur une carte à puce nue.
- **Ne jamais alimenter en 5 V**, et ne jamais déclarer un second périphérique SPI sur le bus de la
  puce.

### Couper l'alimentation du module par un transistor (piste, NON montée)

Sur ce montage, **un démarrage sur deux lève une puce muette** (`Chip ID: 0xFFFF`, toutes les
lectures SPI à 0xFF) : elle n'est alors jamais configurée et reste en IDLE. Un reset logiciel ne la
récupère pas (trois tentatives, trois échecs) ; une **vraie coupure d'alimentation**, si. Piloter
l'alimentation du module depuis un GPIO donnerait donc au firmware le seul remède qui fonctionne —
et le cycle serait immédiat, au lieu des dix minutes que met la reprise actuelle.

```
        3,3 V ──┬───────────┬────────────┬──── source du P-MOSFET
                │           │            │
            [10 kΩ]      [100 nF]     [10 µF]        (10 kΩ = grille tirée au 3,3 V ⇒ éteint)
                │           │            │
                │           └────────────┴──── drain ⇒ VCC du module CC1101
                │
   GPIO libre ──[1 kΩ]── grille du P-MOSFET
```

- **P-MOSFET à niveau logique** en série sur le VCC du module (ex. AO3401, IRLML6402) : source au
  3,3 V, drain vers le module. Grille tirée au 3,3 V par **10 kΩ** (module **éteint** par défaut au
  démarrage, donc puce propre au boot) et pilotée par un **GPIO libre** à travers **1 kΩ**.
  GPIO à l'état **bas = module alimenté** ; laisser le GPIO en haute impédance = module éteint.
- **Vérifier que le transistor conduit à Vgs = −3,3 V** : un MOSFET non « logic level » ne s'ouvre
  pas à cette tension. Prendre un modèle dont Vgs(th) est inférieur à 1,5 V.
- Garder le **10 µF** (et le 100 nF) **côté module**, c'est-à-dire après le transistor.
- **Variante plus simple mais moins propre** : commuter la **masse** du module (N-MOSFET ou NPN
  2N2222, grille/base pilotée par le GPIO à travers 1 kΩ). Dans ce cas les lignes SPI viennent
  piloter une puce non alimentée : ajouter **100 Ω en série sur SCLK / MOSI / CS** pour limiter le
  courant dans les diodes de protection.
- Côté firmware : une sortie GPIO, un cycle **éteint ≥ 300 ms puis rallumé**, puis ré-initialisation
  du composant radio. La datasheet demande une rampe de 0 à 1,8 V en ≤ 5 ms et une coupure d'au
  moins 1 ms — un cycle de quelques centaines de millisecondes les respecte largement.

## Mise en route

```bash
# 1. Secrets (une seule fois) — le fichier n'est jamais versionné
cp esphome/secrets.yaml.example esphome/secrets.yaml && $EDITOR esphome/secrets.yaml

# 2. Compiler
tools/build.sh

# 3. Flasher — USB la première fois, puis OTA par IP
#    Un ESP32-C3 flashé en USB apparaît ici en /dev/ttyACM0 (USB-Serial-JTAG du C3).
#    /dev/ttyUSB0 peut exister mais en nœud inutilisable (c--------- ) : ne pas le viser par défaut.
tools/flash.sh /dev/ttyACM0
tools/flash.sh 172.16.0.205

# 4. Capturer les logs de l'ESP32 (API native, port 6053 — pas de navigateur nécessaire)
#    Les outils qui ouvrent l'API tournent avec le Python du projet (.venv), où aioesphomeapi est installé.
.venv/bin/python tools/capture_logs.py --host 172.16.0.205 --seconds 120 \
    --out logs/capture_$(date +%Y%m%d_%H%M%S).log

# 5. Évaluer les trames captées (décodeur Python indépendant + critères de validité)
tools/eval_frames.py logs/capture_*.log --json logs/rapport.json

# 6. Chercher la station : balayage de fréquence SANS reflasher
.venv/bin/python tools/scan_freq.py --host 172.16.0.205 --list
.venv/bin/python tools/scan_freq.py --host 172.16.0.205 --start 867.8 --stop 868.6 --step 0.05 --dwell 25
```

## Les sept pièges de ce montage (mesurés, pas supposés)

1. **Le CC1101 doit rester le SEUL périphérique du bus SPI.** Déclarer un second périphérique SPI
   dans le YAML — même avec une broche CS **libre et non câblée** — suffit à rendre la puce muette :
   0 capture, 0 trame, sans aucune erreur. Mesuré en alternance avec un firmware de référence sur
   la même carte, dans les mêmes fenêtres d'émission : 0 trame/60 s avec, 5 trames/60 s sans.
   C'est ce qui a coûté le plus cher à ce projet (une instrumentation de diagnostic l'a causé) :
   **instrumenter la puce depuis le même firmware coûte la réception.**
2. **La station émet en CONTINU** — une rafale toutes les 20 s, jour et nuit (confirmé par
   l'utilisateur). Un « 0 trame » n'est donc **jamais** un silence de la station : c'est le
   récepteur. Mais un « 0 trame » ne prouve rien s'il n'y a pas, dans la **même fenêtre**, un
   récepteur de référence qui décode — un démarrage sur deux lève la puce sourde (piège n° 7), et
   une fenêtre vide peut donc aussi bien être une carte muette qu'une absence d'émission. Cette
   leçon vient d'une erreur corrigée : les « phases de silence » de la station (fenêtres
   11:36→12:36 et 13:53→14:53 le 01/10) étaient en réalité des **cartes sourdes**. `tools/ab_cycle.py`
   alterne deux firmwares (flash d'un binaire figé → attente → capture → ligne JSONL) pour comparer
   à conditions égales dans le temps.
3. **Pas de `gdo0_pin` dans le bloc `cc1101`** quand `remote_receiver` consomme la même broche :
   le composant planifie un `pin_mode(INPUT)` différé qui casse la voie RMT.
4. **`ota: encryption: {}`** fait hériter la clé API comme clé OTA (pas de mot de passe séparé à
   gérer). À l'inverse, pour reprendre la main sur une carte qui tourne un firmware tiers, il faut
   un YAML d'appoint **sans** `encryption:` sous `ota:` (`esphome/flash-plain.yaml`) + le binaire
   déjà compilé en `--file`.
5. **Ne recoller que des MORCEAUX de rafale, jamais une rafale entière.** Le RMT du C3 livre parfois
   une rafale en deux morceaux (96 + 82 impulsions) et il faut les recoller en fusionnant les
   impulsions de même signe à la soudure. Mais appliquer ce recollage à **toute** capture fait relire
   la rafale PRÉCÉDENTE : mesuré le 01/10, la version fautive publiait **60 trames pour 30 mesures**
   (chaque compteur TX exactement deux fois, à 20 s d'écart, hors de la fenêtre anti-doublon de 5 s).
   D'où la règle : décoder d'abord la capture SEULE, ne recoller que si elle est trop courte pour
   porter une rafale (`MAX_FRAGMENT_TIMINGS`). Éprouvé par les tests `_coupe_*`.

6. **Une trame bien formée n'est pas une trame JUSTE.** Mesuré le 01/10 sur une fenêtre d'une
   heure : sur 181 trames valides (en-tête + checksum + compteur tous bons, cadence 20,0 s), **2
   étaient fausses** — le décalage d'un bit à l'extraction double tous les octets de valeur, et
   elles annonçaient 178,2 mm de pluie au lieu de 59,2 et une direction de 779°. Le checksum d'une
   trame à décalage de bits peut donc passer. D'où deux règles : (a) une **porte de plausibilité**
   dans le firmware (`vevor_protocol.h`) refuse ce qui est physiquement impossible — direction
   > 359°, humidité > 100 %, vent > 180 km/h, UV > 16 — et le composant les compte dans ses rejets ;
   (b) le **recollage de morceaux** n'est pas innocent : il ne s'applique qu'aux captures trop
   courtes pour porter une rafale, jamais à une rafale complète.

7. **Un démarrage sur deux peut se lever la puce absente du bus SPI** — et rien ne le signale, sauf
   un `captures=0` silencieux. Mesuré le 01/10 sur 6 cycles flash → mesure, même binaire :
   sourd / sain / sourd / sain / sourd / sain. Dans les démarrages sourds, le composant relit
   `Chip ID: 0xFFFF` (toutes les lectures SPI à `0xFF`) : la puce ne répond pas, n'est jamais
   configurée, reste en IDLE d'usine et ne produit rien sur GDO0. Le ré-armement à chaud
   (`reset` + réglages + `begin_rx`) **ne la récupère pas** (3 tentatives, 3 échecs) ; **le
   redémarrage, oui** — l'état de la puce s'inverse à chaque boot, car la puce garde ses registres
   pendant que l'ESP32 redémarre. D'où la surveillance embarquée (`esphome/vevor-7in1.yaml`,
   `interval: 20s`) : état radio journalisé toutes les 20 s (`SANTE radio=… trames=… captures=…`),
   30 tentatives d'initialisation douces (30 × 20 s = 10 min) tant qu'aucune **nouvelle trame** n'est
   publiée, puis **redémarrage automatique**. Le redémarrage part sur le **seul silence de trames**,
   sans consulter `is_failed()` : comme la station émet en continu, tout silence prolongé est une
   panne du récepteur, quelle qu'en soit la cause. Dix redémarrages rapprochés (un par cycle de
   ~10 min), puis repli à un redémarrage toutes les 15 min. Ces lignes de diagnostic partaient
   auparavant avant que l'API soit joignable : c'est ce qui a rendu le défaut si long à voir.

## Auto-évaluation

`tools/eval_frames.py` réimplémente le décodage en Python, indépendamment du C++ du firmware, et
**compare trame par trame** ses valeurs à celles publiées par le firmware. Le verdict `PASS` exige
simultanément :

- au moins N trames valides (`--min-valid`, 10 par défaut) ;
- des valeurs dans les plages physiques **et** une cohérence lux/UV (lux nul avec un UV non nul,
  ou lux hors de portée de l'UV annoncé) ;
- une avance du compteur TX conforme au temps écoulé (~1,95 tick/s ; un écart nul = rafale livrée
  deux fois par le RMT ; un écart multiple = rafales manquées) ;
- une cadence de ~20 s sur les intervalles significatifs ;
- **l'accord champ par champ avec le firmware C++** sur chaque trame.

Un rapport qui contient un constat (séquence incohérente, valeurs implausibles, désaccord avec le
C++) ne peut donc plus conclure `PASS` : la liste des motifs de refus est dans le rapport JSON.
`tools/summarize_window.py` complète l'analyse sur une fenêtre longue (cadence médiane/min/max,
trous, rejets, émissions par tranche de 10 min, plages de valeurs). Les rapports sont conservés
versionnés dans `evidence/` pour que les affirmations restent vérifiables après un `git clone`.

## Accès USB depuis un conteneur LXC (Proxmox)

Pour flasher en USB depuis un conteneur, passer le port série de l'hôte dans le LXC
(`/etc/pve/lxc/<id>.conf`, puis redémarrer le conteneur). L'ESP32-C3 se présente en
**USB-Serial-JTAG**, donc en **`/dev/ttyACM0`** (périphérique de caractères, majeur **166**) — et
**non** en `/dev/ttyUSB0` (majeur 188), qui peut exister sans être utilisable (`c---------`) :

```
lxc.mount.entry: /dev/ttyACM0 dev/ttyACM0 none bind,optional,create=file
lxc.cgroup2.devices.allow: c 166:* rwm
```

Vérifier ensuite `ls -l /dev/ttyACM0` (le nœud doit être `crw-rw----` et accessible) et
l'appartenance au groupe `dialout` (`usermod -aG dialout <utilisateur>`). Sans cela, compilation,
OTA et logs fonctionnent quand même, mais le tout premier flash doit se faire ailleurs
(web.esphome.io ou l'add-on ESPHome).

## Licence et attributions

- **GPL-2.0** (voir `LICENSE`).
- Le format des trames vient de **rtl_433** (`src/devices/vevor_7in1.c`, GPL-2.0) ; une copie de
  référence est conservée dans `references/vevor_7in1.c`. Le décodeur de ce dépôt en dérive d'où
  la licence GPL-2.0.
- Le projet **`WizardPC/esphome-vevor-7in1`** (même protocole, architecture asynchrone) a servi de
  point de comparaison — paramètres radio mesurés et pièges de protocole —, jamais de base de code.
