# Windows 环境部署记录

部署并验收于 2026-09-21。本记录描述这台 Windows 机器的实际安装结果。

## 已部署环境

| 项目 | MACE 环境 | 数据分析环境 |
| --- | --- | --- |
| Conda 名称 | base | carbide-analysis |
| 路径 | C:\Users\admin\anaconda3 | C:\Users\admin\anaconda3\envs\carbide-analysis |
| Python | 3.14.6，保留原版本 | 3.12.14 |
| PyTorch | 2.13.0+cu132，保留原版本 | 不需要 |
| MACE 程序 | mace-torch 0.3.16 | 不安装 |
| 预训练模型 | MACE-MH-1，明确使用 omat_pbe 分支 | 不需要 |
| 主要用途 | GPU 推理、MD、后续微调 | 结构转换、SOAP/FPS、指标、绘图 |

硬件为 RTX 5060 8 GB，驱动 581.29。现有 PyTorch 使用 CUDA 13.2 运行时，已通过实际 GPU 运算和 MACE 微调测试；不需要据此重新安装系统 CUDA Toolkit。可选 CUDA 加速扩展没有安装，其兼容性尚未验收。

## 模型版本与来源

MACE 程序与权重是两个独立版本。本次安装的是当日 PyPI 最新发行版 `mace-torch==0.3.16`，下载的是官方微调指南当前推荐的 **MACE-MH-1**，没有使用裸 `small`/`medium` 别名对应的初代 MACE-MP-0。

- 官方指南：[Fine-tuning Guidance](https://mace-docs.readthedocs.io/en/latest/guide/finetuning_guidance.html)
- 权重地址：[官方 MACE-MH-1](https://github.com/ACEsuit/mace-foundations/releases/download/mace_mh_1/mace-mh-1.model)
- 本地文件：`models/mace-mh-1.model`
- 文件大小：59,208,139 bytes
- SHA-256：`a522eb7f59c7879963d41586528f4980baf33e086c94aa92e3eafdeccad3be47`
- 初始材料分支：`omat_pbe`。这是部署验收的显式选择；正式与 VASP 比较前仍需核对 DFT 设置与参考能量。

`mh-1` 模型包含多个分支，不能仅指定权重而忽略分支含义。当前基础推理示例：

```python
from ase.build import bulk
from mace.calculators import MACECalculator

atoms = bulk("ZrC", "rocksalt", a=4.7, cubic=True)
atoms.calc = MACECalculator(
    model_paths="D:/MaterialModel/models/mace-mh-1.model",
    device="cuda",
    default_dtype="float32",
    head="omat_pbe",
)
print(atoms.get_potential_energy())
print(atoms.get_forces())
print(atoms.get_stress())
```

这里的晶格常数和精度仅用于安装检查，不是经验证的生产参数。

## 如何进入环境

打开 Anaconda Prompt：

```bat
conda activate base
cd /d D:\MaterialModel
python scripts\check_mace_environment.py
```

分析环境：

```bat
conda activate carbide-analysis
cd /d D:\MaterialModel
python scripts\check_analysis_environment.py
```

若使用 PowerShell，切换目录写成 `Set-Location D:\MaterialModel`。若当前终端尚不能识别 conda，可以使用 Anaconda Prompt，或通过完整路径运行：

```powershell
& 'C:\Users\admin\anaconda3\Scripts\conda.exe' run --no-capture-output -n base python 'D:\MaterialModel\scripts\check_mace_environment.py'
```

已有 Python/Jupyter 进程需要退出后重新激活环境，才能读取新设置。

## base 的兼容性处理

原 base 的 NumPy 使用 MKL，而 pip 安装的 PyTorch 携带另一份 Intel OpenMP 运行库；实际测试同时使用时出现 `OMP: Error #15`。本次使用 Intel 官方支持的 **TBB 线程后端**解决了该问题：

```bat
conda env config vars set -n base MKL_THREADING_LAYER=TBB
```

该设置已保存，仅属于 Conda base 的激活配置；没有写入 Windows 全局环境变量。没有设置 `KMP_DUPLICATE_LIB_OK`，没有删除或替换 DLL。此设置会改变 base 中 MKL 的线程调度后端；当前 NumPy、PyTorch 和 MACE 联合计算已验证通过。[Intel 线程后端说明](https://www.intel.com/content/www/us/en/docs/onemkl/developer-guide-windows/2024-2/dynamic-select-the-interface-and-threading-layer.html)

若以后重建了互相兼容的数值库环境，可使用 `conda env config vars unset -n base MKL_THREADING_LAYER` 撤销设置；在本次部署组合中撤销会重新暴露已观测到的冲突。

本次向 base 新增 11 个包，安装前后的清单比对未发现原有包被移除或版本被替换。`matscipy 1.2.0` 已在本机成功编译为 Python 3.14 的 Windows wheel。base 的 Python 3.14 并非我们原建议的保守起点，但本次明确列出的功能验收已全部通过；这不代表所有 MACE 可选功能均已验证。

## 验收结果

- base 与 carbide-analysis 的 `pip check` 均通过。
- MACE-MH-1：8 与 64 原子 ZrC 的能量、力、应力均为有限值，输出形状正确。
- 8 原子体系：10 步短 MD 正常完成，仅作为安装检查。
- GPU 微调：使用模型产生的合成标签，3 个训练构型、1 个验证构型，完成 2 个 epoch、6 次梯度更新，包含能量/力/应力损失。
- 训练检查点保存与加载成功；保存模型在新进程中重新执行 GPU 能量、力、应力预测成功。
- 分析环境：extxyz 读写、ASE/pymatgen 转换、周期 SOAP、距离矩阵、HDF5 读写、CSV、PNG 绘图和 YAML 均通过。

全部验收数据保存在 `tmp/environment-checks/`，**合成标签不是 DFT 数据，不得加入正式研究数据集**。短训练结果也不表示模型已经适配 ZrC。测试中不使用正式测试集。

推理/短 MD 检查记录的 PyTorch 峰值已分配显存约 658 MiB；这是这组小体系测试的内存统计，不是整张卡总占用，更不能用来保证大体系或训练的容量。原始记录见 [部署验收 JSON](environments/windows-validation.json)。

## 分析环境包版本

| 包 | 版本 |
| --- | --- |
| ASE | 3.29.0 |
| pymatgen | 2026.5.4 |
| DScribe | 2.1.2 |
| NumPy | 2.5.3 |
| SciPy | 1.18.1 |
| scikit-learn | 1.9.1 |
| pandas | 3.0.6 |
| matplotlib | 3.11.2 |
| h5py | 3.16.0 |
| PyYAML | 6.0.3 |

## 复现记录

- [分析环境的直接依赖](environments/carbide-analysis.yml)
- [分析环境 Windows 精确包清单](environments/carbide-analysis-win64-explicit.txt)
- [base 安装前 pip 清单](environments/base-before-mace.txt)
- [base 安装后 pip 清单](environments/base-after-mace.txt)
- [base 安装前 Conda 精确清单](environments/base-before-mace-conda-explicit.txt)
- [微调安装验收配置](../configs/experiments/mace_mh1_installation_check.yml)

分析环境可以用 `conda env create -f docs/environments/carbide-analysis.yml` 创建；要复现本次 Windows 构建，使用 `conda create -n carbide-analysis-repro --file docs/environments/carbide-analysis-win64-explicit.txt`。base 清单是已有复杂环境的快照，不建议直接作为跨机器的一键安装脚本。

正式研究开始前仍需完成：VASP 标签接口、DFT 协议与参考能量校准、真实训练/验证/测试划分、高温构型及长时间物理验证。
