// Unit tests for the Vevor 7-in-1 decoder — run WITHOUT hardware.

// Built by tests/run_tests.sh with the compiler in .venv-dev (zig c++). Test frames come from
// tests/frames.py (an independent Python encoder): C++ and Python start from the same spec but
// are written separately, so agreement between them is a real check, not a restatement.

// Usage: tests/test_decoder   (exit code 0 = all passed)

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "vevor_protocol.h"
#include "vectors.h"
#include "pulses.h"
#include "captures.h"

static int g_failures = 0;
static int g_checks = 0;

static const char *CHECK = "\033[32mOK\033[0m";
static const char *FAIL = "\033[31mÉCHEC\033[0m";

static void expect(bool condition, const std::string &label) {
  g_checks++;
  if (!condition) {
    g_failures++;
    printf("  [%s] %s\n", FAIL, label.c_str());
  }
}

static void expect_near(float got, float want, float tol, const std::string &label) {
  g_checks++;
  if (std::fabs(got - want) > tol) {
    g_failures++;
    printf("  [%s] %s : obtenu %.3f, attendu %.3f (±%.3f)\n", FAIL, label.c_str(), got, want, tol);
  }
}

// --- 1. Valid frames decode exactly as the encoder announces ------------------
static void test_vectors() {
  printf("Valid frames et invalides (%d scénarios)\n", VEVOR_VECTOR_COUNT);
  for (int i = 0; i < VEVOR_VECTOR_COUNT; i++) {
    const VevorVector &v = VEVOR_VECTORS[i];
    vevor::Frame f;
    const char *reason = "";
    bool ok = vevor::decode(v.raw, f, &reason);

    std::string name(v.name);
    expect(ok == v.valid, name + " : verdict " + (ok ? "valide" : "rejeté") +
                                (v.valid ? " (attendu valide)" : " (attendu rejeté, motif " +
                                                                    std::string(reason) + ")"));
    if (!v.valid) {
      expect(std::strlen(reason) > 0, name + " : un motif de rejet doit être renseigné");
      // The exact reason matters: blaming the wrong plausibility branch ("direction" instead
      // of "wind", e.g.) would otherwise go unnoticed.
      expect(std::strcmp(reason, v.reject_reason) == 0,
             name + " : motif attendu « " + std::string(v.reject_reason) + " », obtenu « " +
                 std::string(reason) + " »");
      continue;
    }

    expect(f.id == v.id, name + " : id");
    expect(f.channel == v.channel, name + " : canal");
    expect(f.battery_low == v.battery_low, name + " : batterie");
    expect_near(f.temp_c, v.temp_c, 0.06f, name + " : température");
    expect(f.humidity == v.humidity, name + " : humidité");
    expect_near(f.wind_kmh, v.wind_kmh, 0.06f, name + " : vent");
    expect_near(f.gust_kmh, v.gust_kmh, 0.06f, name + " : rafale");
    expect(f.wind_dir_deg == v.wind_dir_deg, name + " : direction");
    expect_near(f.rain_mm, v.rain_mm, 0.06f, name + " : pluie");
    expect(f.uv_index == v.uv, name + " : UV");
    expect(f.lux == v.lux, name + " : luminosité");
    expect(f.tx_counter == v.tx_counter, name + " : compteur TX");
  }
}

// --- 2. rtl_433 reference frame, expected hard-coded ---------------------------
// Expected values computed BY HAND from the rtl_433 source (src/devices/vevor_7in1.c)
// and the frame bytes: the EXTERNAL ANCHOR of decoding.

// A formula error shared by the Python encoder (tests/frames.py) and the C++ would pass the
// whole suite. Useful bytes after the -1 on bytes 8, 9, 11, 12, 13, 14, 16, 17:

//   wind = ((b8<<8)|b9)/8.333f = 13/8.333 = 1.56 km/h ; gust = b10/1.25f = 3/1.25 = 2.4 km/h
//   rain = ((b13<<8)|b14)*0.233f = 55*0.233 = 12.8 mm
//   lux  = (b16<<8)|b17, ×10 if bit 15 set = 14457 lx
static void test_rtl433_reference() {
  printf("Trame de référence rtl_433 (valeurs calculées à la main depuis la source rtl_433)\n");
  const uint8_t raw[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                           0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  vevor::Frame f;
  const char *reason = "";
  expect(vevor::decode(raw, f, &reason), "la trame de référence doit être acceptée");
  expect(f.id == 0xf8f7, "id = 0xf8f7");
  expect(f.temp_c > 23.8f && f.temp_c < 24.0f, "température = 23,9 °C");
  expect(f.humidity == 50, "humidité = 50 %");
  expect_near(f.wind_kmh, 1.6f, 0.06f, "vent = 1,6 km/h (13 ticks / 8,333f)");
  expect_near(f.gust_kmh, 2.4f, 0.06f, "rafale = 2,4 km/h (3 ticks / 1,25f)");
  expect(f.wind_dir_deg == 266, "direction = 266°");
  expect_near(f.rain_mm, 12.8f, 0.06f, "pluie = 12,8 mm (55 ticks × 0,233f)");
  expect(f.uv_index == 1, "UV = 1");
  expect(f.lux == 14457, "luminosité = 14 457 lx");
  expect(f.tx_counter == 0x86, "compteur TX = 0x86");
  expect(f.battery_low, "batterie faible (0x9d)");
}

// --- 2ter. EXTERNAL ANCHOR of the "lux ×10" branch (bit 15 set) -----------------
// The rtl_433 frame above has bit 15 CLEAR (×1 path), so the ×10 branch had no external
// anchor: a factor error shared by the Python encoder and the C++ would self-validate.

// Here the 21 bytes are HARD-CODED and the expected value COMPUTED BY HAND:
//   lux target = 98000 lx (≥ 0x8000 → ×10), lux_raw = 0x8000 | (98000/10) = 0xA648

//   encode b[16]=((0xA648>>8)+1)&0xFF=0xA7 ; b[17]=((0xA648&0xFF)+1)&0xFF=0x49
//   decode (0xA7-1)=0xA6, (0x49-1)=0x48 → 0xA648, bit 15 set → 0x2648×10 = 98000 lx
static void test_lux_x10_anchor() {
  printf("Ancrage externe de la branche lux ×10 (valeur calculée à la main)\n");
  const uint8_t raw[21] = {0xaa, 0x00, 0x1a, 0x2b, 0x1d, 0x02, 0xac, 0x48, 0x01, 0x1c, 0x07,
                           0x01, 0xd7, 0x01, 0x37, 0x0c, 0xa7, 0x49, 0x40, 0x72, 0x41};
  vevor::Frame f;
  const char *reason = "";
  expect(vevor::decode(raw, f, &reason), "la trame lux ×10 doit être acceptée");
  expect(f.lux == 98000, "lux = 98 000 lx ((0xA648 & 0x7FFF) × 10 = 9 800 × 10, à la main)");
}

// --- 2bis. Plausibility gate: a "well-formed" but false frame ------------------
// Two REAL frames from a one-hour window (logs/fenetre_1h_cond) passed header + checksum +
// counter yet showed impossible directions (779°, 835°): one-bit shift at extraction.

// They must be REJECTED, not published — the only guard between "coherent" and "correct".
static void test_plausibility() {
  printf("Porte de plausibilité (trames fausses mais bien formées)\n");
  vevor::Frame f;
  const char *reason = "";

  // Healthy frame from the same window, just before the first faulty frame.
  const uint8_t bonne[21] = {0xaa, 0x00, 0x84, 0xcb, 0x16, 0x02, 0xb9, 0x38, 0x01, 0x3a, 0x0e,
                             0x02, 0x22, 0x01, 0xff, 0x06, 0x9a, 0x2d, 0x95, 0xd1, 0x96};
  expect(vevor::decode(bonne, f, &reason), "trame saine acceptée");
  expect(f.wind_dir_deg == 289, "trame saine : direction 289°");
  expect_near(f.rain_mm, 59.2f, 0.06f, "trame saine : pluie 59,2 mm");

  // Faulty frame #1: direction 779°, rain 178.2 mm, wind 34.2 km/h.
  const uint8_t fausse1[21] = {0xaa, 0x00, 0x84, 0xcb, 0x16, 0x02, 0xbb, 0x38, 0x02, 0x1e, 0x10,
                               0x04, 0x44, 0x03, 0xfe, 0x0b, 0x2f, 0x6e, 0x09, 0x2e, 0x0a};
  expect(!vevor::decode(fausse1, f, &reason),
         "trame à décalage de bits n° 1 refusée (direction 779° impossible)");
  expect(std::strcmp(reason, "direction") == 0, "motif de refus = direction, pas un rejet muet");
  // `f` was just filled by a VALID frame above: a rejected frame must NOT stay marked
  // valid (`out.valid` used to be set BEFORE the plausibility gate).
  expect(!f.valid, "trame refusée : `valid` reste faux (aucun marquage résiduel)");

  // Faulty frame #2: direction 835°, same signature.
  const uint8_t fausse2[21] = {0xaa, 0x00, 0x84, 0xcb, 0x16, 0x02, 0xba, 0x38, 0x02, 0x62, 0x24,
                               0x04, 0x0c, 0x03, 0xfe, 0x0d, 0x32, 0x3f, 0xad, 0xc7, 0xae};
  expect(!vevor::decode(fausse2, f, &reason), "trame à décalage de bits n° 2 refusée (direction 835°)");
}

// --- 3. Robustness: degenerate inputs ------------------------------------------
static void test_robustness() {
  printf("Robustesse\n");
  vevor::Frame f;
  const char *reason = "";

  // All bytes 0xAA: the decoder must not accept garbage.
  uint8_t garbage[21];
  std::memset(garbage, 0xAA, sizeof(garbage));
  expect(!vevor::decode(garbage, f, &reason), "21 octets 0xAA rejetés");

  std::memset(garbage, 0x00, sizeof(garbage));
  expect(!vevor::decode(garbage, f, &reason), "21 octets 0x00 rejetés");

  // A single flipped checksum bit must invalidate the frame.
  uint8_t raw[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                     0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  raw[7] ^= 0x01;  // humidity altered, checksum unchanged
  expect(!vevor::decode(raw, f, &reason), "bit modifié → checksum détecte la corruption");
}

// --- 4. The reject reason must be usable in logs -------------------------------
static void test_reasons() {
  printf("Motifs de rejet (exploitables par la boucle et par eval_frames.py)\n");
  vevor::Frame f;
  const char *reason = "";

  uint8_t bad_header[21] = {0};
  std::memset(bad_header, 0, sizeof(bad_header));
  bad_header[0] = 0xAB;
  expect(!vevor::decode(bad_header, f, &reason) && std::strcmp(reason, "header") == 0,
         "en-tête invalide → motif « header »");

  const uint8_t good[21] = {0xaa, 0x00, 0xf8, 0xf7, 0x9d, 0x02, 0xe3, 0x32, 0x01, 0x0e, 0x03,
                            0x02, 0x0b, 0x01, 0x38, 0x02, 0x39, 0x7a, 0x86, 0xe0, 0x87};
  uint8_t broken[21];
  std::memcpy(broken, good, sizeof(good));
  broken[19] ^= 0xFF;
  expect(!vevor::decode(broken, f, &reason) && std::strcmp(reason, "checksum") == 0,
         "checksum invalide → motif « checksum »");

  std::memcpy(broken, good, sizeof(good));
  broken[20] = 0x00;
  expect(!vevor::decode(broken, f, &reason) && std::strcmp(reason, "tx_counter") == 0,
         "compteur incohérent → motif « tx_counter »");
}

// --- 5. Full chain pulses → bits → frame (async path, no hardware) ---------------
// The real on-board chain: `remote_receiver` delivers signed pulse durations and the decoder
// must recover the frame; durations come from the Python encoder (tests/frames.py --pulses).
static void test_pulse_chain() {
  printf("Chaîne pulses → trame (%d scénarios, périodes essayées par le firmware)\n",
         VEVOR_PULSE_COUNT);
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    const VevorPulseScenario &s = VEVOR_PULSE_VECTORS[i];
    uint8_t raw[vevor::FRAME_BYTES];
    int32_t period_used = 0;
    bool inverted = false;
    const bool ok =
        vevor::decode_timings(s.timings, s.count, vevor::PERIOD_CANDIDATES,
                              vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw,
                              &period_used, &inverted);
    std::string name(s.name);
    expect(ok == s.valid, name + " : extraction " + (ok ? "réussie" : "vide") +
                                (s.valid ? " (attendue réussie)" : " (attendue vide)"));
    if (!ok || !s.valid) {
      continue;
    }
    vevor::Frame f;
    const char *reason = "";
    expect(vevor::decode(raw, f, &reason), name + " : la trame extraite doit être valide");
    expect(f.id == s.id, name + " : id");
    expect_near(f.temp_c, s.temp_c, 0.06f, name + " : température");
    expect_near(f.rain_mm, s.rain_mm, 0.06f, name + " : pluie");
    // Polarity retained: printing it proves nothing, it must be exercised — the inverted-
    // polarity scenario must really come out inverted, otherwise the polarity flip is untested.

    // Period retained: NOT required to be "== 90", it comes from the MEASUREMENT on the burst
    // (estimer_periode_x10): a plausible 50-150 µs value is required, not a grid member — an
    // unknown board is measured, never assumed. Grid selection: test_period_selection().
    expect(period_used >= vevor::PERIODE_MIN_X10 && period_used <= vevor::PERIODE_MAX_X10,
           name + " : période retenue plausible (mesurée sur la rafale)");
    const bool want_inverted = name.find("polarite_inversee") != std::string::npos;
    expect(inverted == want_inverted,
           name + " : polarity retenue " + (inverted ? "inverted" : "normal"));
    printf("    %-30s période retenue %d.%d us, polarity %s\n", s.name,
           (int) (period_used / 10), (int) (period_used % 10),
           inverted ? "inverted" : "normal");
  }
}

// --- 6. Stitching two burst fragments ------------------------------------------
// What RMT really delivers when its hardware memory (96 symbols) is full: TWO fragments.
// The cut falls at a pulse boundary or mid-pulse (same sign → the halves are summed).

// Stitching a WHOLE burst in front of the next one published 60 frames for 31 distinct
// measurements (each TX counter twice): hence MAX_FRAGMENT_TIMINGS, also tested here.
static void test_stitching() {
  printf("Recollage de deux morceaux de rafale (coupure du RMT)\n");
  const VevorPulseScenario *nominal = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "pulses_nominales") == 0) {
      nominal = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(nominal != nullptr, "le scénario nominal de référence existe");
  if (nominal == nullptr) {
    return;
  }

  const int32_t *full = nominal->timings;
  const size_t n = nominal->count;
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  int32_t out[512];
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;

  // (1) CLEAN cut at a pulse boundary (different signs at the splice)
  size_t k = n / 2;
  while (k > 1 && k + 1 < n && (full[k - 1] >= 0) == (full[k] >= 0)) {
    k++;
  }
  size_t m = vevor::stitch_fragments(full, k, full + k, n - k, out, 512);
  expect(m == n && std::memcmp(out, full, n * sizeof(int32_t)) == 0,
         "coupure nette : le recollage redonne exactement la rafale d'origine");
  expect(vevor::decode_timings(out, m, vevor::PERIOD_CANDIDATES, vevor::PERIOD_CANDIDATE_COUNT,
                               bits.data(), bits.size(), raw, &period_used, &inverted),
         "coupure nette : la trame est retrouvée après recollage");

  // (2) cut MID-PULSE: both halves share the same sign and are merged
  size_t j = 0;
  for (size_t i = n / 3; i < n; i++) {
    if (full[i] > 170 || full[i] < -170) {
      j = i;
      break;
    }
  }
  expect(j != 0, "une impulsion de plusieurs bits a été trouvée pour la couper en deux");
  if (j == 0) {
    return;
  }
  std::vector<int32_t> a(full, full + j + 1);
  std::vector<int32_t> b;
  a[j] = full[j] / 2;              // first half
  b.push_back(full[j] - a[j]);     // second half, SAME sign
  b.insert(b.end(), full + j + 1, full + n);
  m = vevor::stitch_fragments(a.data(), a.size(), b.data(), b.size(), out, 512);
  expect(m == n && std::memcmp(out, full, n * sizeof(int32_t)) == 0,
         "coupure au milieu d'une impulsion : les deux moitiés sont réunies");
  expect(vevor::decode_timings(out, m, vevor::PERIOD_CANDIDATES, vevor::PERIOD_CANDIDATE_COUNT,
                               bits.data(), bits.size(), raw, &period_used, &inverted),
         "coupure au milieu d'une impulsion : la trame est retrouvée après recollage");

  // (3) a lone fragment (without its twin) must NOT produce a frame — matching the component,
  //     which only stitches a SHORT capture (MAX_FRAGMENT_TIMINGS)
  expect(!vevor::decode_timings(a.data(), a.size(), vevor::PERIOD_CANDIDATES,
                                vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw,
                                &period_used, &inverted),
         "un morceau seul ne produit pas de trame (d'où le recollage)");
}

// --- 7. Inter-burst hole: the SKIP must really be exercised ---------------------
// `timings_to_bits` SKIPS an over-long pulse (a hole between bursts) instead of converting
// it to bits. If the skip vanishes (threshold ≥ 8000/90 ≈ 88) the hole adds ~88 zero bits.

// The hole must add NO bit: converting WITH and WITHOUT it must give the same bits.
static void test_hole_skip() {
  printf("Trou inter-rafales : saut réellement exercé\n");
  const VevorPulseScenario *trou = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "pulses_trou_inter_rafales") == 0) {
      trou = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(trou != nullptr, "le scénario « trou inter-rafales » existe");
  if (trou == nullptr) {
    return;
  }
  std::vector<int32_t> avec(trou->timings, trou->timings + trou->count);
  std::vector<int32_t> sans;
  for (int32_t t : avec) {
    if (t >= -4000 && t <= 4000) {  // the hole measures -8000: removed for comparison
      sans.push_back(t);
    }
  }
  expect(sans.size() + 1 == avec.size(), "exactement une impulsion de trou a été retirée");
  std::vector<uint8_t> bits_avec(vevor::MAX_BITS);
  std::vector<uint8_t> bits_sans(vevor::MAX_BITS);
  const size_t n_avec = vevor::timings_to_bits(avec.data(), avec.size(), 90, false,
                                               bits_avec.data(), bits_avec.size());
  const size_t n_sans = vevor::timings_to_bits(sans.data(), sans.size(), 90, false,
                                               bits_sans.data(), bits_sans.size());
  expect(n_avec == n_sans,
         "le trou n'ajoute aucun bit (sauté, et non converti en ~88 bits de zéro)");
  expect(n_avec == n_sans && std::memcmp(bits_avec.data(), bits_sans.data(), n_avec) == 0,
         "les bits obtenus sont identiques avec et sans le trou");
}

// --- 8. Bit-period selection: candidate scan continues after a failure -----------
// Two properties, independent of the candidate-list ORDER:
//  (1) EACH candidate decodes a burst emitted at ITS period → 88, 89 AND 87 are exercised;

//  (2) the scan CONTINUES after a failing candidate: the long-run burst
//      (pulses_trame_longue) is period-sensitive and NOT decodable at 88 µs, so the
//      decoder must reach 90 and succeed.
static void test_period_selection() {
  printf("Sélection de la bit period (balayage des candidats)\n");
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;

  // (1) each candidate, ALONE, decodes a burst emitted at its period: we call `essayer_periode`
  // (the "given period" layer), not `decode_timings`, which MEASURES the period first — the fixed
  // grid is now only a fallback, and this test exercises that fallback (test_periode_mesuree).
  int exerces = 0;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    const VevorPulseScenario &s = VEVOR_PULSE_VECTORS[i];
    if (!s.valid || s.period_us <= 0) {
      continue;
    }
    period_used = s.period_us * 10;
    const bool ok = vevor::essayer_periode(s.timings, s.count, s.period_us * 10, bits.data(),
                                           bits.size(), raw, &inverted, nullptr, nullptr);
    expect(ok, std::string(s.name) + " : décodable avec le SEUL candidat " +
                   std::to_string(s.period_us) + " us");
    if (s.period_us == 88 || s.period_us == 89 || s.period_us == 87) {
      exerces++;
    }
  }
  expect(exerces >= 3, "les candidats 88, 89 ET 87 ont tous été réellement exercés");

  // (2) scan after failure, on the period-sensitive burst.
  const VevorPulseScenario *longue = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "pulses_trame_longue") == 0) {
      longue = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(longue != nullptr, "le scénario à longue suite de bits existe");
  if (longue == nullptr) {
    return;
  }
  const int32_t seul88[1] = {88};
  const int32_t sans90[2] = {88, 87};
  const int32_t recherche[2] = {88, 90};
  // We exercise the "given period" layer (`essayer_periode`), which carries the scan;
  // `decode_timings` measures the period first, so using it here would test the measurement,
  // not the fallback.
  period_used = 0;
  expect(!vevor::essayer_periode(longue->timings, longue->count, seul88[0] * 10, bits.data(),
                                 bits.size(), raw, &inverted, nullptr, nullptr),
         "rafale longue : le candidat 88 SEUL échoue (elle est vraiment sensible à la période)");
  bool reussi = false;
  for (int32_t p : sans90) {
    if (vevor::essayer_periode(longue->timings, longue->count, p * 10, bits.data(), bits.size(),
                               raw, &inverted, nullptr, nullptr)) {
      reussi = true;
    }
  }
  expect(!reussi, "rafale longue : sans le candidat 90, aucun candidat ne décode (88 et 87 échouent)");
  period_used = 0;
  expect(vevor::essayer_periode(longue->timings, longue->count, 90 * 10, bits.data(), bits.size(),
                                raw, &inverted, nullptr, nullptr),
         "rafale longue : le balayage CONTINUE après l'échec de 88 et atteint 90 (le candidat 90 la "
         "décode)");
  // The production path decodes it by the MEASURED period: the fixed grid is now only a
  // fallback.
  period_used = 0;
  expect(vevor::decode_timings(longue->timings, longue->count, recherche, 2, bits.data(),
                               bits.size(), raw, &period_used, &inverted) &&
             period_used >= vevor::PERIODE_MIN_X10 && period_used <= vevor::PERIODE_MAX_X10,
         "rafale longue : décodée par la période mesurée sur la rafale");
}

// --- 9. Stitching policy: a FRAGMENT stitches, a COMPLETE burst does not ---------
// The component stitches only when `vevor::is_fragment(size)` holds (predicate shared with
// the test); bounds are MIN_TIMINGS = 40, MAX_FRAGMENT_TIMINGS = 160.

// Stitching a COMPLETE burst re-read the PREVIOUS one (60 frames for 31 distinct measurements).
static void test_fragment_policy() {
  printf("Politique de recollage (morceau vs rafale complète)\n");
  // predicate bounds: 40 included, 160 included, beyond not.
  expect(!vevor::is_fragment(39), "39 pulses : trop court, pas un morceau");
  expect(vevor::is_fragment(40), "40 pulses : morceau (borne basse incluse)");
  expect(vevor::is_fragment(160), "160 pulses : morceau (borne haute incluse)");
  expect(!vevor::is_fragment(161), "161 pulses : n'est plus un morceau");
  // REAL sizes measured on this setup: fragments 96 and 82; complete burst 176-184.
  expect(vevor::is_fragment(96) && vevor::is_fragment(82),
         "les deux morceaux mesurés (96 + 82) seront recollés");
  expect(!vevor::is_fragment(184),
         "une rafale complète mesurée (184) n'est PAS un morceau : jamais recollée");
  expect(!vevor::is_fragment(204), "204 pulses : capture complète, jamais recollée");

  // "TWO FRAGMENTS" case: the nominal burst cut in two, each half a fragment, then stitched
  // — exactly the component's decision (fragment AND previous fragment).
  const VevorPulseScenario *nominal = nullptr;
  for (int i = 0; i < VEVOR_PULSE_COUNT; i++) {
    if (std::strcmp(VEVOR_PULSE_VECTORS[i].name, "pulses_nominales") == 0) {
      nominal = &VEVOR_PULSE_VECTORS[i];
    }
  }
  expect(nominal != nullptr, "le scénario nominal de référence existe");
  if (nominal == nullptr) {
    return;
  }
  const size_t n = nominal->count;
  const size_t k = n / 2;
  expect(vevor::is_fragment(k) && vevor::is_fragment(n - k),
         "les deux moitiés de la rafale nominale sont des morceaux");
  std::vector<int32_t> out(n);
  const size_t m = vevor::stitch_fragments(nominal->timings, k, nominal->timings + k, n - k,
                                           out.data(), out.size());
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;
  expect(m == n && vevor::decode_timings(out.data(), m, vevor::PERIOD_CANDIDATES,
                                         vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(),
                                         raw, &period_used, &inverted),
         "deux morceaux recollés : la trame est retrouvée");
}

// --- 12. One-bit tolerance on the header byte ----------------------------------
// Real dump bursts regularly arrive with ONE wrong header bit (0xAB, 0xAE or 0xEA instead
// of 0xAA) while the next 16 bytes are exact: the front is mis-timed, not the frame.

// `decode_timings` corrects that constant bit — but ONLY if sum, counter and plausibility
// gate then pass. Tolerance is bounded: one bit passes, two fail.
static void pulses_depuis_octets(const uint8_t *octets, size_t n, int32_t periode,
                                 std::vector<int32_t> &out) {
  static const uint8_t PRE[5] = {0xAA, 0xAA, 0xAA, 0xCA, 0x54};
  out.clear();
  int niveau = 1;
  int32_t courant = 0;
  auto pousser = [&](int bit) {
    const int b = bit & 1;
    if (b == niveau) {
      courant += periode;
    } else {
      out.push_back(niveau ? courant : -courant);
      niveau = b;
      courant = periode;
    }
  };
  for (size_t i = 0; i < sizeof(PRE); i++) {
    for (int k = 7; k >= 0; k--) {
      pousser((PRE[i] >> k) & 1);
    }
  }
  for (size_t i = 0; i < n; i++) {
    for (int k = 7; k >= 0; k--) {
      pousser((octets[i] >> k) & 1);
    }
  }
  if (courant > 0) {
    out.push_back(niveau ? courant : -courant);
  }
}

static bool decode_une_trame(const uint8_t *octets) {
  static std::vector<uint8_t> bits(vevor::MAX_BITS);
  std::vector<int32_t> pulses;
  uint8_t sortie[vevor::FRAME_BYTES];
  int32_t periode = 0;
  bool inverse = false;
  size_t rejets = 0;
  pulses_depuis_octets(octets, vevor::FRAME_BYTES, 90, pulses);
  return vevor::decode_timings(pulses.data(), pulses.size(), vevor::PERIOD_CANDIDATES,
                               vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), sortie,
                               &periode, &inverse, &rejets);
}

static void test_header_tolerance() {
  printf("Tolérance d'un bit sur l'octet d'en-tête\n");
  // Frame recorded from the station (ID 33995, 15.6 °C, 80 %, 289°).
  uint8_t intacte[vevor::FRAME_BYTES] = {0xAA, 0x00, 0x84, 0xCB, 0x16, 0x02, 0x90,
                                         0x50, 0x01, 0x01, 0x00, 0x02, 0x22, 0x01,
                                         0xFF, 0x02, 0x31, 0xDF, 0x33, 0x5C, 0x34};
  expect(decode_une_trame(intacte), "trame intacte : décodée");

  uint8_t un_bit[vevor::FRAME_BYTES];
  std::memcpy(un_bit, intacte, vevor::FRAME_BYTES);
  un_bit[0] = 0xAB;   // seen in the dump: one single header bit wrong
  expect(decode_une_trame(un_bit), "en-tête à UN bit faux : corrigé et décodé");

  uint8_t deux_bits[vevor::FRAME_BYTES];
  std::memcpy(deux_bits, intacte, vevor::FRAME_BYTES);
  deux_bits[0] = 0xA9;   // two wrong bits: out of tolerance
  expect(!decode_une_trame(deux_bits), "en-tête à DEUX bits faux : refusé (tolérance bornée)");
}

// --- 13. Bit period MEASURED on the burst, and repair by inserting a bit ---------
// A new user only flashes, on an unknown board, and the code must make the station work
// with no analysis: the decoder MEASURES the bit rate per burst (estimer_periode_x10).

// Four points: (a) the estimate is right on a synthetic burst at the station rate (88.5 µs);
// (b) bursts at a DIFFERENT rate decode with no tuning (another board); (c) a MISSING bit
// in the payload is repaired; (d) an invalid frame stays rejected, repair included.

// Like pulses_depuis_octets, but a TWO-bit pulse can be SHORTENED to one bit (measured on the
// dump bursts: a two-period pulse seen as one). The decoded stream then counts one bit less
// and everything after is shifted — exactly what insertion repair must recover.
static bool raccourcir_une_impulsion(std::vector<int32_t> &pulses, int32_t periode) {
  for (size_t i = pulses.size() / 2; i < pulses.size(); i++) {
    if (pulses[i] == 2 * periode || pulses[i] == -2 * periode) {
      pulses[i] = (pulses[i] > 0) ? periode : -periode;
      return true;
    }
  }
  return false;
}

static void test_periode_mesuree() {
  printf("Période mesurée sur la rafale, et repairation par insertion d'un bit\n");
  const uint8_t trame[vevor::FRAME_BYTES] = {0xAA, 0x00, 0x84, 0xCB, 0x16, 0x02, 0x90, 0x50,
                                             0x01, 0x01, 0x00, 0x02, 0x22, 0x01, 0xFF, 0x02,
                                             0x31, 0xDF, 0x33, 0x5C, 0x34};
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  std::vector<int32_t> pulses;
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t periode = 0;
  bool inverse = false;
  bool repare = false;
  size_t rejets = 0;

  // (a) the estimator recovers the station rate, with no station constant.
  pulses_depuis_octets(trame, vevor::FRAME_BYTES, 88, pulses);
  const int32_t mesuree = vevor::estimer_periode_x10(pulses.data(), pulses.size());
  expect(mesuree >= 875 && mesuree <= 895,
         "estimation du rythme bit : " + std::to_string(mesuree / 10) + "," +
             std::to_string(mesuree % 10) + " us (attendu 88,3-88,9)");

  // (b) DIFFERENT rates: the unknown-board case, decoded with no tuning.
  const int32_t rythmes[] = {87, 88, 89, 90, 91};
  for (int32_t p : rythmes) {
    pulses_depuis_octets(trame, vevor::FRAME_BYTES, p, pulses);
    const int32_t est = vevor::estimer_periode_x10(pulses.data(), pulses.size());
    repare = false;
    const bool ok = vevor::decode_timings(pulses.data(), pulses.size(), vevor::PERIOD_CANDIDATES,
                                          vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(),
                                          raw, &periode, &inverse, &rejets, &repare);
    expect(ok && std::memcmp(raw, trame, vevor::FRAME_BYTES) == 0 && !repare,
           "rafale émise à " + std::to_string(p) + " us : décodée (estimée à " +
               std::to_string(est / 10) + "," + std::to_string(est % 10) + " us)");
  }

  // (c) a TWO-bit pulse measured as ONE: the demodulator shortens a two-period pulse and
  //     everything after shifts by a bit. We shorten a pulse in the payload and insertion
  //     repair must recover the exact frame.
  pulses_depuis_octets(trame, vevor::FRAME_BYTES, 88, pulses);
  expect(raccourcir_une_impulsion(pulses, 88),
         "une impulsion de deux bits a été trouvée dans la charge pour la raccourcir");
  repare = false;
  const bool ok_repare =
      vevor::decode_timings(pulses.data(), pulses.size(), vevor::PERIOD_CANDIDATES,
                            vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw, &periode,
                            &inverse, &rejets, &repare);
  expect(ok_repare && repare && std::memcmp(raw, trame, vevor::FRAME_BYTES) == 0,
         "impulsion de deux bits raccourcie à un bit : repaired, trame exacte retrouvée");

  // (d) counter-test: what does the repair FABRICATE? It widens the set of accepted frames,
  //     so its output must be bounded. 200 RANDOM payloads with correct sync and header:
  //     none may be published (measured: 0 of 200, which is what justifies keeping the repair).
  int fabriquees = 0;
  for (uint32_t graine = 1; graine <= 200; graine++) {
    uint8_t alea[vevor::FRAME_BYTES];
    uint32_t x = graine * 2654435761u;
    for (size_t i = 0; i < vevor::FRAME_BYTES; i++) {
      x = x * 1103515245u + 12345u;
      alea[i] = (uint8_t)(x >> 16);
    }
    alea[0] = 0xAA;   // correct header: sync succeeded
    alea[1] = 0x00;
    pulses_depuis_octets(alea, vevor::FRAME_BYTES, 88, pulses);
    if (vevor::decode_timings(pulses.data(), pulses.size(), vevor::PERIOD_CANDIDATES,
                              vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw,
                              &periode, &inverse)) {
      fabriquees++;
    }
  }
  expect(fabriquees == 0,
         "200 charges utiles aléatoires (synchro et en-tête justes) : " +
             std::to_string(fabriquees) + " publiée(s) — la repairation ne fabrique pas de trame");

  // (e) noise alone: no frame published.
  std::vector<int32_t> bruit;
  for (int i = 0; i < 200; i++) {
    const int32_t d = 40 + (i * 7) % 60;
    bruit.push_back((i % 2 == 0) ? d : -d);
  }
  expect(!vevor::decode_timings(bruit.data(), bruit.size(), vevor::PERIOD_CANDIDATES,
                                vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(), raw,
                                &periode, &inverse),
         "bruit sans préambule : aucune trame publiée");
}

// --- 14. REAL station bursts (regression vectors, acceptance criterion) ----------
// The six bursts of the dump, replayed as-is: the only test on REAL signal (synthetic
// scenarios only reproduce what was thought to describe).

// Criterion fixed in docs/bit-jitter-analysis.md: 5 of 6 must decode, the sixth an assumed
// counter-example (it needs at least two corrections); the five carry the same measurement.
static void test_captures_reelles() {
  printf("Rafales RÉELLES de la station (%d captures du dump du 03/10)\n", VEVOR_REAL_CAPTURE_COUNT);
  std::vector<uint8_t> bits(vevor::MAX_BITS);
  uint8_t raw[vevor::FRAME_BYTES];
  int32_t period_used = 0;
  bool inverted = false;
  bool repaired = false;
  size_t rejected = 0;
  int decodees = 0;
  for (int i = 0; i < VEVOR_REAL_CAPTURE_COUNT; i++) {
    const VevorRealCapture &c = VEVOR_REAL_CAPTURES[i];
    repaired = false;
    const bool ok = vevor::decode_timings(c.timings, c.count, vevor::PERIOD_CANDIDATES,
                                          vevor::PERIOD_CANDIDATE_COUNT, bits.data(), bits.size(),
                                          raw, &period_used, &inverted, &rejected, &repaired);
    if (ok) {
      decodees++;
      printf("    %-18s décodée (%d.%d us, %s) : %s\n", c.name, (int) (period_used / 10),
             (int) (period_used % 10), repaired ? "RÉPARÉE" : "directe",
             vevor::hex_bytes(raw, vevor::FRAME_BYTES).c_str());
      expect(std::memcmp(raw, VEVOR_CAPTURE_PREFIX, VEVOR_CAPTURE_PREFIX_LEN) == 0,
             std::string(c.name) + " : porte bien la mesure de la station (préfixe attendu)");
    } else {
      bool contre_exemple = false;
      for (int k = 0; k < VEVOR_CAPTURE_CONTRE_EXEMPLE_COUNT; k++) {
        if (i == VEVOR_CAPTURE_CONTRE_EXEMPLES[k]) {
          contre_exemple = true;
        }
      }
      printf("    %-18s NON décodée%s\n", c.name,
             contre_exemple ? " (contre-exemple assumé)" : " <-- RÉGRESSION");
    }
  }
  expect(decodees >= VEVOR_CAPTURE_ATTENDUES,
         "rafales réelles : " + std::to_string(decodees) + " décodées sur " +
             std::to_string(VEVOR_REAL_CAPTURE_COUNT) + " (critère : " +
             std::to_string(VEVOR_CAPTURE_ATTENDUES) + " au moins)");
}

// --- 15. Rain: a physically impossible rise is rejected ------------------------
// Two peaks at 7634.5 mm under a clear sky (PRODUCTION), the value staying at 59.2 mm, plus
// a halving (59.18 → 29.36 mm = 254 → 126 ticks, exactly one wrong bit) two minutes before.

// The protocol gate does NOT check rain; the bound applies to the RISE only. A FALL must not
// be rejected: the station zeroes its counter and the protocol documents a legitimate 256-tick
// drop, so rejecting a FALL would reject every frame, forever.
static void test_pluie_plausible() {
  printf("Pluie : hausse physiquement impossible refusée\n");
  const float stable = 59.18f;

  expect(vevor::pluie_plausible(59.2f, stable, true), "hausse normale (+0,02 mm) : acceptée");
  expect(vevor::pluie_plausible(60.1f, stable, true), "hausse de 1 mm : acceptée");
  expect(!vevor::pluie_plausible(7634.5f, stable, true),
         "pic mesuré à 7 634,5 mm : REFUSÉ (hausse impossible)");
  expect(!vevor::pluie_plausible(65.0f, stable, true), "hausse de 6 mm en une rafale : refusée");
  expect(!vevor::pluie_plausible(-1.0f, stable, true), "valeur négative : refusée");

  // Counter-test in both directions, per the protocol's reference decoder
  // (references/PROTOCOL.md): rain can only RISE, or restart at zero after a battery change.

  // A non-zero fall is a corruption even with a valid checksum — rejecting it is CORRECT (the
  // published 59.18 → 29.36 mm value was false).
  expect(!vevor::pluie_plausible(29.36f, stable, true),
         "division par deux observée (59,18 → 29,36 mm) : REFUSÉE (baisse non nulle = corruption)");
  expect(!vevor::pluie_plausible(59.0f, stable, true), "baisse de 0,2 mm : refusée");
  expect(vevor::pluie_plausible(0.0f, stable, true),
         "compteur remis à zéro (changement de pile) : accepté");
  expect(vevor::pluie_plausible(0.2f, 0.0f, true), "première bascule après la remise à zéro : acceptée");
  expect(vevor::pluie_plausible(7634.5f, 0.0f, false),
         "première trame, sans référence : acceptée (elle a déjà passé le reste de la porte)");

  // FRAME-level proof: a frame passing header, sum, counter AND the whole protocol
  // plausibility gate can still carry the peak. We build it and check that the continuity
  // check is what stops it.
  uint8_t pic[vevor::FRAME_BYTES] = {0xAA, 0x00, 0x84, 0xCB, 0x16, 0x02, 0x90, 0x50, 0x01,
                                     0x01, 0x00, 0x02, 0x22, 0x80, 0xFF, 0x02, 0x31, 0xDF,
                                     0x33, 0x00, 0x00};
  uint16_t somme = 0;
  for (int i = 0; i < 19; i++) {
    somme += pic[i];
  }
  pic[19] = (uint8_t)(somme & 0xFF);
  pic[20] = (uint8_t)(pic[18] + 1);
  vevor::Frame f;
  const char *raison = "";
  expect(vevor::decode(pic, f, &raison),
         "la trame au pic traverse en-tête, somme, compteur et porte de plausibilité du protocole");
  expect(f.rain_mm > 7000.0f && f.rain_mm < 7700.0f,
         "elle porte bien la pluie aberrante (7 634,5 mm attendus, " +
             std::to_string(f.rain_mm) + " obtenus)");
  expect(!vevor::pluie_plausible(f.rain_mm, stable, true),
         "c'est le contrôle de continuité qui l'arrête — celui qui manquait ce jour-là");
}

// --- 15. Zero wind: the insertion repair must not fabricate a frame ------------------
// Production defect measured on 04/10/2026: with no wind and no gust (b[8..10] = 01 01 00) the
// published frame carried wind 46.0 km/h and gust 102.4 km/h (b[8..10] = 02 80 80) — 141 frames
// that day. Cause: the insertion repair searched a bit of ANY value at ANY position, and
// 0x01+0x01+0x00 = 0x02+0x80+0x80 (mod 256): the byte sum is preserved, so checksum, counter and
// the whole plausibility gate stayed green and the WRONG position was accepted. The fix requires
// the recovered bit to extend the preceding pulse (same level) — see reparer_par_insertion.
//
// This test sweeps every pulse longer than one bit of two REAL zero-wind frames, shortens each by
// one bit (the measured mechanism: a pulse rounded down), and demands that nothing false comes
// out: a published frame must either be the true frame, or be stopped by the rain continuity
// guard — the component does not publish it then. Before the fix this test fails (02 80 80 is
// published); after it, it passes.
static void test_reparation_vent_nul() {
  printf("Vent nul : la repairation par insertion ne fabrique pas de trame\n");
  const uint8_t trames[2][vevor::FRAME_BYTES] = {
      {0xAA, 0x00, 0x84, 0xCB, 0x16, 0x02, 0x90, 0x50, 0x01, 0x01, 0x00,
       0x02, 0x22, 0x01, 0xFF, 0x02, 0x31, 0xDF, 0x33, 0x5C, 0x34},
      {0xAA, 0x00, 0x84, 0xCB, 0x16, 0x02, 0x8F, 0x58, 0x01, 0x01, 0x00,
       0x02, 0x0F, 0x01, 0xFF, 0x01, 0x01, 0x01, 0x4E, 0x5C, 0x4F},
  };
  static std::vector<uint8_t> bits(vevor::MAX_BITS);
  vevor::Frame vraie;
  const char *raison = "";
  expect(vevor::decode(trames[0], vraie, &raison), "trame de référence : vent nul, acceptée");
  expect_near(vraie.wind_kmh, 0.0f, 0.05f, "référence : vent mesuré 0,0 km/h");

  int essais = 0;
  int fabriquees = 0;
  for (const auto &trame : trames) {
    std::vector<int32_t> pulses;
    pulses_depuis_octets(trame, vevor::FRAME_BYTES, 88, pulses);
    for (size_t i = 0; i < pulses.size(); i++) {
      const int32_t d = pulses[i] > 0 ? pulses[i] : -pulses[i];
      const int32_t bits_impulsion = d / 88;
      if (bits_impulsion < 2) {
        continue;   // seule une impulsion d'au moins deux bits peut en perdre un
      }
      std::vector<int32_t> raccourcies = pulses;
      raccourcies[i] = (pulses[i] > 0) ? (bits_impulsion - 1) * 88 : -(bits_impulsion - 1) * 88;
      uint8_t publiee[vevor::FRAME_BYTES];
      int32_t periode = 0;
      bool inverse = false;
      bool repare = false;
      size_t rejets = 0;
      const bool ok = vevor::decode_timings(raccourcies.data(), raccourcies.size(),
                                            vevor::PERIOD_CANDIDATES, vevor::PERIOD_CANDIDATE_COUNT,
                                            bits.data(), bits.size(), publiee, &periode, &inverse,
                                            &rejets, &repare);
      essais++;
      if (!ok || std::memcmp(publiee, trame, vevor::FRAME_BYTES) == 0) {
        continue;
      }
      // Frame differs: it must NOT pass for the wind/gust, and the component must refuse it
      // through the rain continuity guard, else it reaches Home Assistant.
      vevor::Frame f;
      const char *motif = "";
      const bool publiee_valide = vevor::decode(publiee, f, &motif);
      const bool fausse =
          publiee_valide && (f.wind_kmh != vraie.wind_kmh || f.gust_kmh != vraie.gust_kmh) &&
          vevor::pluie_plausible(f.rain_mm, vraie.rain_mm, true);
      if (fausse) {
        fabriquees++;
        printf("   FAUSSE impulsion %zu (%d bits -> %d) : vent %.1f rafale %.1f pluie %.1f\n", i,
               (int) bits_impulsion, (int) bits_impulsion - 1, f.wind_kmh, f.gust_kmh, f.rain_mm);
      }
    }
  }
  expect(essais > 50,
         "balayage : " + std::to_string(essais) + " pulses raccourcies essayées (2 trames)");
  expect(fabriquees == 0,
         "aucune trame FAUSSE publiée (avant correction : 02 80 80 = 46,0 km/h / 102,4 km/h)");
}

int main() {
  printf("=== Tests du décodeur Vevor 7-en-1 (sans matériel) ===\n\n");
  test_vectors();
  test_rtl433_reference();
  test_lux_x10_anchor();
  test_plausibility();
  test_robustness();
  test_reasons();
  test_pulse_chain();
  test_stitching();
  test_period_selection();
  test_hole_skip();
  test_fragment_policy();
  test_header_tolerance();
  test_periode_mesuree();
  test_captures_reelles();
  test_pluie_plausible();
  test_reparation_vent_nul();

  printf("\n%d vérifications, %d échec(s)\n", g_checks, g_failures);
  if (g_failures == 0) {
    printf("%s TOUS LES TESTS PASSENT\n", CHECK);
    return 0;
  }
  printf("%s %d ÉCHEC(S)\n", FAIL, g_failures);
  return 1;
}
