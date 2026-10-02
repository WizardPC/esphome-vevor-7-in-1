# Intégration Home Assistant — ce qui est vérifié, ce qui est scriptable

HA : `192.168.2.104`. Add-on visé : **ESPHome Device Builder** (slug `esphome`).

> **Statut au 02/10/2026** (bandeau ajouté, commit 9693dbe). Les faits sur l'add-on ci-dessous (slug,
> image, version 2026.9.1, `uart: true`, `map: config:rw`) sont des lectures de dépôt : valables comme
> référence. **En revanche, la section « Sondage à faire dès que le token HA est disponible » n'est pas
> applicable en l'état** : le token HA (`~/projets/vevor-7in1/.ha_token`) est désormais **présent**
> (183 o, 30/09), mais **l'API HA sur le port 8123 ne répond pas** — mesuré le 02/10 :
> `http://192.168.2.104:8123/api/` échoue, seul le port 80 (observateur HAOS) répond. Cohérent avec
> `state/PROGRESS.md` (« aucun service sur 8123 », 30/09). Ne pas compter sur un recoupement météo via
> l'API HA tant que HA Core ne réécoute pas sur 8123.


## Faits vérifiés sur l'add-on (lus dans `esphome/home-assistant-addon`, branche main)

- `slug: esphome`, nom « ESPHome Device Builder », image `ghcr.io/esphome/esphome-hassio`,
  version `2026.9.1` — même version qu'ESPHome installé dans ce conteneur.
- `uart: true` → **l'add-on a accès aux ports série de l'hôte HA** : il peut flasher
  l'ESP32 en USB si la carte est branchée sur la machine qui fait tourner HA.
- `map: config:rw` → les configurations vivent dans `/config/esphome` (dossier HA).
- `ingress: true`, `ingress_port: 0` → l'interface est normalement accessible via l'ingress
  HA (donc derrière l'authentification HA).
- `ports: 6052/tcp: null` → **le port 6052 n'est pas exposé par défaut** ; on peut l'ouvrir
  dans la configuration de l'add-on (`6052/tcp: 6052`) pour parler directement au dashboard.
- Options de configuration : `leave_front_door_open` (désactive toute authentification du
  dashboard — uniquement acceptable sur un LAN de confiance), `default_compile_process_limit`,
  `home_assistant_dashboard_integration`.

## API du dashboard (extraite du bundle officiel `esphome-dashboard`)

- `POST /compile?configuration=<fichier>.yaml` (et `only_generate=true`) → renvoie le journal
  de compilation en flux. **C'est l'endpoint le plus utile : il compile sans authentification
  complexe dès lors que le port est exposé.**
- `GET /edit?configuration=<fichier>.yaml` → renvoie le contenu YAML (permet de relire ce
  qu'il y a dans HA).
- `GET|POST /delete?configuration=...` → supprime une configuration.
- L'**installation (flash) et le suivi des logs passent par un WebSocket**, pas par ces
  endpoints. Le format exact des messages reste à confirmer par sondage une fois l'accès
  ouvert (chemin et protocole non documentés publiquement).

## Conséquence pratique : le partage des rôles

| Étape | Où | Pourquoi |
|---|---|---|
| Compilation | ce conteneur (`tools/build.sh`) | toolchain déjà opérationnelle et vérifiée |
| Premier flash | add-on ESPHome Builder (USB sur l'hôte HA) **ou** web.esphome.io | l'add-on a l'accès UART, pas ce conteneur |
| Flashs suivants | ce conteneur, OTA (`tools/flash.sh <IP>`) | pas de dépendance à HA, plus rapide |
| Logs | ce conteneur, API native port 6053 | structuré, filtrable, indépendant de HA |
| Balayage fréquence | ce conteneur, entité `number` via l'API | aucun reflash nécessaire |
| Valeurs finales | intégration ESPHome dans HA | la carte est découverte et suivie normalement |

Palliatif qui supprime même le premier flash manuel : passer le port USB de l'hôte Proxmox
dans le LXC (voir README). L'agent flashe alors tout lui-même, en USB.

## Sondage à faire dès que le token HA est disponible

```bash
H=http://192.168.2.104:8123
TOKEN=$(<~/projets/vevor-7in1/.ha_token)
curl -s -H "Authorization: Bearer $TOKEN" $H/api/ | jq .
curl -s -H "Authorization: Bearer $TOKEN" $H/api/config | jq '{latitude, longitude, version}'
# add-on présent ? état ? port exposé ? (nécessite un compte admin)
curl -s -H "Authorization: Bearer $TOKEN" $H/api/hassio/addons/esphome/info | jq '{state, ingress_url, network, options}'
# le dashboard répond-il directement ?
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.104:6052/devices
```

Le token sert aussi au recoupement météo indépendant : HA connaît la latitude/longitude
(et éventuellement une station météo locale) pour comparer la température/humidité décodée.
