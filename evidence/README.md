# Preuves synthétiques (versionnées)

Ces fichiers sont la trace vérifiable des mesures citées dans `state/DONE.md`. Les journaux bruts
(2,4 Mo de captures) restent hors dépôt — ils sont régénérables et trop volumineux — mais tout ce
qui permet de juger le résultat est ici, en JSON, pour qu'après un `git clone` les affirmations
soient contrôlables.

| Fichier | Ce qu'il prouve |
|---|---|
| `rapport_fenetre_1h.json` | rapport du **décodeur Python indépendant** (`tools/eval_frames.py`) sur la fenêtre d'une heure : trames trouvées/valides, comparaison champ par champ avec les valeurs publiées par le firmware C++, verdict et motifs de refus |
| `resume_fenetre_1h.json` | synthèse de la même fenêtre (`tools/summarize_window.py`) : cadence médiane/min/max, trous, rejets, répartition des émissions par tranche de 10 min, plages de valeurs |
| `ab_cycle.jsonl` | mesures **alternées** témoin / notre firmware dans les mêmes fenêtres d'émission (`tools/ab_cycle.py`) — c'est cette comparaison qui a isolé la cause des « 0 trame » (second périphérique SPI) |

Régénérer : `tools/capture_logs.py --host <IP> --seconds 3600 --out logs/fenetre.log` puis
`tools/eval_frames.py logs/fenetre.log --json evidence/rapport_fenetre_1h.json` et
`tools/summarize_window.py logs/fenetre.log --json evidence/resume_fenetre_1h.json`.
