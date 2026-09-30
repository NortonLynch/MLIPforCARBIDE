#!/usr/bin/env bash
# Submit all remaining work; run on the login node from WORK.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
mode=${1:-submit}
[[ "$mode" == submit || "$mode" == --resume || "$mode" == --plan ]] || { echo 'Usage: ./submit_all.sh [--plan|--resume]'; exit 2; }
export MACE_PYTHON=${MACE_PYTHON:-"$(dirname "$PWD")/zrc-ase-v100-setup/env/bin/python"}
[[ -x "$MACE_PYTHON" ]] || { echo "Python not found: $MACE_PYTHON; set MACE_PYTHON to the existing env/bin/python"; exit 1; }
export PYTHONNOUSERSITE=1
unset PYTHONPATH
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export MKL_NUM_THREADS=4
export PYTHONDONTWRITEBYTECODE=1
[[ ! -e STOP ]] || { echo 'STOP exists: no jobs submitted.'; exit 1; }
sha256sum -c SHA256SUMS > /dev/null
"$MACE_PYTHON" scripts/run_zrc_hpc.py preflight
# Total concurrency cap, including validating sizes: each size holds at most its slots.
parallel=${MACE_PARALLEL:-8}
[[ "$parallel" =~ ^[0-9]+$ && "$parallel" -ge 3 ]] || { echo 'MACE_PARALLEL must be >=3'; exit 2; }
slot8=$((parallel / 4)); ((slot8 >= 1)) || slot8=1
slot64=$slot8
slot216=$((parallel - slot8 - slot64))
partition=${MACE_PARTITION:-gnall}
validation_time=${MACE_VALIDATION_TIME:-12:00:00}
production_time=${MACE_PRODUCTION_TIME:-48:00:00}
if [[ "$mode" == --plan ]]; then
  echo "Validation: 3 jobs, one GPU each. Arrays: 8 atoms 45 tasks %$slot8; 64 atoms 45 tasks %$slot64; 216 atoms 54 tasks %$slot216."
  echo "Partition $partition; validation $validation_time; production $production_time; 4 CPUs and 32G RAM per GPU worker."
  echo 'Each array depends on its own size validation. No jobs submitted.'
  exit 0
fi
work_root=$(realpath "$HOME/WORK")
case "$PWD/" in "$work_root/"*) ;; *) echo 'Submit under ~/WORK.'; exit 1 ;; esac
command -v sbatch >/dev/null
command -v flock >/dev/null
mkdir -p logs outputs submissions
exec 9>submissions/submit.lock
flock -n 9 || { echo 'Another submission is in progress.'; exit 1; }
ledger=submissions/jobs.tsv
if [[ -s "$ledger" ]]; then
  [[ "$mode" == --resume ]] || { echo 'Already submitted. Use --resume only after prior jobs finish/are cancelled.'; exit 1; }
  active=$(squeue -h -u "${USER:-$(id -un)}" -o '%A')
  while IFS=$'\t' read -r stamp role size jobid; do
    if [[ "$jobid" =~ ^[0-9]+$ ]] && grep -Fxq "$jobid" <<< "$active"; then
      echo "Prior job $jobid is still active. Refusing duplicate submission."; exit 1
    fi
  done < "$ledger"
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
common=(--parsable --partition="$partition" --nodes=1 --ntasks=1 --cpus-per-task=4 --gres=gpu:1 --mem=32G --no-requeue --signal=B:USR1@120 --export=ALL)
[[ -z ${MACE_ACCOUNT:-} ]] || common+=(--account="$MACE_ACCOUNT")
[[ -z ${MACE_QOS:-} ]] || common+=(--qos="$MACE_QOS")
submit_one() {
  local role=$1 size=$2 raw ident
  shift 2
  raw=$(sbatch "$@")
  ident=${raw%%;*}
  [[ "$ident" =~ ^[0-9]+$ ]] || { echo "Unexpected sbatch result: $raw" >&2; exit 1; }
  printf '%s\t%s\t%s\t%s\n' "$stamp" "$role" "$size" "$ident" >> "$ledger"
  echo "Submitted $role size=$size job=$ident" >&2
  printf '%s' "$ident"
}
ids=()
for size in 8 64 216; do
  case "$size" in 8) count=45; slots=$slot8 ;; 64) count=45; slots=$slot64 ;; 216) count=54; slots=$slot216 ;; esac
  gate=$(submit_one validate "$size" "${common[@]}" --job-name="zrc-gate-$size" --time="$validation_time" --output="logs/gate-$size-%j.out" worker.sh validate --size "$size")
  array=$(submit_one production "$size" "${common[@]}" --job-name="zrc-prod-$size" --time="$production_time" --array="0-$((count-1))%$slots" --dependency="afterok:$gate" --kill-on-invalid-dep=yes --output="logs/prod-$size-%A_%a.out" worker.sh produce --size "$size")
  ids+=("$gate" "$array")
done
dependency=$(IFS=:; echo "${ids[*]}")
# A CPU collector runs even if validation/production fails or is cancelled.
collect_args=(--parsable --partition="${MACE_CPU_PARTITION:-cnmix}" --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=2G --time=01:00:00 --no-requeue --export=ALL)
[[ -z ${MACE_ACCOUNT:-} ]] || collect_args+=(--account="$MACE_ACCOUNT")
[[ -z ${MACE_QOS:-} ]] || collect_args+=(--qos="$MACE_QOS")
collector=$(submit_one collect all "${collect_args[@]}" --job-name=zrc-review --dependency="afterany:$dependency" --output='logs/review-%j.out' worker.sh collect)
echo "Submission complete. Collector $collector; records: $ledger"
echo 'Monitor with squeue -u "$USER". Final report: outputs/summary.json'
