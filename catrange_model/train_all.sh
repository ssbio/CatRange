#!/usr/bin/env bash
# Train all 4 CatRange models sequentially (safe for single GPU)
set -euo pipefail
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: bash catrange_model/train_all.sh"
    echo "Uses this checkout and active python; override PY_CATRANGE, CATRANGE_DEVICE (default cuda),"
    echo "CATRANGE_CONFIG_DIR, or CATRANGE_DATA_ROOT (external prepared tensor root)."
    exit 0
fi
if [[ $# -ne 0 ]]; then
    echo "Unexpected argument; use --help." >&2
    exit 2
fi
TRAINING_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXECUTABLE="${PY_CATRANGE:-python}"
CONFIG_DIR="${CATRANGE_CONFIG_DIR:-$TRAINING_ROOT/configs}"
DEVICE="${CATRANGE_DEVICE:-cuda}"
cd -- "$TRAINING_ROOT"
export PYTHONPATH="$TRAINING_ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p logs outputs

echo "=== TRAINING ALL 4 MODELS ===" | tee logs/train_all.log
echo "Started: $(date)" | tee -a logs/train_all.log

for config in kcat_esmc km_esmc kcat_esm2 km_esm2; do
    echo "" | tee -a logs/train_all.log
    echo ">>> Starting ${config} at $(date)" | tee -a logs/train_all.log
    "$PYTHON_EXECUTABLE" scripts/cv_train.py \
        --config "$CONFIG_DIR/${config}.yaml" \
        --device "$DEVICE" \
        2>&1 | tee logs/${config}_train.log
    echo ">>> Finished ${config} at $(date)" | tee -a logs/train_all.log
done

echo "" | tee -a logs/train_all.log
echo "=== ALL 4 MODELS COMPLETE ===" | tee -a logs/train_all.log
echo "Finished: $(date)" | tee -a logs/train_all.log
