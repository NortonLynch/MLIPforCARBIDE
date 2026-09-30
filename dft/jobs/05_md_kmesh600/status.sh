#!/bin/bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$root"
printf 'INDEX\tTASK\tATTEMPT\tSTATE\n'
index=0
while IFS= read -r task; do
    found=0
    for run in "$task"/runs/*; do
        [[ -d $run ]] || continue
        found=1
        state=NO_STATUS_OR_INTERRUPTED
        if [[ -f $run/run-status.tsv ]]; then state=$(awk -F '\t' '$1=="state" {print $2; exit}' "$run/run-status.tsv"); fi
        printf '%s\t%s\t%s\t%s\n' "$index" "$task" "${run##*/}" "$state"
    done
    if (( found == 0 )); then printf '%s\t%s\t-\tNOT_STARTED\n' "$index" "$task"; fi
    index=$((index+1))
done < jobs.list
