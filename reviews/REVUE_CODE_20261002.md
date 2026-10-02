# Revue de code — 02/10/2026 : 2ᵉ tour, nettoyage et état final

- **Dépôt** : `WizardPC/esphome-vevor-7-in-1` — récepteur 868 MHz Vevor 7-en-1 (ESP32-C3 SuperMini + CC1101, ESPHome).
- **Commits de référence** : `5fbc604` (début du 2ᵉ tour) → `9693dbe` (« README : montage physique — résistance, condensateurs et transistor de coupure d'alimentation », `main`, poussé) → branche `revue/nettoyage-doc-20261002` (`a7290f1` revue, `ff2598a` documentation, poussée).
- **Périmètre** : tout le dépôt — composant ESPHome (`esphome/components/vevor_7in1/`), pilote `cc1101` vendorié, protocole (`esphome/includes/vevor_protocol.h`), configuration (`esphome/vevor-7in1.yaml`), outillage (`tools/`, 27 `.py` + 8 `.sh`), tests hors matériel (`tests/`), preuves (`evidence/`), documentation (`README.md`, `MISSION.md`, `state/*`, `references/*`).
- **Méthode** : deux vagues de sous-agents à périmètres disjoints (4 puis 2), plus une vague de correction (3) — et **revérification systématique de chaque conclusion critique par l'agent principal** (reproduction, jamais de confiance). Aucun accès matériel : ni flash, ni connexion à la carte `172.16.0.205` ; le seul build lancé est la compilation locale du firmware.
- **Rapports détaillés** (fichiers locaux, `reviews/` est dans `.gitignore`) : `reviews/round2/01-firmware-armature.md` (487 l.), `02-outillage-preuves.md` (679 l.), `03-documentation-cablage.md` (466 l.), `04-tests-preuves-chiffres.md` (300 l.) — reproduits en annexe de ce fichier.

---

## 1. Faits mesurés (reproduits par l'agent principal, pas rapportés de confiance)

| Fait | Valeur | Établi par |
|---|---|---|
| Suite hors matériel | **377 vérifications, 0 échec** | `bash tools/run_tests.sh` — relancé par l'agent principal **avant et après** les retouches finales |
| Firmware | **BUILD OK**, 966 400 octets | `tools/build.sh` → `esphome/.esphome/build/vevor-7in1/build/firmware.ota.bin` |
| Configuration ESPHome | `INFO Configuration is valid!`, exit 0 | `.venv/bin/esphome config esphome/vevor-7in1.yaml` |
| Fuite de secrets | **aucune** : ni SSID, ni mot de passe Wi-Fi, ni clé API dans l'arbre suivi | `git grep` des valeurs réelles lues dans `esphome/secrets.yaml` (valeurs jamais affichées) |
| Verdicts de preuve | `evidence/rapport_fenetre_1h.json` = `PASS`, 180 trames, 179 intervalles à 20 s | lecture directe du JSON |
| Résumés de preuve | cohérents avec leur rapport après correction (§2/B2) | lecture des deux paires rapport/résumé |

## 2. Constats BLOQUANTS du 2ᵉ tour, et leur état

### B1 — Le filet de tests laissait passer une erreur commune sur le lux ×10 — **CORRIGÉ ET RE-PROUVÉ**
`tests/frames.py:59,121` et `esphome/includes/vevor_protocol.h:104` implémentent la branche « lux ≥ 0x8000 → ×10 », absente de tout ancrage externe (le vecteur rtl_433 a le bit 15 clair), dont la valeur attendue était produite par le décodeur Python lui-même.
**Reproduction initiale (agent principal, copie jetable)** : facteur `10 → 20` injecté *à la fois* dans l'encodeur Python et dans le C++ → `204 vérifications, 0 échec`, exit 0. La suite ne pouvait pas voir l'erreur.
**Correctif** : vecteur `test_lux_x10_anchor()` à octets littéraux, valeur attendue calculée à la main (`0xA648 & 0x7FFF` × 10 = 98 000 lx), jamais via `decode_reference()`.
**Re-vérification (agent principal, après correctif)** : la même injection donne désormais `377 vérifications, 1 échec`, avec le message explicite `[ÉCHEC] lux = 98 000 lx ((0xA648 & 0x7FFF) × 10 = 9 800 × 10, à la main)`.

### B2 — Un résumé de preuve blanchissait son propre rapport — **CORRIGÉ ET VÉRIFIÉ**
`evidence/resume_fenetre_1h_decalage.json` affichait `rejets: 0`, `raisons_rejet: []`, aucun problème, sans même de champ `wind_dir` — alors que son rapport apparié `evidence/rapport_fenetre_1h_decalage.json` concluait `verdict: FAIL` avec 3 motifs (pluie décroissante, deux directions hors plage 779°/835°, deux incohérences de compteur TX) et que `frames_valid` y comptait 181/181 (les trames fautives incluses).
**Cause** : `rejets` (lignes `V7IN1 REJ` du firmware) et `reasons_fail` (décodeur Python indépendant) n'ont pas la même définition, et le résumé n'exportait pas la direction du vent — l'anomalie y était structurellement invisible.
**Correctif** : `tools/summarize_window.py` reprend le verdict et les motifs du rapport (`--rapport`), exporte `wind_dir_deg`, `pluie_decroissante`, `valeurs_hors_plage`, renomme `rejets` → `rejets_firmware`, et **refuse d'écrire un résumé rassurant quand le rapport dit FAIL**.
**Vérification (agent principal)** : `verdict: FAIL`, `motifs_fail` identiques aux `reasons_fail` du rapport, `wind_dir_deg: [43, 835]`, `pluie_decroissante: true`, `rapport_verdict: FAIL`.

### B3 — Le critère de sortie « 60 trames en 10 min » était doublé — **CORRIGÉ (1ᵉʳ tour)**
`build_stitched_()` recollait *toute* capture (y compris complète), republiant la rafale précédente 20 s plus tard, hors de la fenêtre anti-doublon de 5 s.
**Mesure d'origine (1ᵉʳ tour, agent principal)** : 60 lignes `V7IN1 OK` pour **31 `tx_counter` distincts**, chacun exactement 2× ; 60 `RAW` pour 31 contenus distincts ; captures recollées de 655-697 impulsions pour une rafale utile de ~176.
**Correctif** : décodage direct d'abord, recollage seulement si la capture est trop courte pour porter une rafale (`MAX_FRAGMENT_TIMINGS = 160` pour une rafale utile de 176-184), politique centralisée dans `vevor::is_fragment()` et couverte par `test_fragment_policy()` (96+82 recollé ; 184 et 204 jamais recollés).

## 3. Décisions encore en attente (la revue ne peut pas les prendre)

| # | Constat | Où | Décision attendue |
|---|---|---|---|
| M1 | **13 outils morts ou doublons** (~27 % de `tools/`) : `analyze_noise.py`, `analyze_radio_log.py`, `analyze_stream.py`, `balayer_frequence.py`, `dump_pulses.py`, `gdo0_rate_vs_freq.py`, `regler_frequence.py`, `scan_async.py`, `sweep_summary.py`, `witness_fetch.py`, `boot_dump.sh`, `capture_logs.sh`, `sweep_async.sh` | `tools/` | **Supprimer** (recommandé : plusieurs sont remplacés par les outils de la version courante) ou assumer de les garder. Le README ne renvoie plus à `capture_logs.sh`, mais les fichiers restent. |
| M2 | Le **nouveau binaire n'est pas flashé** : la carte (172.16.0.205) tourne l'ancien firmware. Le garde `loop()` (`receiver_ == nullptr` / `is_failed()`) et la politique de recollage testée n'existent que dans le binaire compilé le 02/10 | `build/` vs carte | **Flasher** (coupe la réception quelques minutes) ou garder l'existant tant qu'il décode |
| M3 | `evidence/ab_cycle.jsonl` est **orphelin** : il compare des variantes `nous_v0/v1/v2` dont les YAML ont été supprimés — non régénérable | `evidence/` | Gardé et documenté « historique, non régénérable » (fait dans `evidence/README.md`) ou supprimé |
| M4 | **Puce muette un démarrage sur deux** (`Chip ID: 0xFFFF`) : la cause racine du mutisme radio est trouvée (cadence SPI 200 kHz rétablie à 1 MHz) et les écritures perdues réglées par le matériel (pull-up externe 10 kΩ + 10 µF), mais la loterie au démarrage n'est pas expliquée au niveau du pilote | `state/DONE.md` §2, `README.md` piège 7 | Assumer explicitement le garde-fou (20 s ; 30 tentatives ≈ 10 min ; puis 10 redémarrages rapprochés ; repli 1/15 min) — ou creuser l'alimentation du module |
| M5 | **Transistor** : `README.md` décrit la coupure d'alimentation du module par P-MOSFET comme une **« piste, NON montée »** ; l'utilisateur a parlé d'un « transistor » ajouté au montage. Aucune trace d'un transistor monté dans le dépôt (0 occurrence, historique git compris) | `README.md` §Câblage | **Confirmer** : piste non montée (rien à câbler) ou composant réellement en place (alors : rôle, référence, broches, résistances associées) |
| M6 | **Pull-up sur CS** : les documents disent 10 kΩ (valeur réellement soudée, après correction par l'utilisateur) ; seul le message du commit historique `6c7e164` garde l'ancien 100 kΩ | `state/*`, `README.md` | Rien à faire : rectification propre partout, l'historique git n'est pas réécrit |

## 4. Corrections appliquées — état du dépôt aujourd'hui

### 4.1 Déjà poussé dans `9693dbe` (13:43)
- **Outillage** : `tools/_common.py` créé — une seule version de `key_from_yaml` (5 copies → 1), `maybe_await` (3 → 1), tables de variantes (2 désynchronisées → 1 ; le `KeyError` de `boot_probe.py` est réparé), écritures atomiques (`os.replace`), chemins de sortie résolus depuis la racine (plus jamais selon le CWD) ; 16 scripts rebranchés.
- **Échecs silencieux supprimés**, règle stricte : *rien de mesuré* → « MESURE NULLE » + code 3 ; *mesuré mais aucune trame* → « aucune trame » + code 0 ; *échec technique* → code 2.
- **Tests** : 204 → **377 vérifications**. Ancrage externe du lux ×10, couverture des branches humidité/température/vent/rafale/UV de la porte de plausibilité, faux rejet `vent = 180 km/h` corrigé (marge 0,01), trou inter-rafales réellement exercé, période 88/89/87 exercée et sélection non fragile, politique de recollage testée.
- **Code** : `out.valid` posé après la porte de plausibilité ; garde `receiver_ == nullptr` / `is_failed()` dans `loop()` ; condition de recollage via `vevor::is_fragment()`.
- **Configuration** : commentaires purgés (ré-armature de boot inexistante et dupliquée, « instrument de diagnostic » disparu, chiffres du garde-fou), `esphome/vevor-7in1.yaml.bak-20261001` (ancienne production cassée, invisible dans `git status` car `*.bak-*` ignoré) supprimé après vérification qu'aucun script ne le référence, `esphome/components/cc1101/README-LOCAL.md` corrigé + section de maintenance du fork (base ESPHome 2026.9.1, `grep -rn "MODIFICATION LOCALE"`, comparaison au composant natif installé).
- **Preuves** : résumés d'`evidence/` régénérés et cohérents avec leurs rapports ; `evidence/README.md` corrigé ; `requirements.txt` complété (`esphome==2026.9.1`, `aioesphomeapi==46.3.0`, `pyserial`, Python ≥ 3,12).

### 4.2 Branche `revue/nettoyage-doc-20261002` (poussée, 2 commits)
- `a7290f1` — ce fichier de revue (versionné exprès par `git add -f`, `reviews/` étant ignoré) + déplacement de `state/NUIT.md` → `state/archive/2026-10-01_NUIT.md` et `state/BILAN_NUIT_20261002.md` → `state/archive/2026-10-02_BILAN_NUIT.md`.
- `ff2598a` — documentation remise d'aplomb :
  - `README.md` : « cinq pièges » → **sept** ; **piège 2 corrigé** — la station émet **en continu** (une rafale toutes les 20 s) et les fenêtres vides étaient des démarrages à puce muette, contrairement à ce qu'affirmaient le README et les itérations 11nonies/11septies ; piège 7 (redémarrage sur simple silence de trames, sans `is_failed()`) ; nombres du garde-fou alignés sur le code ; `/dev/ttyACM0` (majeur 166) au lieu de `/dev/ttyUSB0` ; `capture_logs.py` au lieu du `.sh` ; IP d'exemple alignée sur `state/DEVICE_IP` ; chaque option vérifiée contre `--help`.
  - `state/DONE.md` : 204 → **377** vérifications, nombres du garde-fou, §6 recalculé (factorisation faite via `tools/_common.py`, variantes v1-v3 closes, suites ouvertes : M1, M3, M2). Les constats datés sont laissés tels quels.
  - `MISSION.md` : nom du décodeur corrigé (`vevor_protocol.h` au lieu d'un fichier inexistant), commande de capture mise à jour, valeurs radio du projet de référence présentées comme adoptées (et non comme un contraste périmé), notes de relecture du 02/10.
  - `state/PROGRESS.md` : entrée datée du 02/10 **ajoutée en tête** (règle du fichier : jamais de réécriture de l'historique), bandeaux de réfutation sur les entrées contredites, « 128 vérifications » → 377.
  - `state/archive/*` : bandeaux expliquant ce qui est réfuté depuis (pull-up *interne* du YAML, contrôle témoin confondu par la loterie des démarrages, station « par bouffées », surdité attribuée aux écritures SPI) et où lire l'état vrai — **aucune information historique supprimée**.
  - `references/PROTOCOL.md` : préambule corrigé (`AA AA CA CA 54`, conforme à rtl_433 et au code) + bandeaux de statut sur les trois notes de références (`EXTERNAL_CONTEXT_WIZARDPC.md`, `HOME_ASSISTANT.md`, `PROTOCOL.md`).
  - Commentaires de code : préambule de `vevor_protocol.h` aligné sur son tableau (deux `0xAA`, pas trois) ; compteurs cités dans `tests/test_decoder.cpp` explicitement datés « d'alors » (références historiques, pas des chiffres courants).

**Vérifications après ces retouches** : `tools/run_tests.sh` → **377 vérifications, 0 échec** ; aucune modification de comportement (deux commentaires seulement).

## 5. Ce qui n'a PAS pu être vérifié (dit franchement)

- **Rien n'a été flashé** : tous les constats de comportement radio reposent sur les journaux locaux (`logs/`, non versionnés) et sur les rapports `evidence/` — aucun essai en direct sur la carte pendant ces revues.
- Les modifications du composant (`vevor_7in1.cpp` : garde `loop()`, appel `is_fragment`) ne sont **pas compilées par la suite hôte** (dépendances ESPHome) : elles sont couvertes par le build complet, pas par les tests.
- `state/DONE.md` et `state/PROGRESS.md` sont des documents **écrits par le projet lui-même** : cette revue en contrôle les chiffres et les affirmations vérifiables, elle ne reconstitue pas l'historique des mesures matérielles.
- Le mécanisme exact du mutisme lié à un **second périphérique SPI** n'est toujours pas expliqué au niveau du pilote (établi empiriquement, 6 tours alternés).
- La **puce muette un démarrage sur deux** (M4) reste sans explication au niveau du pilote.

## 6. Épilogue — dépôt, accès GitHub, PR

- **Ce qui est sur GitHub** : `main` à `9693dbe` (nettoyage + README câblage) et la branche `revue/nettoyage-doc-20261002` (`a7290f1`, `ff2598a`) — revue consolidée + documentation remise d'aplomb.
- **Aucune pull request n'a été ouverte** : décision de l'utilisateur le 02/10 (« oublie la PR et note tout dans le fichier de revue »). La branche reste disponible sur le dépôt : l'autre intervenant peut la voir telle quelle (`git merge origin/revue/nettoyage-doc-20261002`) ou en demander la suppression.
- **Accès GitHub réellement disponible** : une clé **SSH de déploiement** (`~/.ssh/hermes_vevor_deploy`, alias `github-vevor`) — identité confirmée par `ssh -T` : *« Hi WizardPC/esphome-vevor-7-in-1! »*. Elle autorise `fetch`/`push`, **pas** l'API GitHub (aucune création de PR possible en SSH).
- **Pas de jeton API utilisable** : le `GITHUB_TOKEN` de `~/.hermes/.env` (ligne 456) est **commenté** et c'est un placeholder de 24 caractères (API : `HTTP 401`) ; même constat dans `~/.hermes/profiles/drive/.env`. Coffre Hermes vide (`hermes vault list`), aucune autre installation de `gh` sur la machine (aucun `hosts.yml`). Créer une PR demande donc soit une autorisation par code (device flow), soit un geste humain, soit un PAT déposé dans `~/.hermes/.env`.
- **Ce que la PR aurait servi à trancher** : M1 (13 outils morts), M2 (flash du binaire), M5 (statut du transistor) — ces trois décisions restent ouvertes et sont documentées ici.

## 7. Réserves de méthode (pour l'agent suivant)

- Une fenêtre de mesure **ne vaut rien sans contrôle d'état de la puce** : un démarrage sur deux lève une puce muette (`Chip ID: 0xFFFF`), donc « 0 trame » n'est un résultat que si la carte est prouvée en état sain (`build/valider_etat_b.sh`).
- La station émet **en continu** toutes les 20 s : tout silence prolongé est une panne du récepteur, pas un silence de la station.
- Ne jamais juger un firmware sur un seul démarrage, ni une mesure sur une capture vide : c'est ce qui a produit la plupart des conclusions fausses du projet (voir `state/DONE.md` §3).
- **Un test dont la valeur attendue est produite par le code testé ne prouve rien** : injecter une erreur *des deux côtés* est la seule contre-épreuve valable — c'est ce qui a révélé B1.
- **Un résumé de preuve doit être généré depuis son rapport**, jamais à côté : un résumé rassurant qui contredit son rapport est pire qu'aucun résumé (B2).
- `references/` contient le projet **externe** `WizardPC/esphome-vevor-7in1` : contexte et pièges uniquement, **jamais une base de code** (exigence dure de l'utilisateur ; vérifié : aucun fichier de `references/` n'est importable ni compilable).

---

# Annexes — rapports détaillés du 2ᵉ tour

