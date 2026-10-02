# Revue de code — 2ᵉ tour, état consolidé au 02/10/2026

- **Dépôt** : `WizardPC/esphome-vevor-7-in-1`
- **Commit de référence** : `9693dbe` (« README : montage physique — résistance, condensateurs et transistor de coupure d'alimentation »), `main`, poussé.
- **Périmètre** : tout le dépôt — composant ESPHome (`esphome/components/vevor_7in1/`), pilote `cc1101` vendorié, protocole (`esphome/includes/vevor_protocol.h`), configuration (`esphome/vevor-7in1.yaml`), outillage (`tools/`, 27 `.py` + 8 `.sh`), tests hors matériel (`tests/`), preuves (`evidence/`), documentation (`README.md`, `MISSION.md`, `state/*`, `references/*`).
- **Méthode** : 7 sous-agents en deux vagues (périmètres disjoints) + **revérification de chaque conclusion critique par l'agent principal** (reproduction, pas confiance). Aucun accès matériel : ni flash, ni connexion à la carte `172.16.0.205`, aucun build ESPHome pendant les revues.
- **Rapports détaillés** (fichiers locaux, `reviews/` est dans `.gitignore`) : `reviews/round2/01-firmware-armature.md` (487 l.), `02-outillage-preuves.md` (679 l.), `03-documentation-cablage.md` (466 l.), `04-tests-preuves-chiffres.md` (300 l.).

---

## 1. Faits mesurés (reproduits par l'agent principal, pas rapportés de confiance)

| Fait | Valeur | Établi par |
|---|---|---|
| Suite hors matériel | **377 vérifications, 0 échec** | `bash tools/run_tests.sh`, exécuté par l'agent principal |
| Firmware | **BUILD OK**, 966 400 octets | `tools/build.sh`, binaire `firmware.ota.bin` |
| Configuration ESPHome | `INFO Configuration is valid!`, exit 0 | `.venv/bin/esphome config esphome/vevor-7in1.yaml` |
| Fuite de secrets | **aucune** : ni SSID, ni mot de passe Wi-Fi, ni clé API dans l'arbre suivi | `git grep` des valeurs réelles lues dans `esphome/secrets.yaml` (valeurs non affichées) |
| Verdicts de preuve | `evidence/rapport_fenetre_1h.json` = `PASS`, 180 trames, 179 intervalles à 20 s | lecture directe du JSON |

## 2. Constats BLOQUANTS du 2ᵉ tour, et leur état

### B1 — Le filet de tests laissait passer une erreur commune sur le lux ×10 — **CORRIGÉ**
`tests/frames.py:59,121` et `esphome/includes/vevor_protocol.h:104` implémentent la branche « lux ≥ 0x8000 → ×10 », absente de tout ancrage externe (le vecteur rtl_433 a le bit 15 clair) et dont la valeur attendue était produite par le décodeur Python lui-même.
**Reproduction (agent principal, copie jetable)** : facteur `10 → 20` injecté *à la fois* dans l'encodeur Python et dans le C++ → `204 vérifications, 0 échec`, exit 0. La suite ne pouvait pas voir l'erreur.
**Correctif** : vecteur `test_lux_x10_anchor()` à octets littéraux, valeur attendue calculée à la main (`0xA648 & 0x7FFF` × 10 = 98 000 lx), jamais via `decode_reference()`.
**Re-vérification (agent principal)** : la même injection donne désormais `377 vérifications, 1 échec`, avec le message explicite `[ÉCHEC] lux = 98 000 lx ((0xA648 & 0x7FFF) × 10 = 9 800 × 10, à la main)`.

### B2 — Un résumé de preuve blanchissait son propre rapport — **CORRIGÉ**
`evidence/resume_fenetre_1h_decalage.json` affichait `rejets: 0`, `raisons_rejet: []`, aucun problème, sans même de champ `wind_dir` — alors que son rapport apparié `evidence/rapport_fenetre_1h_decalage.json` concluait `verdict: FAIL` avec 3 motifs (pluie décroissante, deux directions hors plage 779°/835°, deux incohérences de compteur TX) et que `frames_valid` y comptait 181/181 (les trames fautives incluses).
**Cause** : `rejets` (lignes `V7IN1 REJ` du firmware) et `reasons_fail` (décodeur Python indépendant) n'ont pas la même définition, et le résumé n'exportait pas la direction du vent — l'anomalie y était structurellement invisible.
**Correctif** : `tools/summarize_window.py` reprend le verdict et les motifs du rapport (`--rapport`), exporte `wind_dir_deg`, `pluie_decroissante`, `valeurs_hors_plage`, renomme `rejets` → `rejets_firmware`, et **refuse d'écrire un résumé rassurant quand le rapport dit FAIL**.
**Re-vérification (agent principal)** : `verdict: FAIL`, `motifs_fail` identiques aux `reasons_fail` du rapport, `wind_dir_deg: [43, 835]`, `pluie_decroissante: true`.

### B3 — Le critère de sortie « 60 trames en 10 min » était doublé — **CORRIGÉ (tour 1)**
`build_stitched_()` recollait *toute* capture (y compris complète), republiant la rafale précédente 20 s plus tard, hors de la fenêtre anti-doublon de 5 s.
**Mesure d'origine** : 60 lignes `V7IN1 OK` pour **31 `tx_counter` distincts**, chacun exactement 2× ; 60 `RAW` pour 31 contenus distincts.
**Correctif** : décodage direct d'abord, recollage seulement si la capture est trop courte pour porter une rafale (`MAX_FRAGMENT_TIMINGS = 160` pour une rafale utile de 176-184), politique centralisée dans `vevor::is_fragment()` et couverte par `test_fragment_policy()` (96+82 recollé, 184/204 jamais recollé).

## 3. Constats MAJEURS encore ouverts (décision requise)

| # | Constat | Où | Décision attendue |
|---|---|---|---|
| M1 | **13 outils morts ou doublons** (~27 % de `tools/`) : `analyze_noise.py`, `analyze_radio_log.py`, `analyze_stream.py`, `balayer_frequence.py`, `dump_pulses.py`, `gdo0_rate_vs_freq.py`, `regler_frequence.py`, `scan_async.py`, `sweep_summary.py`, `witness_fetch.py`, `boot_dump.sh`, `capture_logs.sh`, `sweep_async.sh` | `tools/` | **Supprimer** (recommandé : plusieurs sont remplacés par les outils de la version courante, et `README.md` renvoie encore à `capture_logs.sh`) ou assumer de les garder |
| M2 | Le **nouveau binaire n'est pas flashé** : la carte (172.16.0.205) tourne l'ancien firmware. Le garde `loop()` (`receiver_ == nullptr`/`is_failed()`) et la politique de recollage testée n'existent que dans le binaire compilé aujourd'hui | `build/` vs carte | **Flasher** (coupe la réception quelques minutes) ou garder l'existant tant qu'il décode |
| M3 | `evidence/ab_cycle.jsonl` est **orphelin** : il compare des variantes `nous_v0/v1/v2` dont les YAML ont été supprimés — non régénérable par ce commit | `evidence/` | Gardé et marqué « historique, non régénérable » (fait dans `evidence/README.md`) ou supprimé |
| M4 | **Puce muette un démarrage sur deux** (`Chip ID: 0xFFFF`) : cause racine du mutisme radio identifiée (cadence SPI 200 kHz) et écritures perdues réglées par le matériel, mais la loterie au démarrage n'est pas expliquée au niveau du pilote | `state/DONE.md` §2, `README.md` piège 7 | Reste ouvert : le firmware redémarre automatiquement (30 tentatives ~10 min, puis 10 redémarrages, puis 1 par 15 min) — comportement à assumer explicitement |
| M5 | **Transistor** : `README.md` décrit la coupure d'alimentation par P-MOSFET comme une **« piste, NON montée »** ; l'utilisateur a parlé d'un « transistor » ajouté au montage. Aucune trace d'un transistor monté dans le dépôt | `README.md` §Câblage | **Confirmer** : piste non montée (rien à câbler) ou composant réellement en place (alors : rôle, référence, broches, résistances associées) |

## 4. Constats MINEURS / documentation, corrigés par cette branche

- `README.md` : titre « Les **cinq** pièges » alors que **sept** sont listés ; nombres du garde-fou (« 3 min / 8 min ») faux ; piège 7 affirmant un redémarrage « uniquement si la radio s'avoue en échec » alors que le code redémarre sur simple silence de trames ; **piège 2 affirmant encore que « la station émet par bouffées »** — `state/DONE.md` §3 établit le contraire (c'étaient des démarrages à puce muette) ; blocs de mise en route ne citant que `/dev/ttyUSB0` (cette carte est sur `/dev/ttyACM0`) et renvoyant à `tools/capture_logs.sh` ; commandes à revalider contre `--help` après la réécriture des outils.
- `state/DONE.md` : « 204 vérifications » (→ 377), nombres du garde-fou, §6 « suites » à recalculer (factorisation faite via `tools/_common.py`, variantes supprimées).
- `state/PROGRESS.md` : consigne du fichier = « jamais de réécriture de l'historique » → **entrée datée ajoutée en tête**, entrées réfutées annotées, pas effacées.
- `state/NUIT.md`, `state/BILAN_NUIT_20261002.md` : notes de travail antérieures à la découverte de la cause racine → bandeau de réfutation et/ou déplacement en archive (aucune suppression : c'est un journal de diagnostic).
- `esphome/vevor-7in1.yaml` : commentaires purgés (ré-armature de boot inexistante et dupliquée, « instrument de diagnostic » disparu, chiffres du garde-fou). `esphome/vevor-7in1.yaml.bak-20261001` (ancienne production cassée, invisible dans `git status` car `*.bak-*` ignoré) supprimé après vérification qu'aucun script ne le référence.
- `esphome/components/cc1101/README-LOCAL.md` : « une seule modification » (→ 10 marquages réels), « 20 relectures (~5 s) » (→ 4 essais 50 ms + 60 relectures non bloquantes ≈ 15 s), et ajout d'une section de maintenance du fork (base ESPHome 2026.9.1, `grep -rn "MODIFICATION LOCALE"`, comparaison au composant natif installé).
- `requirements.txt` : complété (`esphome==2026.9.1`, `aioesphomeapi==46.3.0`, `pyserial`, Python ≥ 3,12).
- **Source de vérité de l'outillage** : `tools/_common.py` (une seule version de `key_from_yaml`, `maybe_await`, tables de variantes, écritures atomiques, chemins relatifs à la racine) ; les échecs silencieux sont supprimés — *rien de mesuré* → « MESURE NULLE » + code 3, *mesuré mais aucune trame* → « aucune trame » + code 0, *échec technique* → code 2.

## 5. Ce qui n'a PAS pu être vérifié (dit franchement)

- **Rien n'a été flashé** : tous les constats de comportement radio reposent sur les journaux locaux (`logs/`, non versionnés) et sur les rapports `evidence/` — aucun essai en direct sur la carte pendant ces revues.
- Les modifications du composant (`vevor_7in1.cpp` : garde `loop()`, appel `is_fragment`) ne sont **pas compilées par la suite hôte** (dépendances ESPHome) : elles sont vérifiées par revue et par le build complet, pas par les tests.
- `state/DONE.md` et `state/PROGRESS.md` restent des documents **écrits par le projet lui-même** : cette revue en contrôle les chiffres et les affirmations vérifiables, elle ne reconstitue pas l'historique des mesures matérielles.
- Le mécanisme exact du mutisme lié à un second périphérique SPI n'est toujours pas expliqué au niveau du pilote (établi empiriquement, 6 tours alternés).

## 6. Réserves de méthode (pour l'agent suivant)

- Une fenêtre de mesure **ne vaut rien sans contrôle d'état de la puce** : un démarrage sur deux lève une puce muette (`Chip ID: 0xFFFF`), donc « 0 trame » n'est un résultat que si la carte est prouvée en état sain (`build/valider_etat_b.sh`).
- La station émet **en continu** toutes les 20 s : tout silence prolongé est une panne du récepteur, pas un silence de la station.
- Ne jamais juger un firmware sur un seul démarrage, ni une mesure sur une capture vide : c'est ce qui a produit la plupart des conclusions fausses du projet (voir `state/DONE.md` §3).
- `references/` contient le projet **externe** `WizardPC/esphome-vevor-7in1` : contexte et pièges uniquement, **jamais une base de code** (exigence dure de l'utilisateur ; aucun fichier de `references/` n'est importable ni compilable, vérifié).
