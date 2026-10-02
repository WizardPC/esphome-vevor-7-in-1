> **ARCHIVE — BILAN DE TRAVAIL DATÉ, PARTIELLEMENT RÉFUTÉ** (bandeau ajouté le 02/10/2026, commit 9693dbe).
> Ce fichier a été déplacé de `state/BILAN_NUIT_20261002.md` vers `state/archive/`. Rédigé le 02/10 à
> 07h32, **avant** la découverte de la cause racine.
>
> **Ce qui est périmé ou à nuancer :** l'hypothèse « l'intégrité du lien SPI en *écriture* » (§4)
> décrivait l'état de la nuit **sous le handicap du SPI à 200 kHz** ; les écritures perdues ont été
> réglées par les soudures de l'utilisateur (pull-up externe 10 kΩ + 10 µF), mais ce n'était **pas** la
> cause de la surdité. Le « taux de démarrages sains » (0/10) mesuré cette nuit n'est plus une
> référence. La station émet **en continu** (pas par bouffées) : les fenêtres vides étaient des
> « carte sourde » (`state/DONE.md` §3).
>
> **Cause racine réelle, trouvée le 02/10** : la cadence SPI de **200 kHz** du pilote `cc1101`.
> **Pour l'état vrai : `state/DONE.md` et les entrées du 02/10 de `state/PROGRESS.md`.** Ne rien
> corriger dans le corps : c'est une preuve horodatée.

# Bilan de la nuit — récepteur Vevor 7-en-1 868 MHz (nuit du 01 au 02/10/2026)

Rédigé le 02/10/2026 à 07h32 (heure de Paris), à partir des journaux. Chaque chiffre porte sa source ;
aucune valeur de mémoire. `logs/nuit_*.log` n'existe pas : les journaux de la nuit sont
`logs/veille_etats.log` et `logs/veille_ecritures_hors_prises.txt` (seuls fichiers modifiés après
`state/NUIT.md`) ; `logs/diag_fscal.log` (00h50), `logs/test_86830.log` (00h45),
`logs/controle_temoin.log` (00h59) et `logs/ab_cycle.jsonl` (01h22) sont antérieurs à la note.

## 1. Ce qui a été mesuré, et par quel moyen

- Veille d'états non invasive (bouton « Réappliquer la config radio », sans redémarrage), 240 fenêtres
  de 60 s, 01h41 → 05h46 : **0 état sain, 49 états A, 191 états B** — `logs/veille_etats.log`, bilan final.
- **Aucune trame décodée de toute la nuit** : somme des `trames=` = 0 sur 240 cycles, aucune ligne
  « V7IN1 OK » dans `logs/veille_etat_*.log`.
- Séquence des états : A 01h41→01h46 · B 01h47→02h30 · A 02h31→02h44 · B 02h45→03h43 · A 03h44→03h58 ·
  B 03h59→05h27 · A 05h28→05h41 · B →05h46 (`logs/veille_etats.log`).
- Écritures de registres encore perdues, palliatifs actifs : **28 cycles sur 240** avec un registre
  définitivement non écrit après 4 essais — 0x19 (FOCCFG) ×21, 0x0B (FSCTRL1) ×17, 0x08 (PKTCTRL0) ×9,
  0x0F (FREQ0) ×4, dont « ECRITURE NON PRISE FREQ0 : ecrit 0xE8, relu 0xEC » —
  `logs/veille_ecritures_hors_prises.txt`.
- Le firmware en service tournait bien à **200 kHz** (header compilé `spi::DATA_RATE_200KHZ`,
  `esphome/.esphome/build/vevor-7in1/src/esphome/components/cc1101/cc1101.h:21` ; binaire
  `build/variants/nous_prod.ota.bin`, 01h30, sha256 22b711ce…, identique au `firmware.ota.bin` du build).
  → le test 200 kHz « à refaire en état B » est de fait fait : il ne change rien.
- Calibration VCO, 191 lectures : FSCAL1 de 0x00 à 0x3E, **jamais 0x3F** ; FSCAL2 = 0x0C dans 187/191 ;
  MARCSTATE = 0x0D (RX) 191/191 → PLL verrouillée, l'errata SWRZ020E (FSCAL1 = 0x3F) n'est pas en cause.
- Contrôle par le témoin (00h50 → 00h57) : témoin 11 trames au tour 1, **0 au tour 2** ; notre firmware
  0 aux deux tours — `logs/controle_temoin.log` → l'avantage du témoin était confondu par la loterie.
- Taux après pull-up CS : « 10 cycles mesurés, 0 avec au moins une trame » —
  `logs/loterie_apres_pullup.log` (01h23).
- Relevé à 07h32 (`tools/read_state.py`) : carte joignable, Captures RMT = 40, Trames valides = 0,
  Trames rejetées = 0, Fréquence CC1101 = 868,35, toutes les grandeurs météo = None.

## 2. Ce qui a changé dans le firmware

- **Broche CS avec pull-up** : `cs_pin` GPIO7 déclaré `mode: {output: true, pullup: true}` —
  `esphome/vevor-7in1.yaml:138-147` (commit 9d158a9, 01h09). Portée : n'agit qu'après le `setup()`.
- **Relectures non bloquantes** de l'identité (1 par `loop()`, 250 ms d'écart, budget 15 s) — supprime le
  « CRASH DETECTED … Task wdt » de la version bloquante — `esphome/components/cc1101/cc1101.cpp` (commit
  95f2e2b, 00h34).
- **Diagnostic CHIP_RDYn** (bit 7 du status byte) : « pas prête » (état A, `0xFFFF`) contre « prête,
  liaison en cause » (état B, `0x0014`, status `0x0F`) — même commit.
- **Contrôle des écritures** (relire après écrire) puis **écriture vérifiée avec 4 réessais**
  (TEST0/1/2 exceptés) — commits 95f2e2b et 4aab2b4 (01h31).
- **Calibration VCO** embarquée (FSCAL1/FSCAL2/FSCAL0 + MARCSTATE après entrée en RX) — commits 95f2e2b
  et 4aab2b4 ; d'où les 191 lectures de la nuit.
- **Cadence SPI 1 MHz → 200 kHz** — `esphome/components/cc1101/cc1101.h:21` (commit 4aab2b4).
- **Outils de balayage de fréquence** : `tools/balayer_frequence.py` (±100 kHz → 0 trame sur 868,25 /
  868,30 / 868,35 / 868,40 / 868,45) et `tools/regler_frequence.py` (commit 95f2e2b).

## 3. État de la carte à la fin de la nuit : MUETTE (mais vivante)

`logs/veille_etats.log`, dernier cycle :
`[05:46] cycle 240 : B (répond, se configure, ne démodule rien) trames=0 | [I][cc1101:307]: calibration VCO : FSCAL1=0x18 (valide), FSCAL2=0x0C, FSCAL0=0x0D, MARCSTATE=0x0D`
Sa fenêtre `logs/veille_etat_240.log` : « CC1101 trouvé après 1 relecture(s) : Chip ID: 0x0014 (status
0x0F, CHIP_RDYn haut 0 fois) », « SANTE radio=ok trames=0 captures=58 … rejets=8 ».
→ Puce présente, PLL verrouillée, des candidats de trame atteignent la validation et sont rejetés ; mais
la puce ne démodule rien. Ce n'est pas une puce morte, c'est une puce mal configurée.

Deux écarts avec la note de passation, à savoir : la veille s'est arrêtée à **05h46** (240 cycles de
60 s), pas « vers 07h00 » comme prévu ; et `state/NUIT.md` porte une section datée 02h00 alors que son
dernier commit est de 01h44 Paris (0a6e447) — les libellés d'heure de la note sont approximatifs.

## 4. Hypothèse retenue (hypothèse, pas fait)

Les écritures qui n'atteignent pas la puce malgré pull-up CS + 200 kHz + 4 réessais désignent
l'intégrité du lien en **écriture** (alimentation, masse, découplage), pas le code ni le quartz. Ce que
corrobore la dégradation temporelle (180 trames en une heure à 15h58 le 01/10, plus rien après 21h16).
À valider par le changement d'alimentation du matin.

## 5. Reste à faire ce matin

1. **Changement d'alimentation** de l'ESP32 (prévu) ; ajouter au même passage : pull-up **externe** 10 kΩ
   sur CS (GPIO7), 100 nF au plus près du VCC du module, vérifier que DCOUPL n'est pas relié au 3,3 V
   (liste de `state/NUIT.md`, section 02h00).
2. **Contrôle du décodage avec le firmware témoin**, en fenêtres alternées, 2 tours minimum : une seule
   fenêtre ne prouve rien (erreur du 01/10).
3. Si une écriture lâche encore : relire la VCO pendant une capture via « Réappliquer la config radio »
   et relancer `SCAL` en boucle au premier `FSCAL1 = 0x3F` (jamais observé cette nuit).
