"""Build the user-approved ENCUT=600 eV / k6,k7 ZrC VASP delivery."""
from pathlib import Path
import argparse,hashlib,json,shutil,tarfile
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'dft/jobs/05_md_kmesh600'
NAME='zrc-dft600-k67'
ARCHIVE=ROOT/'hpc'/f'{NAME}.tgz'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def text(p,s):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s.strip()+'\n',encoding='utf-8',newline='\n')
def save(p,s):text(p,json.dumps(s,ensure_ascii=False,indent=2))
SUBMIT=r'''#!/bin/bash
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
'''
ARRAY=r'''#!/bin/bash
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
'''
RUN=r'''#!/bin/bash
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
'''
STATUS=r'''#!/bin/bash
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
'''
PACK=r'''#!/bin/bash
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
'''
README='''# ZrC 600 eV：18构型 × k6/k7，36个VASP静态任务

本批由用户指定固定ENCUT=600 eV，仅比较Gamma中心6×6×6和7×7×7网格，不安排700/800 eV任务。每个原始64原子构型保持位置与晶胞不变。18个构型已完成来源核验；它们用于DFT协议比较，尚无DFT结果。

## 上传与一次提交

把 `zrc-dft600-k67.tgz` 和 `.tgz.sha256` 放到超算的工作目录，登录节点执行：

```bash
sha256sum -c zrc-dft600-k67.tgz.sha256
tar -xzf zrc-dft600-k67.tgz
cd zrc-dft600-k67
./submit_all.sh
```

tar内已设置脚本执行权限、Linux换行，无需conda/Python环境。脚本只在登录节点调用sbatch；VASP由计算节点执行。也可先运行 `./submit_all.sh --dry-run` 查看配置，不提交任务。

## 资源与运行方式

- 分区固定 `cnall`。sinfo中`cnall*`的星号表示默认分区，不属于提交名称。
- 一个数组含0–35，共36个独立任务；默认最多同时运行4个。
- 每任务1节点、56 MPI进程、每进程1线程；沿用现有JobModel与集群手册。没有GPU申请、没有额外汇总作业，也不设置曾触发不匹配的内存参数。
- 时限默认240小时，沿用现有JobModel；这是最长允许时间，不是预计耗时。实际是否接受时限及资源以集群策略为准。
- 依次加载 `compilers/intel/oneapi-2023/config` 和 `soft/vasp/vasp.6.3.2`，通过 `mpirun -np 56 vasp_std` 启动。
- NCORE/KPAR不新增调参，沿用当前INCAR基线的默认行为；实际NBANDS、k点数、内存与耗时以OUTCAR为准。

改变并发量的例子：`DFT_PARALLEL=2 ./submit_all.sh`。可选 `DFT_TIME`、`DFT_ACCOUNT`、`DFT_QOS` 只在有需要时指定。不会默认猜填账户或QOS。

## 文件与可追溯性

`structures/01_.../k6`和`k7`，直到18，共36个输入目录；每目录含INCAR、POSCAR、KPOINTS、POTCAR、job.json、POTCAR.meta.json、INPUT_SHA256SUMS。POTCAR使用用户已有PAW-PBE.64库，Zr_sv在前、C在后，与Zr32/C32一致。

`jobs.list`按数组序号列出任务，`tasks.tsv`提供序号、构型、网格、温度与体积。`job.json`是输入参数和来源记录，VASP不读取它；用于后续自动核对，不是额外计算任务。

其他设置保持一致：PBE、PREC=Accurate、EDIFF=1E-7、ISMEAR=0、SIGMA=0.10、ISPIN=1、LREAL=F、LASPH=T、ADDGRID=F、ISYM=0、NSW=0、IBRION=-1、ISIF=2。SIGMA是固定数值展宽，不按离子目标温度变化。保存完整应力，不弛豫MD帧，不生成WAVECAR/CHGCAR。

每次运行把输入复制到该任务的 `runs/数组号_序号/` 中，保留每次尝试、stdout.vasp、stderr.vasp、OUTCAR、OSZICAR、vasprun.xml和run-status.tsv。不会覆盖失败结果；原始输入目录不写VASP输出。

首次成功提交后重复执行完整submit_all会被阻止，以免重复计费。若个别任务失败，先检查原因与队列状态，再明确重提，例如：

```bash
DFT_TASKS=3,7 ./submit_all.sh
```

此处3和7是tasks.tsv中的零起始数组序号，不是构型编号。重提使用原参数、新数组号的新目录，不从失败输出续算。遇到不明sbatch返回会留下UNCERTAIN，不自动重复提交；提交过程异常退出可能留有.submit-lock，应先检查队列与提交记录再处理。

## 查看进度与回传

提交后终端会显示数组号：`squeue -r -j 数组号`。`./status.sh`列出36个任务的本地运行状态，`submissions/history.tsv`记录所有提交。

VASP退出后检查正常结束、自洽收敛标志和XML闭合；通过只标记 `EXECUTION_COMPLETE_REVIEW_PENDING`，不把它称为DFT精度已经通过。所有任务结束（包括失败）后执行：

```bash
./package_results.sh
```

会在上一级目录生成带时间戳的结果tgz和sha256。把两者拷回本机即可；包中保留所有成功/失败尝试和完整输入。打包期间不要重提任务或修改结果。

## 回传后的比较规则

固定18帧中01号冷态中心体积构型为相对能量参考r；比较
`delta_relative_e = [(E_k6(i)-E_k6(r))-(E_k7(i)-E_k7(r))]/64`。
采用与力一致的TOTEN；原始绝对能量差另外保存。逐帧比较相对能量差≤1 meV/atom、力分量RMS≤0.01 eV/Å、最大力分量差≤0.03 eV/Å、最大应力分量差≤0.10 GPa，同时记录SCF步数、实际k点数和耗时。r自身相对能量差为零，仍需检查其力和应力。

7³作为本批较密对照，不预先认定绝对收敛。若6³满足全部预算，可据此次覆盖范围选择6³以减少成本；若不满足，再根据结果讨论，脚本不会自动加密、放宽阈值或追加任务。600 eV是用户选择的固定设置，本批不认证截断能收敛，也不证明高温相态或平衡物性。
'''
def build():
 if DEST.exists():raise RuntimeError(f'Refuse to overwrite existing delivery: {DEST}')
 src=ROOT/'dft/structures/zrc_calibration18';manifest=read(src/'manifest.json')
 assert manifest['count']==18 and read(src/'export-verification.json')['all_passed']
 potmeta=read(ROOT/'dft/jobs/00_smoke/zrc8/POTCAR.meta.json')
 pieces=[]
 for p in potmeta['potentials']:
  data=(ROOT/p['source_path']).read_bytes();assert hashlib.sha256(data).hexdigest()==p['source_sha256'];pieces.append(data)
 pot=b''.join(pieces);assert hashlib.sha256(pot).hexdigest()==potmeta['sha256']
 incar=(ROOT/'dft/jobs/00_smoke/zrc8/INCAR').read_text(encoding='utf-8-sig')
 incar='\n'.join(line for line in incar.splitlines() if not line.startswith('#'))
 assert 'ENCUT = 600' in incar
 tasks=[];lines=[];tsv=['array_index\tstructure_id\tkmesh\ttask_path\ttarget_temperature_K\tvolume_scale']
 for row in manifest['structures']:
  original=ROOT/row['POSCAR'];assert sha(original)==row['POSCAR_sha256']
  for k in [6,7]:
   sub=f'structures/{row["structure_id"]}/k{k}';d=DEST/sub;d.mkdir(parents=True)
   data=incar.replace('SYSTEM = 00_smoke_zrc8',f'SYSTEM = ZrC64_cal{row["calibration_rank"]:02d}_600eV_k{k}')
   text(d/'INCAR','# User-selected fixed ENCUT=600 eV; compare k6/k7 only.\n'+data)
   shutil.copyfile(original,d/'POSCAR')
   text(d/'KPOINTS',f'Gamma-centered {k}x{k}x{k}\n0\nGamma\n{k} {k} {k}\n0 0 0')
   (d/'POTCAR').write_bytes(pot);save(d/'POTCAR.meta.json',potmeta)
   job={'array_index':len(tasks),'task_path':sub,'structure_id':row['structure_id'],'frame_id':row['frame_id'],'natoms':64,'species':['Zr','C'],'counts':[32,32],'ENCUT_eV':600,'kmesh':[k,k,k],'kmesh_centering':'Gamma','source_group':row['source_group'],'target_temperature_K':row['target_temperature_K'],'volume_scale':row['volume_scale'],'MD_seed':row['md_seed'],'POSCAR_sha256':sha(d/'POSCAR'),'POTCAR_sha256':potmeta['sha256'],'INCAR_sha256':sha(d/'INCAR'),'KPOINTS_sha256':sha(d/'KPOINTS'),'source_record':row,'DFT_protocol_id':'zrc-pbe64-zrsv-c-600-k67-calibration-20260924','label_status':'not_calculated','dataset_eligible':False,'partition':'cnall','comparison_relative_energy_reference_structure':manifest['reference_structure_id']}
   save(d/'job.json',job)
   names=['INCAR','POSCAR','KPOINTS','POTCAR','job.json','POTCAR.meta.json']
   text(d/'INPUT_SHA256SUMS','\n'.join(f'{sha(d/n)}  {n}' for n in names))
   tasks.append(job);lines.append(sub)
   tsv.append(f'{job["array_index"]}\t{row["structure_id"]}\t{k}x{k}x{k}\t{sub}\t{row["target_temperature_K"]}\t{row["volume_scale"]}')
 for name,s in [('submit_all.sh',SUBMIT),('job_array.slurm',ARRAY),('run_one.sh',RUN),('status.sh',STATUS),('package_results.sh',PACK),('README.md',README)]:text(DEST/name,s)
 text(DEST/'jobs.list','\n'.join(lines));text(DEST/'tasks.tsv','\n'.join(tsv))
 shutil.copyfile(src/'manifest.json',DEST/'source-manifest.json')
 save(DEST/'manifest.json',{'schema_version':1,'bundle_name':NAME,'prepared_date':'2026-09-24','task_count':36,'structure_count':18,'ENCUT_eV':600,'kmeshes':[[6,6,6],[7,7,7]],'reference_structure_id':manifest['reference_structure_id'],'POTCAR_sha256':potmeta['sha256'],'source_manifest_sha256':sha(src/'manifest.json'),'resources':{'partition':'cnall','nodes_per_task':1,'mpi_ranks_per_task':56,'cpus_per_rank':1,'maximum_concurrent_tasks_default':4,'time_limit_default':'240:00:00'},'DFT_submitted':False,'ENCUT_selection':'explicit_user_choice_not_new_cutoff_validation','kmesh_selection':'pending_returned_comparison','scientific_validation':False,'script_source_sha256':sha(Path(__file__)),'tasks':tasks})
 text(DEST/'SHA256SUMS','\n'.join(f'{sha(p)}  {p.relative_to(DEST).as_posix()}' for p in sorted(DEST.rglob('*')) if p.is_file()))
 print(f'Prepared {len(tasks)} VASP jobs in {DEST}',flush=True)
def archive():
 expected=[]
 for line in (DEST/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
  h,name=line.split('  ',1);p=DEST/name;assert p.is_file() and sha(p)==h,(name,'changed');expected.append(p)
 with tarfile.open(ARCHIVE,'w:gz',format=tarfile.PAX_FORMAT) as tf:
  for p in [*expected,DEST/'SHA256SUMS']:
   info=tf.gettarinfo(str(p),arcname=NAME+'/'+p.relative_to(DEST).as_posix())
   info.mode=0o755 if p.suffix in ['.sh','.slurm'] else 0o644
   info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
   with p.open('rb') as f:tf.addfile(info,f)
 text(ARCHIVE.with_suffix('.tgz.sha256'),f'{sha(ARCHIVE)}  {ARCHIVE.name}')
 print(f'Packed {ARCHIVE.name}: {ARCHIVE.stat().st_size} bytes; sha256 {sha(ARCHIVE)}',flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--archive-only',action='store_true');args=parser.parse_args()
 if not args.archive_only:build()
 archive()
