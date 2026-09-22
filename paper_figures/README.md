# 论文模型图、算法图与实验图

> **Final-paper update (2026-09-23):** Fig. 5 / Fig. 6 的绘图数据接口、paired CSV、图注和脚本已切换到正式 **8 independent scenarios × 3 algorithm repetitions** 主比较，并统一显示名为 **B-ALNS / ESI-ALNS**。Publication-data validation run `35749187944` 已通过：K=50 为 24 common-strict pairs（14 better / 10 equal / 0 worse），K=80 为 21 common-strict pairs（17 / 4 / 0）。当前仓库中既有 PDF/SVG/PNG 是此前生成的二进制导出；在重新执行 `python paper_figures/scripts/plot_experiments.py` 前，不应把旧 Fig. 5/6 二进制文件作为最终投稿版本。其他实验图的数据口径未因 v5–v7 改变。

本目录保留系统模型、已确认的算法框架固定版，以及独立新增的算法图形机制版。三张图均使用 Microsoft Visio 原生矢量构建，白底、英文标签、Times New Roman 字体；文字、图标和路径均可编辑。两种算法图是同一 Fig. 2 的备选表达，供比较选择。

另新增 **Fig. 3–13 与 Fig. S1–S2，共 13 组实验图**，使用 Matplotlib，统一 183 mm 宽度、Times New Roman、英文标签和至少 8.5 pt 字号。数值图采用矢量 PDF/SVG，PNG 为 300 dpi。Generic ALNS 用蓝色圆点，Proposed Hybrid 用橙色方点；配对图用空心圆与实心方点区分重合样本。此次制作没有覆盖系统模型或任一算法图。

## 实验图交付

- [13 页合并 PDF](output/experimental_figures_all.pdf)
- [完整交付 ZIP](output/experimental_figures_package.zip)
- [彩色总览](output/experiment_overview.png) / [灰度总览](output/experiment_overview_grayscale.png)
- [英文图注及统计口径](experiment_captions.md)
- [验证报告](experiment_verification.md) / [逐图机器核验记录](experiment_verification.json)

| 图号 | 内容 | PDF | SVG | 300 dpi PNG |
|---|---|---|---|---|
| Fig. 3 | 负载能耗与配对收益 | [PDF](output/pdf/fig03_dense_workload.pdf) | [SVG](output/svg/fig03_dense_workload.svg) | [PNG](output/png/fig03_dense_workload.png) |
| Fig. 4 | 卸载、接触与路线结构 | [PDF](output/pdf/fig04_workload_structure.pdf) | [SVG](output/svg/fig04_workload_structure.svg) | [PNG](output/png/fig04_workload_structure.png) |
| Fig. 5 | 基线能耗及严格可行率 | [PDF](output/pdf/fig05_baseline_comparison.pdf) | [SVG](output/svg/fig05_baseline_comparison.svg) | [PNG](output/png/fig05_baseline_comparison.png) |
| Fig. 6 | K=50/80 逐对能耗 | [PDF](output/pdf/fig06_paired_comparison.pdf) | [SVG](output/svg/fig06_paired_comparison.svg) | [PNG](output/png/fig06_paired_comparison.png) |
| Fig. 7 | 精英机制消融 | [PDF](output/pdf/fig07_elite_ablation.pdf) | [SVG](output/svg/fig07_elite_ablation.svg) | [PNG](output/png/fig07_elite_ablation.png) |
| Fig. 8 | MEC/UAV 数量敏感性 | [PDF](output/pdf/fig08_mec_uav_sensitivity.pdf) | [SVG](output/svg/fig08_mec_uav_sensitivity.svg) | [PNG](output/png/fig08_mec_uav_sensitivity.png) |
| Fig. 9 | 接触次数上限 | [PDF](output/pdf/fig09_contact_budget.pdf) | [SVG](output/svg/fig09_contact_budget.svg) | [PNG](output/png/fig09_contact_budget.png) |
| Fig. 10 | 带宽及资源影子价格 | [PDF](output/pdf/fig10_bandwidth_shadow.pdf) | [SVG](output/svg/fig10_bandwidth_shadow.svg) | [PNG](output/png/fig10_bandwidth_shadow.png) |
| Fig. 11 | 迭代预算敏感性 | [PDF](output/pdf/fig11_iteration_budget.pdf) | [SVG](output/svg/fig11_iteration_budget.svg) | [PNG](output/png/fig11_iteration_budget.png) |
| Fig. 12 | 强搜索参考质量与耗时 | [PDF](output/pdf/fig12_strong_reference.pdf) | [SVG](output/svg/fig12_strong_reference.svg) | [PNG](output/png/fig12_strong_reference.png) |
| Fig. 13 | 真实地理路线及配对结果 | [PDF](output/pdf/fig13_stanislaus_case.pdf) | [SVG](output/svg/fig13_stanislaus_case.svg) | [PNG](output/png/fig13_stanislaus_case.png) |
| Fig. S1 | 空间分布鲁棒性 | [PDF](output/pdf/figS1_spatial_robustness.pdf) | [SVG](output/svg/figS1_spatial_robustness.svg) | [PNG](output/png/figS1_spatial_robustness.png) |
| Fig. S2 | 覆盖半径敏感性 | [PDF](output/pdf/figS2_coverage_radius.pdf) | [SVG](output/svg/figS2_coverage_radius.svg) | [PNG](output/png/figS2_coverage_radius.png) |

## 实验图离线重建

本次环境为 Python 3.13.12，解析后的完整依赖版本保存在 [requirements-experiments-lock.txt](requirements-experiments-lock.txt)。使用独立环境，不修改项目的 `uv.lock`。系统另需 Times New Roman 字体和已加入 PATH 的 Poppler `pdftoppm`。

在项目根目录中，环境准备完成后，一条命令生成 13 组图、实际 PDF 彩色/灰度预览、总览、合并 PDF、验证报告与 ZIP：

```powershell
python paper_figures/scripts/plot_experiments.py
```

首次创建独立环境可使用：

```powershell
uv venv --python 3.13 .venv-paper-figures
uv pip install --python .venv-paper-figures/Scripts/python.exe -r paper_figures/requirements-experiments-lock.txt
& .venv-paper-figures/Scripts/python.exe paper_figures/scripts/plot_experiments.py
```

本机已准备的解释器为 `$env:TEMP/uav_mec_paper_figures_py313/Scripts/python.exe`。重绘直接使用 `data/raw` 中的正式逐次记录和 `data/map` 中的已核验路线与 USGS 底图，不下载数据，也不重新执行算法。交付 ZIP 包含新增图、脚本、绘图快照与汇总 CSV；重建脚本按本项目目录结构运行，并检查原概念图和项目文件的保护哈希，因此应在本项目中使用。

脚本职责：`prepare_experiment_data.py` 获取五份指定正式制品；`experiment_data.py` 负责筛选、去重、配对及舍入精度检查；`figure_style.py` 统一样式；三个 `plot_*.py` 模块分别绘制主实验、敏感性和参考/地理实验；`verify_experiment_figures.py` 检查实际文件并打包。

仅在缓存缺失或明确需要重新求解时使用 `prepare_geography_map.py`。它要求 Python 3.13，核对源代码与正式提交一致，并对 S45/A100 的能耗、距离、59 个任务覆盖及原始经纬度逐点检查。正式 CI 使用 Python 3.13.15，本地可用环境为 3.13.12；核心数值依赖版本相同，复现能耗 **869675.431725 J**、距离 **47645.919487 m**，与正式结果完全匹配。

## 实验数据与保护记录

汇总依据为原始 `paper_results/*.csv`。新增逐次数据快照对应正式 GitHub 制品：10651261069、10640744688、10643135771、10647510876、10674531133。来源仓库、运行 URL、提交号、制品与 JSON 的 SHA-256 见 [来源记录](data/experiment_sources.json)。与正式汇总不一致的本地旧 K=50 输出未参与绘图。

基线比较共有五种方法：Greedy+MEC Repair、FR-NM、Route-GA、Generic ALNS，以及本文 Proposed Hybrid，即四种基线加本文方法。Fig. 5 的能耗与严格率两个面板均完整展示这五种方法；K=50 的 Greedy 能耗仅来自 2/3 个严格场景，已在轴标签与图注中明确。Fig. 3 的负载矩阵仅有 Generic/Hybrid 正式数据，Fig. 13 的真实地理实验未运行 Route-GA，各图按实际实验范围展示。

严格 Stage-1 能耗、Stage-2 QoS、独立场景去重、逐对百分比及条件样本数的规则见英文图注。Fig. 3 的误差条为真实逐次数据的样本标准差；仅有汇总的消融与敏感性实验未添加误差条。Fig. 13 使用固定 USFS 历史火点及建模 MEC 部署，属于 GIS 驱动案例。

新增 [保护清单](data/preserved_files.json) 扩展到原有三张概念图、场景文件、原脚本、12 份 CSV、`uv.lock` 和已有 sanity 实例，共 32 个文件。重绘前后均核验其 SHA-256；不会把发生变化的原文件自动登记为新基线。

## 文件

| 图 | 可编辑源文件 | 论文插图 | 预览 |
|---|---|---|---|
| Fig. 1 系统模型 | [VSDX](visio/fig01_system_model.vsdx) | [PDF](output/pdf/fig01_system_model.pdf)、[SVG](output/svg/fig01_system_model.svg) | [PNG](output/png/fig01_system_model.png) |
| Fig. 2 算法框架：固定版 | [VSDX](visio/fig02_hybrid_alns_framework.vsdx) | [PDF](output/pdf/fig02_hybrid_alns_framework.pdf)、[SVG](output/svg/fig02_hybrid_alns_framework.svg) | [PNG](output/png/fig02_hybrid_alns_framework.png) |
| Fig. 2 算法框架：图形机制版 | [VSDX](visio/fig02_hybrid_alns_visual.vsdx) | [PDF](output/pdf/fig02_hybrid_alns_visual.pdf)、[SVG](output/svg/fig02_hybrid_alns_visual.svg) | [PNG](output/png/fig02_hybrid_alns_visual.png) |

建议按 **183 mm 双栏宽度**插入论文。模型图高约 126.3 mm，算法固定版高约 172.9 mm，图形机制版高约 144.9 mm。PNG 为 300 dpi 预览，正式论文优先使用 PDF/SVG。

**固定状态：** 系统模型、算法固定版的 VSDX/PDF/SVG/PNG、场景 JSON，以及原构图脚本和共享渲染脚本共 12 个文件已记录 SHA-256，见 [固定文件清单](frozen_baseline.json)。新增图只使用独立名称生成；以上文件在此次制作中保持字节级一致。

模型图保留四旋翼无人机、九个监测站、通信塔与机柜、机库及停机坪，以及两个覆盖区和两条巡航路线。七棵林木用于提示应用场景；卡片表示机载任务缓存，芯片表示机载计算，菱形表示 MEC 接触位置。位置、路线及对象数量均为架构示意。

算法图左侧以 01–05 编号串联五个主步骤，深色标题条突出 ALNS 探索与精英结构改进，较粗的纵向箭头标明主流程。右侧以成对箭头表示被反复调用的候选评价模块，并用标题与底色区分筛选、严格 CVX 求解和返回结果；底部用三个浅色标题卡片展示接触点调整、批次合并和任务处理模式切换。分区、编号、字重和留白共同形成视觉层次，不依赖颜色才能理解。具体判断与异常退出见 [配套伪代码和机制说明](algorithm_notes.md)。

图形机制版以三层结构表达算法：上方为五阶段主线；中部左侧展示同一组任务的原路线、破坏与重插入，右侧展示路线、接触点、批次和处理位置的四种候选操作；底部通过芯片、带宽分配条及能耗/状态符号展示资源评价。图内英文为 **54 词**，固定版为 166 词，减少约 **67.5%**；按英文字母片段统计，含缩写及公式中的英文字母，任务编号与标点不计。所有例子、分配条和最终路线均为机制示意，不代表某次实验结果。

## 英文图注

**Fig. 1. System model of multi-UAV forest patrol with intermittent heterogeneous MEC connectivity.** UAVs depart from a common depot, visit fixed monitoring nodes, collect and carry tasks, and return within the patrol cycle. Collected tasks can be processed locally or uploaded in batches at selected contacts inside MEC coverage. Heterogeneous MEC servers provide wireless bandwidth and CPU capacities $(B_e,F_e)$. Solid arrows denote patrol routes, dotted arrows denote task uploads, dashed boundaries denote MEC coverage, and diamonds identify contacts. The two patrol loops and nine monitoring nodes illustrate the architecture rather than a specific experimental instance.

**Fig. 2. Hybrid ALNS framework and illustrative structural moves.** (a) Greedy initialization and feasibility repair are followed by generic ALNS exploration, strict validation of the exploration best, and problem-specific elite refinement. The displayed main path assumes a strict-optimal Stage-1 resource baseline; otherwise, refinement is skipped and the non-strict status is returned. Elite refinement accepts only meaningful UAV-energy improvements and stops when no qualifying move remains or the round limit is reached. (b) Paired arrows indicate repeated candidate evaluation: exploration uses proxy/precheck screening with CVX checks when required, while the baseline and elite candidates use strict Stage-1 CVX resource optimization. KKT analysis characterizes resource-allocation laws and supports small-instance cross-checks. (c) Independent examples illustrate contact-point adjustment, batch merging at a later contact, and reassignment from local to MEC computation. All illustrated moves remain subject to feasibility and energy evaluation.

**Fig. 2 (visual alternative). Graphical mechanisms of Hybrid ALNS.** The upper sequence shows initialization, exploration, strict Stage-1 CVX validation, elite refinement, and the final solution; the displayed path assumes a feasible, strict-optimal continuous baseline. (a) Tasks 2 and 5 are removed from the current route and reinserted in a different order. Dashed orange circles retain the removed task locations, while pale dashed edges show their former connections. Evaluation precedes the exploration acceptance rule and adaptive updates; exploration need not decrease energy at every iteration. (b) Independent candidate examples modify route order, contact position, upload batches, or computation mode. Batch merging retains tasks 1, 2, and 3 at the later contact c₂. Shortlisted candidates are evaluated, and only feasible, strict-optimal candidates with a meaningful energy gain ΔE > τ are accepted. Here τ denotes the implementation's combined improvement threshold, including numerical and absolute/relative tolerances. (c) Paired peripheral arrows represent repeated candidate evaluation and returned scores/status. Proxy and feasibility screening invoke CVX as needed; baseline validation and elite evaluation use strict Stage-1 CVX. Circles denote tasks, squares denote depots, diamonds denote MEC contacts, and dashed ellipses denote coverage. E(D) is UAV energy for fixed discrete decisions D after resource optimization; tick and cross symbols denote possible returned statuses. Allocation bars and route changes are schematic, not measured improvements. KKT provides analytical support and small-instance cross-checks; non-strict exits, progressive widening, stopping rules, and optional Stage-2 are described in the accompanying algorithm notes.

## 编辑与重生成

当前继续修改图形机制版时，使用其独立构图源和脚本，避免覆盖固定版：

- [图形机制版构图源](visio/assets/fig02_hybrid_alns_visual.scene.json)
- [图形机制版生成脚本](scripts/build_algorithm_visual.mjs)

原 [算法固定版构图脚本](scripts/build_algorithm_figure.mjs) 及两张固定图的 JSON 作为可复现源保留。构图脚本仅描述图形，实际 VSDX/PDF/SVG/PNG 仍由 Visio 生成。

```powershell
# 仅生成独立的图形机制版
node paper_figures/scripts/build_algorithm_visual.mjs
& paper_figures/scripts/render_concept_figures.ps1 -FigureName 'fig02_hybrid_alns_visual'
```

渲染依赖 Windows PowerShell/PowerShell 和已安装的 Microsoft Visio；运行算法构图脚本另需 Node.js。构图源包含全部图形坐标、曲线、文本、样式和语义图层，重新生成不依赖旧版文件或网络。坐标原点在左上角，画布宽度为 1000 单位，换算比例为 0.183 mm/单位。

渲染器启动独立的不可见 Visio 实例，导出同名 VSDX、PDF、SVG 和 PNG，并重新打开 VSDX 核验图形数量。生成会覆盖同名导出文件；若手动修改过 VSDX，应同步修改构图源或先另存副本。导出目标若已在 Visio 中打开，请先关闭该文件。

原渲染器省略 `-FigureName` 时会重新生成所有场景，包括固定版；为保留固定文件，使用上述明确指定图形机制版的命令。固定记录用于校验文件是否变化，不设置操作系统只读属性。

## 内容依据与素材

- 绘图规范：[`docs/paper_figure_design_spec.md`](../docs/paper_figure_design_spec.md)。
- 系统与符号：项目 [`README.md`](../README.md) 和 [`docs/current_research_achievements.md`](../docs/current_research_achievements.md)。
- 算法定位：[`docs/paper_experiment_summary.md`](../docs/paper_experiment_summary.md)。
- Strict gate：[`hybrid.py`](../src/uav_mec/algorithms/alns/hybrid.py) 的 `run_uav_mec_hybrid_alns`。
- Near-miss、候选扩展和接受机制：[`problem_operators.py`](../src/uav_mec/algorithms/alns/problem_operators.py) 的 `contact_mode_intensification`。
- 本地 FIFO、同 UAV/MEC 的批次前驱与批内 EDF：[`events.py`](../src/uav_mec/evaluation/events.py) 的 `build_event_info`。
- Stage-2 资源分配：[`cvx_solver.py`](../src/uav_mec/optimization/resource/cvx_solver.py)。

算法图的首次 strict CVX 评估位于 near-miss 判断之前；扩展候选再次通过 strict CVX 验证。非严格基线单独退出，无有效改进时停止强化。KKT 表示解析结构，CVXPY 提供 paper-scale 正确性验证；图中的最终离散解不声明全局最优。

模型图的空间布局参考用户提供论文 `匿名版本_编辑部技术意见修订_最终提交版.docx` 中的 Fig. 1。未修改参考论文，也未引入其中的车辆、云端或联邦调度结构。图标采用经调整的 ByteDance IconPark 矢量素材，作者、原件、许可及修改说明见 [在线素材来源](visio/assets/online/ASSET_SOURCES.md)。

## 验证

- 系统模型有 291 个 Visio 原生图形，算法固定版有 158 个，图形机制版有 258 个；无嵌入式图片对象。
- 三份 PDF 均为单页矢量图，文字可提取、标签完整且无页面越界；PNG 为 300 dpi。
- 图形机制版字号为 8.5–13 pt；论文尺寸和灰度预览已检查，任务在操作前后保持一致。
- 固定文件清单的 12 个 SHA-256 均已复核；原文件没有变化。
- 当前核验记录：[verification.json](verification.json)。
