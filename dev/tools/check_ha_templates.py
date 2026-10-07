#!/usr/bin/env python3
"""Every template in the versioned HA card must be ACCEPTED by Home Assistant.

Why this exists. The card's sky icon used `(elevation | sin)` on a value in DEGREES, while HA's
`sin` filter takes RADIANS. For any normal elevation the sine was negative, `** 1.15` then produced
a complex number, HA refused the whole template — and the icon silently disappeared from the card.
The offline simulation in check_ha_card.py could not see it: it defined `sin` itself, in degrees, so
it agreed with the card and disagreed with HA. A checker that re-implements the logic can only ever
test its own version of it.

So this check simulates nothing: it posts each template to Home Assistant and fails on any refusal.
If HA is unreachable it says SKIPPED out loud rather than pretending to have verified anything.

    dev/tools/check_ha_templates.py [card.yaml]
"""

import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
HA_URL = "http://192.168.2.104"


def templates(node, out):
    """Collect every string that contains template syntax, wherever it sits in the card."""
    if isinstance(node, dict):
        for value in node.values():
            templates(value, out)
    elif isinstance(node, list):
        for value in node:
            templates(value, out)
    elif isinstance(node, str) and ("{{" in node or "{%" in node):
        out.append(node)


def main() -> int:
    try:
        import yaml
    except ImportError:
        sys.exit("missing dependency (PyYAML) — run with .venv/bin/python")

    card_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dev/docs/ha-card.yaml"
    found = []
    templates(yaml.safe_load(card_path.read_text(encoding="utf-8")), found)
    token = (ROOT / ".ha_token").read_text(encoding="utf-8").strip()

    refused = 0
    for template in found:
        flat = " ".join(template.split())
        request = urllib.request.Request(
            HA_URL + "/api/template",
            data=json.dumps({"template": template}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            rendered = urllib.request.urlopen(request, timeout=20).read().decode().strip()
            print("   OK       %-52s -> %s" % (flat[:52], " ".join(rendered.split())[:60]))
        except urllib.error.HTTPError as e:
            refused += 1
            print("   REFUSED  %-52s -> %s" % (flat[:52], e.read().decode()[:140]))
        except Exception as e:  # network down, HA restarting…
            print("   SKIPPED  Home Assistant unreachable (%s): the card's templates are NOT verified" % e)
            return 0

    print("   %d template(s) submitted, %d refused by Home Assistant" % (len(found), refused))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
