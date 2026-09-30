# ZrC 600 eV：18构型 × k6/k7，36个VASP静态任务

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
