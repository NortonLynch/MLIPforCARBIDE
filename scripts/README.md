# 执行入口

当前状态见[任务进度](../docs/project-status.md)。首轮MD已完成，本地停止标记保留。脚本包含不同阶段与历史用途，不能按文件名顺序全部执行。

| 用途 | 脚本 | 当前说明 |
| --- | --- | --- |
| 环境验收 | `check_mace_environment.py`、`check_analysis_environment.py` | 安装测试，合成标签不是研究数据 |
| 结构/性能起点 | `prepare_zrc_mace_boxes.py`、`benchmark_mace_boxes.py` | 初始结构与短推理基准 |
| MD引擎与审核 | `zrc_md_engine.py`、`zrc_md_review.py` | 数值积分、检查点与日志审查 |
| 本地MD | `run_zrc_md_campaign.py`、`start_zrc_md_campaign.ps1` | 历史入口；不要重复启动已完成矩阵 |
| 集群MD | `run_zrc_hpc.py`、`run_zrc216_continuous.py` | 原批次及216原子连续协议 |
| 集群MD打包 | `build_zrc_hpc_bundle.py`、`build_zrc216_continuous_bundle.py` | 依赖当时目录/状态，旧包已归档清理 |
| 清理前审核 | `audit_completed_round1.py` | 一次性历史操作，依赖已删除的重复tgz |
| 候选池/选样 | `prepare_zrc_calibration_pool.py` | CPU整理、SOAP、18帧导出与6条序列；重跑会重写派生产物 |
| 导出核查 | `verify_zrc_calibration_export.py` | 回读原始轨迹核对结构/分组，写出核验和预算并集 |
| 前期DFT准备 | `prepare_zrc_vasp_jobs.py`、`assemble_zrc_potcars.py` | 输入/赝势组装，受对应协议与阶段约束 |
| 前期DFT审核 | `review_zrc_convergence.py`、`review_zrc_confirmation.py` | 11项收敛及3项补测 |
| 当前DFT打包 | `build_zrc_dft_kmesh_bundle.py` | 600 eV、18帧×k6/k7，需要本地结构、赝势与依赖 |
| 当前DFT离线测试 | `test_zrc_dft_delivery_offline.py` | 模拟调度/VASP，无真实提交 |

当前提交与回传说明在[05_md_kmesh600](../dft/jobs/05_md_kmesh600/README.md)。Git不分发POTCAR、权重、原始轨迹及完整tgz，见[工作区说明](../docs/workspace-guide.md)。正式标签接口、训练和可靠性评估模块仍待实现。

## CPU测试

在项目根目录执行：

```powershell
conda run --no-capture-output -n carbide-analysis python -m unittest discover -s tests -v
```

`tests/`覆盖检查点、恢复调度、数值审查、集群调度和216原子连续协议。使用合成或模拟对象，不运行真实研究MD，不提供DFT准确性证明。

2026-09-30验证：49项中47项通过；2项针对已退役的`submit_review_only.sh`而显式跳过，历史验收保存在`hpc/reviews/collector-submission/`。迁移/连续计算测试使用归档协议和临时合成检查点，不依赖已删除的旧任务包或私有生产轨迹。Windows请通过Conda激活运行，以加载正确的数值库。
