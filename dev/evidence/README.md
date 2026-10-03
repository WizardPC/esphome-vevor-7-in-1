# Synthetic evidence (versioned)

These files are the checkable trace of the measurements quoted in `state/DONE.md`. The raw logs
(`logs/`, several hundred kB to a few MB) stay **out of the repository** (`.gitignore`) — so they are
**not replayable** after a plain `git clone` — but every report keeps the raw frames (21 bytes per
frame), so the claims remain **checkable**.

| File | Window | What it proves |
|---|---|---|
| `rapport_fenetre_1h.json` | **validated** (`logs/verif_garde_fou_60min.log`) | report of the **independent Python decoder** (`tools/eval_frames.py`): frames found/valid, field-by-field comparison with the C++ firmware, verdict **PASS**, 0 refusal reasons |
| `resume_fenetre_1h.json` | **validated** (same log) | summary of the same window (`tools/summarize_window.py --rapport …`): cadence, gaps, `rejets_firmware`, `wind_dir_deg`, `valeurs_hors_plage`, and the **verdict taken from its report** |
| `resume_fenetre_1h.txt` | **validated** (same log) | human-readable text version of the summary above, produced by the same script (`--txt`) |
| `rapport_fenetre_1h_decalage.json` | **faulty** (`logs/fenetre_1h_cond_20261001.log`) | independent decoder's report on the bit-shift window: verdict **FAIL**, **3 reasons** (decreasing rain, implausible values, 2 TX-counter inconsistencies) |
| `resume_fenetre_1h_decalage.json` | **faulty** (same log) | summary of the faulty window: verdict **FAIL** and **the same 3 reasons** as its report (a summary can no longer contradict its report) |
| `ab_cycle.jsonl` | — | **alternating** measurements, reference vs. our firmware (`tools/ab_cycle.py`). **HISTORICAL — not regenerable from HEAD** (see below) |

## Every summary is PAIRED with its report

`tools/summarize_window.py` is run with `--rapport <rapport_eval_frames.json>`: it **takes the
verdict and the reasons** from the independent decoder and exits with code 1 when the report says
`FAIL`. It adds `wind_dir_deg` and `valeurs_hors_plage`, two anomalies that were **structurally
invisible** in the old format.

⚠️ The `rejets_firmware` field (and `raisons_rejet_firmware`) counts the `V7IN1 REJ` lines **of the
firmware**: it is **not** the independent decoder's verdict (`reasons_fail`). The two measurements
are distinct and can diverge — the faulty window has **no** firmware rejection at all while the
independent decoder condemns it. Never read `rejets_firmware: 0` as a "clean verdict": read
`verdict` / `motifs_fail`.

## `ab_cycle.jsonl` — KEPT, marked historical

**Decision: KEEP** (with the note "historical, not regenerable from HEAD").
Reason: this file documents the experiment that **isolated the cause** of the "0 frame" runs (the
reference firmware decoded while our variants stayed at 0), an experiment still cited by
`state/DONE.md`. It was produced by an earlier version of `ab_cycle.py` and **mixes two campaigns**
(v0/v1 then v2); the `nous_v0/v1/v2` variants have been removed, so **`ab_cycle.py` at HEAD can no
longer regenerate it** identically. It is kept as an archive, not presented as reproducible.

## Regenerating (from a clone that still has the local logs)

The reports were produced from the following real logs (exact names, `logfile` fields):

```sh
# VALIDATED window (180 frames, PASS)
tools/eval_frames.py    logs/verif_garde_fou_60min.log      --json evidence/rapport_fenetre_1h.json
tools/summarize_window.py logs/verif_garde_fou_60min.log \
    --rapport evidence/rapport_fenetre_1h.json \
    --json evidence/resume_fenetre_1h.json  --txt evidence/resume_fenetre_1h.txt

# FAULTY window (181 frames, FAIL — 3 reasons)
tools/eval_frames.py    logs/fenetre_1h_cond_20261001.log   --json evidence/rapport_fenetre_1h_decalage.json
tools/summarize_window.py logs/fenetre_1h_cond_20261001.log \
    --rapport evidence/rapport_fenetre_1h_decalage.json \
    --json evidence/resume_fenetre_1h_decalage.json
```

To capture a new window: `tools/capture_logs.py --host <IP> --seconds 3600
--out logs/verif_garde_fou_60min.log` (a relative path targets the **project root**). The
`--json`/`--out` scripts write **atomically** (temporary file + `os.replace`).
