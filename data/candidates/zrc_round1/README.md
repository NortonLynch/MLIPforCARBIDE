# 首轮ZrC构型池

162条数值完成的采样轨迹，去掉各条t=0后共32,400帧。64原子原始10,800帧，在250 fs网格上保留2,160帧用于几何选择；原始50 fs轨迹完整保留于HPC结果归档或本地实验目录。250 fs间距不是独立性保证。

| 文件 | 作用 |
| --- | --- |
| `all-sampling-frames.csv` | 三种尺寸全部32,400帧的来源索引、源文件哈希和明确标作MACE的诊断值 |
| `trajectory-diagnostics.csv` | 每条轨迹的温度、压力、势能块变化、短距离和相关性诊断 |
| `candidates64.json`、`candidates64.extxyz` | 2,160帧的来源与无DFT标签结构 |
| `soap64.npz`、`soap-method.json` | 1560维结构描述符及完整参数/版本 |
| `scan-summary.json`、`selection-summary.json` | 检查结果、选择结果与身份哈希 |
| `sequences/` | 两方法×三选样种子，每条200帧；取前20/50/100/200 |
| `DFT-budget-unions.json` | 多序列去重后的DFT成本与逐帧请求来源；全部N=200共552个唯一帧 |
| `selection-coverage.csv` | 开发侧描述符覆盖诊断，不是预测误差 |

只把MD seed17用于开发；42/2026分别预留验证与测试，详见 `data/splits/zrc_round1_frozen_groups.json`。选样种子与MD种子不同。校准18帧从训练候选中排除；其POSCAR在 `dft/structures/zrc_calibration18/`。

所有结构均未标注，所有相态未指派。没有优化结构，也没有把216原子子盒裁成64原子。

[研究依据与本轮结论](../../../docs/candidate-selection-20260924.md)
