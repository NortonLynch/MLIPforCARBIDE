# 数据与复现约定

> 当前进度见 [project-status.md](project-status.md)。本轮按全局MD种子划分来源：17开发/校准、42验证预留、2026测试预留，同种子的尺寸/体积/加热后代不拆分。18个协议校准帧不计入训练序列，详见 [冻结方案](candidate-selection-20260924.md)。PBE.64 smoke与基础收敛计算已审核，真实MD帧的36项网格比较尚待回传。

## 目录和数据流

`raw → candidates → labeled → splits → experiments → results`

VASP 6.3.2 输入统一存放在 `dft/jobs/`，其中 `job-list.csv` 为参数清单，`jobs.list` 为相对路径清单；POTCAR 已从用户提供的 `dft/potpaw_PBE.64.tgz` 解压库按 POSCAR 顺序组装，当前协议为 `zrc-pbe64-zrsv-c-v2-proposed`，来源、势头信息和校验值见 `dft/jobs/potcar-inventory.json`。轻量输入与清单纳入版本控制，原始输出在对应作业目录归档并由该目录的 `.gitignore` 排除。解析得到的规范标签保存在 `data/labeled/`。模型检查点保存在 `models/`。上述大型产物由 `.gitignore` 排除；将其存储位置、校验值和来源写入轻量清单后再版本化。

换库前的输入、旧烟雾测试 Slurm 15309631 输出及审核证据保存在 `dft/archive/paw-pbe-legacy-before-64/`。旧势结果属于原协议；新PBE.64烟雾测试、11项收敛与3项补测均已审核。解析历史结果必须读取同一归档中的原始输入，不能关联到活动目录的新POTCAR，也不能混用两个协议的标签。

## 单位和构型记录

统一使用 Å、eV、eV/Å、eV/Å³。能量标签保存总能量，评估时另外计算每原子误差。应力采用拉伸为正的 3×3 张量；适配器必须验证原始程序的符号、单位与分量顺序，并明确应力与 virial 的转换。

建议交换格式为 extxyz，具体读写适配器后续实现。每个构型至少关联以下元数据：

| 字段 | 含义 |
| --- | --- |
| structure_id | 不可变构型 ID，重复构型共享可核查标识 |
| material | ZrC、HfC 或 TaC |
| source_group | 原始轨迹或同源结构组，用于隔离数据划分 |
| source_model / source_run / frame | 生成模型、运行编号和帧索引 |
| temperature_K / volume_A3 | 采样条件；未知时保留为空，不捏造 |
| phase_label / phase_evidence | 状态标签和依据；未验证时标为 unknown |
| dft_protocol_id | DFT 设置及版本的关联键 |
| label_status | pending、converged 或 failed |
| split | train、validation 或 test |

仅将经过收敛和完整性检查的标签加入可用数据集。失败 DFT 作业保留状态与原因，不当作有效训练样本。

## 数据隔离

先按来源分组再划分数据，清理跨集合重复和近重复构型。独立测试清单冻结并记录校验值；不使用测试标签挑选训练样本、调参或决定停止。验证集可以用于模型选择，但不属于最终测试结果。

## 每次实验记录

实验编号建议为 `zrc_<stage>_<strategy>_n<budget>_s<seed>_<timestamp>`。保存配置快照、代码版本（若有提交则记录提交号）、依赖版本、权重标识与校验值、数据清单校验值、种子、DFT 协议、硬件、运行时间、失败信息和指标文件。

指标至少注明单位、构型数量、原子数量和聚合方式。扩散系数需要报告拟合时间区间及单位，结构量需要记录统计条件。只有具备参考或明确判据的结果才可用于声明可靠性。
