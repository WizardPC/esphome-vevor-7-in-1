#!/usr/bin/env python3
import json, urllib.request, os
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
def get(path):
    req = urllib.request.Request("http://192.168.2.104" + path,
                                 headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())
print("api/ ->", get("/api/"))
st = get("/api/states")
print(len(st), "entites")
for x in st:
    e = x["entity_id"]
    if "vevor" in e or "esp32_weather" in e:
        print(e, "=", x["state"], "|", x.get("last_changed"))
