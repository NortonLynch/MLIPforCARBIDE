# 256 原子 ZrC 三相计算输入

本目录对应 2026-11-23 提交的 12 个 Zr₁₂₈C₁₂₈ 构型。习惯从结构入手的读者，可在选帧表找到一行，再在 `vasp/structures/` 里打开同名 `.POSCAR`。表中 `poscar_sha256` 对应文件的原始字节，`target_K` 是母轨迹设定温度，`instantaneous_K` 是取帧时的离子动温。[选帧表](../cohort.csv) · [判相与标注方案](../protocol.md)

## 复用两相母帧

`lammps/parent.data` 是训练种子 43719 在 3100 K 两相制备轨迹第 46000 步（23 ps）的完整晶胞。三条续算均从这组坐标重新赋速。`cases.tsv` 给出温度和种子，`in.coexist` 定义 0.5 fs 时间步、120 ps 演化及沿界面法向的压力控制。`in.potential` 给出 MEAM 的元素顺序与参数调用。[母帧](lammps/parent.data) · [三条工况](lammps/cases.tsv) · [LAMMPS 输入](lammps/in.coexist) · [势函数调用](lammps/in.potential)

每个温度使用单独的运行目录，将上述输入和 Ouyang 等人在 *Calphad* 85（2024）102680 所用的 LAMMPS 版 `library.meam`、`ZrC.meam` 放在一起。作者参数包中的 QuantumATK 与 LAMMPS 文件有区别。以下命令以 3250 K 为例，另两条工况将 `T` 改为 3200 或 3290。原计算使用 LAMMPS 22Dec2022、8 个 MPI 进程。

```sh
mpirun -np 8 lmp -in in.coexist -var T 3250 -var seed 43719 -var potinc in.potential
```

| 外部输入 | 本批使用文件的 SHA-256 |
| --- | --- |
| `library.meam` | `659e26486b2050599e8bc09c977d570e4b542a174b9f062c70944381b0dec961` |
| `ZrC.meam` | `d06d71400c32d81668e46d095c951b0efb49ac2f6941a7a523b173be0d6afb16` |
| VASP `POTCAR`，PAW-PBE.64，按 Zr_sv、C 拼接 | `14f29842e7a19e8251a90aaef4221903201a49d54af90190dd4e75ee9d5d6bd1` |

## 复用 DFT 单点

每一行 `cohort.csv` 对应一个固定晶胞、固定坐标的结构。单点目录使用所选结构作为 `POSCAR`，搭配共用的 `INCAR`、上表对应的 `POTCAR`，以及改名为 `KPOINTS` 的工作网格。`reference_mesh` 有值的三行各增加一个独立目录，只替换为加密网格。VASP 版本为 6.3.2。`INCAR` 的 `SYSTEM` 沿用界面模板的名称，逐帧相态以清单中的 `phase` 为准。[12 份结构](vasp/structures/) · [共用 INCAR](vasp/INCAR) · [工作网格](vasp/KPOINTS.working) · [加密网格](vasp/KPOINTS.reference)
