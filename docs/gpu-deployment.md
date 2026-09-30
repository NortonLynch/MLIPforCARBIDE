# GPU 部署清单与单张 RTX 5060 的适用范围

核对日期：2026-09-21。本文是部署建议，尚未在目标硬件上安装或测速。以 Linux + NVIDIA GPU 为假设，实际版本组合应按驱动、GPU 架构和所选模型发行版确定。

## 单张 5060 能做到哪一步

若指桌面 RTX 5060，官方规格是 8 GB 显存、Blackwell 架构。它可以作为 ZrC 最小验证的起步设备，但不应直接承诺完成全部多体系、多模型和长时间 MD 实验的周转时间。[NVIDIA 规格](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5060-family/)

以下是实施判断，不是该卡的实测结果：

| 工作 | 建议 |
| --- | --- |
| 构型生成、VASP 输出解析、SOAP/FPS、绘图 | 主要使用 CPU 和系统内存，可以安排在 CPU 节点或本地运行 |
| MACE 小模型、MatterSim 小模型零样本预测 | 优先尝试，逐个模型加载、分批处理构型 |
| 小周期体系的短 MD | 适合先验证流程与测时，长轨迹成本按实测外推 |
| MACE 小模型微调及同架构从头训练 | 从 batch size 1、验证 batch size 1 开始，必须实际测试含力/应力损失的训练步骤 |
| UMA 推理 | 先确认权重访问资格，再试小模型；8 GB 下的适用体系规模不能只凭参数量判断 |
| 多体系、多策略、多种子与长时间大体系 MD | 建议使用更大显存和更多可用 GPU 工时的集群 |

100–200 个训练构型并不意味着必须同时把它们的计算图放入显存。峰值显存更取决于每批的原子数、邻居数、模型宽度/层数、精度及求导需求。训练力损失比仅做一次能量预测更耗资源，只有单点测试通过还不够。

建议先选一个 ZrC 小模型，用约 64 个原子的构型做冒烟测试；这只是测试起点，不是生产尺寸推荐或容量保证。后续独立检查有限尺寸误差和周期邻居处理，不能为了装入显存缩小截断半径或生产体系而不验证物理影响。

## 优先部署的环境

建议建立四个隔离环境，Python 3.12 可作为初始候选；最终以选定发行版依赖为准。不要强行统一所有环境的 PyTorch 版本。

| 环境 | 直接需要的包 | 作用 |
| --- | --- | --- |
| carbide-mace | GPU 版 torch、mace-torch、ase | 核心环境：MACE 推理、MD、微调和从头训练 |
| carbide-mattersim | mattersim、与其依赖相容的 GPU 版 torch、ase | 第二个零样本基线 |
| carbide-uma | fairchem-core、匹配的 GPU 版 torch、huggingface_hub、ase | UMA 零样本基线，先确认权重权限 |
| carbide-analysis | ase、pymatgen、dscribe、numpy、scipy、scikit-learn、pandas、matplotlib、h5py、pyyaml | 结构处理、SOAP、选择策略、指标与作图；不要求 GPU |

MACE 的安装包名是 `mace-torch`。官方提供 `mace_run_train` 及 foundation_model 微调入口。[安装](https://mace-docs.readthedocs.io/en/latest/guide/installation.html)、[微调](https://mace-docs.readthedocs.io/en/latest/guide/finetuning.html)

MatterSim 当前主分支要求 Python >=3.12，并依赖 torch、e3nn、torch_geometric 等；还声明了 torchvision/torchaudio 等依赖。让所选版本的依赖解析器处理，不照抄其他模型环境的依赖列表。主分支要求不等于所有历史发行版要求。[官方安装说明](https://github.com/microsoft/mattersim)、[依赖元数据](https://github.com/microsoft/mattersim/blob/main/pyproject.toml)

UMA 使用 `fairchem-core`。官方快速开始要求先申请 Hugging Face 权重访问权限；无机材料使用 `omat` 任务。模型页另列分发地区限制，目前包含中国；若目标部署地区受限，先以其他可获取模型开展工作。代码包能安装不代表权重一定可获取。[官方仓库](https://github.com/facebookresearch/fairchem)、[UMA 模型页](https://huggingface.co/facebook/UMA)

DScribe 用于生成 SOAP 描述符，FPS 是选择算法，可在项目内实现，无需先引入大型主动学习框架。[DScribe 官方说明](https://github.com/SINGROUP/dscribe)

## 集群基础程序

- NVIDIA 驱动：通常由管理员部署；先在实际分配到的 GPU 节点运行 nvidia-smi。
- Python 环境管理：使用集群已有 Conda/Micromamba，或 uv/venv；每个模型独立环境。
- PyTorch GPU 构建：同时满足模型依赖、GPU 架构和驱动要求，不默认安装最新版就一定兼容。
- Git 和数据传输工具：用于代码版本与 CPU/GPU 集群间的数据同步；rsync/scp 依据集群支持选择。
- GCC/G++、CMake、Ninja：仅在安装包或扩展需要本地编译时准备。
- CUDA Toolkit/nvcc：编译 CUDA 扩展时再按要求部署；使用预编译 PyTorch 通常无需额外安装完整 Toolkit。
- 调度器：沿用集群已有 Slurm/PBS；首轮申请一张 GPU 即可，不需要自行搭建分布式调度系统。

PyTorch 官方从 2.7 的 CUDA 12.8 构建引入 Blackwell 支持；新版本的 CUDA 构建矩阵会变化。2.12 官方已说明转向 CUDA 13.0+ 的 Blackwell 构建路径。5060 的最终组合需要检查所选模型发行版，不宜沿用旧 CUDA 11.x/12.1 教程。[2.7 发布说明](https://pytorch.org/blog/pytorch-2-7/)、[2.12 发布说明](https://pytorch.org/blog/pytorch-2-12-release-blog/)、[安装选择器](https://pytorch.org/get-started/locally/)

驱动显示的 CUDA Version 不等于当前 Python 环境中 PyTorch 使用的 CUDA 运行时；记录 torch.__version__、torch.version.cuda 和实际 GPU 名称。预编译包与完整 Toolkit 的区别见 [PyTorch 官方论坛维护者说明](https://discuss.pytorch.org/t/how-do-i-get-started-with-cuda-and-pytorch/223816)。

## 可以暂缓的组件

- LAMMPS 及模型专用接口：先用 ASE 跑小体系流程，后续大规模 MD 再单独部署与验收。
- cuEquivariance / OpenEquivariance 等加速组件：基础版本正确后，再检查其 GPU 架构、CUDA 与模型兼容性，并验证加速前后数值一致性。[MACE 加速说明](https://mace-docs.readthedocs.io/en/latest/guide/cuda_acceleration.html)
- 多 GPU 训练、Ray 服务与集群通信调优：单卡 MVP 无需主动配置；包管理器带入的依赖可以保留。
- W&B、MLflow、JupyterLab：可选；初期配置快照、CSV 指标与本地日志即可。
- GPU 版 VASP：目前 DFT 已安排在 CPU 集群，GPU 端可专注于 MLIP。

不要为省显存直接假定 FP16/BF16 适用于所有力和应力计算。可先评估所选模型支持的 FP32，再对代表性构型做精度对照及 MD 能量漂移检查；部分模型或参考计算需要更高精度。

## 权重与部署验收

1. 固定各模型发行版、具体权重、文件校验值及缓存位置；计算节点无外网时，在可联网节点预先下载可合法获取的权重。
2. 在 GPU 作业中检查 torch.cuda.is_available()、GPU 名称，实际执行 GPU 张量运算，而不只检查能否 import。
3. 每个模型对同一份 ZrC 构型输出有限值的能量、力、应力；核对单位、应力符号及输出形状。
4. MACE 实际执行包含力/应力损失的短训练，完成保存、恢复和重新预测；单点推理通过不能代替训练验收。
5. 跑 100–1000 步小体系 MD 冒烟测试，记录热身后每步时间、峰值显存、NaN 和异常终止。这不能代替长时间物理验证。
6. 分别测试高温/高密度等可能增加邻居数的构型，避免只用常温晶体估算资源。
7. 记录 pip freeze/锁文件与 pip check 结果。通过后再扩展原子数、轨迹长度和重复次数。

例如 1 ns、1 fs 步长需要 100 万步；若实测每步耗时 t 秒，单条轨迹时间约为 100 万 × t 秒，再乘以温度点与重复次数。这里没有假定 5060 的每步性能。

最终精确安装命令仍需要：操作系统、GPU 型号/显存、驱动版本、调度器、外网访问条件，以及选定的模型发行版。现阶段最优先把 carbide-mace 与 carbide-analysis 部署并验收，再逐一增加基线模型。
