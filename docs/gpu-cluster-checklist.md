# GPU 集群部署清单：ZrC / MACE-MH-1

核对日期：2026-09-21。本文给出目标配置与部署验收要求；尚未连接或安装目标 GPU 集群。当前本地首轮 MD 使用 **ASE 积分器 + MACE 力计算 + PyTorch/CUDA**，不经过 LAMMPS。

## 1. 先部署可复现的 ASE 路线

| 项目 | 部署要求 | 作用 |
| --- | --- | --- |
| Linux、NVIDIA 驱动、Slurm | 沿用集群管理员配置；在实际 GPU 作业中检查 | GPU 访问与任务调度 |
| Conda / Micromamba / venv | 建立独立 `carbide-mace` 环境 | 避免污染系统 Python |
| Python | 建议 3.12，作为集群起点 | 与科学计算及 GPU 扩展的兼容性较稳妥；不是模型唯一支持版本 |
| PyTorch | GPU 构建；按 GPU 架构、驱动和发行版选择 CUDA wheel | MACE 推理及训练 |
| `mace-torch==0.3.16` | 固定为本机正在使用的程序版本 | 推理、微调、从头训练 |
| `ase==3.29.0` | 固定与本地一致 | 结构读写、NVT/NVE 积分器、轨迹 |
| NumPy、SciPy、PyYAML | 采用与所选 MACE/PyTorch 兼容的版本，验收后锁定 | 数值处理与配置 |
| e3nn、matscipy 等 | 让 `mace-torch` 的依赖解析安装，并记录最终版本 | 模型和邻居列表等依赖 |
| Git、文件同步工具 | 使用集群已有 Git / scp / rsync | 代码与数据传输 |

MACE 的安装包名是 `mace-torch`。应先根据计算节点选择 PyTorch 构建，再安装 MACE；不要把 Windows 的 Python 3.14、PyTorch 2.13/CUDA 13.2 组合直接当作所有 Linux 节点的要求。[MACE 安装说明](https://mace-docs.readthedocs.io/en/latest/guide/installation.html)、[PyTorch 安装选择器](https://pytorch.org/get-started/locally/)

MACE 0.3.16 的发布说明要求 Python 至少为 3.9；部分旧教程首页仍写更老的下限。这里选择 Python 3.12 是项目部署建议。[0.3.16 发布说明](https://github.com/ACEsuit/mace/releases/tag/v0.3.16)

部署顺序示例，PyTorch 安装行需要由节点实际信息决定：

```bash
conda create -n carbide-mace python=3.12 pip
conda activate carbide-mace
# 在此安装 PyTorch 官方选择器给出的、适配计算节点的 GPU 版本。
python -m pip install 'mace-torch==0.3.16' 'ase==3.29.0' pyyaml
python -m pip check
python -m pip freeze > carbide-mace-linux-pip.txt
```

只运行预编译的 ASE/PyTorch 路线时，通常无需自行编译 LAMMPS、安装完整 CUDA Toolkit 或配置 MPI。若某个依赖缺少适配 wheel、需要本地编译，则按该包的要求加载编译器。已有 Windows 精确 Conda 清单不能直接作为 Linux 锁文件。

## 2. 必须一并带到集群的项目文件

- `models/mace-mh-1.model`，始终显式选择 `omat_pbe` 分支。
- 模型 SHA-256：`a522eb7f59c7879963d41586528f4980baf33e086c94aa92e3eafdeccad3be47`。
- 当前版本的 MD 程序、任务清单、起始结构和参数配置。保留原子顺序、质量、盒子、周期边界、随机种子与模型精度。
- 若搬迁未完成轨迹，传输完整检查点及其配套日志，保持原协议版本；不能仅拿最终 POSCAR 重新赋速后称作续跑。
- 为每个任务分配独立输出目录，保留队列状态和失败原因。不同 GPU 作业不得同时写同一轨迹。

计算节点若无外网，提前在可联网节点取得依赖和官方权重；运行时直接读本地模型，避免作业启动时隐式下载。

## 3. 数据分析环境

可沿用独立 `carbide-analysis` 环境，安装 `ase`、`pymatgen`、`dscribe`、`numpy`、`scipy`、`scikit-learn`、`pandas`、`matplotlib`、`h5py`、`pyyaml`。它负责 DFT 输出解析、SOAP/FPS 选样、RDF/MSD 和误差分析，通常不需要 GPU。

MatterSim、UMA 是后续其他模型基线，应另建环境；它们不属于当前 MACE 首轮 MD 的前置依赖。现阶段 GPU 节点也无需安装 GPU 版 VASP，DFT 继续由 CPU 集群负责。

## 4. 何时安装 LAMMPS

MACE 是给出能量、力和应力的势模型；ASE 或 LAMMPS 是推进原子运动的模拟程序。当前 8、64、216 原子任务可以继续使用 ASE。需要更大体系、LAMMPS 专用功能或多 GPU 空间分解时，再评估 LAMMPS 的实际收益。

针对本项目的 **MACE-MH-1，应采用 ML-IAP 接口作为部署路线**。官方从 MACE 0.3.15 起明确修复了该模型非线性交互模块的 ML-IAP 支持；不能假设旧的 `pair_style mace` / libtorch 教程同样适用。[MACE 0.3.15 发布说明](https://github.com/ACEsuit/mace/releases/tag/v0.3.15)

ML-IAP 路线额外需要：

| 组件 | 要求 |
| --- | --- |
| LAMMPS | 固定源码发行版或提交；确认包含目标 ML-IAP/Kokkos 接口 |
| 编译环境 | CMake、C++ 编译器、MPI、与 Kokkos 和 GPU 匹配的 CUDA Toolkit |
| LAMMPS 构建 | 启用 Kokkos CUDA、`ML-IAP`、`MLIAP_ENABLE_PYTHON`、`ML-SNAP`、`PYTHON`、共享库；按 MPI 路线启用 `BUILD_MPI` |
| Python 接口 | 安装本次编译生成的 LAMMPS Python 包；确保它与实际加载的共享库属于同一次构建 |
| cuEquivariance | `cuequivariance`、`cuequivariance-torch`、匹配 CUDA 大版本的 `cuequivariance-ops-torch-cu12` 或 `-cu13` |
| CuPy | 与所选 CUDA 运行时及 Python 相容的 CuPy 构建 |

上述是组件清单，准确编译选项需按 GPU 架构和选定 LAMMPS 版本设置。不能照抄其他机器的 Kokkos 架构参数。[MACE ML-IAP 部署说明](https://mace-docs.readthedocs.io/en/latest/guide/lammps_mliap.html)、[LAMMPS 构建选项](https://docs.lammps.org/Build_extras.html)

NVIDIA 当前文档给出了 CUDA 12/13 的 cuEquivariance 内核包，其 Linux wheel 支持与 Python/PyTorch 下限应按实际发行版核对。应将三类 cuEquivariance 包固定为相容版本，并执行实际计算验证。它在 ASE 路线中属于可选加速，在当前 MACE ML-IAP 转换路线中会被使用。[NVIDIA cuEquivariance](https://docs.nvidia.com/cuda/cuequivariance/)

官方不同页面的示例存在年代差异，例如 ML-IAP 教程的旧 PyTorch 建议和部分 CUDA 11 命令，不宜作为当前集群的统一版本锁定规则。先固定本项目 MACE 版本，再选择相容依赖并验收。

## 5. MACE-MH-1 的 ML-IAP 转换与输入

已核对本机 `mace-torch==0.3.16` 的 `create_lammps_model.py`：默认格式仍是 `libtorch`，因此需要显式指定格式和分支。模型转换在 GPU 作业中进行，优先使用与后续运行相同的 GPU 架构；按精度验证结果选择 `float32` 或 `float64`。以下只展示 `float32` 候选，不能代替精度验收：

```bash
python -m mace.cli.create_lammps_model models/mace-mh-1.model \
  --format=mliap --head=omat_pbe --dtype=float32
```

输出文件为 `models/mace-mh-1.model-mliap_lammps.pt`。虽然原权重有多个分支，导出的模拟势应固定为一个分支。

按当前 LAMMPS 正式文档，统一接口的输入为：

```text
units       metal
atom_style  atomic
newton      on
# read_data 等结构读取指令在此完成。
pair_style  mliap unified models/mace-mh-1.model-mliap_lammps.pt 0
pair_coeff  * * Zr C
```

这里只在数据文件的类型 1=Zr、类型 2=C 时使用 `Zr C`；元素映射必须与实际数据一致。`units metal` 的时间单位是 ps，因此 0.5 fs 对应 `timestep 0.0005`。`unified ... 0` 的末尾参数属于邻居处理选项，不能省略。[LAMMPS ML-IAP 语法](https://docs.lammps.org/pair_mliap.html)

先测试单 GPU，再决定是否进行多 GPU 分解；8–216 原子任务更适合优先把多个独立任务分配给不同 GPU，而不是预设单条轨迹跨 GPU 更快。这是针对本项目规模的调度建议，最终由实际吞吐量决定。

## 6. 资源申请与通过条件

建议先申请 **1 张 NVIDIA GPU、4–8 CPU 核、32 GB 主内存**运行短基准；这是资源起点，不是硬性最低要求。24 GB 显存为后续扩展留出余量，但并非当前 8–216 原子推理的必要下限。本地 RTX 5060 8 GB 已通过这些盒子的短推理测试。48/80 GB GPU 可在较大模型训练或增大批量后评估，不应在未测量前当作必需。

验收必须在 Slurm 分配到的 GPU 计算节点完成：

1. 记录 GPU 型号、驱动、操作系统/glibc、Python、PyTorch/CUDA、MACE、ASE 和全部扩展版本；实际运行 GPU 运算。
2. 用同一模型、分支及构型，对比本地/集群能量、力和静态应力；先确认元素、单位和精度一致。
3. 对 8、64、216 原子各运行短 MD，记录预热后的每步时间、显存及输出完整性；高温和压缩构型也纳入检查。
4. 执行 NVE 步长/精度检查、温度自由度检查和中断续跑检查。计算完成不等于物理结果已获 DFT 验证。
5. 若使用 LAMMPS，在多个固定构型上与 ASE 对比能量、力和应力。两者的温控算法或随机数实现不同，不要求逐帧轨迹完全重合。
6. 后续训练另行执行含力/应力损失的短训练、保存与恢复。推理成功不能替代训练验收。

只有这些结果合格后，才把所选依赖组合锁定为本项目集群环境。准确的 PyTorch/CUDA wheel、Kokkos 架构和 Slurm GPU 参数仍取决于目标集群 GPU、驱动、系统版本及队列配置。
