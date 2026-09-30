#!/usr/bin/env bash
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit using submit_all.sh}"
export MACE_PYTHON=${MACE_PYTHON:-"$(dirname "$PWD")/zrc-ase-v100-setup/env/bin/python"}
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
run_tag="${SLURM_JOB_ID}-${SLURM_ARRAY_TASK_ID}"
export XDG_CACHE_HOME="$PWD/outputs/cache/$run_tag"
export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib" TORCH_HOME="$XDG_CACHE_HOME/torch" TMPDIR="$XDG_CACHE_HOME/tmp"
mkdir -p "$MPLCONFIGDIR" "$TORCH_HOME" "$TMPDIR" logs
exec "$MACE_PYTHON" -u scripts/run_zrc216_continuous.py produce