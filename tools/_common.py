#!/usr/bin/env python3
"""Socle partagé des outils du projet Vevor 7-en-1.

Rassemble ce qui était recopié d'un script à l'autre : chemins, chargement de la
clé API (UN seul comportement), connexion native ESPHome, table des variantes de
firmware, motifs de regex et écritures atomiques.

Contrat de code retour (imposé à tout le dépôt) :
    RC_OK           = 0  succès ; comprend le RÉSULTAT NÉGATIF « aucune trame »
                          (une mesure faite qui ne trouve rien est un résultat,
                          pas un échec).
    RC_SIGNAL_ABSENT= 1  réservé aux outils dont le contrat historique distingue
                          explicitement « rien reçu » (ex. tcp_probe, eval_frames).
    RC_ERREUR       = 2  échec TECHNIQUE : connexion, fichier, capture, écriture
                          d'un réglage non prise par la carte.
    RC_MESURE_NULLE = 3  RIEN N'A ÉTÉ MESURÉ : aucun état d'entité reçu, fichier
                          de log vide, capture vide, aucune ligne de démarrage.
                          Toujours distinct d'un RC_OK « aucune trame ».

Aucun effet de bord à l'import : pas d'argparse, pas d'asyncio.run, pas de
connexion. aioesphomeapi n'est importé qu'au moment d'ouvrir un `Device`, pour
que les outils purement fichiers (eval_frames, summarize_window) restent
utilisables sans la bibliothèque d'API.
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

# --- Chemins : UNE SEULE racine, jamais le CWD ------------------------------
ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_YAML = ROOT / "esphome" / "vevor-7in1.yaml"
SECRETS_YAML = ROOT / "esphome" / "secrets.yaml"
DEFAULT_HOST = "172.16.0.205"
DEFAULT_PORT = 6053
ESPHOME = ROOT / ".venv" / "bin" / "esphome"
PY = ROOT / ".venv" / "bin" / "python"
# Témoin (projet de référence) construit HORS dépôt ; paramétrable.
TEMOIN = pathlib.Path(os.environ.get(
    "VEVOR_TEMOIN_DIR", str(pathlib.Path.home() / "projets" / "_temoins")))

# --- Codes retour -----------------------------------------------------------
RC_OK = 0
RC_SIGNAL_ABSENT = 1
RC_ERREUR = 2
RC_MESURE_NULLE = 3


# Bloc `encryption:` du YAML ESPHome (privé : le seul point d'entrée public de
# la clé est `key_from_yaml` / `resolve_key`).
_KEY_RE = re.compile(r"encryption:\s*\n(?:[ \t].*\n)*?[ \t]+key:\s*(.+?)\s*$", re.M)


def out_path(p) -> pathlib.Path:
    """Résout un chemin de SORTIE : un chemin relatif vise la RACINE du projet.

    Décision unique du dépôt (§1.6 de la revue) : `--out`/`--json` relatifs ne
    dépendent jamais du répertoire courant, sinon lancer un outil depuis /tmp
    écrit ailleurs selon le script.
    """
    path = pathlib.Path(p)
    return path if path.is_absolute() else ROOT / path


def key_from_yaml(path=None) -> str | None:
    """Clé de chiffrement de l'API native, lue dans le YAML ESPHome.

    UN SEUL comportement, pour tout le dépôt :
    - `key: <base64>`          -> renvoyée telle quelle ;
    - `key: !secret <nom>`     -> résolue dans le `secrets.yaml` situé À CÔTÉ
                                  du YAML (par défaut `esphome/secrets.yaml`).
    Renvoie None si `path` n'existe pas ou si le bloc `encryption:` est absent
    (API non chiffrée).
    Lève FileNotFoundError si `!secret` est demandé mais que le nom ou le
    `secrets.yaml` manque : JAMAIS un None silencieux (il produisait le message
    trompeur « Connection requires encryption »).
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
        raise FileNotFoundError(f"!secret {name!r} demandé mais {secrets} est absent")
    sm = re.search(rf"^{re.escape(name)}:\s*(\S+)",
                   secrets.read_text(encoding="utf-8", errors="replace"), re.M)
    if not sm:
        raise FileNotFoundError(f"clé {name!r} absente de {secrets}")
    return sm.group(1).strip().strip("\"'")


def resolve_key(explicit=None, yaml_path=None) -> str | None:
    """Point d'entrée unique : --key > $ESPHOME_API_KEY > YAML (via key_from_yaml)."""
    return explicit or os.environ.get("ESPHOME_API_KEY") or key_from_yaml(yaml_path)


# --- Utilitaires async ------------------------------------------------------
async def maybe_await(value):
    """`subscribe_logs`/`subscribe_states`/`button_command` renvoient tantôt une
    coroutine tantôt l'objet selon la version d'aioesphomeapi : un `await` en dur
    casse selon la version."""
    return await value if inspect.isawaitable(value) else value


def _aioesphomeapi():
    """Import tardif : les outils purement fichiers ne dépendent pas de l'API."""
    import aioesphomeapi
    return aioesphomeapi


# --- Connexion native ESPHome ----------------------------------------------
class Device:
    """Contexte async : connexion, liste d'entités, états abonnés, compteurs.

    Remplace les connexions ad hoc recopiées (press_button, dump_pulses,
    scan_async) et la classe dupliquée de scan_freq.
    """

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
        """Attend d'avoir reçu au moins `min_states` états. Sans cela, lire 0
        confond « puce muette » et « rien reçu côté API ». Renvoie le nombre
        d'états reçus."""
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
        """Écrit la fréquence ; lève SystemExit si l'entité est introuvable."""
        k = self.key_of(FREQ_RE)
        if k is None:
            raise SystemExit("entité « Fréquence CC1101 » introuvable — firmware à jour ? (--list)")
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
        return num(self.get("Trames valides")), num(self.get("Trames rejetées")), rssi


# --- Table des variantes : SOURCE DE VÉRITÉ UNIQUE --------------------------
# nom : (répertoire de travail, YAML, binaire OTA figé, description)
VARIANTS: dict[str, tuple[pathlib.Path, str, pathlib.Path, str]] = {
    "temoin": (TEMOIN / "witness-test", "witness.yaml",
               TEMOIN / "witness-test/.esphome/build/vevor-weather-station/build/firmware.ota.bin",
               "projet de référence (WizardPC/esphome-vevor-7in1), compilé par nos soins"),
    "origine": (ROOT / "esphome", "vevor-7in1.yaml",
                ROOT / "build/variants/nous_pilote_origine.ota.bin",
                "pilote d'origine d'ESPHome, notre YAML"),
    "prod": (ROOT / "esphome", "vevor-7in1.yaml",
             ROOT / "build/variants/nous_prod.ota.bin",
             "notre firmware de production"),
    "prod_avant_revue": (ROOT / "esphome", "vevor-7in1.yaml",
                         ROOT / "build/variants/prod_avant_revue.ota.bin",
                         "notre firmware d'avant la revue"),
}


def variant_of(name: str) -> tuple[pathlib.Path, str, pathlib.Path, str]:
    """Renvoie l'entrée VARIANTS ou échoue explicitement et lisiblement.

    Remplace le KeyError nu de boot_probe.py : un nom inconnu n'est plus une
    trace, c'est un message qui liste les variantes disponibles.
    """
    try:
        return VARIANTS[name]
    except KeyError:
        raise SystemExit(
            f"variante inconnue : {name!r} — disponibles : {', '.join(sorted(VARIANTS))}")


# --- Motifs partagés --------------------------------------------------------
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Ancrés au début de ligne : `TS_RE` ne doit pas matcher un [12:34:56] en milieu.
TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")
# ANCRÉ volontairement : `fr[ée]quence` sans ancre matchait aussi « Offset
# fréquence » (capteur), et `key_of()` prend le premier nom correspondant dans
# l'ordre de livraison des entités. Un `number_command` envoyé à la clé d'un
# capteur est silencieusement ignoré par l'appareil : le réglage ne faisait RIEN,
# sans aucune erreur. NE JAMAIS désancrer ce motif.
FREQ_RE = re.compile(r"^\s*fr[ée]quence", re.I)      # « Fréquence CC1101 »
VALID_RE = re.compile(r"^\s*trames valides", re.I)
REJECT_RE = re.compile(r"^\s*trames rejet", re.I)
RSSI_RE = re.compile(r"^\s*rssi\b", re.I)
CAP_RE = re.compile(r"captures=(\d+) \(\+(\d+)\)")
RAW_RE = re.compile(r"RAW[ :=]+((?:[0-9a-fA-F]{2}[ \t]+){20}[0-9a-fA-F]{2})")
OK_RE = re.compile(r"OK[ :=]+(\{.*\})")


# --- Écriture atomique ------------------------------------------------------
def atomic_write_text(out, text: str) -> pathlib.Path:
    """Écriture ATOMIQUE : fichier temporaire dans le même répertoire, fsync,
    puis os.replace. Jamais de fichier tronqué si l'outil est interrompu.
    Un chemin relatif est résolu par rapport à ROOT (jamais au CWD)."""
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
    """Idem `atomic_write_text`, pour un objet JSON (indenté, non ASCII échappé)."""
    return atomic_write_text(out, json.dumps(obj, ensure_ascii=False, indent=2))
