# ZrC 首轮 MACE 剩余144组 一次提交包

本包用于探索1000的 V100 / ASE / MACE 环境，接续原162组矩阵。已有18组完整生产任务在本地完成，本包不重复提交；其余144组的自身短测末态、位置、动量、晶胞、质量和PCG64随机数状态完整保留。原始本地记录不修改。

## 一次提交

环境沿用已经通过作业15325225验收的个人环境。**不要删除超算上的 `zrc-ase-v100-setup/env`**，本次只整理本地工作区。无需重装依赖或再次上传环境安装包。

把 `zrc-round1-remaining.tgz` 和 `.tgz.sha256` 上传到 `~/WORK/MaterialModel-HPC`，不要覆盖一个已经运行过的同名目录。

```bash
cd ~/WORK/MaterialModel-HPC
sha256sum -c zrc-round1-remaining.tgz.sha256
tar -xzf zrc-round1-remaining.tgz
cd zrc-round1-remaining
./submit_all.sh
```

脚本通过 sbatch 提交全部依赖，不在登录节点跑 MD。提交完成即可断开登录。`submissions/jobs.tsv` 记录所有作业号。没有发送邮件等外部通知。

默认环境路径为相邻目录 `../zrc-ase-v100-setup/env/bin/python`。如环境放在其他地方，提交前设置：

```bash
export MACE_PYTHON=/你的实际路径/env/bin/python
```

## 提交范围和依赖

| 尺寸 | 剩余生产组合 | 默认最多同时运行 | 生产开始条件 |
| --- | --- | --- | --- |
| 8原子 | 45 | 2张GPU | 8原子验证通过 |
| 64原子 | 45 | 2张GPU | 64原子验证通过 |
| 216原子 | 54 | 4张GPU | 216原子验证通过 |

每个任务申请1张GPU、4 CPU核、32GB主内存。默认总计最多8张GPU（验证期间各尺寸最多一张，随后由对应生产组接替）。并发是上限，实际取决于排队和账号配额。全部144组以3个Slurm任务数组提交，不是一次占用144张卡。

一个命令会提交3个验证作业、3个生产数组及1个CPU汇总作业。验证使用gnall，汇总使用cnmix。某个尺寸验证失败时，仅其生产数组因依赖失败取消；其他尺寸继续。原始失败输出保留。

每个尺寸的验证在自身中心体积、seed17的3000K和6000K短测末态上进行：

1. float32/float64能量、力、应力对照；能量仍采用热态减同盒理想结构能量。
2. 各1 ps NVE、0.5/0.25 fs步长检查，仍使用绝对线性漂移≤1 meV/(atom·ps)门槛。
3. 对门控选定的步长/精度执行100 fs NVT连续/中断恢复对照，50 fs处故意保存中断。位置最大分量差≤1e-6 Å、动量最大分量差≤1e-5 ASE内部单位，最终随机数状态严格一致。这些迁移检查容差在HPC执行前固定，不在失败后自动放宽。

每个生产组合从自己的已通过短测末态重新分支运行5 ps平衡+10 ps采样。ASE Langevin、FixCom、摩擦0.01 fs⁻¹、日志5 fs、候选帧与检查点50 fs沿用原协议。仅允许原来的三档有限数值尝试：0.5 fs/float32、0.25 fs/float32、0.25 fs/float64，并受对应尺寸验证结果进一步约束。不会重新赋速或改变温度、体积、种子。

本包把Windows短测末态作为新生产段的可追溯起点。集群重新记录环境与段签名，不把跨操作系统迁移冒充逐位相同的旧段续跑。集群内中断恢复须使用同一包、同一环境和原输出目录。

## 配额及时间

可预览提交规模，不提交：

```bash
./submit_all.sh --plan
```

默认验证作业限时12小时、每个生产任务48小时，均是墙钟上限，不是耗时预测。根据账号配额可以先限制并发：

```bash
MACE_PARALLEL=4 ./submit_all.sh
```

MACE_PARALLEL至少为3，分别为三个尺寸保留一个并行槽。其他可选变量：MACE_PARTITION（默认gnall）、MACE_CPU_PARTITION（默认cnmix）、MACE_ACCOUNT、MACE_QOS、MACE_VALIDATION_TIME、MACE_PRODUCTION_TIME。未指定账户/QOS时沿用集群默认，不猜填。

## 进度和恢复

```bash
squeue -u "$USER"
./status.sh
```

status.sh汇总已有记录，未完成时返回非零状态属于正常提示；它会检查已完成输出的哈希，可能产生一定文件读取量，无需频繁运行。最终汇总作业自动生成 `outputs/summary.json` 和 `outputs/candidate-trajectories.json`。后者列出集群已通过生产段的采样轨迹，模型预测不是DFT标签；本地18组的轨迹仍保留在原工作区。

任务独立目录为 `outputs/production/组合名/`，各有queue、runtime、环境记录、日志、帧与检查点，不共写同一队列。验证输出在 `outputs/validation/原子数/`。不要修改 manifest、脚本或输入文件来绕过签名和审核。

如果超时或节点故障，先检查日志。脚本会响应Slurm结束前信号，尽量提交检查点；突然被强制杀死时，从最后完整提交的检查点恢复。不要在旧作业仍运行时重复提交。

修复基础设施问题、确认原作业均退出后，可以：

```bash
./submit_all.sh --resume
```

已通过且文件校验一致的任务跳过，不重复MD；中断任务保留原参数、位置、动量和RNG。数值重试耗尽的blocked_review不会因重提而清空。脚本查到前次作业仍在队列中时拒绝重复提交。任何提交中途失败已提交的作业号仍保存在ledger中，先查看其状态。

需要主动停止时，在包根目录建立 `STOP` 文件，各工作进程在检查位置保存退出；此标记不会被自动清除。只有明确决定恢复后才移除用户STOP。无需修改本地旧矩阵的STOP或FINISH_CURRENT_JOB文件。

## 保留与解释

`tasks.tsv` 是144组输入清单。`manifest.json` 包含来源哈希、已完成18组排除清单和环境要求。`provenance/` 保留本地矩阵状态及HPC静态验收证据。本地原162组短测、6项原始门控、18组生产结果及失败/恢复记录仍保留于experiments；DFT文件不属于本次清理范围。

全部通过仅表示声明时长完成且数值审核通过，不代表DFT精度、热平衡、液相、熔点或扩散系数已获验证。提交包未包含DFT提交或模型训练入口。

Slurm依赖与信号参考：https://slurm.schedmd.com/sbatch.html
