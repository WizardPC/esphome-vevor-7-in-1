# État final — récepteur Vevor 7-en-1 868 MHz (ESP32-C3 SuperMini + CC1101, ESPHome)

**Statut : OBJECTIF DE `MISSION.md` ATTEINT** (01/10/2026, 09:32-09:42 UTC).

## Ce qui est vérifié (fenêtre `logs/validation_prod_20261001.log`)

- **60 trames décodées et validées en 600 s** (09:32:43 → 09:42:23 UTC), **0 rejet**, 0 échec de
  checksum/compteur — le décodeur C++ du firmware **et** le décodeur Python indépendant
  (`tools/eval_frames.py`, verdict `PASS`) donnent les mêmes 60 trames, tout validées.
- **Cadence mesurée : 20,0 s pile** (médiane = min = max sur 30 rafales ; les 30 « intervalles de
  0 s » sont le doublon de livraison du RMT, ignoré par le compteur « doublons »).
- **Valeurs plausibles sur toute la fenêtre** : T 17,5-17,7 °C, H 66-74 %, vent variable,
  rafale ≥ vent, direction 273-299°, **pluie monotone 59,2 mm**, UV 2-3, lux 11 520-29 970,
  une seule station (`id 33995` = 0x84CB), aucun problème de plage physique.
- **Recoupement par une source indépendante** : le firmware témoin (`WizardPC/esphome-vevor-7in1`),
  compilé et flashé par nous sur la même carte, lisait la même station au même moment
  (T 17,5 °C / H 70-71 % / pluie 59,2 mm / lux 18 810-19 080 à 09:19 UTC).

## La cause de nos « 0 trame » (et sa correction)

Le composant maison `vevor_7in1` déclarait un **second périphérique SPI** sur le bus du CC1101
(instrument de lecture des registres, `cs_pin` sur GPIO10). Avec ce périphérique : 0 trame et
0 à 6 captures RMT. Sans lui : 5 trames/60 s, puis 60 trames/10 min. Le témoin n'a jamais eu
qu'un seul périphérique sur ce bus. Correction : `cs_pin` retiré de la config de production
(+ ré-armature radio du boot retirée, elle contournait ce symptôme).

## Fichiers

- Firmware : `esphome/vevor-7in1.yaml` (production corrigée, sauvegarde
  `vevor-7in1.yaml.bak-20261001`) ; binaire `build/variants/nous_prod.ota.bin`.
- Preuves : `logs/validation_prod_20261001.log`, `logs/validation_prod_rapport.json`,
  `logs/validation_prod_eval.txt` ; mise en évidence de la cause : `logs/ab_cycle.jsonl`
  (alternance témoin / nos variantes) et le journal d'itérations `state/PROGRESS.md`
  (itérations 11septies et 11octies).

## Suites recommandées (non bloquantes)

1. Nettoyer les entités devenues inertes dans le YAML (inventaire de registres, RSSI/MARCSTATE,
   boutons « Dump impulsions » et « Relire l'inventaire ») — elles restent vides puisque le
   composant n'a plus d'accès SPI.
2. Contrôle physique de la station : elle émet **par bouffées** (mesuré : ON 08:04-08:09,
   silence 43 min, ON 08:53-09:42+). Un émetteur solaire qui s'arrête ainsi mérite un contrôle
   (pile / supercondensateur de l'unité extérieure, afficheur intérieur).
3. Boucle planifiée `5fe5aac7bcf4` : laissée **en pause** (elle n'a plus lieu d'être).
