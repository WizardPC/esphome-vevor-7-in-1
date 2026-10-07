# Home Assistant integration — what is verified, what is scriptable

HA: `192.168.2.104`. Target add-on: **ESPHome Device Builder** (slug `esphome`).

> **Status as of 02/10/2026** (banner added, commit 9693dbe). The facts about the add-on below (slug,
> image, version 2026.9.1, `uart: true`, `map: config:rw`) are repository readings: valid as
> references. **However, the section "Polling to do as soon as the HA token is available" is not
> applicable as it stands**: the HA token (`~/projets/vevor-7in1/.ha_token`) is now **present**
> (183 B, 30/09), but **the HA API on port 8123 does not respond** — measured on 02/10:
> `http://192.168.2.104:8123/api/` fails, only port 80 (HAOS observer) responds. Consistent with
> `state/PROGRESS.md` ("no service on 8123", 30/09). Do not count on a weather cross-check via
> the HA API as long as HA Core does not listen again on 8123.


## Verified facts about the add-on (read in `esphome/home-assistant-addon`, branch main)

- `slug: esphome`, name "ESPHome Device Builder", image `ghcr.io/esphome/esphome-hassio`,
  version `2026.9.1` — same version as the ESPHome installed in this container.
- `uart: true` → **the add-on has access to the HA host's serial ports**: it can flash
  the ESP32 over USB if the board is plugged into the machine running HA.
- `map: config:rw` → the configurations live in `/config/esphome` (HA folder).
- `ingress: true`, `ingress_port: 0` → the interface is normally accessible via HA
  ingress (therefore behind HA authentication).
- `ports: 6052/tcp: null` → **port 6052 is not exposed by default**; it can be opened
  in the add-on configuration (`6052/tcp: 6052`) to talk directly to the dashboard.
- Configuration options: `leave_front_door_open` (disables all authentication of the
  dashboard — only acceptable on a trusted LAN), `default_compile_process_limit`,
  `home_assistant_dashboard_integration`.

## Dashboard API (extracted from the official `esphome-dashboard` bundle)

- `POST /compile?configuration=<file>.yaml` (and `only_generate=true`) → returns the compilation
  log as a stream. **This is the most useful endpoint: it compiles without complex
  authentication as soon as the port is exposed.**
- `GET /edit?configuration=<file>.yaml` → returns the YAML content (allows re-reading what
  is in HA).
- `GET|POST /delete?configuration=...` → deletes a configuration.
- **Installation (flash) and log follow-up go through a WebSocket**, not through these
  endpoints. The exact message format remains to be confirmed by polling once access is
  open (path and protocol not publicly documented).

## Practical consequence: the role split

| Step | Where | Why |
|---|---|---|
| Compilation | this container (`tools/build.sh`) | toolchain already operational and verified |
| First flash | ESPHome Builder add-on (USB on the HA host) **or** web.esphome.io | the add-on has UART access, this container does not |
| Subsequent flashes | this container, OTA (`tools/flash.sh <IP>`) | no dependency on HA, faster |
| Logs | this container, native API port 6053 | structured, filterable, independent of HA |
| Frequency sweep | this container, `number` entity via the API | no reflash needed |
| Final values | ESPHome integration in HA | the board is discovered and tracked normally |

Palliative that even removes the first manual flash: pass the Proxmox host's USB port
into the LXC (see README). The agent then flashes everything itself, over USB.

## Polling to do as soon as the HA token is available

```bash
H=http://192.168.2.104:8123
TOKEN=$(<~/projets/vevor-7in1/.ha_token)
curl -s -H "Authorization: Bearer ***" $H/api/ | jq .
curl -s -H "Authorization: Bearer ***" $H/api/config | jq '{latitude, longitude, version}'
# add-on present? state? port exposed? (needs an admin account)
curl -s -H "Authorization: Bearer ***" $H/api/hassio/addons/esphome/info | jq '{state, ingress_url, network, options}'
# does the dashboard respond directly?
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.104:6052/devices
```

The token is also used for the independent weather cross-check: HA knows the latitude/longitude
(and possibly a local weather station) to compare the decoded temperature/humidity.
