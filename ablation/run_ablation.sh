#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: bash ablation/run_ablation.sh [OUTPUT_DIRECTORY]"
  echo "Uses this checkout and active python; override PY_CATRANGE, CATRANGE_ROOT,"
  echo "CATRANGE_CONFIG, CATRANGE_DEVICE (default auto), or CATRANGE_DATA_ROOT."
  exit 0
fi
if [[ $# -gt 1 ]]; then
  echo "Expected at most one output directory; use --help." >&2
  exit 2
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TRAINING_ROOT="${CATRANGE_ROOT:-$SCRIPT_DIR/../catrange_model}"
PY="${PY_CATRANGE:-python}"
OUT="${1:-$SCRIPT_DIR/runs/kcat_esmc_ablation}"

"$PY" "$SCRIPT_DIR/train_catrange_ablation.py" \
  --catrange-root "$TRAINING_ROOT" \
  --config "${CATRANGE_CONFIG:-$TRAINING_ROOT/configs/kcat_esmc.yaml}" \
  --output-dir "$OUT" \
  --device "${CATRANGE_DEVICE:-auto}"

"$PY" "$SCRIPT_DIR/plot_ablation_results.py" \
  --results-dir "$OUT" \
  --dpi 600

echo "CatRange ablation complete: $OUT"
