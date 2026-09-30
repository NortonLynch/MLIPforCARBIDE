# 第一轮结果之后的 3 项补测

**本批已完成审核。800/k12 的联合应力差超标，900/k14 有 PSMAXN 警告；当前优先按 [文献复核](../../../docs/dft-cutoff-literature-review.md) 验证 600 eV 候选；[01c_reference_check](../01c_reference_check/README.md) 仅为可选。以下保留原补测设计。**

原 11 项都正常结束；但 k8 相对 k10 的最大应力差为 0.234 GPa，超过本项目 0.10 GPa 的标准。因此新增下列输入，继续确定小晶胞参数。三个目录都已放入实际 PBE.64 POTCAR 和公共 JobModel，由用户在集群提交。

| 目录 | ENCUT | Gamma-centered k 网格 | 用途 |
| --- | --- | --- | --- |
| encut_800_k12 | 800 eV | 12×12×12 | 与已有 800/k10 比较，并作为更密网格候选 |
| encut_800_k14 | 800 eV | 14×14×14 | 同时比较 k10、k12，检查非单调应力是否稳定 |
| encut_900_k14 | 900 eV | 14×14×14 | 与 800/k14 检查截断能；作为候选设置的联合精度参考 |

提交清单 [jobs.list](jobs.list) 中的路径相对于上一级 `dft/jobs`；本批记录见 [manifest.json](manifest.json)。沿用原 01_convergence 的同一个受扰动 8 原子 POSCAR，SIGMA=0.10、EDIFF=1E-7、ISPIN=1；没有修改任何已完成任务的计算输入或原始输出。

在每个作业目录内执行 `sbatch JobModel`。三个任务可独立运行；这张清单仅包含本批补测，不含已完成的 11 个任务，也不含尚待同步参数的 02–04 阶段。

验收要求：能量 ≤1 meV/atom、力分量 RMS ≤0.01 eV/Å、最大力分量差 ≤0.03 eV/Å、最大应力分量差 ≤0.10 GPa，全部同时满足。必须检查候选参数相对 900/k14 的直接联合差值。没有预先认定 k12 或任何最高档已完全收敛；若结果不满足，继续补测。

完整规则见 [DFT 标注精度标准](../../../docs/dft-labeling-standard.md)。
