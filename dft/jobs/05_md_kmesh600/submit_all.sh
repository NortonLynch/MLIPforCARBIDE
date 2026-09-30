#!/bin/bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$root"
dry_run=0
if [[ ${1:-} == --dry-run ]]; then dry_run=1; shift; fi
if (( $# )); then echo 'Usage: ./submit_all.sh [--dry-run]' >&2; exit 2; fi
parallel=${DFT_PARALLEL:-4}
indices=${DFT_TASKS:-0-35}
if [[ ! $parallel =~ ^[0-9]+$ ]] || (( parallel < 1 || parallel > 36 )); then
    echo 'DFT_PARALLEL must be an integer from 1 through 36.' >&2; exit 2
fi
# Retry syntax deliberately permits a comma-separated list of exact task indices only.
if [[ $indices != 0-35 ]]; then
    if [[ ! $indices =~ ^[0-9]+(,[0-9]+)*$ ]]; then echo 'DFT_TASKS must be 0-35 or comma-separated indices (e.g. 3,7).' >&2; exit 2; fi
    IFS=, read -r -a selected <<< "$indices"
    seen=,
    for index in "${selected[@]}"; do
        if [[ ${#index} -gt 2 ]] || (( 10#$index > 35 )) || [[ $index != $((10#$index)) ]] || [[ $seen == *,$index,* ]]; then
            echo 'Task indices must be unique integers between 0 and 35, without leading zeroes.' >&2; exit 2
        fi
        seen+="$index,"
    done
fi
sha256sum --check --quiet SHA256SUMS
if [[ $(wc -l < jobs.list) -ne 36 ]]; then echo 'Expected exactly 36 jobs.' >&2; exit 2; fi
args=(sbatch --parsable --partition=cnall --nodes=1 --ntasks=56 --ntasks-per-node=56
      --cpus-per-task=1 --time="${DFT_TIME:-240:00:00}" --no-requeue --export=ALL
      --chdir="$root" --array="$indices%$parallel" --job-name=zrc600-k67
      --output='logs/vasp-%A_%a.out' --error='logs/vasp-%A_%a.err')
[[ -z ${DFT_ACCOUNT:-} ]] || args+=(--account="$DFT_ACCOUNT")
[[ -z ${DFT_QOS:-} ]] || args+=(--qos="$DFT_QOS")
args+=(job_array.slurm)
printf '36 prepared static tasks; ENCUT=600 eV; k6/k7; cnall; 56 MPI ranks per task; parallel limit %s.\n' "$parallel"
if (( dry_run )); then printf '%q ' "${args[@]}"; printf '\nDry run only; nothing submitted.\n'; exit 0; fi
command -v sbatch >/dev/null || { echo 'sbatch is unavailable. Run on the HPC login node.' >&2; exit 2; }
mkdir -p logs submissions
if [[ $indices == 0-35 && -e submissions/all-job-id.txt ]]; then
    echo "Full array already submitted as $(cat submissions/all-job-id.txt). No duplicate submission." >&2
    echo 'To retry selected failed tasks, explicitly set DFT_TASKS=3,7 (example).' >&2; exit 2
fi
if [[ -e submissions/UNCERTAIN ]]; then echo 'Previous sbatch response was ambiguous; inspect submissions and squeue before retrying.' >&2; exit 2; fi
mkdir submissions/.submit-lock 2>/dev/null || { echo 'Another submission is in progress; inspect submissions/.submit-lock if a prior shell was interrupted.' >&2; exit 2; }
trap 'rmdir submissions/.submit-lock 2>/dev/null || true' EXIT
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
printf '%q ' "${args[@]}" > "submissions/$stamp.command.txt"
printf '\n' >> "submissions/$stamp.command.txt"
set +e
"${args[@]}" > "submissions/$stamp.sbatch.txt" 2> "submissions/$stamp.sbatch.err"
rc=$?
set -e
if (( rc != 0 )); then cat "submissions/$stamp.sbatch.err" >&2; exit "$rc"; fi
raw=$(cat "submissions/$stamp.sbatch.txt")
if [[ ! $raw =~ ^[0-9]+(\;[a-zA-Z0-9_.-]+)?$ ]]; then
    printf '%s\n' "$raw" > submissions/UNCERTAIN
    echo 'Unexpected successful sbatch response; inspect saved output and squeue; do not blindly resubmit.' >&2; exit 2
fi
job_id=${raw%%;*}
printf '%s\t%s\t%s\t%s\n' "$stamp" "$job_id" "$indices" "$parallel" >> submissions/history.tsv
if [[ $indices == 0-35 ]]; then printf '%s\n' "$job_id" > submissions/all-job-id.txt; fi
printf 'Submitted array %s. Follow with: squeue -r -j %s\n' "$job_id" "$job_id"
