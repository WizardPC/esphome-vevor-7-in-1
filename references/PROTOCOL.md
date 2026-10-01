# Protocole RF — Station Vevor 7-en-1 868 MHz (réf. YT60309 / famille YT602xx)

Source de vérité : décodeur `vevor_7in1.c` de rtl_433 (merbanan/rtl_433, `src/devices/vevor_7in1.c`).
Fabricant réel : Fujian Youtong Industries. Modèles documentés : YT60231 (868 MHz EU),
YT60234 (915 MHz US). Même protocole et même checksum entre les deux bandes.

## Couche radio

- Modulation : **2-FSK** (NRZ / PCM), pas d'OOK.
- Débit : période bit **87 µs** → **~11 494 bauds**.
- Déviation : **±37 kHz** (mesuré sur l'unité 915 MHz).
- Rafale : **~85 ms toutes les 20,000 s** (tous les capteurs dans chaque trame).
- Centre mesuré 915,031 MHz pour le nominal 915,000 → **prévoir un offset de fréquence**
  (le CC1101 remonte `freq_offset` à chaque paquet : c'est notre outil de calage).
- Preamble : `AA AA AA` puis syncword `CA CA 54`, puis la charge utile.

## Trame

Après détection du motif `AA AA CA CA 54`, on extrait **21 octets** `b[0..20]` :

| Octet | Champ | Décodage |
|---|---|---|
| b[0] | fixe | `0xAA` |
| b[1] | type/canal | nibble haut = type (0), nibble bas = canal ; vaut `0x00` |
| b[2..3] | ID capteur | `(b[2]<<8) \| b[3]` (16 bits) |
| b[4] | batterie | bit7 = 1 → batterie faible (`0x9d` = low, `0x1d` = ok) |
| b[5..6] | température | `raw = (b[5]<<8)\|b[6]` ; `T°C = (raw - 500) * 0.1` |
| b[7] | humidité | `%` direct |
| b[8..9] | vitesse vent | **-1 sur chaque octet**, puis `km/h = raw / 8.333` |
| b[10] | rafale | `km/h = b[10] / 1.25` (pas de -1) |
| b[11..12] | direction | **-1 sur chaque octet**, puis `deg = ((b[11] & 0x0f) << 8) \| b[12]` |
| b[13..14] | pluie | **-1 sur chaque octet**, puis `mm = raw * 0.233` |
| b[15] | UV | `(b[15] & 0x1f) - 1` |
| b[16..17] | luminosité | **-1 sur chaque octet** ; si bit15 = 1 → `(val & 0x7fff) * 10`, sinon `val` lux |
| b[18] | compteur TX | incrémenté à chaque émission |
| b[19] | checksum | `sum(b[0..18]) & 0xFF` |
| b[20] | compteur TX+1 | doit valoir `(b[18] + 1) & 0xFF` |

**Ordre des opérations impératif** : le checksum est calculé sur les octets **bruts**,
les décrémentations (-1) ne s'appliquent qu'**après** validation.

## Critères d'auto-évaluation (vérité terrain, sans SDR)

Un décodage est considéré valide si :

1. `sum(b[0..18]) & 0xFF == b[19]` (checksum) ;
2. `b[20] == (b[18] + 1) & 0xFF` (compteur cohérent) ;
3. `b[0] == 0xAA` et `b[1] == 0x00` ;
4. cadence entre trames d'un même ID ≈ 20 s ± 1 s ;
5. entre deux trames consécutives du même ID : compteur TX +1, pluie **croissante ou égale**,
   température/humidité variant de façon continue (pas de saut de plusieurs dizaines de °C) ;
6. plausibilité physique : `-40 ≤ T ≤ +60 °C`, `0 ≤ HR ≤ 100 %`, `0 ≤ vent ≤ 180 km/h`,
   `0 ≤ direction ≤ 359°`, `0 ≤ UV ≤ 16`, lux ≥ 0 ;
7. recoupement avec une source indépendante : Open-Meteo (API libre, lat/lon de la maison)
   pour la température/humidité extérieure, à ±5 °C / ±20 % près.

## Pièges connus

- Un faux positif est possible si la valeur LUX est au maximum → n'accepter que des trames
  dont le checksum ET le compteur sont bons.
- Le CC1101 en mode packet peut se synchroniser à côté (`sync_mode: 16/16`, sync `CA 54`) :
  toujours filtrer par checksum plutôt que par longueur.
- Si aucun paquet : balayer la fréquence (867,8 → 868,6 MHz par pas de 50 kHz) et surveiller
  RSSI + `freq_offset` ; l'antenne spirale fournie limite fortement la portée (viser < 15 m
  pour la mise au point, puis antenne λ/4).
