# 工作区与版本管理说明

更新：2026-09-30。最新进度统一见[project-status.md](project-status.md)。本次整理更新入口、区分当前/历史状态并完善Git范围；原始轨迹、检查点和冻结输入的路径保持不变，避免破坏来源引用。

## 当前入口与历史记录

| 用途 | 入口 |
| --- | --- |
| 研究进度与待办 | [project-status.md](project-status.md) |
| 当前36项DFT | [05_md_kmesh600](../dft/jobs/05_md_kmesh600/README.md) |
| 候选池与分层选样 | [candidate-selection-20260924.md](candidate-selection-20260924.md) |
| 全部MD的统一索引 | [trajectory-index.json](../hpc/reviews/completed-round1-20260924/trajectory-index.json) |
| 本地18组生产轨迹 | `experiments/zrc_mace_round1/jobs/`，仅本地 |
| 集群90+54组生产轨迹 | `hpc/results/round1-8-64/`、`hpc/results/round1-216/`，仅本地 |
| 历史执行来源 | `hpc/archive/submission-provenance/`，保留原始配置/代码，不是当前提交入口 |
| 历史进度与操作 | `project-progress-20260923.md`、`mace-hpc-remaining.md`等，保留当时状态 |

本地campaign旧summary只覆盖本地调度范围，不能替代162组汇总索引。历史配置中pending、旧目录、旧作业号及哈希反映当时状态，不批量改写为当前状态。清理前一次性审核脚本依赖已删除的旧包，不能从当前目录完整重跑。

## Git保存的内容

- 源码、CPU测试、环境记录、研究设计与最新进度。
- 非赝势DFT输入（INCAR/POSCAR/KPOINTS）、18个校准构型、输入身份与审核记录。
- 候选池轻量诊断、描述符方法、六条选样序列、成本并集和冻结来源。
- 已完成MD的文件索引、哈希及审核摘要；历史失败记录保留真实状态。

`src/carbide_mlip/`仍为模块规划，当前功能在`scripts/`。`data/labeled/`与正式`results/`尚无真实研究标签或评估产物。

## 仅保存在本地的内容

| 内容 | 原因与恢复要求 |
| --- | --- |
| 模型权重与训练检查点 | 大型二进制；按[模型记录](../models/README.md)取得权重并校验 |
| 原始MD轨迹、日志与检查点 | Git只保存索引；从独立数据备份恢复到索引中的相对路径 |
| 完整候选结构池、32,400帧索引、SOAP数组 | 可从原始数据重建；轻量选择结果已版本化 |
| POTCAR、赝势库及含赝势的tgz/zip | 不随源码分发；需使用有权访问的同版Zr_sv/C文件组装并核验 |
| OUTCAR、vasprun.xml等原始DFT输出 | 数据另行备份，输入及审核报告保留在Git |
| 用户提供的集群docx手册、tmp/及缓存 | 本地参考和临时产物，不纳入本次源码快照 |

**GitHub克隆是源码、非赝势输入和证据快照，不是完整计算数据备份**。本地说明中“POTCAR已组装”“tgz已准备”指此工作区；Git克隆不含这些文件，不能直接将输入目录当成完整可提交包。恢复数据/权重/赝势后，按对应脚本重新检查身份并打包，不绕过输入校验。

文档中指向本地大文件的链接在GitHub不可用属于分发边界，不代表文件被删除。历史绝对路径用于追溯，不保证在其他电脑存在。

## 字节身份与后续更新

`.gitattributes`对配置、数据清单、DFT输入、HPC证据及脚本关闭自动换行转换，避免Windows/Linux检出改变已有SHA-256，同时保留文本差异。新建/修改Linux提交脚本仍需LF换行。编辑受清单保护的输入或代码后，须生成明确的新版本及对应清单，不能改写历史哈希来伪装原文件未变。

新结果回传时先更新审核证据和[当前进度](project-status.md)，再同步根README摘要；旧日期报告保留历史状态。

## CPU测试

在已有`carbide-analysis`环境中执行：

```powershell
conda run --no-capture-output -n carbide-analysis python -m unittest discover -s tests -v
```

测试覆盖调度、检查点、数值审查及模拟提交，不加载真实MACE权重或提交集群任务；测试通过不等于DFT精度或物理验证通过。当前DFT包另有[历史离线验收](../hpc/reviews/dft600-k67-delivery/offline-tests.json)。

2026-09-30本机Conda环境实测49项：47项通过、2项因旧collector-only脚本已退役而跳过。原先依赖已删除任务包的测试已改为读取版本化归档协议，在临时目录生成合成检查点；生产代码与原始结果未修改。
