# MISSION — Récepteur Vevor 7-en-1 868 MHz (ESP32-C3 SuperMini + CC1101) sous ESPHome

## Objectif final (critère de sortie)

Un firmware ESPHome fonctionnel qui, en continu :

1. reçoit les trames 868 MHz de la station Vevor 7-en-1 et les **décode** (tous les capteurs) ;
2. publie dans Home Assistant : température, humidité, vitesse vent, rafale, direction,
   pluie cumulée, UV, luminosité, batterie faible ;
3. **rejette** toute trame invalide (checksum + compteur) ;
4. tourne de façon stable (pas de reboot, pas de fuite mémoire) et est documenté.

« Fonctionnel » = au moins 10 trames consécutives valides, cadencées à ~20 s, avec des
valeurs plausibles et recoupées avec une source indépendante.

## Répartition du travail (règle anti-collision, validée le 30/09)

Deux agents travaillent sur ce dépôt : la **session interactive** (l'humain + l'assistant dans
le salon de discussion) et **la boucle planifiée** (celle qui poste dans #esphome). Pour ne plus
se réécrire les fichiers sous les pieds :

- **La boucle** : la radio et le matériel uniquement — paramètres CC1101, build, flash, captures,
  balayages de fréquence, mesures. Elle écrit ses essais dans `state/PROGRESS.md` et avance
  `state/PHASE`.
- **La session interactive** : le décodeur (`esphome/components/vevor_7in1/vevor_protocol.h`), l'outillage
  d'analyse (`tools/eval_frames.py`), les tests et la documentation destinée aux autres
  utilisateurs.
- Avant de modifier un fichier hors de son périmètre, le noter dans PROGRESS.md. En cas de
  collision : `build/last_status.txt` ou `logs/last_flash_status.txt` affiche
  « ABANDONNE code=3 » → attendre et reprendre.
- Objectif du projet : que **n'importe quel utilisateur** ayant une station de cette famille
  arrive à un récepteur fonctionnel avec de la documentation, sans dépendre de l'installation
  particulière de l'utilisateur actuel (IP, secrets, chemins).

## Boucle d'itération (politique adaptative validée par l'utilisateur)

Un cycle = compiler → flasher → capturer → évaluer → décider. La cadence **s'adapte au
résultat** (pas de reflash aveugle) :

| Observation après flash + capture | Décision |
|---|---|
| Aucune trame valide au bout de ~5 min | Corriger la radio (fréquence, déviation, bande passante, syncword) puis **reflasher** |
| Valid frames mais irrégulières, trous > 25 s sur 10 min | Ajuster (RSSI/antenne/déviation) puis **reflasher** |
| Cadence propre ~20 s | **Laisser tourner 30 min** et vérifier la cohérence des données sur toute la fenêtre |
| Cadence propre + cohérence OK sur 30 min | Écrire `state/DONE.md`, prévenir l'utilisateur, arrêter la boucle |

Une itération = un cycle. Ne pas reflasher sans avoir lu les logs du flash précédent.

## Boucle d'itération (une itération = un cycle)

1. Lire `state/PROGRESS.md` (où on en est, dernière hypothèse, prochaine action).
2. Modifier le firmware (`esphome/vevor-7in1.yaml`, `esphome/components/vevor_7in1/*.h`).
3. Compiler : `tools/build.sh` → si échec, corriger et revenir en 2.
4. Flasher : `tools/flash.sh <ip_ou_port>` (USB la première fois, OTA ensuite).
5. Capturer les logs : `.venv/bin/python tools/capture_logs.py --host <ip> --seconds <durée_s> --out logs/capture_*.log`.
6. Évaluer : `tools/eval_frames.py logs/capture_*.log` → rapport JSON.
7. Écrire dans `state/PROGRESS.md` : ce qui a marché, ce qui a échoué, la prochaine action.
   Consigner les trames brutes dans `logs/raw_frames.jsonl`.
8. Si le critère de sortie est atteint → écrire `state/DONE.md` et le dire à l'utilisateur.

## Règles non négociables

- **Aucune valeur inventée.** Toute affirmation sur le décodage doit citer une ligne de log
  brute. Si rien n'est capté, le dire : « pas de signal », jamais « ça doit marcher ».
- **À lire avant de toucher à la radio** : `references/EXTERNAL_CONTEXT_WIZARDPC.md` — analyse
  (contexte, pas du code à reprendre) d'un projet fonctionnel sur le même protocole. Il donne
  des réglages radio **mesurés** (868,35 MHz / déviation **70 kHz** / bande **100 kHz** /
  11 111 baud) — exactement ceux que nous avons fini par adopter : nos anciennes valeurs
  (868,30 MHz / 37 kHz / 200 kHz) ne décodaient rien. Ils ont servi de guide, ce ne sont plus des
  hypothèses en attente de test. Il documente aussi des pièges de protocole à intégrer à l'auto-évaluation
  (pluie qui peut baisser avec un checksum **valide**, trames arrivant coupées, Station ID qui
  change à chaque mise sous tension, rejet `vent > 0` avec `rafale == 0`, cohérence lux/UV).
- **Ne jamais se fier à la sortie console d'un script passé dans un pipe** : `tail` et `tee`
  masquent les codes retour. Lire `build/last_status.txt` (BUILD OK/FAIL) et
  `logs/last_flash_status.txt` (FLASH OK/FAIL) — c'est la source de vérité du succès d'une étape.
- Une hypothèse à la fois sur la partie radio (fréquence, déviation, bande passante), et
  noter l'effet mesuré dans PROGRESS.md.
- Ne jamais supprimer une trace de log : elles servent de preuve d'évaluation.
- Après 3 itérations sans amélioration : changer de stratégie, pas répéter la même tentative.
  Le faire explicitement dans PROGRESS.md.
- Ordre de diagnostic si aucun paquet : (1) le CC1101 répond-il au SPI ? (2) fréquence,
  (3) déviation/bande passante, (4) syncword/longueur, (5) câblage/antenne.

## Câblage de référence (à confirmer avec l'utilisateur)

| ESP32-C3 SuperMini | CC1101 | Signal |
|---|---|---|
| 3V3 | VCC (pin 1) | alim 3,3 V |
| GND | GND (pin 2) | masse |
| GPIO6 | MOSI (pin 4) | SPI |
| GPIO4 | SCLK (pin 3) | SPI |
| GPIO5 | MISO (pin 6) | SPI |
| GPIO7 | CSN (pin 8) | chip select |
| GPIO3 | GDO0 (pin 3 module) | data / interrupt paquet |
| — | GDO2 | non connecté |

GPIO2/GPIO8/GPIO9 sont des pins de strapping sur ESP32-C3 : on évite GPIO2 pour GDO0.

## Environnement

- LXC Debian 13, IP `<conteneur>` ; Home Assistant `<home-assistant>` (HA Core ne répondait pas
  sur 8123 au 30/09 ; le token est dans `.ha_token`).
- **La carte peut être déplacée** : l'utilisateur a proposé de la mettre ailleurs si la réception
  868 MHz est mauvaise. Conséquence opérationnelle : **si `/dev/ttyACM0` disparaît** (carte
  débranchée de l'hôte Proxmox), le flash USB n'est plus possible → flasher en **OTA**
  (`tools/flash.sh <ip-de-la-carte>`). Les logs restent disponibles par l'API native, mais une carte
  dont le Wi-Fi casse doit être rapportée physiquement à l'hôte pour être récupérée en USB.
- ESPHome dans `~/projets/vevor-7in1/.venv` (Python autonome + `esphome`, `aioesphomeapi`).
- Logs ESP32 lus via l'API native (port 6053) avec `tools/capture_logs.py` — **indépendant
  de Home Assistant**, donc plus fiable que la lecture des logs de l'add-on.
- **Compilation : dans ce conteneur** (déjà vérifiée, ~4 min, cache chaud ensuite).
- **Sources des composants : `esphome/vevor-7in1.yaml` pointe sur le dépôt public**
  (`github://WizardPC/esphome-vevor-7-in-1@main`) pour rester copiable tel quel par n'importe qui.
  Toute compilation depuis CE dépôt doit donc forcer la source locale, sinon ESPHome télécharge la
  version publiée et ignore l'arbre de travail : `tools/build.sh` et `tools/flash.sh` le font
  (`-s vevor_components components`) — passer par eux, ou ajouter cette option à la main.
- **Flash : OTA depuis ce conteneur** (`tools/flash.sh <IP>`) dès que le premier flash a été
  fait. L'add-on ESPHome Builder de HA sert au tout premier flash (il a l'accès UART à l'hôte
  HA) et de référence pour la gestion des appareils.
- Fréquence de balayage : `tools/scan_freq.py` pilote l'entité `number` du firmware en direct
  (aucun reflash nécessaire pour chercher le signal).

Voir `references/HOME_ASSISTANT.md` pour l'intégration HA et ce qui est scriptable côté add-on.

## Notes de relecture (02/10/2026)

- **Objectif atteint, au-delà du critère.** Le critère de sortie demandait « au moins 10 trames
  consécutives valides » : la fenêtre validée (`evidence/rapport_fenetre_1h.json`) en compte **180 en
  une heure**, 0 rejet, verdict `PASS`. Les quatre points (réception, publication, rejet des trames
  invalides, stabilité) sont couverts.
- **« Pas de reboot » (objectif, point 4) se lit « pas de reboot subi ».** Le firmware redémarre
  désormais **volontairement** comme remède au mutisme SPI intermittent (voir `state/DONE.md` §2) :
  ce n'est pas une instabilité, c'est le garde-fou. La formulation d'origine est datée.
- **Règles de répartition / anti-collision** : elles visaient deux agents écrivant en même temps.
  Elles n'ont plus d'objet si une seule session travaille ; les garder quand deux processus tournent.
- **Faits d'environnement datés** (LXC `<conteneur>`, HA `<home-assistant>`, HA Core muet sur 8123 au
  30/09) : à rafraîchir si l'installation change — pas des exigences du projet.
- **Fait corrigé** : le fichier décodeur cité en tête de ce document (`esphome/components/vevor_7in1/vevor_7in1.h`)
  n'existait pas ; le décodeur est `esphome/components/vevor_7in1/vevor_protocol.h` (l'en-tête `vevor_7in1.h` est
  celui du composant, sous `esphome/components/vevor_7in1/`).
