# ESI-ALNS：多无人机边缘智能计算联合优化

`develop` 为当前代码与论文实验结果的统一入口。实现多无人机巡护路径、接触访问、计算模式、上传批次与 MEC 资源分配的联合优化。

当前七算法：**GR-MR、FTR-NM、RGA-MR、SA-MR、DPSO-MR、B-ALNS、ESI-ALNS**。ESI 在共享的 B-ALNS 探索结果上强化离散结构；候选须经过固定结构凸优化和完整残差验收，第二阶段在能耗容差内减少 MEC CPU 预留。

## 内容导航

| 路径 | 内容 |
| --- | --- |
| `src/uav_mec/` | 当前算法、实例、事件时序、资源求解与独立验收 |
| `experiments/` | 当前实验运行、汇总、归档核验和绘图入口 |
| `configs/` | 实例配置及冻结数值依赖 |
| `data/real_case/stanislaus/` | GIS 数据快照和来源说明 |
| `results/` | 主实验、扩展、预算、消融和经验参考；含原始压缩包、摘要与 SHA-256 清单 |
| `figures/` | 最新 23 幅 PDF/SVG/PNG/TIFF、CSV 和地图源资产 |
| `tests/` | 当前算法、资源验收、统计口径与归档完整性测试 |
| `.github/workflows/` | 自动核验与手动实验两条工作流 |
| `docs/reproduction.md` | 完整复现步骤及运行入口说明 |
| `docs/results.md` | 记录数量、统计范围和结论边界 |

## 安装

建议用 Python 3.14.5 与冻结数值依赖重建环境。源码声明最低 Python 3.11；其他依赖组合可以运行，但不保证逐位复现冻结结果。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r configs/requirements-frozen.txt
.venv/Scripts/python.exe -m pip install -e ".[dev,plot]"
```

Linux/macOS 将 `.venv/Scripts/python.exe` 替换为 `.venv/bin/python`。以下命令均在仓库根目录执行，使用已安装本项目的 Python 环境。

## 校验已有实验（不重新求解）

```powershell
python -m pytest
python experiments/manage_results.py verify
python experiments/verify_recorded_results.py
```

最后一条命令解压全部原始记录，重新构建资源约束和时序、复验残差，并与发布的全部汇总统计对比。结果和详细日志写入 `outputs/reproduction/`。归档中保留失败、缺失及预算超时；发现字节不一致或不完整矩阵会停止。

原始记录共 **109 个 JSON 文件，约 1.33 GiB**，无损压缩为 **16 个 ZIP，约 97.6 MiB**。这些记录直接随 Git 保存，不依赖会过期的 Actions 工件。

## 运行新实验

```powershell
python experiments/run_seven_methods.py --phase pilot --tasks 30 --scenario 45 --output outputs/new/pilot/K30_S45.json
python experiments/run_seven_methods.py --phase formal --tasks 40 --scenario 45 --output outputs/new/formal/K40_S45.json
python experiments/run_extension.py --study bandwidth --level 1.5 --scenario 45 --output outputs/new/extension/bandwidth_1.5_S45.json
```

完整矩阵、消融和软预算命令见 [复现说明](docs/reproduction.md)。新实验写入独立目录；不要覆盖 `results/`，也不要把不同源码身份的记录混合汇总。

GitHub **Actions → Run current experiment block → Run workflow** 可以选择主实验、接触上限、带宽、GIS 或完整串行预算对照。普通推送只触发测试及离线核验，不启动全量优化实验。

## 图件

直接使用 `figures/pdf/` 中已确认的最终图。`figure_data_map.json` 给出逐图数据位置，`manifest.json` 绑定最终文件字节。

```powershell
python experiments/plot_figures.py --output-dir outputs/figures
```

绘图入口从当前 CSV 重建 20 幅实验图，图 1、2、19 复制已确认的矢量资产。重建输出与冻结稿分开；不同系统字体可能影响字形和布局。保留完整坐标框、简单线型、图 7/8 分组柱状、无局部放大和无误差棒。统计区间仍保留在 CSV；缺失值不转成零。

## 结果口径

主实验有 816 条记录，其中 667 条通过两阶段验收。扩展图表有 408 条记录，含 306 条新计算与 102 条主实验复用记录；另有 96 条软预算对照和 180 条消融记录。

固定探索配置下的能耗改善不能替代等时间优势的证据。预算对照尚未建立稳定优势；80 任务的七算法共同有效集合较小。经验参考只用于描述观察到的差距，不是全局最优值。详见 [结果说明](docs/results.md)。

本次整理保留当前方法与有效证据，移除了旧强化变体、旧五算法运行入口、重复图包、过时工作流与一次性写稿脚本。历史提交仍可通过 Git 追溯。
