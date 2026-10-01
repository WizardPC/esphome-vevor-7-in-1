# Contexte externe — projet `WizardPC/esphome-vevor-7in1` (analyse, PAS une base de code)

Projet analysé le 30/09/2026 : <https://github.com/WizardPC/esphome-vevor-7in1> (licence MIT).
Source, comme nous : `rtl_433/src/devices/vevor_7in1.c`.

> **Consigne de l'utilisateur : ne PAS s'en servir comme base de code.** Notre implémentation
> reste indépendante (c'est ce qui garde sa valeur au recoupement entre notre C++ et notre
> décodeur Python). Ce document ne rapporte que des **paramètres mesurés** et des **pièges de
> protocole**, à traiter comme des hypothèses à tester, preuve à l'appui.

## 1. Le point le plus important : nos réglages radio sont probablement faux

Configuration publiée comme fonctionnelle (station 868 MHz EU) :

| Paramètre | Eux (fonctionnel) | Nous (actuel) | Écart |
|---|---|---|---|
| `frequency` | **868,35 MHz** | 868,30 MHz | à recentrer |
| `modulation_type` | 2-FSK | 2-FSK | ✓ |
| `symbol_rate` | **11 111** (période bit 90 µs ; **88,3 µs** annoncés par l'utilisateur → 11 325 bauds) | 11 494 (87 µs) | proche, dans la tolérance du CC1101 |
| `fsk_deviation` | **70 kHz** | 37 kHz | **×1,9 — suspect n°1** |
| `filter_bandwidth` | **100 kHz** | 200 kHz | **2× trop large — suspect n°2** |

Cohérence : `symbol_rate` 11 111 ↔ période bit 90 µs (nous : 87 µs d'après rtl_433, 11 494).

Pourquoi ça expliquerait nos 0 trame valide : avec une déviation réelle de ~70 kHz annoncée à
37 kHz dans le registre, le démodulateur FSK du CC1101 travaille sur une hypothèse fausse, et
notre filtre à 200 kHz laisse entrer deux fois plus de bruit — d'où des verrous de syncword sur
du bruit (−105…−108 dBm, LQI=127) et **jamais** de trame cohérente. À tester en priorité :
`868.35 MHz / 70 kHz / 100 kHz / 11111 baud`, puis balayage fin de la fréquence.

## 2. Architecture différente (à connaître comme repli documenté, pas à copier)

Eux **n'utilisent pas le mode packet** : le composant `cc1101` d'ESPHome met la puce en
**2-FSK asynchrone**, les bits démodulés sortent sur GDO0/GDO2, sont captés par
`remote_receiver` (leur réglage : `filter: 65us`, `idle: 2000us`), et un composant externe
reconvertit les impulsions en bits (`bit_period` par défaut **90 µs**).

Deux enseignements de protocole valables quelle que soit l'architecture :

- **Les trames arrivent coupées.** Leur décodeur contient une logique de reconstitution
  (`prev_fragment_` / `stitched_`, « Trame coupée reconstruite avec succès »). Une capture
  incomplète ne veut donc pas forcément dire « signal absent » : il peut manquer un fragment.
- Ils gèrent un **décalage (« skew ») du rythme bit** (`timings_to_bits_(raw, skew_us)`) : le
  récepteur peut avoir une horloge légèrement décalée et il faut essayer plusieurs décalages.

Notre montage a déjà GDO0 sur GPIO3, donc basculer vers ce chemin asynchrone est possible sans
recâbler — c'est un repli crédible si le mode packet reste muet après correction de la déviation.

## 3. Pièges de protocole documentés (à intégrer à notre auto-évaluation)

- **Un checksum valide ne garantit pas une valeur de pluie correcte.** La station lit son
  compteur 16 bits pendant qu'il se reporte et peut publier l'octet bas rebouclé avec l'octet
  haut périmé : exactement **256 ticks (59,6 mm) de moins**, checksum valide, environ une fois
  tous les 59,6 mm de pluie. → Un checksum OK ne suffit pas : il faut un contrôle de cohérence
  de la pluie (saut suspect à confirmer sur la trame suivante à ±2 ticks).
- **La pluie ne peut que monter**, ou repartir à zéro pile à la suite d'un changement de pile.
  Une baisse non nulle est une corruption — quelle que soit sa répétition. Un zéro n'est accepté
  qu'après **3 trames consécutives** (une corruption ne se répète pas, une remise à zéro si).
- Le compteur de pluie **sature à 15 209,8 mm = 65 278 ticks (0xFEFE)**. Cohérent avec
  l'encodage « +1 par octet » : `0xFF` est inatteignable, d'où la valeur max `0xFE 0xFE`.
- **Contrôle de plausibilité vent** : une trame avec `vent > 0` et `rafale == 0` est rejetée
  (une rafale ne peut pas être nulle si le vent moyen ne l'est pas).
- **Filtre luminosité/UV** : rejeter `lux == 0` avec un UV non nul, et les lux incompatibles
  avec l'index UV de la même trame.
- **Batterie** : l'indicateur (`0x9d` faible / `0x1d` normal) demande une **confirmation sur
  plusieurs trames** avant d'être publié (il est ambigu, rtl_433 le soupçonne d'être aussi le
  bouton d'appairage).
- **L'ID de la station change à chaque mise sous tension** (changement de pile). Conséquence :
  épingler l'ID, et s'attendre à devoir le retrouver après une pile. Corollaire important pour
  nous : **une autre station du voisinage sur le même protocole écraserait nos valeurs** si on
  n'épingle pas l'ID. Notre firmware publie déjà l'ID — il faut s'en servir.
- Le décompte des stations est **par bloc** : chaque décodeur suit son propre total de pluie.

## 4. Matériel (rappel)

Module CC1101 **bande 868 MHz** ET **antenne 868 MHz** obligatoires (les modules/antennes
433 MHz, majoritaires dans les résultats de recherche, ne fonctionnent pas). Notre module est
bien un 868 MHz et l'utilisateur l'a confirmé.

## 5. Ce que cela change concrètement pour nous

1. **Avant tout nouveau balayage**, reflasher avec `868.35 MHz / 70 kHz / 100 kHz / 11111 baud`
   (nos valeurs actuelles sont suspectées fausses sur la déviation et la bande passante).
2. Balayer ensuite **finement** autour de 868,35 MHz (±150 kHz par pas de 10–25 kHz) : le
   centre réel dépend de l'unité (rtl_433 mesure des décalages de quelques dizaines de kHz).
3. Enrichir `tools/eval_frames.py` : rejeter `vent > 0` avec `rafale == 0` ; traiter les baisses
   de pluie non nulles comme corruption ; exiger 3 zéros consécutifs avant d'accepter une remise
   à zéro ; vérifier la cohérence lux/UV.
4. Si le mode packet reste muet après ces corrections, essayer le chemin asynchrone
   (`remote_receiver` sur GDO0/GPIO3 avec `filter: 65us`, `idle: 2000us`) — c'est un repli
   documenté, pas une reprise de code.

## 6. Rythme bit : 88,3 µs et la fonction de « recentrage »

L'utilisateur signale que la période bit réelle est **88,3 µs** (→ 11 325 bauds), et non les
90 µs (11 111 bauds) que ce projet met par défaut. C'est cohérent : leur README présente
`bit_period` comme « à ne toucher que si le timing de votre récepteur est décalé et que les
trames ne valident jamais ». Notre valeur actuelle, 11 494 bauds (87 µs), est à −1,5 % de
88,3 µs : les trois valeurs encadrent la réalité.

Ce que fait exactement leur recentrage (`vevor_decoder.cpp`) :

- `timings_to_bits_(raw, skew_us)` convertit les impulsions en bits avec
  `num = (duration + period/2) / period` : arrondi au multiple le plus proche de la période bit ;
- le décalage est appliqué à chaque impulsion : `duration = (val > 0) ? (val - skew) : (-val + skew)` ;
- `try_decode_raw_()` essaie **8 décalages fixes** : `SKEW_CANDIDATES[] = {0, 7, -7, 14, -14, 21, 25, 28}`
  et accepte le premier qui donne `0xAA` + checksum valide — en testant tous les candidats au
  lieu de s'arrêter au premier échec ;
- la liste est asymétrique (beaucoup plus de valeurs positives) : leur récepteur mesure des
  impulsions systématiquement **plus longues** que l'idéal, et le skew les recale.

**Conséquence pour nous : ce n'est pas notre problème, et c'est structurel.** En mode packet,
c'est le **CC1101 lui-même** qui fait la synchronisation bit (verrouillage sur le syncword, avec
`symbol_rate` comme valeur nominale seulement) : il tolère quelques pourcents d'erreur et
n'exige aucun décalage par récepteur. Leur mécanisme existe parce que leur architecture est
**asynchrone** : `remote_receiver` livre des durées d'impulsions brutes, et c'est au décodeur de
les convertir en bits avec un diviseur, d'où la sensibilité à la période exacte et au biais de
mesure. Chercher un réglage fin à 88,3 µs ne débloquera donc rien tant qu'on reste en mode
packet — les vrais suspects restent la **déviation (37 → 70 kHz)** et la **bande (200 → 100 kHz)**.

Ce qui compte en revanche :

- si les trames ne valident toujours pas après correction de la déviation et de la bande,
  essayer `symbol_rate` ≈ **11 325** (88,3 µs) — c'est un test à un paramètre, peu coûteux ;
- si on bascule un jour sur le chemin asynchrone, cette recherche de skew (8 candidats) et la
  valeur 88,3 µs deviennent **indispensables** : sans elles, le chemin asynchrone ne peut pas
  convertir les impulsions en bits correctement.
