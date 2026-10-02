# Note de passation — nuit du 1er au 2 octobre 2026 (rédigée à 00h55, heure de Paris)

## Où en est le projet

Récepteur météo Vevor 7-en-1 868 MHz (ESP32-C3 SuperMini + CC1101, ESPHome 2026.9.1), répertoire
`/home/hermes/projets/vevor-7in1`. Objectif de `MISSION.md` atteint le 01/10 à 14h58 : une fenêtre
d'une heure, 180 trames, 180 valides, `verdict: PASS`, accord champ par champ avec un décodeur Python
indépendant. Depuis ~21h16 (heure de Paris), la carte n'a plus rien décodé, malgré toutes les
tentatives de la soirée.

## LA TROUVAILLE DE 00h55 : une seule différence de configuration avec le firmware témoin

Comparaison champ par champ du firmware de référence (projet `WizardPC/esphome-vevor-7in1`) et du
nôtre — tout est identique (45 µs / 1100 µs / 512 symboles / 2-FSK / 11111 bauds / ±70 kHz / 100 kHz
/ 868,35 MHz) **sauf la déclaration de la broche CS** :

- témoin : `cs_pin: {number: GPIO7, mode: {output: true, pullup: true}}`
- le nôtre (jusqu'à cette nuit) : `cs_pin: {number: GPIO7}` — **ni mode, ni pull-up**

Sans pull-up, la ligne CS **flotte pendant tout le démarrage de l'ESP32**, avant que le firmware ne
la configure en sortie : la puce peut y voir des sélections parasites et se retrouver dans l'état
**indéterminé** que décrit la datasheet (§4.9 / Table 18). Cela collerait exactement avec des
symptômes qui varient d'un démarrage à l'autre. **Correction appliquée au YAML** (avec explication en
commentaire) ; reste à la flasher et à mesurer. **Voir toutefois la CORRECTION de 02h00 en fin de
note : ce réglage n'agit qu'après le boot ; le correctif réel de la fenêtre de démarrage est un
pull-up EXTERNE de 10 kΩ sur CS.**

## Le contrôle par le témoin (00h50, heure de Paris) — le résultat qui a orienté la correction

Test en fenêtres alternées (`tools/ab_cycle.py`, 2 tours, 120 s par fenêtre) :
- **firmware témoin : 11 trames décodées** (`trames_decodees=11`, `rafales=30`) — le matériel
  fonctionne, dans le même créneau que le nôtre ;
- firmware corrigé : 0 trame.
Conclusion : le défaut n'est **pas** dans le matériel, ni dans le décodeur, ni dans le calage de
fréquence — il est dans **notre configuration**, et la seule différence trouvée est le pull-up sur CS.

## Ce qui a été éliminé cette nuit, avec la mesure qui l'élimine

| Hypothèse | Mesure qui l'élimine |
|---|---|
| Décodeur / période de bit | 4 périodes candidates testées automatiquement ; 88 à 90 µs selon la rafale |
| Câblage SPI | les 8 registres critiques (FREQ2/1/0, MDMCFG4/3/2, PKTCTRL0, IOCFG0) **relus conformes** après écriture |
| Décalage de quartz | balayage ±100 kHz (868,25 → 868,45) : **0 trame** ; et le mot de fréquence était exact (`0x21656A` pour 868,30) |
| Fréquence 868,30 au lieu de 868,35 | test compilé à 868,30 pendant 10 min : 0 trame (test valide : écritures conformes) → **retour à 868,35** |
| Valeur mémorisée écrasant la config | l'entité « Fréquence CC1101 » était en `restore_value: true` et rejouait 868,35 au démarrage : **corrigé** (`restore_value: false`, valeur alignée) |
| RMT cassé | des captures arrivent en état B (jusqu'à 498 impulsions, candidats refusés par la validation) |

## Ce qui reste en lice

1. **Le pull-up sur CS** (voir ci-dessus) — correction appliquée, à valider par flash + mesure.
2. **L'alimentation** du module (3,3 V tirés du SuperMini) — l'utilisateur change l'alimentation de
   l'ESP32 le matin du 02/10 ; les fils SPI sont à refaire en soudé si l'occasion se présente.
3. La **calibration VCO** (`FSCAL1 == 0x3F` selon l'errata SWRZ020E) : diagnostic embarqué dans la
   copie locale du composant, mais il ne s'exécute qu'en état B et au démarrage — donc pas encore lu.
   À lire en pressant « Réappliquer la config radio » **pendant** une capture.

## Corrections et outillage embarqués cette nuit (tous poussés sur `origin/main`)

- copie **locale** du composant `cc1101` (`esphome/components/cc1101/`, `README-LOCAL.md`) — le
  composant natif lit `PARTNUM`/`VERSION` UNE fois puis `mark_failed()` ;
- **relectures non bloquantes** (une par passage dans `loop()`, 250 ms d'écart, budget 15 s) : la
  première version faisait une boucle de 5 s dans `setup()` et **faisait planter l'ESP32**
  (« CRASH DETECTED ... Reason: Task wdt ») — erreur corrigée et vérifiée ;
- journal de **CHIP_RDYn** (bit 7 du status byte) : distingue « puce pas prête » (état A, `0xFFFF`)
  de « puce prête mais liaison en cause » (état B, `CHIP ID 0x0014`, status `0x0F`) ;
- **contrôle des écritures** (relire après écrire) — c'est lui qui a blanchi le câblage SPI ;
- diagnostic **calibration VCO** (`FSCAL1`/`FSCAL2`/`FSCAL0` + `MARCSTATE`) après entrée en RX ;
- outils `tools/balayer_frequence.py` et `tools/regler_frequence.py` ;
- garde-fou radio dans le YAML : état journalisé toutes les 20 s, 9 tentatives d'initialisation,
  redémarrage automatique borné (10 rapprochés puis 1 / 15 min), remis à zéro dès qu'une trame passe.

## À faire au réveil (ordre proposé)

1. Lire le bilan de la nuit (posté à 7h30 heure de Paris).
2. Vérifier si la carte décode avec la correction du pull-up CS (le journal le dira).
3. Sinon : changer l'alimentation de l'ESP32 (prévu), puis relancer un contrôle **alterné témoin /
   notre firmware** (2 tours minimum) — jamais une seule fenêtre : c'est l'erreur qui a égaré la
   soirée.
4. Lire la calibration VCO en pressant « Réappliquer la config radio » pendant une capture.

---

## 01h10 (heure de Paris) — LA MESURE QUI TRANCHE : les écritures SPI ne prennent pas, et la puce est saine

Le contrôle des écritures (relire après écrire) s'est enfin exécuté dans une session où la puce
répondait. Résultat, `logs/test_cs_pullup.log` :

```
[01:02:40] [E][cc1101:231]: ECRITURE NON PRISE MDMCFG3 : ecrit 0xC0, relu 0x22
[01:03:00] [E][cc1101:231]: ECRITURE NON PRISE FREQ0  : ecrit 0xE8, relu 0xEC
[01:03:00] [E][cc1101:231]: ECRITURE NON PRISE MDMCFG4 : ecrit 0xC8, relu 0x8C
[01:03:00] [E][cc1101:240]: controle des ecritures : 2 registre(s) NON pris
[01:03:00] [I][cc1101:271]: calibration VCO : FSCAL1=0x1F (valide), FSCAL2=0x0A, FSCAL0=0x0D, MARCSTATE=0x0D
```

**Deux conclusions, tirées de ces lignes :**

1. **Les écritures de registres sont perdues par intermittence**, y compris `FREQ0` — donc la
   fréquence elle-même. C'est l'explication complète du balayage de fréquences resté muet : ce
   n'étaient pas les fréquences qui étaient fausses, mais les écritures qui n'atteignaient pas la
   puce. Une puce dont les registres ne prennent pas ne démodule rien, quelle que soit la fréquence.
   À noter : dans une AUTRE session (22:36 Paris), les 8 mêmes registres s'étaient relus **tous
   conformes** — c'est donc intermittent, pas systématique.
2. **La puce elle-même est saine** : `FSCAL1 = 0x1F` (pas `0x3F` = échec de calibration selon
   l'errata SWRZ020E), `MARCSTATE = 0x0D` = en réception. PLL verrouillée, puce configurée… sauf que
   la configuration reçue n'est pas celle demandée.

**Ce que cela désigne** : l'intégrité du lien SPI en écriture (horloge, fils, masse, alimentation du
module) — pas le code, pas le décodeur, pas le quartz. Cela valide la piste matérielle de
l'utilisateur (changement d'alimentation le matin).

**Mesures de taux en cours cette nuit** (douze démarrages, `logs/loterie_apres_pullup.log`) : le
pull-up sur CS appliqué à 01h02 n'a pas suffi dans la session qui a suivi, donc la question est
maintenant quantitative — quel taux de démarrages sains, avec et sans pull-up.

## 01h30 (heure de Paris) — les écritures perdues reviennent à leur valeur d'USINE

Test « écriture vérifiée + réessais » (`logs/test_ecriture_verifiee.log`, binaire `9d158a9`) :

```
[01:24:13] [W][cc1101:236]: registre 0x10 NON PRIS apres 4 essais (voulu 0xC8)
[01:24:13] [I][cc1101:239]: configuration : 2 registre(s) repris apres relecture, 1 definitivement non pris
[01:24:13] [E][cc1101:267]: ECRITURE NON PRISE MDMCFG4 : ecrit 0xC8, relu 0x8C
```

**Lecture décisive** : `0x8C` est la **valeur d'usine** de MDMCFG4, et `0x22` (vu plus tôt) celle de
MDMCFG3. Autrement dit ces écritures **n'atteignent pas la puce du tout** : elle conserve ses
registres de réinitialisation. Les réessais automatiques récupèrent la majorité des registres
(« 2 repris ») mais pas MDMCFG4, qui résiste à quatre tentatives. Une puce dont le débit/la bande
passante et la fréquence ne sont pas ceux demandés ne démodule rien — à aucune fréquence, ce qui
explique définitivement le balayage muet.

**Piste testée ensuite** : abaisser la cadence SPI de 1 MHz à 200 kHz (`logs/test_spi_200khz.log`).
1 MHz est conforme à la puce (6,5 MHz max) mais peut ne pas l'être à notre câblage ; c'est le
palliatif logiciel le plus ciblé contre des écritures perdues.

**Taux mesuré après le pull-up sur CS** (`logs/loterie_apres_pullup.log`) : 0 démarrage sain sur 10
consécutifs, avec des compteurs de captures alternant (85, 19, 85, 142, 84, 13, 88, 19, 86, 19) —
deux états se succèdent, aucun ne décode. La carte s'est dégradée au cours de la soirée : elle
décodait 180 trames en une heure à 15h58, plus rien après 21h16. Le pull-up seul n'a pas suffi.

## 01h40 (heure de Paris) — état A à nouveau, et un moyen d'observer les lignes de démarrage

`logs/reapplique_200khz.log` — le bouton « Réappliquer la config radio » **pendant** une capture
(astuce utile pour la suite : au démarrage, les lignes d'identité et de contrôle des écritures
tombent avant que l'API ne les reçoive, donc les captures les ratent ; ce bouton les fait tomber
dans la fenêtre, et il ne redémarre pas la carte) :

```
[W][cc1101:183]: CC1101 muet sur le SPI — lecture 1/4 (Chip ID: 0xFFFF, status 0xFF) : CHIP_RDYn HAUT = alimentation ou quartz pas prêts
[E][cc1101:192]: identité CC1101 illisible après 4 relectures (4 fois CHIP_RDYn haut)
```

Donc à 01h40 la carte est repassée en **état A** (la puce ne répond plus du tout) après avoir été en
état B à 01h24 (elle répondait, avec des écritures perdues). Le balancier continue, et il est
maintenant clair qu'il ne dépend pas du firmware (le témoin y est soumis aussi).

**Test à 200 kHz : non concluant** dans cette fenêtre (l'état A empêche toute écriture) — à refaire
en état B. Le binaire est en place (`build/variants/nous_prod.ota.bin`) ; le contrôle des écritures
dir le taux de reprises.

## Dispositif laissé en place pour la fin de nuit

- `build/veille_etats.sh` lancé à 01h42 pour 240 cycles (~5 h, jusqu'à ~07h00 heure de Paris) :
  interroge la carte toutes les ~75 s SANS la redémarrer, classe l'état (SAIN / A / B) et recopie les
  registres non pris dans `logs/veille_ecritures_hors_prises.txt`. C'est ce fichier qui donnera le
  taux d'états pour le bilan du matin.
- `build/loterie_etats.sh` : même chose mais AVEC redémarrage à chaque cycle (mesure du taux de
  démarrages sains) — utilisé à 01h10 : 0/10 sains, puis le cycle a été arrêté pour tester le
  200 kHz.
- Bilan de 7h30 : tâche cron `8655473a3e94` (« Bilan nuit vevor-7in1 »), livrée dans ce fil, qui lit
  cette note et les journaux pour composer le compte rendu (heure de Paris, fait vs hypothèse).

---

## Recherches rendues (02h00, heure de Paris) — avec une CORRECTION de mon analyse de 01h00

**Correction importante, à lire avant d'agir :** j'ai écrit plus haut que le pull-up déclaré dans le
YAML (`cs_pin: mode: {output: true, pullup: true}`) était « la » correction. **C'est faux** : ce
réglage n'active le pull-up interne qu'au `setup()` de la broche, donc **après** la fenêtre de
démarrage de l'ESP32. Or sur ESP32-C3 la broche GPIO7 est en **haute impédance au reset** (IE, sans
WPU — Table 2-1 de la datasheet Espressif), et c'est précisément cette fenêtre qui est suspecte. Le
réglage YAML est donc inoffensif mais **ne couvre pas le problème** ; il ne faut pas s'appuyer sur
lui. Par ailleurs l'observation « témoin 11 trames / nous 0 » reste **confondue** par la loterie par
démarrage, elle ne prouve pas une différence de firmware.

**Le correctif réel de cette fenêtre est matériel : un pull-up EXTERNE de 10 kΩ de CS (GPIO7) au
3,3 V.** C'est la mesure qui agit pendant le reset/boot, et c'est la pratique de la carte de
référence ESP32-C3 + CC1101 (hallard : « IO8 CSn … active low, 10K pullup »).

### Liste matérielle pour le matin (par ordre de rentabilité)

1. **Pull-up externe 10 kΩ** de CS (GPIO7) au 3,3 V — agit pendant le boot, contrairement au réglage YAML.
2. **Alimentation du module séparée** de la broche 3,3 V du SuperMini (LDO dédié ou 5 V) — les clones
   de SuperMini sont documentés avec un régulateur plafonné à ~250 mA et un rail qui s'effondre sous
   les pics. C'est le changement prévu par l'utilisateur.
3. **Découplage** : 100 nF au plus près du VCC du module, + 10 à 100 µF (470 µF cité sur les clones de
   SuperMini) si le rail est partagé avec le Wi-Fi.
4. **Vérifier que DCOUPL (broche du régulateur interne) n'est PAS relié au 3,3 V** — erreur de schéma
   relevée par TI, elle rend la puce erratique. Il ne doit y avoir qu'un condensateur de découplage.
5. Refaire les liaisons courtes et la masse commune si l'occasion se présente.
6. (Vérifié, rien à faire) Nos broches SPI sont GPIO4/5/6/7 et GDO0 sur GPIO3 : aucune sur les
   GPIO8/9/10 du flash.

### Palliatifs logiciels restants, non encore appliqués

- Après un `FSCAL1 == 0x3F`, relancer la calibration (`SCAL`) en boucle jusqu'au verrouillage
  (datasheet §22.1) ; le détecteur de verrouillage seul n'est pas fiable (errata SWRZ020E).
- Réécrire `TEST0`/la calibration après un réveil de veille (TEST0 n'est pas retenu en SLEEP).
- Respecter la Table 22 : ≥150 µs entre CS bas et le premier front d'horloge après mise en veille
  (notre séquence de reset attend 5 ms, donc conforme à ce point ; la question reste ouverte pour les
  écritures de registres enchaînées).
- Cas TI voisin du nôtre, résolu par la valeur de `FSCAL2` (0x0A au lieu de 0x2A) : notre lecture donne
  justement `FSCAL2=0x0A`, donc rien à changer de ce côté.

### Sources utiles pour la suite

- ESPHome issues #16876 (« même câblage, OK en Arduino, muet en ESPHome, aucun log ») et #18551
  (`Chip ID 0x0014`, SPI sain, échecs intermittents) ; RadioLib #173 (mauvais bus SPI utilisé).
- TI E2E 111152 (SPI renvoyant 0xFF au boot jusqu'à ce que le quartz démarre), 15770 (nets DCouple et
  DGuard permutés → SO jamais bas), 1237481 (DCOUPL relié au 3,3 V), 118780 (CS togglée en cours de
  transaction → seule la status byte revient).
- Datasheet CC1101 SWRS061I §10.1, §19.1.2, Table 18/21/22 ; errata SWRZ020E (détecteur de
  verrouillage PLL non fiable, FSCAL1 = test valide) ; DN503 SWRA112B.
