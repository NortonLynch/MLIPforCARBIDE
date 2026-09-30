#!/usr/bin/env bash
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit using submit_all.sh}"
export MACE_PYTHON=${MACE_PYTHON:-"$(dirname "$PWD")/zrc-ase-v100-setup/env/bin/python"}
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export OPENBLAS_NUM_THREADS="$OMP_NUM_THREADS"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"
run_tag="${SLURM_JOB_ID:-manual}-${SLURM_ARRAY_TASK_ID:-single}"
export XDG_CACHE_HOME="$PWD/outputs/cache/$run_tag"
export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
export TORCH_HOME="$XDG_CACHE_HOME/torch"
export TMPDIR="$XDG_CACHE_HOME/tmp"
mkdir -p "$MPLCONFIGDIR" "$TORCH_HOME" "$TMPDIR" logs
sha256sum -c SHA256SUMS > "logs/input-check-$run_tag.txt"
# exec keeps the Python process as the batch PID, receiving B:USR1 before walltime.
exec "$MACE_PYTHON" -u scripts/run_zrc_hpc.py "$@"
