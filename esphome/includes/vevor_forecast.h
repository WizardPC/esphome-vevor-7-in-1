#pragma once
// Local weather-forecast estimation for the Vevor 7-in-1 868 MHz receiver.
//
// Pure logic: no ESPHome, no hardware. Compiled and exercised off-board by tests/test_decoder.cpp
// (tools/run_tests.sh), exactly like the frame decoder in vevor_protocol.h.
//
// ---------------------------------------------------------------------------------------------
// READ THIS BEFORE COMPARING WITH THE CONSOLE'S ICON
// ---------------------------------------------------------------------------------------------
// The display console shows one of SIX weather icons: Sunny, Partly Cloudy, Cloudy, Rainy,
// Stormy, Snowy. Owner's manual (Vevor YT60309, section "Weather Forecast", p. 20) states how it
// is produced:
//
//   "The built-in barometer can notice atmospheric pressure changes, and based on the data
//    collected, can predict the weather conditions. There are 6 weather icons --- Sunny, Partly
//    Cloudy, Cloudy, Rainy, Stormy and Snowy.
//    NOTE: The accuracy of a general pressure-based forecast is about 65-70%. Forecasts are not
//    guaranteed. It may not necessarily reflect the current situation."
//
// The forecast is therefore computed by the CONSOLE, from the CONSOLE's own barometer
// (specification table: measuring range 600-1100 hPa, pressure trend over the past hour with a
// 2 hPa/0.06 inHg step).
//
// The outdoor 7-in-1 sensor neither measures nor transmits pressure. Its documented payload is
// "temperature, humidity, wind speed, wind direction, rainfall, UVI and light intensity", and the
// 21-byte RF frame decoded here has no pressure field (see vevor_protocol.h and
// references/PROTOCOL.md). Consequence, stated plainly: THE STATION'S OWN FORECAST IS NOT
// RECEIVABLE WITH THIS HARDWARE. No firmware can read it off the air, and this file does not
// pretend to reproduce the console's (undocumented) pressure algorithm.
//
// What this file does: estimate the same six categories from the quantities that ARE received,
// with explicit thresholds, so Home Assistant gets a forecast entity derived only from measured
// data. Two families of states, in this priority order:
//
//   1. Precipitation states come from the rain counter, the outdoor temperature and the wind
//      gust -> SNOWY / STORMY / RAINY. Thresholds are the published WMO ones (see below).
//   2. Clear-sky states come from the measured illuminance compared with a clear-sky model
//      computed from the sun elevation -> SUNNY / PARTLY_CLOUDY / CLOUDY. This is a PROXY: it
//      separates "bright / degraded / dim" sky, it is not a cloud-cover measurement, and it
//      cannot say anything at night (below the horizon the estimator reports UNKNOWN rather than
//      inventing a value).
//
// Third, separate entity, exactly as the manual defines it (p. 20, "Ice Alert"):
//    "When outdoor temperature is lower than 1°C/33.8°F, the snowflake icon will appear on the
//     LCD display."  -> ice_alert(), a plain threshold on the received temperature.
//
// Every threshold used below is named, stated in a comment with its source, and exercised at its
// boundaries by the test suite.

#include <cmath>
#include <cstdint>
#include <cstring>

namespace vevor {

// The six manual categories, plus UNKNOWN for "no defensible answer" (night, no time sync, no
// rain history yet). UNKNOWN is deliberately distinct from the six: it lets Home Assistant show
// "unknown" instead of a plausible-looking but unbacked value.
enum class Forecast : uint8_t {
  UNKNOWN = 0,
  SUNNY,
  PARTLY_CLOUDY,
  CLOUDY,
  RAINY,
  STORMY,
  SNOWY,
};

// Stable identifiers for the published state (never translate these: automations bind to them).
// The French display name lives in the YAML `name:`; this string is the machine value.
inline const char *forecast_name(Forecast f) {
  switch (f) {
    case Forecast::SUNNY:
      return "sunny";
    case Forecast::PARTLY_CLOUDY:
      return "partly_cloudy";
    case Forecast::CLOUDY:
      return "cloudy";
    case Forecast::RAINY:
      return "rainy";
    case Forecast::STORMY:
      return "stormy";
    case Forecast::SNOWY:
      return "snowy";
    default:
      return "unknown";
  }
}

// ---------------------------------------------------------------------------------------------
// Thresholds
// ---------------------------------------------------------------------------------------------

// Manual p. 20: "When outdoor temperature is lower than 1°C/33.8°F, the snowflake icon will
// appear". STRICTLY lower, on the outdoor temperature we receive.
static constexpr float ICE_ALERT_C = 1.0f;
inline bool ice_alert(float temp_c) { return temp_c < ICE_ALERT_C; }

// Rain accumulation window. The station sends one burst every 20 s and the rain counter is a
// cumulative tick counter (0.233 mm per tip), so intensity can only be estimated by differencing
// the counter over time. 16 samples at 75 s ≈ 20 minutes: long enough for a single tip to be
// meaningful (0.233 mm / 20 min ≈ 0.7 mm/h), short enough for the state to follow the weather.
static constexpr size_t RAIN_SAMPLES = 16;
static constexpr uint32_t RAIN_SAMPLE_MS = 75000;
static constexpr uint32_t RAIN_WINDOW_MS = 20u * 60u * 1000u;

// The window only counts as a measurement once it spans this much: a single 0.233 mm tip
// differenced over 90 s would read as 9 mm/h ("heavy rain") purely because the window is short.
// Below MIN_RATE_SPAN_MS the estimator reports "not raining" and a 0 rate — an explicit "I do not
// know yet" rather than a number the data cannot support (the first 5 minutes after a boot).
static constexpr uint32_t MIN_RATE_SPAN_MS = 5u * 60u * 1000u;

// "Raining" = the counter moved at all inside the window.
static constexpr float RAIN_MEASURABLE_MMH = 0.0f;

// STORMY: either a heavy rain rate or a strong gust while it rains.
//  - 7.6 mm/h is the WMO threshold for "heavy rain" (steady rain, 7.6-50 mm/h);
//  - 40 km/h is the lower end of the "strong breeze / near gale" band (39-49 km/h).
static constexpr float STORM_RAIN_MMH = 7.6f;
static constexpr float STORM_GUST_KMH = 40.0f;

// Clear-sky model. Horizontal clear-sky illuminance is approximated by the standard
// Kittler/CIE expression Ev = 133 800 * sin(elevation)^1.15 lux (used in daylight photometry;
// good to roughly ±20 %, which is ample for a three-way bright/degraded/dim split).
// Below MIN_SUN_ELEVATION_DEG the expression is dominated by atmospheric attenuation and the
// ratio becomes meaningless -> UNKNOWN instead of a guess. 3° also covers the "sun below
// horizon" case (negative elevation).
static constexpr float CLEAR_SKY_LUX_COEF = 133800.0f;
static constexpr float CLEAR_SKY_MIN_LUX = 1000.0f;
static constexpr float MIN_SUN_ELEVATION_DEG = 3.0f;
// Measured-lux / clear-sky-lux ratios. Chosen so that a modest haze or thin cloud still reads
// SUNNY and a genuinely overcast sky reads CLOUDY; see the test cases for where they sit.
static constexpr float SUNNY_RATIO = 0.70f;
static constexpr float PARTLY_CLOUDY_RATIO = 0.35f;

// Anti-flapping: the published state only follows the raw state once it has held for HOLD_MS
// (30 frames at 20 s). The very first state of a boot is published sooner (FIRST_HOLD_MS) so
// Home Assistant is not left guessing for ten minutes after every restart.
static constexpr uint32_t FORECAST_HOLD_MS = 10u * 60u * 1000u;
static constexpr uint32_t FORECAST_FIRST_HOLD_MS = 60u * 1000u;

// ---------------------------------------------------------------------------------------------
// Building blocks (free functions: each one is testable on its own)
// ---------------------------------------------------------------------------------------------

// Clear-sky horizontal illuminance for a sun elevation in degrees, in lux. 0 below the horizon.
inline float clear_sky_lux(float elevation_deg) {
  if (!(elevation_deg > 0.0f)) {  // also catches NaN
    return 0.0f;
  }
  const float s = std::sin(elevation_deg * 3.14159265358979323846f / 180.0f);
  return CLEAR_SKY_LUX_COEF * std::pow(s, 1.15f);
}

// Bright / degraded / dim, from measured lux and the clear-sky reference.
inline Forecast classify_sky(float lux, float elevation_deg) {
  if (!(elevation_deg >= MIN_SUN_ELEVATION_DEG)) {
    return Forecast::UNKNOWN;  // night, grazing sun, or NaN
  }
  const float clear = clear_sky_lux(elevation_deg);
  if (clear < CLEAR_SKY_MIN_LUX) {
    return Forecast::UNKNOWN;
  }
  if (!(lux >= 0.0f)) {  // also catches NaN
    return Forecast::UNKNOWN;
  }
  const float ratio = lux / clear;
  if (ratio >= SUNNY_RATIO) {
    return Forecast::SUNNY;
  }
  if (ratio >= PARTLY_CLOUDY_RATIO) {
    return Forecast::PARTLY_CLOUDY;
  }
  return Forecast::CLOUDY;
}

// Rain intensity from a counter difference (mm) over an elapsed time (ms), in mm/h.
inline float rain_rate_mmh(float delta_mm, uint32_t delta_ms) {
  if (delta_ms == 0) {
    return 0.0f;
  }
  return delta_mm * 3600000.0f / (float) delta_ms;
}

// ---------------------------------------------------------------------------------------------
// Estimator
// ---------------------------------------------------------------------------------------------

struct ForecastInputs {
  float temp_c{0.0f};                  // outdoor temperature, °C
  float gust_kmh{0.0f};                // wind gust, km/h
  float rain_mm{0.0f};                 // cumulative rain counter of the frame, mm
  float lux{0.0f};                     // illuminance of the frame, lx
  float sun_elevation_deg{NAN};        // sun elevation, degrees (NAN when unavailable)
  bool time_valid{false};              // is the board's clock set?
  uint32_t now_ms{0};                  // millis()
};

class ForecastEstimator {
 public:
  // Feed one decoded frame; returns the state to publish.
  Forecast update(const ForecastInputs &in) {
    this->update_rain_(in.rain_mm, in.now_ms);

    Forecast raw;
    if (this->raining_) {
      // Precipitation observed in the window: temperature first (snow below the manual's ice
      // threshold, i.e. strictly under 1 °C — the same boundary as the ice alert, one rule),
      // then intensity/wind for the storm/rain split.
      if (ice_alert(in.temp_c)) {
        raw = Forecast::SNOWY;
      } else if (this->rain_rate_ >= STORM_RAIN_MMH || in.gust_kmh >= STORM_GUST_KMH) {
        raw = Forecast::STORMY;
      } else {
        raw = Forecast::RAINY;
      }
    } else if (in.time_valid && !std::isnan(in.sun_elevation_deg)) {
      raw = classify_sky(in.lux, in.sun_elevation_deg);
    } else {
      // No rain and no usable sun position: nothing defensible to say.
      raw = Forecast::UNKNOWN;
    }

    if (raw != this->candidate_) {
      this->candidate_ = raw;
      this->candidate_since_ms_ = in.now_ms;
    }
    const uint32_t hold = this->published_once_ ? FORECAST_HOLD_MS : FORECAST_FIRST_HOLD_MS;
    if (this->candidate_ != this->published_ &&
        (uint32_t) (in.now_ms - this->candidate_since_ms_) >= hold) {
      this->published_ = this->candidate_;
      this->published_once_ = true;
    }
    return this->published_;
  }

  // Last state returned by update().
  Forecast state() const { return this->published_; }
  // Estimated rain intensity over the window, mm/h (also used for the storm split).
  float rain_rate_mmh() const { return this->rain_rate_; }
  // Counter moved inside the window.
  bool raining() const { return this->raining_; }
  // Number of rain samples held (0-16); the estimate only becomes meaningful from 2 samples on.
  size_t rain_samples() const { return this->sample_count_; }

 protected:
  // Ring-less sliding window: 16 entries, chronological, oldest dropped when full (128 bytes
  // moved at most once per 75 s — irrelevant on an ESP32).
  void push_sample_(float rain_mm, uint32_t now_ms) {
    if (this->sample_count_ == RAIN_SAMPLES) {
      std::memmove(&this->sample_ms_[0], &this->sample_ms_[1],
                   (RAIN_SAMPLES - 1) * sizeof(uint32_t));
      std::memmove(&this->sample_mm_[0], &this->sample_mm_[1],
                   (RAIN_SAMPLES - 1) * sizeof(float));
      this->sample_count_--;
    }
    this->sample_ms_[this->sample_count_] = now_ms;
    this->sample_mm_[this->sample_count_] = rain_mm;
    this->sample_count_++;
    this->last_sample_ms_ = now_ms;
  }

  void update_rain_(float rain_mm, uint32_t now_ms) {
    if (std::isnan(this->last_rain_mm_)) {
      // First frame ever: anchor the counter and open the window.
      this->last_rain_mm_ = rain_mm;
      this->push_sample_(rain_mm, now_ms);
    } else if (rain_mm < this->last_rain_mm_ - 1.0f) {
      // The counter went backwards: the sensor was reset (fresh batteries). A new counter says
      // nothing about the old one — restart the window instead of computing a negative rate.
      this->sample_count_ = 0;
      this->last_rain_mm_ = rain_mm;
      this->push_sample_(rain_mm, now_ms);
    } else {
      this->last_rain_mm_ = rain_mm;
      if ((uint32_t) (now_ms - this->last_sample_ms_) >= RAIN_SAMPLE_MS) {
        this->push_sample_(rain_mm, now_ms);
      }
    }

    this->rain_rate_ = 0.0f;
    this->raining_ = false;
    if (this->sample_count_ < 2) {
      return;
    }
    // Oldest sample still inside the window.
    size_t first = 0;
    while (first + 1 < this->sample_count_ &&
           (uint32_t) (now_ms - this->sample_ms_[first]) > RAIN_WINDOW_MS) {
      first++;
    }
    const uint32_t span = (uint32_t) (now_ms - this->sample_ms_[first]);
    if (span == 0) {
      return;
    }
    if (span < MIN_RATE_SPAN_MS) {
      // Window too short to support a rate: say "not raining" rather than "heavy rain".
      return;
    }
    if (span > RAIN_WINDOW_MS + RAIN_SAMPLE_MS) {
      return;
    }
    const float delta_mm = this->sample_mm_[this->sample_count_ - 1] - this->sample_mm_[first];
    // Qualified: the member function of the same name would shadow the free function here.
    this->rain_rate_ = vevor::rain_rate_mmh(delta_mm, span);
    this->raining_ = delta_mm > RAIN_MEASURABLE_MMH;
  }

  uint32_t sample_ms_[RAIN_SAMPLES]{};
  float sample_mm_[RAIN_SAMPLES]{};
  size_t sample_count_{0};
  uint32_t last_sample_ms_{0};
  float last_rain_mm_{NAN};
  float rain_rate_{0.0f};
  bool raining_{false};
  Forecast candidate_{Forecast::UNKNOWN};
  uint32_t candidate_since_ms_{0};
  Forecast published_{Forecast::UNKNOWN};
  bool published_once_{false};
};

}  // namespace vevor
