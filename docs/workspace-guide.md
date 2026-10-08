# 工作区与版本管理说明

更新：2026-10-08。最新进度统一见[project-status.md](project-status.md)。36/36项DFT通过回传审核，18对k6/k7全部通过既定预算，后续同类ZrC64静态标注采用600 eV / Gamma中心6³工作基准；18帧MACE真实DFT对照已完成。这些校准帧不是独立测试集，尚未认证可靠温度边界。本次整理更新入口与当前/历史状态；原始轨迹、检查点和冻结输入的路径保持不变，避免破坏来源引用。

## 当前入口与历史记录

| 用途 | 入口 |
| --- | --- |
| 研究进度与待办 | [project-status.md](project-status.md) |
| 36项DFT与MACE校准审核 | [2026-10-08完整报告](../dft/reviews/dft600-k67-20261008/report.md) |
| 后续DFT标注工作基准 | [zrc_dft_labeling_v1.json](../configs/experiments/zrc_dft_labeling_v1.json)，600 eV / Gamma 6³及验收要求 |
| 已完成DFT交付来源 | [05_md_kmesh600](../dft/jobs/05_md_kmesh600/README.md)，保留冻结输入及历史提交规则，无需重复执行 |
| 候选池与分层选样 | [candidate-selection-20260924.md](candidate-selection-20260924.md) |
| 全部MD的统一索引 | [trajectory-index.json](../hpc/reviews/completed-round1-20260924/trajectory-index.json) |
| 本地18组生产轨迹 | `experiments/zrc_mace_round1/jobs/`，仅本地 |
| 集群90+54组生产轨迹 | `hpc/results/round1-8-64/`、`hpc/results/round1-216/`，仅本地 |
| 完整DFT回传结果 | `hpc/results/zrc-dft600-k67-20261008/`，仅本地；保留输入、运行输出和提交历史 |
| 历史执行来源 | `hpc/archive/submission-provenance/`，保留原始配置/代码，不是当前提交入口 |
| 历史进度与操作 | `project-progress-20260923.md`、`mace-hpc-remaining.md`等，保留当时状态 |
| 历史演示资料 | `outputs/ZrC项目汇报_20260930.pptx`；代表当时的汇报内容，不替代最新结果报告 |
| 演示概念图 | `docs/figures/briefing-atoms-concept-20260930.png`；研究示意，不是计算结果或可靠性证据 |

本地campaign旧summary只覆盖本地调度范围，不能替代162组汇总索引。历史配置中pending、旧目录、旧作业号及哈希反映当时状态，不批量改写为当前状态。清理前一次性审核脚本依赖已删除的旧包，不能从当前目录完整重跑。

冻结网格比较配置`configs/experiments/zrc_dft600_k67.json`中的提交状态仍保留交付时含义；新结论另存为`zrc_dft_labeling_v1.json`，不改写原包哈希。22号原取消尝试与成功补算`15535277_22`均作为来源证据保留，恢复脚本无需再次执行；成功补算不能证明旧启动异常的具体根因。600 eV为用户固定参数，本批k6/k7比较未新增截断能或绝对收敛认证。

## Git保存的内容

- 源码、CPU测试、环境记录、研究设计与最新进度。
- 非赝势DFT输入（INCAR/POSCAR/KPOINTS）、18个校准构型、输入身份与审核记录。
- 候选池轻量诊断、描述符方法、六条选样序列、成本并集和冻结来源。
- 已完成MD的文件索引、哈希及审核摘要；历史失败记录保留真实状态。
- DFT网格比较与MACE校准对照的审核报告、轻量派生指标和图表；原始DFT输出另行备份。
- 已核查的历史汇报PPT、概念图与生成说明；日期和示意属性由[演示资料索引](../outputs/README.md)标明。

`src/carbide_mlip/`仍为模块规划，当前功能在`scripts/`。真实DFT校准输出保存在上述HPC回传目录，对照结果在`dft/reviews/dft600-k67-20261008/`；`data/labeled/`的正式标签导出接口与正式`results/`的独立验证/测试产物仍待建立，不能将已有校准审核误解为正式独立评估。

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

当前下一步为标签验收与导出接口、独立验证/测试预算及判据、按冻结来源和选样序列开展首批标注，再完成多种子训练比较与物理验证。本次整理不启动新MD/DFT任务，也不移动原始科研数据。

## CPU测试

在已有`carbide-analysis`环境中执行：

```powershell
conda run --no-capture-output -n carbide-analysis python -m unittest discover -s tests -v
```

测试覆盖调度、检查点、数值审查及模拟提交，不加载真实MACE权重或提交集群任务；测试通过不等于DFT精度或物理验证通过。当前DFT包另有[历史离线验收](../hpc/reviews/dft600-k67-delivery/offline-tests.json)。

2026-09-30本机Conda环境实测49项：47项通过、2项因旧collector-only脚本已退役而跳过。原先依赖已删除任务包的测试已改为读取版本化归档协议，在临时目录生成合成检查点；生产代码与原始结果未修改。

2026-10-08再次运行49项CPU测试：47项通过，2项仍按上述退役原因跳过。提交前完成1,938次SHA-256核对，覆盖972个MD生产文件、324个MD审核文件、18个校准POSCAR、36套DFT核心输入/输出、262条冻结输入校验和两份任务/结果包；全部匹配。另核查JSON/Python解析、14份Shell脚本语法及入口链接，见[本次版本检查记录](reviews/repository-check-20261008.json)。仅将散落的22号空日志移入诊断证据目录；科研数据未删除、未移动。
