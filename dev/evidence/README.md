# Evidence (versioned)

These files are the checkable trace of the project's measurements. The raw logs (`dev/logs/`, hundreds of
kB to a few MB) stay **out of the repository** (`.gitignore`) — so they are **not replayable** after a
plain `git clone` — but every report keeps the raw frames (21 bytes per frame), so the claims remain
**checkable**. Paths below are relative to the **repository root**.

| File | Window | What it proves |
|---|---|---|
| `rapport_fenetre_1h.json` | **validated** (`dev/logs/verif_garde_fou_60min.log`) | report of the **independent Python decoder** (`dev/tools/eval_frames.py`): 180 frames, field-by-field comparison with the C++ firmware, verdict **PASS**, 0 refusal reasons |
| `resume_fenetre_1h.json` | validated (same log) | summary of the same window (`dev/tools/summarize_window.py --report …`): cadence, gaps, `firmware_rejects`, `wind_dir_deg`, `out_of_range_values`, and the **verdict taken from its report** |
| `resume_fenetre_1h.txt` | validated (same log) | human-readable text version of the summary above (`--txt`) |
| `rapport_fenetre_1h_decalage.json` | **faulty** (`dev/logs/fenetre_1h_cond_20261001.log`) | independent decoder's report on the bit-shift window: 181 frames, verdict **FAIL**, **3 reasons** (decreasing rain, implausible values, 2 TX-counter inconsistencies) |
| `resume_fenetre_1h_decalage.json` | faulty (same log) | summary of the faulty window: verdict **FAIL** and **the same 3 reasons** as its report |
| `apres_periode.json` | — | the "measured period + bounded repairs" window (880 s, 45 frames, 0 missed). **HISTORICAL** (see below) |
| `ab_cycle.jsonl` | — | **alternating** measurements, reference vs. our firmware. **HISTORICAL** (see below) |

## Every summary is PAIRED with its report

`dev/tools/summarize_window.py` is run with `--report <report.json>`: it **takes the verdict and the
reasons** from the independent decoder and exits with code 1 when the report says `FAIL`. It adds
`wind_dir_deg` and `out_of_range_values`, two anomalies that were structurally invisible before.

⚠️ Two reading traps. `firmware_rejects` counts the **firmware's** `V7IN1 REJ` lines, **not** the decoder's
verdict (`reasons_fail`): the faulty window has **no** firmware rejection at all while the decoder condemns
it, so never read `firmware_rejects: 0` as a clean verdict — read `verdict` / `reasons_fail`. And
`frames_valid` means **header + checksum + counter only**; physical plausibility lives in
`findings`/`reasons_fail` and in the verdict.

## Regenerating (from a clone that still has the local logs)

```sh
# VALIDATED window (180 frames, PASS)
dev/tools/eval_frames.py    dev/logs/verif_garde_fou_60min.log    --json dev/evidence/rapport_fenetre_1h.json
dev/tools/summarize_window.py dev/logs/verif_garde_fou_60min.log \
    --report dev/evidence/rapport_fenetre_1h.json \
    --json dev/evidence/resume_fenetre_1h.json --txt dev/evidence/resume_fenetre_1h.txt

# FAULTY window (181 frames, FAIL — 3 reasons)
dev/tools/eval_frames.py    dev/logs/fenetre_1h_cond_20261001.log --json dev/evidence/rapport_fenetre_1h_decalage.json
dev/tools/summarize_window.py dev/logs/fenetre_1h_cond_20261001.log \
    --report dev/evidence/rapport_fenetre_1h_decalage.json \
    --json dev/evidence/resume_fenetre_1h_decalage.json
```

To capture a new window: `dev/tools/capture_logs.py --host <IP> --seconds 3600 --out dev/logs/window.log`.
The `--json`/`--out` scripts write **atomically** (temporary file + `os.replace`).

These JSON files were regenerated at the current tree. Their **structural key names** are the ones the
tools emit; the human-readable **values** (findings, verdicts, refusal reasons) are English.

## Historical files (kept, but not regenerable from the current tree)

`apres_periode.json` captures the "measured period + bounded repairs" step (45 published frames, 45
distinct TX counters, 0 missed emission, chip present on the SPI bus throughout). It is French-keyed and
its generator is **not** in the repository.

`ab_cycle.jsonl` documents the experiment that **isolated the cause** of the "0 frame" runs (the reference
firmware decoded while our variants stayed at 0). It **mixes two campaigns** (v0/v1, then v2) produced by
an earlier `ab_cycle.py`; that tool — and its `nous_v0/v1/v2` variants — have been removed, so the file can
no longer be regenerated. It is kept as an archive, not presented as reproducible.
