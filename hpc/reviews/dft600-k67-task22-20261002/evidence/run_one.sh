#!/bin/bash
# Module initialization scripts may reference unset variables, so do not use nounset here.
set -eo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
index=${1:?Missing array index}
if [[ ! $index =~ ^[0-9]+$ ]] || (( index < 0 || index > 35 )); then echo 'Invalid array index.' >&2; exit 2; fi
: "${SLURM_JOB_ID:?Run via the Slurm array, not on the login node}"
: "${SLURM_NTASKS:?Missing MPI allocation}"
: "${SLURM_ARRAY_JOB_ID:?Missing Slurm array identity}"
[[ $SLURM_JOB_ID =~ ^[0-9]+$ && $SLURM_ARRAY_JOB_ID =~ ^[0-9]+$ ]] || exit 2
[[ $SLURM_NTASKS == 56 ]] || { echo 'This package requires the declared 56 MPI ranks.' >&2; exit 2; }
mapfile -t tasks < "$root/jobs.list"
[[ ${#tasks[@]} == 36 ]] || { echo 'Invalid job list.' >&2; exit 2; }
relative=${tasks[$index]}
[[ $relative == structures/*/k[67] && $relative != *..* ]] || { echo 'Invalid job path.' >&2; exit 2; }
input_dir="$root/$relative"
cd "$input_dir"
sha256sum --check --quiet INPUT_SHA256SUMS
mkdir -p runs
run_dir="$input_dir/runs/${SLURM_ARRAY_JOB_ID}_${index}"
mkdir "$run_dir"  # Never overwrite any existing attempt, even after an interrupted run.
cp INCAR POSCAR KPOINTS POTCAR job.json POTCAR.meta.json INPUT_SHA256SUMS "$run_dir/"
cd "$run_dir"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
finish() {
    rc=$?
    trap - EXIT
    state=FAILED
    if (( rc == 0 )); then state=EXECUTION_COMPLETE_REVIEW_PENDING; fi
    printf 'state\t%s\nexit_code\t%s\nstarted_utc\t%s\nended_utc\t%s\nslurm_job_id\t%s\narray_job_id\t%s\narray_index\t%s\n' \
        "$state" "$rc" "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SLURM_JOB_ID" "$SLURM_ARRAY_JOB_ID" "$index" > run-status.tsv
    exit "$rc"
}
trap finish EXIT
printf 'state\tRUNNING\nstarted_utc\t%s\n' "$started" > run-status.tsv
printf 'Input: %s\nRun directory: %s\n' "$relative" "$run_dir"
if ! type module >/dev/null 2>&1; then
    if [[ -f /etc/profile.d/modules.sh ]]; then source /etc/profile.d/modules.sh; fi
fi
type module >/dev/null 2>&1 || { echo 'Environment Modules is unavailable; use the site module initialization.' >&2; exit 2; }
module load compilers/intel/oneapi-2023/config
module load soft/vasp/vasp.6.3.2
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
command -v mpirun >/dev/null
command -v vasp_std > executable-path.txt
module list > modules.txt 2>&1
mpirun -np "$SLURM_NTASKS" vasp_std > stdout.vasp 2> stderr.vasp
# These are completion checks only, not numerical/physical certification.
grep -qF 'General timing and accounting' OUTCAR || { echo 'OUTCAR normal end is missing.' >&2; exit 3; }
grep -qF 'aborting loop because EDIFF is reached' OUTCAR || { echo 'Electronic convergence was not recorded.' >&2; exit 3; }
grep -qF '</modeling>' vasprun.xml || { echo 'vasprun.xml is incomplete.' >&2; exit 3; }
sha256sum --check --quiet INPUT_SHA256SUMS
printf 'VASP completed. Energy/force/stress accuracy and warnings require result review.\n'
