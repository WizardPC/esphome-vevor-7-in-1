#!/usr/bin/env python3
"""Shared foundation for the Vevor 7-in-1 tools: paths, API key, connection, variants.

Return codes: 0 OK (including the negative result "no frame"), 1 reserved for tools that
distinguish "nothing received", 2 technical error, 3 nothing measured.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import pathlib
import re
import tempfile

# --- Paths: a single root, never the CWD ------------------------------------
DEV = pathlib.Path(__file__).resolve().parent.parent   # dev/
ROOT = DEV.parent                                      # repo root
DEFAULT_YAML = ROOT / "esphome" / "vevor-7in1.yaml"
SECRETS_YAML = ROOT / "esphome" / "secrets.yaml"
# No hardcoded address: the host comes from $VEVOR_HOST, else the tool asks for it.
DEFAULT_HOST = os.environ.get("VEVOR_HOST", "")
DEFAULT_PORT = 6053
ESPHOME = ROOT / ".venv" / "bin" / "esphome"
PY = ROOT / ".venv" / "bin" / "python"
# Witness (reference project) is built outside the repo; overridable via $VEVOR_TEMOIN_DIR.
TEMOIN = pathlib.Path(os.environ.get(
    "VEVOR_TEMOIN_DIR", str(pathlib.Path.home() / "projets" / "_temoins")))

# --- Return codes -----------------------------------------------------------
RC_OK = 0
RC_SIGNAL_ABSENT = 1
RC_ERREUR = 2
RC_MESURE_NULLE = 3


# ESPHome YAML `encryption:` block (private: use key_from_yaml / resolve_key).
_KEY_RE = re.compile(r"encryption:\s*\n(?:[ \t].*\n)*?[ \t]+key:\s*(.+?)\s*$", re.M)


def out_path(p) -> pathlib.Path:
    """Resolve an output path: a relative path targets the repo ROOT, never the CWD."""
    path = pathlib.Path(p)
    return path if path.is_absolute() else ROOT / path


def key_from_yaml(path=None) -> str | None:
    """API encryption key from the ESPHome YAML; resolves `!secret` in the sibling secrets.yaml.

    Returns None when the file or the `encryption:` block is absent; raises FileNotFoundError when
    `!secret` is requested but its name or secrets.yaml is missing (never a silent None).
    """
    yaml_path = pathlib.Path(path) if path else DEFAULT_YAML
    if not yaml_path.is_absolute():
        yaml_path = ROOT / yaml_path
    if not yaml_path.exists():
        return None
    txt = yaml_path.read_text(encoding="utf-8", errors="replace")
    m = _KEY_RE.search(txt)
    if not m:
        return None
    val = m.group(1).strip().strip("\"'")
    if not val.startswith("!secret"):
        return val or None
    parts = val.split(None, 1)
    name = parts[1] if len(parts) > 1 else ""
    secrets = yaml_path.parent / "secrets.yaml"
    if not name or not secrets.exists():
        raise FileNotFoundError(f"!secret {name!r} requested but {secrets} is missing")
    sm = re.search(rf"^{re.escape(name)}:\s*(\S+)",
                   secrets.read_text(encoding="utf-8", errors="replace"), re.M)
    if not sm:
        raise FileNotFoundError(f"key {name!r} missing from {secrets}")
    return sm.group(1).strip().strip("\"'")


def resolve_key(explicit=None, yaml_path=None) -> str | None:
    """Single entry point: --key > $ESPHOME_API_KEY > YAML (via key_from_yaml)."""
    return explicit or os.environ.get("ESPHOME_API_KEY") or key_from_yaml(yaml_path)


# --- Async helpers ----------------------------------------------------------
async def maybe_await(value):
    """Return the value, awaiting it only if awaitable (aioesphomeapi varies by version)."""
    return await value if inspect.isawaitable(value) else value


def _aioesphomeapi():
    """Lazy import: file-only tools must not depend on the API library."""
    import aioesphomeapi
    return aioesphomeapi


# --- Native ESPHome connection ----------------------------------------------
class Device:
    """Async context: connection, entity list, states, counters (replaces ad-hoc copies)."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 key: str | None = None):
        self.host, self.port, self.key = host, port, key
        aio = _aioesphomeapi()
        self.cli = aio.APIClient(
            host, port, None, noise_psk=None if key in (None, "", "None") else key)
        self.state: dict[int, float] = {}
        self.keys: dict[str, int] = {}
        self.info = None

    async def __aenter__(self) -> "Device":
        await self.cli.connect(login=True)
        self.info = await self.cli.device_info()
        entities, _ = await self.cli.list_entities_services()
        for e in entities:
            name = getattr(e, "name", "") or ""
            self.keys[name] = e.key
            if hasattr(e, "state"):
                self.state[e.key] = e.state
        await maybe_await(self.cli.subscribe_states(
            lambda s: self.state.__setitem__(s.key, getattr(s, "state", None))))
        return self

    async def __aexit__(self, *exc) -> None:
        await self.cli.disconnect()

    async def wait_states(self, timeout_s: float = 10.0, min_states: int = 1) -> int:
        """Wait until at least `min_states` states have been received. Otherwise, reading 0
        confuses a "mute chip" with "nothing received on the API side". Returns the number
        of states received."""
        for _ in range(max(1, int(timeout_s / 0.25))):
            if len(self.state) >= min_states:
                break
            await asyncio.sleep(0.25)
        return len(self.state)

    def key_of(self, pattern: re.Pattern) -> int | None:
        for name, k in self.keys.items():
            if pattern.search(name):
                return k
        return None

    def has(self, pattern: re.Pattern) -> bool:
        return self.key_of(pattern) is not None

    def get(self, name: str):
        k = self.keys.get(name)
        return self.state.get(k) if k is not None else None

    def set_freq(self, mhz: float):
        """Write the frequency; raise SystemExit if the entity is missing."""
        k = self.key_of(FREQ_RE)
        if k is None:
            raise SystemExit("entity \"CC1101 frequency\" not found — firmware up to date? (--list)")
        return self.cli.number_command(k, mhz)

    def counts(self) -> tuple[float, float, float | None]:
        def num(v) -> float:
            try:
                return 0.0 if v is None or math.isnan(float(v)) else float(v)
            except (TypeError, ValueError):
                return 0.0

        rssi = self.get("RSSI")
        try:
            if rssi is None or math.isnan(float(rssi)):
                rssi = None
        except (TypeError, ValueError):
            rssi = None
        return num(self.get("Valid frames")), num(self.get("Rejected frames")), rssi


# --- Variant table: single source of truth ----------------------------------
# name: (workdir, YAML, frozen OTA binary, description)
VARIANTS: dict[str, tuple[pathlib.Path, str, pathlib.Path, str]] = {
    "temoin": (TEMOIN / "witness-test", "witness.yaml",
               TEMOIN / "witness-test/.esphome/build/vevor-weather-station/build/firmware.ota.bin",
               "reference project (WizardPC/esphome-vevor-7in1), compiled by us"),
    "origine": (ROOT / "esphome", "vevor-7in1.yaml",
                DEV / "build/variants/nous_pilote_origine.ota.bin",
                "ESPHome original driver, our YAML"),
    "prod": (ROOT / "esphome", "vevor-7in1.yaml",
             DEV / "build/variants/nous_prod.ota.bin",
             "our production firmware"),
    "prod_corrige": (ROOT / "esphome", "vevor-7in1.yaml",
                     DEV / "build/variants/nous_prod_corrige.ota.bin",
                     "our driver + the 03/10 fix (GDO0 interrupt attached before any early return)"),
    "prod_avant_revue": (ROOT / "esphome", "vevor-7in1.yaml",
                         DEV / "build/variants/prod_avant_revue.ota.bin",
                         "our firmware from before the review"),
}


def variant_of(name: str) -> tuple[pathlib.Path, str, pathlib.Path, str]:
    """Return the VARIANTS entry, or exit with the list of available variants (no bare KeyError)."""
    try:
        return VARIANTS[name]
    except KeyError:
        raise SystemExit(
            f"unknown variant: {name!r} — available: {', '.join(sorted(VARIANTS))}")


# --- Shared patterns --------------------------------------------------------
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Anchored at line start: TS_RE must not match a [12:34:56] mid-line.
TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")
# Anchored on purpose: an unanchored pattern also matched the "Offset" sensor, whose name
# contains the same French word — its key silently ignores number_command and the setting did
# nothing. Never unanchor it.
FREQ_RE = re.compile(r"cc1101 frequency", re.I)      # entity "CC1101 frequency"
VALID_RE = re.compile(r"^\s*trames valides", re.I)
REJECT_RE = re.compile(r"^\s*trames rejet", re.I)
RSSI_RE = re.compile(r"^\s*rssi\b", re.I)
CAP_RE = re.compile(r"captures=(\d+) \(\+(\d+)\)")
RAW_RE = re.compile(r"RAW[ :=]+((?:[0-9a-fA-F]{2}[ \t]+){20}[0-9a-fA-F]{2})")
OK_RE = re.compile(r"OK[ :=]+(\{.*\})")


# --- Atomic write -----------------------------------------------------------
def atomic_write_text(out, text: str) -> pathlib.Path:
    """Atomic write: temp file, fsync, os.replace; relative paths resolve to ROOT."""
    p = out_path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def atomic_write_json(out, obj) -> pathlib.Path:
    """Same as atomic_write_text, for a JSON object (indented, non-ASCII kept)."""
    return atomic_write_text(out, json.dumps(obj, ensure_ascii=False, indent=2))
