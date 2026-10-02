# Preuves synthétiques (versionnées)

Ces fichiers sont la trace vérifiable des mesures citées dans `state/DONE.md`. Les journaux bruts
(`logs/`, plusieurs centaines de Ko à quelques Mo) restent **hors dépôt** (`.gitignore`) — ils ne
sont donc **pas rejouables** après un simple `git clone` — mais chaque rapport conserve les trames
brutes (21 octets par trame), de sorte que les affirmations restent **contrôlables**.

| Fichier | Fenêtre | Ce qu'il prouve |
|---|---|---|
| `rapport_fenetre_1h.json` | **validée** (`logs/verif_garde_fou_60min.log`) | rapport du **décodeur Python indépendant** (`tools/eval_frames.py`) : trames trouvées/valides, comparaison champ par champ avec le firmware C++, verdict **PASS**, 0 motif de refus |
| `resume_fenetre_1h.json` | **validée** (même log) | synthèse de la même fenêtre (`tools/summarize_window.py --rapport …`) : cadence, trous, `rejets_firmware`, `wind_dir_deg`, `valeurs_hors_plage`, et le **verdict repris de son rapport** |
| `resume_fenetre_1h.txt` | **validée** (même log) | version texte (lisible) du résumé ci-dessus, produite par le même script (`--txt`) |
| `rapport_fenetre_1h_decalage.json` | **fautive** (`logs/fenetre_1h_cond_20261001.log`) | rapport du décodeur indépendant sur la fenêtre du décalage : verdict **FAIL**, **3 motifs** (pluie décroissante, valeurs implausibles, 2 incohérences de compteur TX) |
| `resume_fenetre_1h_decalage.json` | **fautive** (même log) | synthèse de la fenêtre fautive : verdict **FAIL** et **les mêmes 3 motifs** que son rapport (un résumé ne peut plus contredire son rapport) |
| `ab_cycle.jsonl` | — | mesures **alternées** témoin / notre firmware (`tools/ab_cycle.py`). **HISTORIQUE — non régénérable par HEAD** (voir ci-dessous) |

## Chaque résumé est APPARIÉ à son rapport

`tools/summarize_window.py` est lancé avec `--rapport <rapport_eval_frames.json>` : il **reprend
le verdict et les motifs** du décodeur indépendant et sort en code 1 quand le rapport dit `FAIL`.
Il ajoute `wind_dir_deg` et `valeurs_hors_plage`, deux anomalies qui étaient **structurellement
invisibles** dans l'ancien format.

⚠️ Le champ `rejets_firmware` (et `raisons_rejet_firmware`) compte les lignes `V7IN1 REJ`
**du firmware** : ce **n'est pas** le verdict du décodeur indépendant (`reasons_fail`). Les deux
mesures sont distinctes et peuvent diverger — la fenêtre fautive n'a **aucun** rejet firmware
alors que le décodeur indépendant la condamne. Ne jamais lire `rejets_firmware: 0` comme un
« verdict propre » : lire `verdict` / `motifs_fail`.

## `ab_cycle.jsonl` — GARDÉ, marqué historique

**Décision : GARDER** (avec la mention « historique, non régénérable par HEAD »).
Raison : ce fichier documente l'expérience qui a **isolé la cause** des « 0 trame » (le témoin
décode pendant que nos variantes restent à 0), expérience encore citée par `state/DONE.md`. Il a
été produit par une version antérieure d'`ab_cycle.py` et **mélange deux campagnes** (v0/v1 puis
v2) ; les variantes `nous_v0/v1/v2` ont été supprimées, donc **`ab_cycle.py` de HEAD ne peut plus
le régénérer** à l'identique. On le conserve comme archive, sans le présenter comme reproductible.

## Régénérer (depuis un clone qui a encore les logs locaux)

Les rapports ont été produits depuis les journaux réels suivants (noms exacts, champs `logfile`) :

```sh
# Fenêtre VALIDÉE (180 trames, PASS)
tools/eval_frames.py    logs/verif_garde_fou_60min.log      --json evidence/rapport_fenetre_1h.json
tools/summarize_window.py logs/verif_garde_fou_60min.log \
    --rapport evidence/rapport_fenetre_1h.json \
    --json evidence/resume_fenetre_1h.json  --txt evidence/resume_fenetre_1h.txt

# Fenêtre FAUTIVE (181 trames, FAIL — 3 motifs)
tools/eval_frames.py    logs/fenetre_1h_cond_20261001.log   --json evidence/rapport_fenetre_1h_decalage.json
tools/summarize_window.py logs/fenetre_1h_cond_20261001.log \
    --rapport evidence/rapport_fenetre_1h_decalage.json \
    --json evidence/resume_fenetre_1h_decalage.json
```

Pour capturer une nouvelle fenêtre : `tools/capture_logs.py --host <IP> --seconds 3600
--out logs/verif_garde_fou_60min.log` (un chemin relatif vise la **racine du projet**). Les
scripts `--json`/`--out` écrivent de façon **atomique** (fichier temporaire + `os.replace`).
