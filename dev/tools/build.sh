#!/usr/bin/env bash
# Compiles the firmware. Usage: tools/build.sh [yaml_name_without_extension]
#
# The return code is ALWAYS ESPHome's (never tee/tail's) and an explicit marker is written to
# build/last_status.txt, so the autonomous loop cannot mistake a failure for a success when
# the output goes through a pipe.
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/: tools, tests, docs, logs
ROOT="$(cd "$DEV/.." && pwd)"            # repo root: esphome/ lives here, and nothing else
YAML="${1:-vevor-7in1}"
mkdir -p "$DEV/build" "$DEV/logs"
# Lock shared with flash.sh: the autonomous loop and an interactive session can start a
# build/flash at the same time on the same build dir. The lock makes the collision impossible:
# the second waits, then gives up cleanly with an explicit status.
exec 9>"$DEV/build/.build_flash.lock"
flock -w 1500 9 || {
  printf 'BUILD ABORTED code=3 lock held (another build/flash is running)\n' | tee "$DEV/build/last_status.txt"
  exit 3
}
cd "$ROOT/esphome"
echo "[build] $YAML"

# The YAML defaults to the public repo (github://): here we compile the LOCAL tree.
"$ROOT/.venv/bin/esphome" -s vevor_components components compile "$YAML.yaml" > "$DEV/build/last_compile.log" 2>&1
CODE=$?
tail -20 "$DEV/build/last_compile.log"

BIN="$ROOT/esphome/.esphome/build/$YAML/build/firmware.ota.bin"
if [ "$CODE" -eq 0 ] && [ -f "$BIN" ]; then
  printf 'BUILD OK code=0 binary=%s size=%s bytes\n' "$BIN" "$(stat -c %s "$BIN")" | tee "$DEV/build/last_status.txt"
  exit 0
fi
printf 'BUILD FAIL code=%s (see build/last_compile.log)\n' "$CODE" | tee "$DEV/build/last_status.txt"
exit "$CODE"
