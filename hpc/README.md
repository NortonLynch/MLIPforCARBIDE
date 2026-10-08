# HPC交付与结果归档

> 2026-10-08更新：36/36项DFT结果已回传验收，18对k6/k7全部通过四项比较预算；18帧MACE真实DFT对照已完成。原始结果见[回传目录](results/zrc-dft600-k67-20261008/)，结论见[完整审核](../dft/reviews/dft600-k67-20261008/report.md)与[当前进度](../docs/project-status.md)。此前162组MD生产数据与18份校准POSCAR身份复核通过。下列tgz、原始生产数据与模型保留在本地，不随Git分发；Git保留非赝势输入、索引和审核证据，详见[工作区说明](../docs/workspace-guide.md)。

已完成的CPU交付包：[zrc-dft600-k67.tgz](zrc-dft600-k67.tgz)和[校验文件](zrc-dft600-k67.tgz.sha256)。固定600 eV，18个64原子构型各算6³/7³网格，共36个VASP静态任务；分区cnall。原[提交说明](../dft/jobs/05_md_kmesh600/README.md)及冻结配置保留历史状态，该批无需再提交。

2026-10-02异常恢复入口[retry22-submit.sh](retry22-submit.sh)现仅供历史追溯，无需再次执行。它只提交22号，显式排除待核查节点`ibc12b07n24`，保留原输入与提交历史；已有活动数组、队列查询失败或重复恢复提交时会拒绝。最新回传确认旧`15501455_22`已取消，新`15535277_22`在`ibc11b09n15`以`COMPLETED / 0:0`结束，耗时3:21:25，VASP结果通过验收。旧启动异常的根因仍未证明，见[原诊断证据](reviews/dft600-k67-task22-20261002/audit.json)。

## 已完成的DFT网格比较与校准对照

| 目录 / 文件 | 内容 |
| --- | --- |
| `results/zrc-dft600-k67-20261008/` | 完整DFT回传数据、运行输入、Slurm日志与提交历史；保留旧失败和成功补算证据 |
| `../dft/reviews/dft600-k67-20261008/` | 36项验收、18对网格比较及MACE校准对照报告与派生分析 |
| `../configs/experiments/zrc_dft_labeling_v1.json` | 后续同ZrC64协议的600 eV / Gamma 6³工作基准与标签验收要求 |

36项均通过正常结束、EDIFF、输出完整性及最高能带占据检查，原包262条SHA-256校验一致。后续基准适用于本次ZrC64协议范围；600 eV为用户固定值，本批未新增截断能或绝对收敛认证。18帧MACE对照属于校准诊断，不能视为独立测试集或可靠温度边界。本次审核未提交新任务。

## 已完成的首轮MD结果

2026-09-24 已审核全部 **162/162** 组生产任务：本地18组、HPC原包90组、216原子连续补算54组。各组完成5 ps预定平衡段和10 ps采样段；不据此认定已达到热平衡或物理正确。

| 目录 | 内容 |
| --- | --- |
| `results/round1-8-64/production/` | HPC完成的8/64原子90组生产轨迹、检查点和逐组审查 |
| `results/round1-216/production/` | 新回传216原子54组连续生产轨迹和逐组审查 |
| `results/*/logs/`、`submissions/` | 原始Slurm日志、提交记录 |
| `reviews/completed-round1-20260924/` | 完成审核、162组统一路径索引、清理前文件哈希、压缩包比对、清理清单 |
| `reviews/completed-round1-20260924/numerical-evidence/` | 小型门控证书及216原子失败断点对照的原始证据 |
| `archive/submission-provenance/` | 两次提交的冻结配置、代码、清单；仅供追溯，不是当前可执行包 |
| `archive/`、其余`reviews/` | 既往部署和审核历史 |

本地18组仍在 `experiments/zrc_mace_round1/jobs/`。模型唯一主副本在 `models/mace-mh-1.model`；所有原始pilot起点仍在本地campaign。STOP与停止当前组控制文件保持原样。

已删除四个经逐文件比对相同的tgz、旧校验旁文件、两份重复模型及部署输入、成功验证的中间轨迹与过时提交入口。迁移后复核972个段文件的哈希；全部生产数据保留。实际净节省约488.3 MiB，详见 [清理记录](reviews/completed-round1-20260924/cleanup-result.json)。旧证书里的路径和哈希是历史记录，部分验证中间文件已按要求清除，不能声称仍可从该路径重新散列它们。

**首轮MACE无待提交GPU任务，本轮DFT比较也已完成。** 旧MACE文档中的tgz上传指令已失效；本页顶部DFT包与恢复脚本均保留供追溯，不应重复提交。源代码归档若要重建运行包，需重新准备环境、权重和输入，不能直接运行归档提交脚本。

后续入口：[候选池与DFT校准方案](../docs/candidate-selection-20260924.md)、[18个校准结构](../dft/structures/zrc_calibration18/README.md)。216原子本轮使用整段连续计算，没有宣称通过其旧的严格断点轨迹一致性门槛。
