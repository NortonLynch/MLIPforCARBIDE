# 参考计算复核：850 eV / k14、k16

**文献复核后，本批降为可选参考检查，不是当前必须提交的任务。当前优先验证 600 eV 候选在代表性构型上的相对能量、力和应力；详见 [文献评估](../../../docs/dft-cutoff-literature-review.md)。下文保留原设计。**

前三项补测已返回。800/k12 相对 900/k14 的最大应力差为 0.120301453 GPa，超过 0.10 GPa；900/k14 又出现 Zr_sv 的 `PSMAXN for non-local potential too small` 警告，不能未经核实就当作可靠高精度参考。

当前保守候选为 800 eV/k14，尚未正式认证。本目录只新增两项，用同一构型、同一赝势寻找没有未解决物理警告的参考，并检查联合精度。

| 输入目录 | ENCUT | Gamma-centered 网格 | 比较目的 |
| --- | --- | --- | --- |
| encut_850_k14 | 850 eV | 14×14×14 | 与已有 800/k14 比较截断能，并检查 PSMAXN 警告是否消失 |
| encut_850_k16 | 850 eV | 16×16×16 | 与 850/k14 检查网格，与 800/k14 直接检查联合差值 |

两个目录均包含 INCAR、POSCAR、KPOINTS、POTCAR、来源元数据及 JobModel。在各目录执行 `sbatch JobModel`；[jobs.list](jobs.list) 路径相对于上一级 `dft/jobs`，无需重跑 01b。

验收须同时满足：能量差 ≤1 meV/atom、力分量 RMS ≤0.01 eV/Å、最大力分量差 ≤0.03 eV/Å、最大应力分量差 ≤0.10 GPa。三组比较分别为 800/k14↔850/k14、850/k14↔850/k16、800/k14↔850/k16。先审查正常结束、真实 SCF 收敛及所有物理警告；数值差通过不能覆盖未解决的参考警告。

850 eV 是新的待验证点，并非官方保证不会报警的设置。若仍出现警告，应先评估降低参考截断能或另立更硬赝势协议，不要修改 POTCAR 内容、只改变文件中的 PSMAXN 数字，或继续盲目提高 ENCUT。官方说明见 [PSMAXN 警告](https://vasp.at/forum/viewtopic.php?p=26126) 与 [POTCAR 规则](https://vasp.at/wiki/POTCAR)。

完整审核见 [confirmation-2026-09-21](../../reviews/confirmation-2026-09-21.md)，标准见 [DFT 标注精度标准](../../../docs/dft-labeling-standard.md)。这批通过后仍要在实际超胞和高温代表帧上验证，不能把单张人工构型等同于整个研究范围。
