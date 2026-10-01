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
commentaire) ; reste à la flasher et à mesurer.

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
