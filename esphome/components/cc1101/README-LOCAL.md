# Copie LOCALE du composant `cc1101` d'ESPHome — pourquoi elle existe

Ce dossier est une copie de `esphome/components/cc1101` d'ESPHome 2026.9.1, déclarée en
`external_components` dans `esphome/vevor-7in1.yaml` pour **prendre le pas** sur le composant natif.
Une seule modification, dans `cc1101.cpp` :

**Vérification d'identité avec relectures, et journalisation de `CHIP_RDYn`.**

La version d'origine lit `PARTNUM` puis `VERSION` **une seule fois**, puis appelle `mark_failed()` :
sur ce montage, un démarrage sur deux se levait avec `Chip ID: 0xFFFF` (toutes les lectures SPI à
0xFF) et la carte restait muette **toute la session**. Or la datasheet CC1101 (SWRS061I) dit :
- §10.1 : `CHIP_RDYn` (bit s7 du status byte) « reste haut jusqu'à ce que l'alimentation ET le
  quartz soient stabilisés » — et pendant ce temps l'en-tête SPI renvoie `0xFF` sur SO ;
- §4.9 + Table 18 : la rampe d'alimentation doit faire 5 ms de 0 à 1,8 V, sinon l'état de la puce est
  indéterminé jusqu'à un `SRES` (et la séquence de reset complète n'est requise qu'à la première mise
  sous tension : §19.1.2).

Donc `0xFFFF` ne veut pas dire « câblage faux » mais « puce pas prête ». RadioLib, la bibliothèque de
référence, boucle 10 relectures espacées de 10 ms pour cette raison (jgromes/RadioLib,
`CC1101.cpp`). Ici : jusqu'à **20 relectures** (~5 s) avant d'abandonner, et **journal de
`CHIP_RDYn`** à chaque tentative, ce qui départage les deux causes :

| Journal | Lecture |
|---|---|
| `CHIP_RDYn HAUT = alimentation ou quartz pas prêts` | côté matériel (alimentation, quartz, POR) |
| `CHIP_RDYn bas = puce prête, donc liaison SPI en cause` | côté câblage (MISO/MOSI/CS, masse) |

Source de la vérité pour toute mise à jour : le fichier d'ESPHome, pour que le diff reste lisible.
