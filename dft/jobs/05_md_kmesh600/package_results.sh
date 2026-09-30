#!/bin/bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$root"
# Run only after squeue shows that the array has ended; never make a partial transfer silently.
if [[ -f submissions/history.tsv ]] && command -v squeue >/dev/null; then
    # Query live jobs once, so completed IDs aged out of Slurm are not mistaken for an error.
    if ! active_ids=$(squeue -h -u "${USER:-$(id -un)}" -o '%F' 2>/dev/null); then
        echo 'Cannot verify current queue state. Check squeue before packaging.' >&2; exit 2
    fi
    while IFS=$'\t' read -r stamp job_id indices parallel; do
        if printf '%s\n' "$active_ids" | grep -Fxq "$job_id"; then
            echo "Array $job_id still has queued/running jobs. Package after it ends." >&2; exit 2
        fi
    done < submissions/history.tsv
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
output="$root/../zrc-dft600-k67-results-$stamp.tgz"
./status.sh > "results-status-$stamp.tsv"
items=(manifest.json source-manifest.json jobs.list tasks.tsv SHA256SUMS README.md submit_all.sh job_array.slurm run_one.sh status.sh package_results.sh "results-status-$stamp.tsv" structures)
[[ ! -d logs ]] || items+=(logs)
[[ ! -d submissions ]] || items+=(submissions)
# Includes failures, XML, OUTCAR, input identity and every attempt. No labels are altered.
tar -czf "$output" "${items[@]}"
(cd "$(dirname "$output")" && sha256sum "$(basename "$output")" > "$(basename "$output").sha256")
printf 'Return this file and its sha256 file: %s\n' "$output"
