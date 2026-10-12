#!/usr/bin/env bash
# Run *privately*, without uploading proprietary Meteonorm or EPW derivatives to GitHub.
set -euo pipefail
: "${ENERGYPLUS_BIN:?Set ENERGYPLUS_BIN to the verified EnergyPlus 26.2.0 executable}"
: "${ENERGYPLUS_OFFICIAL_IDF:?Set ENERGYPLUS_OFFICIAL_IDF to the official v26.2.0 testfiles/1ZoneUncontrolled.idf}"
: "${METEONORM_GRAZ_BASELINE:?Set METEONORM_GRAZ_BASELINE to Graz-hour_contemporary_seed1.epw}"
: "${P7C4_RESEARCH_ARCHIVE:?Set P7C4_RESEARCH_ARCHIVE to the user's original P7C4 28-EPW ZIP}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${P7C5B_OUTPUT_DIR:-$ROOT/outputs_private}"
mkdir -p "$OUT"
python "$ROOT/p7c5b_solar_illuminance.py" \
 --baseline "$METEONORM_GRAZ_BASELINE" \
 --source-zip "$P7C4_RESEARCH_ARCHIVE" \
 --out "$OUT/corrected_epw"
python "$ROOT/p7c5b_private_energyplus_benchmark.py" \
 --energyplus "$ENERGYPLUS_BIN" \
 --official-idf "$ENERGYPLUS_OFFICIAL_IDF" \
 --baseline "$METEONORM_GRAZ_BASELINE" \
 --epw-dir "$OUT/corrected_epw" --out "$OUT/energyplus"