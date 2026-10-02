# Copie LOCALE du composant `cc1101` d'ESPHome — pourquoi elle existe

Ce dossier est une copie de `esphome/components/cc1101` d'ESPHome **2026.9.1**, déclarée en
`external_components` dans `esphome/vevor-7in1.yaml` pour **prendre le pas** sur le composant natif.

## Modifications locales

Toutes les retouches sont marquées `MODIFICATION LOCALE` dans le code : **10 marquages au total**
(8 blocs dans `cc1101.cpp`, 2 déclarations dans `cc1101.h`). Elles portent sur :

1. **identité relue avec réessais** : 4 essais à 50 ms dans `configure()`, puis jusqu'à **60
   relectures non bloquantes à 250 ms (≈ 15 s)** traitées depuis `loop()` — jamais de boucle
   bloquante dans `setup()`, qui déclencherait le watchdog — avec **journal de `CHIP_RDYn`** ;
2. **écriture de registre VÉRIFIÉE**, réécrite jusqu'à prise (4 essais), plus un **bloc de
   contrôle** des 8 registres clés (FREQ2/1/0, MDMCFG4/3/2, PKTCTRL0, IOCFG0) ;
3. **`delay(20)` de stabilisation** avant l'entrée en RX, et **contrôle de la calibration VCO
   (`FSCAL1`)** après l'entrée en RX ;
4. **`enter_calibrated_` réessaie le verrouillage PLL** (`PLL_LOCK_RETRIES = 3`) au lieu
   d'abandonner sur un dépassement de délai ;
5. **cadence SPI rétablie à `DATA_RATE_1MHZ`** (contre les 200 kHz d'une itération antérieure, où
   la puce ne sortait qu'un flux de bruit).

## Pourquoi la relecture d'identité

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
`CC1101.cpp`). Ici : 4 essais à 50 ms, puis jusqu'à 60 relectures à 250 ms (≈ 15 s) depuis `loop()`
avant d'abandonner, et **journal de `CHIP_RDYn`** à chaque tentative, ce qui départage les deux
causes :

| Journal | Lecture |
|---|---|
| `CHIP_RDYn HAUT = alimentation ou quartz pas prêts` | côté matériel (alimentation, quartz, POR) |
| `CHIP_RDYn bas = puce prête, donc liaison SPI en cause` | côté câblage (MISO/MOSI/CS, masse) |

## Maintenance du fork

- **Version de base** : ESPHome **2026.9.1** (`esphome version`). C'est la seule référence ; le
  dossier n'est pas un paquet versionné, donc à chaque montée de version d'ESPHome les correctifs
  amont **ne sont pas récupérés automatiquement**.
- **Source de vérité pour le diff** : le composant natif installé, pour que l'écart reste lisible —
  p. ex. `.venv/lib/python3.13/site-packages/esphome/components/cc1101/`.
- **Retrouver les modifications** : `grep -rn "MODIFICATION LOCALE" esphome/components/cc1101/`
  liste les 10 marquages (8 blocs dans `cc1101.cpp`, 2 dans `cc1101.h`).
- **Rejouer les modifications** après une montée d'ESPHome : comparer le dossier local au composant
  natif de la nouvelle version (`diff -ru <natif> esphome/components/cc1101/`), puis reporter les
  blocs marqués. Il n'existe **pas** de fichier de patch : les blocs `MODIFICATION LOCALE` tiennent
  lieu de jeu de hunks. Si l'écart devient difficile à suivre, générer un `diff -u` (natif → local)
  et le déposer dans ce dossier.
- **Contrôle minimal après mise à jour** : `configure()` doit journaliser l'identité
  (`CC1101 trouvé…`), le « contrôle des écritures » doit être conforme sur les 8 registres, et la
  cadence SPI doit rester `DATA_RATE_1MHZ`.
