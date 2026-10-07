#!/usr/bin/env python3
"""Binary identity: queries the ESPHome native API (device_info -> compilation_time)."""
from __future__ import annotations
import asyncio, pathlib, sys, os
sys.path.insert(0, "/home/hermes/projets/vevor-7in1/dev/tools")
from _common import resolve_key  # noqa

import aioesphomeapi

async def run():
    key = resolve_key(None)
    print("key used:", "yes" if key else "none")
    cli = aioesphomeapi.APIClient("172.16.0.205", 6053, None, noise_psk=key)
    await cli.connect(login=True)
    info = await cli.device_info()
    print("device_info:")
    for champ in ("name", "friendly_name", "mac_address", "esphome_version", "compilation_time",
                  "model", "manufacturer", "project_name", "project_version"):
        print("   %-18s %s" % (champ, getattr(info, champ, "(missing)")))
    await cli.disconnect()

asyncio.run(run())
