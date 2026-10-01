# État final — récepteur Vevor 7-en-1 868 MHz (ESP32-C3 SuperMini + CC1101, ESPHome)

**Statut : objectif de `MISSION.md` atteint** — et **corrigé** après la revue de code du 01/10
(dossier `reviews/`, non versionné), qui a mis en évidence deux défauts dans la première version
validée : un **comptage de trames doublé** et une **instrumentation SPI toujours active**. Ce
document dit ce qui est prouvé, et par quoi.

## 1. Le défaut de la première validation, corrigé depuis

La première fenêtre (`logs/validation_prod_20261001.log`, 600 s, firmware d'avant revue) avait été
annoncée comme « 60 trames validées ». **C'était trompeur, et la revue l'a établi puis je l'ai
revérifié moi-même** : ces 60 lignes ne contenaient que **30 mesures distinctes**, chacune publiée
deux fois (chaque compteur TX apparaissait exactement 2×). Cause : le recollage inter-captures
s'appliquait à **toute** capture, y compris complète — les 480 impulsions précédentes étaient
recollées devant chaque nouvelle rafale, si bien que le décodeur relisait la rafale PRÉCÉDENTE et la
republiait 20 s plus tard, hors de la fenêtre anti-doublon de 5 s.

Correction (`esphome/components/vevor_7in1/vevor_7in1.cpp`, `esphome/includes/vevor_protocol.h`) :
**décodage direct d'abord**, recollage **uniquement entre deux morceaux** de rafale
(`MAX_FRAGMENT_TIMINGS = 160` ; mesuré : une rafale utile fait 176 à 184 impulsions). Éprouvé hors
matériel — `tests/test_decoder.cpp` couvre maintenant la coupure nette, la coupure AU MILIEU d'une
impulsion et le morceau isolé (**198 vérifications, 0 échec**).

Second défaut corrigé : l'instrumentation SPI (`sample_radio_()`) était appelée dans `loop()` alors
que son commentaire la disait désactivée, et comme `SPIDelegate::is_ready()` renvoie `true` même sans
broche CS, elle publiait toutes les 10 s un faux `RSSI=-74.0 dBm (brut 0x00)`, `SLEEP`,
`FREQ=0.00000 MHz` (60 lignes pendant la fenêtre de validation). Toute l'instrumentation SPI a été
**supprimée** (composant, schéma, YAML) : c'est elle qui rendait la puce muette (voir §2).

## 2. La cause des « 0 trame » historiques

Identifiée par **alternance témoin / notre firmware dans les mêmes fenêtres d'émission**
(`tools/ab_cycle.py`, mesure conservée dans `evidence/ab_cycle.jsonl`) : notre composant déclarait un
**second périphérique SPI** sur le bus du CC1101 (instrument de lecture des registres, `cs_pin` sur
GPIO10). Avec : **0 capture RMT, 0 trame**. Sans : **5 trames/60 s**. Le firmware de référence n'a
jamais eu qu'un seul périphérique sur ce bus.

## 3. Ce qui est vérifié, et par quoi

- **Décodage et cadence** : fenêtre d'une heure du firmware corrigé — voir
  `evidence/rapport_fenetre_1h.json` (décodeur Python indépendant) et
  `evidence/resume_fenetre_1h.json` (cadence, trous, rejets, plages de valeurs).
- **Deux implémentations indépendantes comparées champ par champ** : `tools/eval_frames.py` compare,
  trame par trame, les valeurs publiées par le C++ à celles de son propre décodeur ; le verdict
  `PASS` exige cet accord **et** des valeurs plausibles (plages physiques + cohérence lux/UV) **et**
  une avance de compteur TX conforme au temps écoulé **et** une cadence ~20 s. Un rapport qui contient
  un constat ne peut plus conclure `PASS` (c'était le défaut du verdict précédent : `PASS` avec
  « 59 ruptures de séquence » dans son propre corps).
- **Ancrage externe du décodage** : la trame de référence de rtl_433 est vérifiée en dur dans
  `tests/test_decoder.cpp`, valeurs **calculées à la main** depuis `rtl_433/src/devices/vevor_7in1.c`
  (vent 13 ticks / 8,333 = 1,6 km/h, rafale 3 / 1,25 = 2,4 km/h, pluie 55 × 0,233 = 12,8 mm, lux
  14 457). Contre-épreuve faite : injecter la même erreur d'échelle de vent dans l'encodeur Python
  **et** dans le C++ fait désormais ÉCHOUER la suite (avant, elle passait 173/173).
- **Recoupement par un second récepteur** : le firmware de référence, compilé et flashé par nous sur
  la même carte, lisait la même station au même moment (T 17,5 °C, H 70-71 %, pluie 59,2 mm).

## 4. Fichiers

- Firmware : `esphome/vevor-7in1.yaml` ; binaire mesuré : `build/variants/nous_prod.ota.bin`
  (non versionné — `build/` est ignoré par git, d'où `evidence/` pour les preuves synthétiques).
- Preuves versionnées : `evidence/` (rapports JSON de la fenêtre d'une heure + `ab_cycle.jsonl`).
- Journal complet des itérations : `state/PROGRESS.md`.

## 5. Suites ouvertes (dites franchement)

1. **La station émet par bouffées** (mesuré : ON 08:04-08:09, silence 43 min, ON 08:53-09:42+, …).
   Toute mesure « 0 trame » doit être validée par un créneau témoin dans la MÊME fenêtre — c'est la
   règle que ce projet a payée cher. Un contrôle physique de l'unité extérieure (pile /
   supercondensateur, afficheur intérieur) reste recommandé.
2. **Le mécanisme exact** par lequel un second périphérique SPI sur une broche CS libre rend la puce
   muette n'est pas expliqué au niveau du pilote ESPHome : la cause est établie par la mesure.
3. **Duplication d'outillage** : `key_from_yaml()` existe encore en plusieurs copies (sans bug connu
   après vérification), et `maybe_await` en trois exemplaires — à factoriser dans `tools/_common.py`.
4. Les variantes de diagnostic `vevor-7in1-v1/v2/v3.yaml` ont été **supprimées** (obsobètes, et
   v1/v3 contenaient encore le second périphérique SPI — mauvais exemple à laisser dans le dépôt).
