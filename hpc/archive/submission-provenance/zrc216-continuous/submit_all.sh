#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
mode=${1:-submit}
[[ "$mode" == submit || "$mode" == --plan || "$mode" == --retry-from-start ]] || { echo 'Usage: ./submit_all.sh [--plan|--retry-from-start]'; exit 2; }
export MACE_PYTHON=${MACE_PYTHON:-"$(dirname "$PWD")/zrc-ase-v100-setup/env/bin/python"}
[[ -x "$MACE_PYTHON" ]] || { echo "Existing environment Python missing: $MACE_PYTHON"; exit 1; }
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
unset PYTHONPATH
[[ ! -e STOP ]] || { echo 'STOP exists; no jobs submitted.'; exit 1; }
"$MACE_PYTHON" scripts/run_zrc216_continuous.py preflight
parallel=${MACE_PARALLEL:-4}
[[ "$parallel" =~ ^[1-9][0-9]*$ && "$parallel" -le 54 ]] || { echo 'MACE_PARALLEL must be 1..54'; exit 2; }
if [[ "$mode" == --plan ]]; then
  echo "54 independent 216-atom tasks; max $parallel GPUs; 1 GPU per task; no CPU collector job."
  echo 'Each task: continuous 5 ps + 10 ps; no partial-production resume.'
  exit 0
fi
work_root=$(realpath "$HOME/WORK")
case "$PWD/" in "$work_root/"*) ;; *) echo 'Submit under ~/WORK'; exit 1 ;; esac
command -v sbatch >/dev/null
command -v flock >/dev/null
mkdir -p submissions logs outputs
exec 9>submissions/submit.lock
flock -n 9 || { echo 'Another submission is in progress'; exit 1; }
ledger=submissions/jobs.tsv
if [[ -s "$ledger" && "$mode" != --retry-from-start ]]; then
  echo 'Already submitted; use --retry-from-start after all earlier jobs exit.'; exit 1
fi
active=$(squeue -h -u "${USER:-$(id -un)}" -o '%F %A' | tr ' ' '\n')
# Refuse overlap with the original submitted matrix or an earlier continuous attempt.
prior=$(awk -F '\t' '{print $4}' provenance/previous-jobs.tsv)
if [[ -f "$ledger" ]]; then prior+=$'\n'$(awk -F '\t' '{print $4}' "$ledger"); fi
while read -r ident; do
  if [[ "$ident" =~ ^[0-9]+$ ]] && grep -Fxq "$ident" <<< "$active"; then
    echo "Prior job $ident is still active; no overlapping submission."; exit 1
  fi
done <<< "$prior"
args=(--parsable --partition="${MACE_PARTITION:-gnall}" --nodes=1 --ntasks=1 --cpus-per-task=4 --gres=gpu:1 --mem=32G --time="${MACE_TIME:-48:00:00}" --no-requeue --signal=B:USR1@120 --export=ALL --array="0-53%$parallel" --job-name=zrc216-cont --output='logs/prod-%A_%a.out')
[[ -z ${MACE_ACCOUNT:-} ]] || args+=(--account="$MACE_ACCOUNT")
[[ -z ${MACE_QOS:-} ]] || args+=(--qos="$MACE_QOS")
if ! raw=$(sbatch "${args[@]}" worker.sh); then
  echo 'Submission rejected; no successful job ID recorded.' >&2; exit 1
fi
ident=${raw%%;*}
[[ "$ident" =~ ^[0-9]+$ ]] || { echo "Unexpected sbatch response: $raw; inspect squeue before retry." >&2; exit 1; }
printf '%s\tcontinuous_production\t216\t%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" "$ident" >> "$ledger"
echo "Submitted array $ident: 54 tasks, at most $parallel GPUs."
echo 'Collect on Windows after downloading outputs, logs and submissions; no CPU job required.'