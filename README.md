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
| `tests/` | 198 vérifications hors carte (nominal, polarité inversée, capture tronquée, gigue, biais, bruit, recollage) |
| `tools/` | build, flash, capture de logs, évaluation, balayage de fréquence, synthèse de fenêtre, comparaison A/B |
| `evidence/` | rapports JSON versionnés : résultat d'une fenêtre, comparaison témoin/nous (voir `evidence/README.md`) |
| `requirements.txt` | dépendances de la machine qui pilote la carte (ESPHome, aioesphomeapi) |
| `references/PROTOCOL.md` | description du protocole ; `references/vevor_7in1.c` : source rtl_433 (GPL-2.0) |
| `state/PROGRESS.md` | journal d'itérations complet (ce qui a marché, ce qui a échoué, pourquoi) |
| `state/DONE.md` | état final, preuves, suites |

## Câblage

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

## Mise en route

```bash
# 1. Secrets (une seule fois) — le fichier n'est jamais versionné
cp esphome/secrets.yaml.example esphome/secrets.yaml && $EDITOR esphome/secrets.yaml

# 2. Compiler
tools/build.sh

# 3. Flasher — USB la première fois, puis OTA par IP
tools/flash.sh /dev/ttyUSB0
tools/flash.sh 192.168.2.50

# 4. Capturer les logs de l'ESP32 (API native, port 6053 — pas de navigateur nécessaire)
tools/capture_logs.sh 192.168.2.50 120

# 5. Évaluer les trames captées (décodeur Python indépendant + critères de validité)
tools/eval_frames.py logs/capture_*.log --json logs/rapport.json

# 6. Chercher la station : balayage de fréquence SANS reflasher
tools/scan_freq.py --host 192.168.2.50 --list
tools/scan_freq.py --host 192.168.2.50 --start 867.8 --stop 868.6 --step 0.05 --dwell 25
```

## Les cinq pièges de ce montage (mesurés, pas supposés)

1. **Le CC1101 doit rester le SEUL périphérique du bus SPI.** Déclarer un second périphérique SPI
   dans le YAML — même avec une broche CS **libre et non câblée** — suffit à rendre la puce muette :
   0 capture, 0 trame, sans aucune erreur. Mesuré en alternance avec un firmware de référence sur
   la même carte, dans les mêmes fenêtres d'émission : 0 trame/60 s avec, 5 trames/60 s sans.
   C'est ce qui a coûté le plus cher à ce projet (une instrumentation de diagnostic l'a causé) :
   **instrumenter la puce depuis le même firmware coûte la réception.**
2. **La station émet par bouffées.** Un « 0 trame » ne prouve rien s'il n'y a pas, dans la **même
   fenêtre**, un récepteur de référence qui décode. `tools/ab_cycle.py` alterne deux firmwares
   (flash d'un binaire figé → attente → capture → ligne JSONL) pour comparer à conditions égales.
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
   pendant que l'ESP32 redémarre. D'où la surveillance embarquée : état radio journalisé chaque
   minute, ré-armement à 3 min, et **redémarrage automatique à 8 min — uniquement si la radio
   s'avoue en échec**, jamais pour une station simplement à l'arrêt. Ces lignes de diagnostic
   partaient auparavant avant que l'API soit joignable : c'est ce qui a rendu le défaut si long à
   voir.

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
(`/etc/pve/lxc/<id>.conf`, puis redémarrer le conteneur) :

```
lxc.mount.entry: /dev/ttyUSB0 dev/ttyUSB0 none bind,optional,create=file
lxc.cgroup2.devices.allow: c 188:* rwm
```

Vérifier ensuite `ls -l /dev/ttyUSB0` et l'appartenance au groupe `dialout`
(`usermod -aG dialout <utilisateur>`). Sans cela, compilation, OTA et logs fonctionnent quand
même, mais le tout premier flash doit se faire ailleurs (web.esphome.io ou l'add-on ESPHome).

## Licence et attributions

- **GPL-2.0** (voir `LICENSE`).
- Le format des trames vient de **rtl_433** (`src/devices/vevor_7in1.c`, GPL-2.0) ; une copie de
  référence est conservée dans `references/vevor_7in1.c`. Le décodeur de ce dépôt en dérive d'où
  la licence GPL-2.0.
- Le projet **`WizardPC/esphome-vevor-7in1`** (même protocole, architecture asynchrone) a servi de
  point de comparaison — paramètres radio mesurés et pièges de protocole —, jamais de base de code.
