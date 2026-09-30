# ZrC 首批 VASP 6.3.2 输入

> Git分发说明：下文“POTCAR已组装”与“完整包”指本地工作区。GitHub仅保存非赝势输入、脚本和来源清单，不包含POTCAR、原始输出或完整压缩包；克隆后需恢复合法取得的同版赝势并重新核验/打包。参见 [工作区说明](../../docs/workspace-guide.md)。最新状态见 [当前进度](../../docs/project-status.md)。

> 当前待提交：用户指定的 [05_md_kmesh600](05_md_kmesh600/README.md)，18个真实MD构型×6³/7³，共36个600 eV静态任务，分区cnall。完整输入含POTCAR；使用配套submit_all.sh一次提交。下列旧收敛与02–04草案不属于本次提交范围。


原始设计包含 **24 个作业目录**，另有 3 项已完成补测及 2 项可选参考输入，每个包含 `INCAR`、`POSCAR`、`KPOINTS`、已组装的 `POTCAR`，以及 `job.json`、`POTCAR.meta.json` 两份记录。这些输入已统一更新为 `potpaw_PBE.64`，新版 00_smoke 及第一轮 11 项计算已审核；原 600 eV/k8 未满足精度要求，3 项补测也已审核；两项参考复核输入留作可选。计算任务由你在 CPU 集群提交。

**文献复核后优先验证 600 eV 在代表性构型上的相对能量、力和应力；01c 的两项参考检查为可选，不是必须追加任务。原 11 项与 3 项补测均已完成。** 依据见 [文献评估](../../docs/dft-cutoff-literature-review.md)。 后续目录已备好，但应根据收敛结果同步更新参数后再计算。

最新结论见 [3 项补测审核报告](../reviews/confirmation-2026-09-21.md)；首轮见 [11 项审核报告](../reviews/convergence-2026-09-21.md) 与 [DFT 精度标准](../../docs/dft-labeling-standard.md)。当前 24 项原始设计清单保留，补测使用独立清单；02–04 阶段仍保留原始草案输入，应在补测后同步参数再提交。

## 目录与提交顺序

| 目录 | 数量 | 内容与用途 |
| --- | --- | --- |
| `00_smoke/zrc8` | 1 | 8 原子岩盐 ZrC，检查程序、POTCAR 和输出能否正常工作 |
| `01_convergence` | 11 | 同一受扰动的 8 原子构型；检查截断能、k 网格、SIGMA、EDIFF 及非磁性假设 |
| `01b_confirmation` | 3 | 新增 800/k12、800/k14、900/k14，补验应力和联合精度 |
| `01c_reference_check` | 2 | 850/k14、850/k16，检查参考警告及联合精度 |
| `02_relax/zrc8` | 1 | 收敛协议确定后，优化晶体体积、形状与原子坐标 |
| `03_supercell_check` | 3 | 同一受扰动的 64 原子超胞，比较 2³、3³、4³ k 网格 |
| `04_atomic_references` | 8 | 可选：Zr/C 孤立原子的自旋候选与真空盒大小检查 |

纯路径清单见 [jobs.list](jobs.list)（路径相对于本目录，按阶段排序，不代表可一次性提交全部作业）；完整参数表见 [job-list.csv](job-list.csv)，机器可读的设计记录见 [manifest.json](manifest.json)。所有结构均为可复现的人工构建结构；扰动构型**没有温度标签，不是液体，也不是平衡 MD 样本**。

## 1. POTCAR 已从本地赝势库组装

用户提供的 `dft/potpaw_PBE.64.tgz` 已解压至 `dft/psudopotential/potpaw_PBE.64`，并已从该库为全部 24 个目录重新生成 POTCAR。上传这些作业目录即可，无需再配置 VASPKIT 或重新生成 POTCAR。`dft/zrc-vasp632-inputs.zip` 已更新为包含 POTCAR 的完整输入包。

| 势名称 | 实际 TITEL | ZVAL | ENMAX |
| --- | --- | --- | --- |
| Zr_sv | PAW_PBE Zr_sv 04Jan2005 | 12 | 229.898 eV |
| C | PAW_PBE C 08Apr2002 | 4 | 400.000 eV |

使用新版库中的 `Zr_sv/POTCAR` 和 `C/POTCAR`，按每个 POSCAR 的元素顺序进行字节拼接，不修改势内容。ZrC 的顺序为 `Zr_sv`、`C`，孤立原子只包含其对应的一份势。拼接方式依据 [VASP 官方 POTCAR 说明](https://vasp.at/wiki/POTCAR)。

当前库按用户提供的 `potpaw_PBE.64.tgz` 发行包锁定，记录压缩包及所选文件的校验值。单个 POTCAR 的 TITEL 日期是势生成日期，不等于整套库的发行版本；C 保留 2002 年日期并不表示此次仍在使用旧库。README.UPDATES 包含历年更新，不能仅凭其开头的旧日期判断库版本。

此前通过的 Slurm 15309631 烟雾测试使用旧势。完整旧输入、输出、来源记录和旧上传包已保存在 `dft/archive/paw-pbe-legacy-before-64/`，其中作业位于 `jobs/00_smoke/zrc8`。这些原始文件保留不变；当前活动目录已完成新势烟雾测试，审核见 [smoke-15309852](../reviews/smoke-15309852.md)。不能将旧输出与新的 POTCAR 配对，也不能把旧验收视为新版协议已通过。

记录见 [potcar-inventory.json](potcar-inventory.json) 及各目录的 `POTCAR.meta.json`，包括来源路径、TITEL、ZVAL、ENMAX、源文件/解压内容/合并结果的 SHA-256。全部作业的 ENCUT 不低于最大 ENMAX；晶胞优化的 600 eV 也高于 1.3×400=520 eV。这些检查不替代实际数值收敛测试。

赝势库、POTCAR 和包含它们的上传压缩包留在本地，并已排除 Git 跟踪；轻量来源记录纳入版本控制。原始赝势库未被修改。

## job.json 是什么

`job.json` 是本项目的作业说明卡，不是 VASP 输入。它记录该作业的用途/阶段、原子数与元素顺序、INCAR 参数、k 网格、构型来源分组、POSCAR 校验值、POTCAR 校验值及计算/数据集划分状态，供后续整理能量、力和应力标签时追溯来源。

VASP 运行需要 INCAR、POSCAR、KPOINTS、POTCAR；不读取 `job.json` 或 `POTCAR.meta.json`。保留 JSON 有助于防止结果与输入混淆。00_smoke 已审核为 `label_status=converged`，但 `dataset_eligible=false`，仅通过运行检查；11 项收敛作业也已标记 `converged`，但均不作为生产数据；其他作业仍为 `not_calculated`。`dataset_split=unassigned` 表示尚未分配训练/验证/测试集合。提交任务不会自动更新这些字段，需要结果整理流程更新。若手动修改输入，应同步记录，避免说明与实际计算不一致。

## 2. 原始试验起点（历史设计）

下表保留最初设计以解释已有文件。2026-09-21 审核已否定 600 eV/k8 作为最终生产组合；当前重新验证 600 eV 候选，以代表性构型的相对能量、力和应力决定生产参数；原 900 eV 警告仍保留记录，详见上方新标准：

| 参数 | 起始值 | 设计目的 |
| --- | --- | --- |
| GGA | PE | PBE 泛函，不加 U、SOC 或色散修正 |
| POTCAR | Zr_sv + C | 纳入 Zr 半芯态，后续需检查极端构型适用性 |
| ENCUT | 600 eV | 作为拟定生产起点，用 520/600/700/800 eV 检验 |
| PREC | Accurate | 使用较严格的网格精度 |
| EDIFF | 1E-7 eV/晶胞 | 电子收敛；另有 1E-8 对照 |
| ALGO / NELM | Normal / 200 | 稳健的电子迭代起点；达到步数上限不算收敛 |
| ISMEAR / SIGMA | 0 / 0.10 eV | 固定 Gaussian 数值展宽，另有 0.05/0.20 对照 |
| LREAL | .FALSE. | 避免实空间投影近似影响力的一致性 |
| LASPH | .TRUE. | 保留 PAW 球内非球形梯度贡献 |
| ADDGRID | .FALSE. | 固定默认网格方案；不未经验证地引入附加网格设置 |
| ISPIN | 1，体相 | 非磁性起点，另有自旋极化诊断 |
| ISYM | 0，单点 | 不对受扰动构型强制空间对称性 |
| NSW / IBRION / ISIF | 0 / -1 / 2 | 固定原子与晶胞，只计算能量、力和完整应力 |
| ISTART / ICHARG | 0 / 2 | 独立从头电子求解，避免意外复用不一致的波函数 |
| LWAVE / LCHARG | .FALSE. / .FALSE. | 首批减少大输出文件，保留 OUTCAR 与 vasprun.xml |

首个烟雾测试使用 4×4×4 网格；拟定 8 原子体相生产设置为 8×8×8；64 原子超胞先比较 2×2×2、3×3×3、4×4×4。所有网格均为 Gamma-centered，原点偏移为零。它们不等于仅 Gamma 点，体相作业应使用 **vasp_std**。

目标程序为 VASP 6.3.2，保留原有收敛研究设计；没有使用 `ISIF=8`、`EFERMI=MIDGAP` 或新版本的有限温度四面体选项。INCAR 不统一写入机器相关的 NCORE/KPAR。公共提交模板 `dft/JobModel` 沿用已运行过的集群模块与 MPI 启动方式，并增加输入检查和线程设置；提交前仍需核对其中的分区与资源请求。工作目录指向具体作业目录，首轮 MPI 使用 `OMP_NUM_THREADS=1`，并行参数随后单独测速。

## 3. 怎么做收敛判断

所有 `01_convergence` 作业的 POSCAR 完全相同，因此可以直接比较力和应力分量。使用受扰动结构是为了避免完美晶体的对称性让力处处为零而掩盖误差。

| 比较内容 | 对应作业 |
| --- | --- |
| 截断能 | `encut_520_k8`、`encut_600_k8`、`encut_700_k8`、`encut_800_k8` |
| k 网格 | `encut_800_k4`、`encut_800_k6`、`encut_800_k8`、`encut_800_k10` |
| 展宽 | `sigma_0.05`、`encut_800_k10`（0.10）、`sigma_0.20` |
| 电子阈值 | `encut_800_k10`（1E-7）与 `ediff_1e-8` |
| 自旋 | `encut_600_k8` 与 `spin_check`，后者有小的初始磁矩，未约束总自旋 |

建议作为第一轮数值判据：能量差不大于 **1 meV/atom**，力分量 RMS 差不大于 **0.01 eV/Å** 且最大分量差不大于 **0.03 eV/Å**，应力最大分量差不大于 **0.1 GPa**。这是本项目拟定的误差预算，不是 VASP 官方保证值。

比较应看最高两档是否形成平台；800 eV 与 10³ k 网格只是当前最高测试点，不自动代表真值。如果没有平台就继续增加。改变 SIGMA 也改变数值自由能面，需要同时比较能量、力、应力以及熵项，不应只看某个能量差小就认定收敛。

选择最终参数后，还需在实际采集的高温固态、短键/压缩及液态构型上抽查。当前这一张受扰动晶体不能证明整个极端条件空间都收敛。

## 4. 优化与超胞单点

`02_relax/zrc8` 的初始晶格常数为 **4.7 Å 的近似值**。它采用 `IBRION=2`、`ISIF=3`、`ISYM=2`、`EDIFFG=-0.005`，同时允许坐标与晶胞优化。提交前把已确定的 ENCUT、k 点、SIGMA 等同步进去；检查 ENCUT 至少达到该 POTCAR 的 `1.3×max(ENMAX)`，并通过实际应力收敛验证。

完成后检查残余力、残余压力以及是否用尽 NSW。将最终 CONTCAR 放到新的单点目录，用固定的最终参数重新计算；体积变化时平面波基组与 Pulay 应力可能影响结果，不能只凭优化程序结束就接受结果。

`03_supercell_check` 三个目录是同一张压缩、剪切和轻微扰动的 64 原子晶体，用于检验更接近后续标注尺寸的 k 点需求。先使用收敛后的 ENCUT/SIGMA。它与 8 原子收敛构型不是简单重复关系，不可直接拿两者总能量作收敛差。

后续给真实 MD 帧做标签时沿用静态参数：**NSW=0，不优化该帧**。换入真实 POSCAR 后按其晶胞确定 k 网格、重新检查元素顺序，并创建新的作业来源记录。不要把这里的示例构型当作已经平衡的高温数据。

## 5. 可选孤立原子参考

Zr 与 C 各有 `NUPDOWN=0/2/4` 的自旋候选，`MAGMOM` 与其一致；盒子为 16×17×18 Å，Gamma 单点，`ISPIN=2`、`ISYM=0`、`SIGMA=0.01`、`EDIFF=1E-8`。自旋 2 另有 20×21×22 Å 的盒子检查。

这些是候选原子态，**不能预先认定某个自旋就是 DFT 最低能态**。应比较真正收敛的能量和占据；若最低态不是自旋 2，要给获胜态补做大盒子检查，并视需要检查展宽与初始占据。最终 ENCUT 与元素赝势必须与体相协议一致。孤立原子低展宽是为得到原子基准而单列的协议，并非混入体相的常规标签。

对于 MACE-MH-1，E0 与可学习偏置共同影响原子参考，不能把两个原子能量直接机械地替换到所有模型分支。即使暂不做原子参考，也可先完成体相流程，随后评估只使用训练数据的参考能量估计方案。

## 6. 输出与标签的物理含义

每个作业保留 `INCAR`、`POSCAR`、`KPOINTS`、实际使用的 `POTCAR` 及其来源/校验记录、`OUTCAR`、`OSZICAR`、`vasprun.xml` 和调度日志；优化作业还要保留 `CONTCAR`。记录输出中的 VASP 实际版本。

本协议拟采用与力一致的 **自由能 TOTEN** 作为能量标签，同时保留 energy without entropy 和 energy(sigma→0)，方便检查和与预训练数据对照。VASP 展宽下的力和应力与自由能一致；不要将某个外推能量直接与力混配而不检查差异。ASE 解析时需明确区分 `free_energy` 与 `energy`。

本包用 Gaussian 数值展宽，**SIGMA=0.10 不表示离子温度为某一数值，更不会随 4500–6000 K 自动变化**。首轮研究的是统一电子处理下的高温原子构型。如果以后研究电子温度效应，应另立 Fermi-Dirac 协议并记录电子温度，不混入当前单一能量面的训练集。

VASP OUTCAR 应力正号表示压缩；项目约定正号表示拉伸。解析时需要转换符号、kBar 单位与 Voigt 顺序；ASE 已转换的应力不要再次翻转。`1 kBar = 0.1 GPa`。

本方案是独立设计的 PBE 数据协议，**尚未证明与 MH-1 的 OMat 预训练标签设置完全一致**。因此零样本能量偏移不能全部解释为模型失效，必须先核对参考能量、赝势和电子处理差异。

## 参考与状态

- [VASP：赝势选择](https://vasp.at/wiki/Choosing_pseudopotentials)
- [VASP：ENCUT](https://vasp.at/wiki/ENCUT)
- [VASP：展宽方法与力一致性](https://vasp.at/wiki/Smearing_technique)
- [VASP：ISIF 与应力、晶胞优化](https://vasp.at/wiki/ISIF)
- [VASP：LREAL](https://vasp.at/wiki/LREAL)
- [VASP：LASPH](https://vasp.at/wiki/LASPH)
- [VASP：NUPDOWN](https://vasp.at/wiki/NUPDOWN)
- [MACE：微调参考能量说明](https://mace-docs.readthedocs.io/en/latest/guide/finetuning_guidance.html)

设计日期：2026-09-21。已检查结构、元素顺序和各组参数一致性；未在本机执行 VASP。赝势内容已按用户提供的 `potpaw_PBE.64` 发行包及文件校验值锁定；新版集群烟雾测试已通过，实际参数收敛仍待完成。

## 输入版本与复现

协议标识为 `zrc-pbe64-zrsv-c-v2-proposed`，目标程序为 VASP 6.3.2；集群可用 VASPKIT 1.3.5，但本次 POTCAR 直接由本地库组装。活动作业统一位于本目录；换库前的输入与计算证据已独立归档，当前上传包由 .64 输入重新生成。

从项目根目录运行 `python scripts/prepare_zrc_vasp_jobs.py` 可复现三类 VASP 输入、各目录的设计记录与作业清单；需要 ASE 和 NumPy。生成器不会覆盖手工修改过的文件。`input-validation.json` 记录当前完整输入的静态解析检查结果，不表示 VASP 已运行或参数已收敛。

本次组装入口为 `scripts/assemble_zrc_potcars.py`，从项目根目录运行。脚本默认读取当前 .64 库，重复运行时核对现有 POTCAR 与源文件是否一致；再次更换势时必须先归档已有输入和结果。原始输入生成器也会拒绝覆盖已更新的作业记录。
