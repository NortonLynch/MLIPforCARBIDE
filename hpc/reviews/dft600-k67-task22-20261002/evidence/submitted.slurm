#!/bin/bash
#SBATCH --job-name=zrc600-k67
#SBATCH --partition=cnall
#SBATCH --nodes=1
#SBATCH --ntasks=56
#SBATCH --ntasks-per-node=56
#SBATCH --cpus-per-task=1
#SBATCH --time=240:00:00
#SBATCH --no-requeue
#SBATCH --output=logs/vasp-%A_%a.out
#SBATCH --error=logs/vasp-%A_%a.err
set -euo pipefail
root=${SLURM_SUBMIT_DIR:?Submit with submit_all.sh from the bundle root}
exec bash "$root/run_one.sh" "${SLURM_ARRAY_TASK_ID:?Missing Slurm array index}"
