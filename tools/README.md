# Outils — ce qui est actif, ce qui est un diagnostic conservé

Ce dossier mélange deux choses, et ce fichier sert à ne plus les confondre. Règle de fond : **aucun
outil n'est supprimé sans vérifier ses références** — la liste de « 13 outils morts » de la revue du
02/10 s'est révélée fausse au moins pour `dump_pulses.py`, qui est l'outil du bouton « Dump
impulsions » et qui a permis de trancher, le même jour, entre un flux propre et un bruit de
démodulateur. Effacer un outil parce qu'il n'est « pas cité dans le README » fait perdre la boîte à
outils de diagnostic du projet.

Pour vérifier qu'un outil est réellement inutilisé avant de le retirer :

```bash
# Références hors du dossier tools/ (hors journaux et revues)
grep -rn --exclude-dir=logs --exclude-dir=reviews --exclude-dir=.git \
     --exclude-dir=.esphome --exclude-dir=.venv "NOM_DU_FICHIER.py" .
```

## 1. Outils du flux courant

| Outil | Rôle |
|---|---|
| `build.sh` | compile le firmware (`BUILD OK` / `BUILD FAIL` dans un fichier) |
| `flash.sh` | téléverse en OTA (USB la première fois) |
| `run_tests.sh` | suite hors matériel (377 vérifications, aucune carte requise) |
| `capture_logs.py` | capture les journaux par l'API native (port 6053) ; `--append` pour ajouter |
| `eval_frames.py` | décodeur Python indépendant : verdict trame par trame contre le firmware |
| `summarize_window.py` | résumé d'une fenêtre **généré depuis son rapport** (`--rapport`), refuse de blanchir un FAIL |
| `read_state.py` | relevé des entités par l'API (captures, trames, fréquence…) |
| `press_button.py` | appuie sur un bouton du firmware (`--list-buttons` pour la liste) |
| `dump_pulses.py` | relève les durées brutes du bouton « Dump impulsions » — l'outil qui distingue un signal d'un bruit |
| `decoder_dump.py` | décode hors carte ces durées brutes (4 périodes × 2 polarités × 8 alignements) |
| `ab_cycle.py` | alterne plusieurs binaires figés dans des fenêtres interleavées (témoin / nous) |
| `_common.py` | socle commun : lecture de `api_key`, `maybe_await`, tables de variantes, écritures atomiques |

Scripts d'expérience associés, dans `build/` : `valider_etat_b.sh` (n'accepte de mesurer qu'en état B
de la puce), `bissect_1mhz.sh`, `loterie_etats.sh`, `experience_*.sh`.

## 2. Diagnostics conservés (historiques, mais fonctionnels)

Ils ont servi à établir les constats consignés dans `state/PROGRESS.md`, et resserviraient si un
symptôme revient. Rangés ici pour la lisibilité, pas parce qu'ils seraient cassés.

| Outil | Ce qu'il a servi à établir |
|---|---|
| `balayer_frequence.py`, `regler_frequence.py`, `scan_freq.py`, `sweep_summary.py`, `sweep_async.sh` | balayage de fréquence sans reflasher ; a écarté l'hypothèse d'un quartz décalé |
| `analyze_stream.py`, `analyze_noise.py`, `analyze_radio_log.py`, `gdo0_rate_vs_freq.py` | analyse du flux démodulé (mode porteuse), du bruit et du débit de la sonde |
| `scan_async.py`, `boot_probe.py`, `boot_dump.sh`, `count_probe.py`, `serial_log.py` | sondes de démarrage et de comptage |
| `witness_fetch.py`, `witness_probe.py`, `witness_summary.py` | récupération et analyse du projet de référence (contexte uniquement, jamais une base de code) |
| `verify_radio_config.py`, `net_scan.py`, `find_esp32.py`, `tcp_probe.py` | vérification de configuration, découverte de la carte et des ports |
| `fix_python_env.sh`, `loop_monitor.sh` | environnement Python du conteneur ; filtre d'empreinte de l'ancienne boucle planifiée (cron supprimé depuis) |
| `capture_logs.sh` | **remplacé** par `capture_logs.py` (l'API native, pas l'USB : la série tronque les lignes longues) |

## 3. Ce qu'un outil de ce dossier ne doit jamais faire

- écrire dans un secret, ni l'afficher (`esphome/secrets.yaml`, `.ha_token`) ;
- annoncer un succès sans mesure : « rien de mesuré » → **MESURE NULLE** et code 3 ; « mesuré, aucune
  trame » → code 0 ; échec technique → code 2 ;
- conclure sur une fenêtre sans avoir vérifié l'état de la puce : un démarrage sur deux lève une puce
  muette (`Chip ID: 0xFFFF`) sur ce montage — d'où `build/valider_etat_b.sh` ;
- être testé sur un journal fabriqué à la main : ESPHome colorise ses lignes, et un parseur qui ne
  détache pas les séquences ANSI annonce « aucune trame » sur une fenêtre qui en contient 181.
