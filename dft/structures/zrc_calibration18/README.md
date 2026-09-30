# 18个64原子DFT校准构型

**结构已准备并核验；对应36个静态单点的完整提交包已生成，尚未计算DFT。**

6个温度（300/1500/3000/4500/5250/6000 K）×3个体积比（0.95/1.00/1.05），各取1帧，均为MD seed17的开发数据。每帧64原子，元素顺序固定Zr32、C32；未来赝势顺序Zr_sv、C，使用当前PAW-PBE.64。

- `01_*`至`18_*`：POSCAR和structure.json，后者记录原始轨迹、帧索引、SHA-256、温度/体积、选择理由及独立的MACE诊断值。
- [structures.list](structures.list)：18个POSCAR相对工作区根目录的路径。
- [structures.csv](structures.csv)：便于查看的条件与来源表。
- [manifest.json](manifest.json)：冻结结构清单。
- `calibration18.extxyz`：连续18帧的纯结构查看文件，没有DFT标签。
- [export-verification.json](export-verification.json)：独立核查结果；位置仅做周期包裹，晶胞和内部构型未改变。

**固定相对能量参考**：`01_zrc64_T0300_v100_s17_f0085`。本批用于DFT截断能/k网格校准，与后续训练预算分开，不把校准帧加入生成的Random/FPS训练序列。

用户最新决定为固定600 eV，在全部18个结构上比较6³和7³网格。36个完整输入及提交脚本见 [当前DFT任务](../../jobs/05_md_kmesh600/README.md)。本目录继续保留原始结构与来源，不弛豫采样帧，不把structure.json中的MACE预测当作DFT标签。

详见 [完整筛选与DFT推进方案](../../../docs/candidate-selection-20260924.md)。高温相态与热平衡均尚未认证。
