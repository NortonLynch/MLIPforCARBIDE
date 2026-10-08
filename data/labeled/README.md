# DFT 标注

保存验收后的规范化能量、力和应力标签；关联`structure_id`与`dft_protocol_id`。批量标签默认仅保存在本地。

2026-10-08：36项校准DFT已完成审核；18个独立构型的k6/k7结果和MACE对照保存在[本次审核目录](../../dft/reviews/dft600-k67-20261008/report.md)。后续同类ZrC64使用[标注基准v1](../../configs/experiments/zrc_dft_labeling_v1.json)。当前尚未向本目录导出正式训练/验证/测试集，不把校准帧或同构型网格重复计算计作独立测试样本。

本批原始输出位于`hpc/results/zrc-dft600-k67-20261008/`；`dft/jobs/`保留冻结输入及更早的计算记录。完整标签验收/导出接口、独立验证/测试清单和能量参考处理仍见[当前任务](../../docs/project-status.md)。
