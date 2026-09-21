# 数据与复现约定

## 目录和数据流

`raw → candidates → labeled → splits → experiments → results`

DFT 原始作业保存在 `dft/jobs/`，解析得到的规范标签保存在 `data/labeled/`。模型检查点保存在 `models/`。上述大型产物由 `.gitignore` 排除；将其存储位置、校验值和来源写入轻量清单后再版本化。

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
