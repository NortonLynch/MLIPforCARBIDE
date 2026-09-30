#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
python=${MACE_PYTHON:-"$(dirname "$PWD")/zrc-ase-v100-setup/env/bin/python"}
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
unset PYTHONPATH
"$python" scripts/run_zrc_hpc.py collect
