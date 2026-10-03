# Reproducing the console's weather forecast in Home Assistant

Written on request: *"if the station cannot provide the information, the firmware must not invent it —
remove that code and document the rules as tables, to be applied in Home Assistant."* The firmware
side of the estimate has been removed; what follows is the rule book, kept out of the board.

## 1. Why the board publishes no forecast

| Fact | Source |
|---|---|
| The console computes its six icons (Sunny, Partly Cloudy, Cloudy, Rainy, Stormy, Snowy) from **its own barometer**: range 600-1100 hPa, pressure trend over the past hour, and the manual itself warns the accuracy is *"about 65-70%"* | Vevor YT60309 owner's manual, *Weather Forecast*, p. 20 |
| The outdoor 7-in-1 sensor **neither measures nor transmits pressure**. Its payload is temperature, humidity, wind speed, wind direction, rainfall, UV index and illuminance — the 21-byte frame has no pressure field | manual *Specifications*; `references/PROTOCOL.md`; `esphome/components/vevor_7in1/vevor_protocol.h` |
| *"When outdoor temperature is lower than 1 °C/33.8 °F, the snowflake icon will appear"* | manual, *Ice Alert*, p. 20 |

**Consequence: the station's own forecast icon cannot be read off the air with this hardware.** No
firmware can do it. The board therefore publishes measured quantities only, and any forecast is built
in Home Assistant — where it is visible, editable and testable.

## 2. Inputs used below

| Vevor entity (adapt the ids to your naming) | Unit | Used for |
|---|---|---|
| temperature (outdoor) | °C | ice alert, snow/rain split |
| wind gust | km/h | storm branch |
| cumulative rain | mm | rain intensity (differenced) |
| illuminance | lx | cloudiness proxy |
| `sun.sun` attribute `elevation` | ° | clear-sky reference (Home Assistant's `sun` integration) |

## 3. Rule 1 — ice alert (straight from the manual, no firmware needed)

| Condition | Result |
|---|---|
| outdoor temperature **< 1.0 °C** — strictly below, the manual says *"lower than"* | ice alert ON |

## 4. Rule 2 — rain intensity, from the cumulative counter

The station sends a **cumulative** rain counter, 0.233 mm per tip. Intensity only exists as a
difference over time, so the rules that make it meaningful are as important as the formula.

| Parameter | Value | Why |
|---|---|---|
| window | 20 min | long enough that a single tip (0.233 mm) means something: 0.233 mm / 20 min ≈ 0.7 mm/h |
| sampling | 1 sample per 75 s | the station sends one frame every 20 s; 75 s is enough and keeps the history small |
| minimum span before publishing a rate | 5 min | one tip differenced over 90 s would read 9 mm/h — "heavy rain" — purely because the window is short |
| rate formula | `rate_mmh = Δmm × 3 600 000 / Δms` | — |
| counter goes **backwards** by more than 1 mm | the sensor was reset (fresh batteries): restart the window, never compute a negative rate | a new counter says nothing about the old one |
| span shorter than the minimum | report **0 mm/h and "not raining"** | an explicit "not yet" rather than a number the data cannot support |

## 5. Rule 3 — the six states, in priority order

Evaluated top to bottom; the first matching row wins.

| # | State | Condition | Threshold source |
|---|---|---|---|
| 1 | `snowy` | raining **and** temperature < 1 °C | manual p. 20 — same boundary as the ice alert, one rule |
| 2 | `stormy` | raining **and** (rate ≥ **7.6 mm/h** **or** gust ≥ **40 km/h**) | WMO: "heavy rain" starts at 7.6 mm/h; strong breeze / near gale starts at 39 km/h |
| 3 | `rainy` | raining (the counter moved inside the window), not snowy, not stormy | — |
| 4 | `sunny` | not raining, sun elevation ≥ **3°**, illuminance ≥ **0.70 ×** clear-sky reference | ratio set so thin haze still reads sunny |
| 5 | `partly_cloudy` | not raining, sun elevation ≥ 3°, illuminance ≥ **0.35 ×** reference | — |
| 6 | `cloudy` | not raining, sun elevation ≥ 3°, below both ratios | — |
| — | `unknown` | night (elevation < 3°), clock not set, or not enough rain history | deliberately distinct from the six: never invent a value |

## 6. Rule 4 — clear-sky reference (the cloudiness proxy)

| Item | Value |
|---|---|
| Clear-sky horizontal illuminance, Kittler/CIE approximation | `Ev = 133 800 × sin(elevation)^1.15` lx (good to roughly ±20 %, ample for a three-way split) |
| Ignore the proxy below | elevation < 3°, **or** a reference below 1 000 lx: atmospheric attenuation dominates and the ratio becomes meaningless |
| Split | `sunny` ≥ 0.70, `partly_cloudy` ≥ 0.35, otherwise `cloudy` |

This is a **proxy for brightness**, not a cloud-cover measurement: it cannot say anything at night,
which is exactly why the night case returns `unknown` instead of a plausible-looking guess.

## 7. Rule 5 — anti-flapping

| Rule | Value |
|---|---|
| do not publish a change until the new raw state has held for | 10 min |
| exception: the first state after a restart | 60 s |

## 8. Sketch in Home Assistant

Starting point, meant to be adapted and tested in your own configuration — it is not deployed
anywhere and has not been exercised against a live Home Assistant.

```yaml
# Rain intensity: difference of the cumulative counter over 20 minutes.
sensor:
  - platform: statistics
    name: "Vevor rain intensity"
    entity_id: sensor.pluie_cumulee        # cumulative rain, mm
    state_characteristic: change
    sampling_size: 20
    max_age: { minutes: 20 }
    # Report 0 rather than a meaningless rate while the window is shorter than 5 min:
    # gate the published value with a template sensor on this raw one.

# The six states. sun.sun's elevation attribute is provided by Home Assistant's `sun` integration.
template:
  - sensor:
      - name: "Vevor forecast (estimate)"
        unique_id: vevor_forecast_estimation
        state: >-
          {% set t    = states('sensor.temperature_exterieure') | float(none) %}
          {% set gust = states('sensor.vent_rafale')            | float(0) %}
          {% set rain = states('sensor.vevor_rain_intensity')   | float(0) %}
          {% set lux  = states('sensor.luminosite')             | float(0) %}
          {% set elev = state_attr('sun.sun', 'elevation')      | float(-90) %}
          {% set clear = 133800 * (elev | sin) ** 1.15 if elev > 0 else 0 %}
          {% set raining = rain > 0 %}
          {% if raining and t is not none and t < 1 %}snowy
          {% elif raining and (rain >= 7.6 or gust >= 40) %}stormy
          {% elif raining %}rainy
          {% elif elev >= 3 and clear >= 1000 %}
            {% set r = lux / clear %}
            {% if r >= 0.70 %}sunny{% elif r >= 0.35 %}partly_cloudy{% else %}cloudy{% endif %}
          {% else %}unknown{% endif %}
```

Notes on the sketch:

* the **anti-flapping** rule (§7) is not in the template: add it with a `trigger`ed template sensor or
  an automation holding the value, so a single frame cannot flip the icon;
* the **"not yet"** rule (§4) needs the window's span, which the `statistics` sensor does not expose —
  gate the rate on a template sensor or on `last_changed` of the counter;
* the **ice alert** is one line: `binary_sensor` on `temperature < 1`, exactly as the manual defines it.

## 9. What this will never give you

* the console's own icon — it comes from a barometer we cannot read;
* a cloud-cover measurement — only a brightness ratio;
* anything at night: `unknown` is the honest answer;
* and the manual's own reservation applies to any pressure-based forecast, ours included: *"Forecasts
  are not guaranteed. It may not necessarily reflect the current situation."*
