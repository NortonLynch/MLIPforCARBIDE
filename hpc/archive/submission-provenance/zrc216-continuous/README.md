# 216原子剩余54组：连续生产任务包

适用于探索1000 V100、现有已验收的ASE/MACE环境。新目录独立于旧zrc-round1-remaining，保留旧6000 K恢复验证失败证据，不将其改写为通过。

## 上传与提交

上传 zrc216-continuous.tgz 和 zrc216-continuous.tgz.sha256 到 ~/WORK/MaterialModel-HPC。首次解压到新目录，不覆盖正在运行的同名目录：

```bash
cd ~/WORK/MaterialModel-HPC
sha256sum -c zrc216-continuous.tgz.sha256
tar -xzf zrc216-continuous.tgz
cd zrc216-continuous
./submit_all.sh --plan
./submit_all.sh
```

自动使用相邻目录 ../zrc-ase-v100-setup/env/bin/python；请保留超算原环境，无需安装新依赖。环境路径不同时，设置 MACE_PYTHON=/实际路径/env/bin/python。

默认提交一个54元素的数组，最多同时运行4个任务，每项1张V100、4 CPU核、32GB主内存、墙钟上限48小时。`--mem=32G`是CPU主内存，并非显存请求。验证复用原HPC上已通过的216原子3000/6000 K静态精度和4项NVE检查，检查证据哈希及运行环境一致性。不重算已完成的8、64原子任务；不提交CPU汇总作业。旧MD作业仍在排队/运行时拒绝新提交。

只改变并发上限可用 `MACE_PARALLEL=2 ./submit_all.sh`；范围1–54，默认4不是最优卡时结论。其他可选变量：MACE_PARTITION（gnall）、MACE_TIME（48:00:00）、MACE_ACCOUNT、MACE_QOS。不主动配置MPS或同卡多进程，现有计费与共享策略需以超算规则为准。

## 运行协议

- 54组：6温度300/1500/3000/4500/5250/6000 K × 3体积比例0.95/1/1.05 × 3种子17/42/2026。
- 各自使用原来已通过的0.5 ps短测末态；保存的位置、动量、晶胞、质量和PCG64状态不重新生成。
- 同一进程中运行5 ps平衡和10 ps采样，段间在内存中传递状态；0.5 fs、float32、MACE-MH-1/omat_pbe、ASE Langevin、FixCom、摩擦0.01 fs⁻¹与原设置一致。
- 原有NVE漂移、静态数值精度、有限值、灾难性不稳定、时长和轨迹完整性门槛不放宽。数值失败直接blocked_review，保留证据；本包不自动换参数。
- 每50 fs仍写检查点供审计，但绝不读入中断的生产检查点继续计算。基础设施中断后，显式重提才会建立新run目录，从原始短测末态重跑整组15 ps，旧目录保留。每组最多3次完整尝试；数值失败不因重提清空。
- 原100 fs恢复等价测试的失败保留在provenance内。新协议不使用生产段断点恢复，因此该测试不作为连续执行的放行条件，亦不宣称已通过它。

## 检查状态与重新提交

```bash
squeue -u "$USER"
```

日志：logs/prod-作业号_数组索引.out。每组输出：outputs/production/组合名/task.json 和 run-0001、run-0002…；每个run含环境、数值结果、审核与 resources.json（实际PyTorch峰值显存与耗时）。没有记录的GPU上下文显存不能从此文件推算为零。

若发生超时/节点故障，先确认前次所有作业已退出，然后执行：

```bash
./submit_all.sh --retry-from-start
```

已通过且结果校验一致的组合跳过；中断组合从原始短测末态重跑；blocked_review保持阻塞。不要删除失败输出后伪装成第一次尝试。STOP文件放在包根目录可停止各进程并阻止新提交；用户STOP不会自动删除。

## 回传和本机汇总

所有任务结束后，打包结果：

```bash
cd ~/WORK/MaterialModel-HPC/zrc216-continuous
tar --exclude='outputs/cache' -czf ../zrc216-continuous-results.tgz outputs logs submissions
```

下载到本机 D:\MaterialModel\hpc，PowerShell中执行：

```powershell
cd D:\MaterialModel\hpc
tar -xzf .\zrc216-continuous-results.tgz -C .\zrc216-continuous
conda run -n carbide-analysis python .\zrc216-continuous\scripts\run_zrc216_continuous.py collect
```

新包的候选轨迹清单仅列216原子54组；旧8/64原子108组留在原目录。summary将显示本包通过数与项目生产段累计数（108＋本包通过数），不需要把新结果搬进旧目录。collect退出1表示未全部通过，不等于Conda环境有问题。只有54组全部通过才显示162组完成。

完整数值运行不等于DFT物理正确性、热平衡、液态、熔点或扩散系数已验证。本包不执行DFT或训练。