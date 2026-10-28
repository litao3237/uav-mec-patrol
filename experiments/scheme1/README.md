# 方案一：多无人机路线 + 上传停靠（火场态势侦察）

问题定义与背景论证见论文资料 `26_方案一问题定义_火场态势侦察_20261026/问题定义与背景论证.md`。这里的脚本只用 Python 标准库（`gate2_analyze.py` 另需 matplotlib），参数沿用 `configs/v27_timeliness.yaml` 的冻结值。

| 脚本 | 作用 | 输出 |
|---|---|---|
| `stop_dp_verify.py` | 结构性质 P1（分段时间不变）、P2（逐份送达 + WSPT 时全部上传最优）、P3（给定顺序时停靠动态规划精确，与穷举对拍） | `stop_dp_verify_out.txt` |
| `batch_counterexample.py` | 整批送达语义下 P2 不成立的构造反例 | `batch_counterexample_out.txt` |
| `degeneracy_check.py` | 冻结参数下只优化 AoI 的退化检查与 AoI–时长预算折中；含加速动态规划 | `degeneracy_check_out.txt` |
| `dp_crosscheck.py` | 加速动态规划与已验证实现、独立事件模拟穷举的对拍 | `dp_crosscheck_out.txt` |
| `gate2_check.py` | 第二道检验：单机 6/7/8 个观测点，枚举全部访问顺序 + 帕累托动态规划求联合最优，与两阶段（精确最短回路 + 动态规划）比较；判定规则写在文件开头 | `gate2_results*.json`、`gate2_out.txt` |
| `gate2_analyze.py` | 第二道检验结果的特征分析与作图（本地运行） | `gate2_features_out.txt`、`gate2_*.png` |
| `gate3_check.py` | 第三道检验（规模外推）：A 校准局部搜索、B 每机 10/13/16 个观测点的扇形与火线实例、C 5 架机的跨机分配；判定规则写在文件开头，全文见论文资料 `28_规模外推检验_20261026/检验方案.md` | `gate3_*.json`、`gate3_out.txt` |

## 运行

- **Actions（正式数字）**：
  - `.github/workflows/scheme1-stops.yml`：改动 `experiments/scheme1/**`（第三道检验、分析脚本与本说明除外）或该工作流时运行。`verify` 作业复现结构性质与退化检查；`gate2` 作业按（观测点总数，种子）分 12 个分片并行；`gate2-summary` 汇总后判定。
  - `.github/workflows/scheme1-gate3.yml`：改动 `gate3_check.py` 或该工作流时运行，A、B、C 三部分分 44 个分片并行，`summary` 汇总后判定。
  - 结果在运行页 Summary 与产物中。
- **本地预览**：在本目录运行 `python gate2_check.py run`（全部实例，默认 11 进程）或其余脚本；输出写在本目录（已被提交的只有脚本）。

## 正式实现与论文实验

检验脚本之外，正式算法、基线与实验工具在包 `src/uav_mec/scheme1/` 中，实验规划见论文资料 `29_论文实验规划_20261026/实验规划.md`。

| 位置 | 作用 |
|---|---|
| `src/uav_mec/scheme1/`（params、instance、stops、tsp、search） | 本文方法：两阶段起点 → 机内局部搜索 → 跨机移动，以精确停靠动态规划评估，时间价格下界筛选与前缀复用加速 |
| `src/uav_mec/scheme1/baselines.py` | 基线 B0 只在基地上传、B1 就近贪心停靠、B2 两阶段、B3 静态分簇（仿 Huang 2026）、B4 截止驱动（仿 Raj 2026），与本文方法同一初始分配、同一预算 |
| `src/uav_mec/scheme1/experiment.py` | 在一个实例上运行全部方法，用独立事件模拟统一评估；记录逐份数据（AoI、是否超时、采集与送达时刻）、逐机统计、收敛过程、下界与精确值样本、计时、实例特征与几何信息；`summary_rows` 展开成 CSV 行 |
| `experiments/scheme1_plots.py` | 统一作图模块：方法的颜色、纹理与标记固定，中英文两套标签，每张图存 PDF 与 PNG；`demo` 子命令在冒烟种子 97–99 的小实例上运行全部方法并出示例图 |
| `experiments/scheme1_experiments.py` | 论文实验 E1–E3：`shard` 运行一个分片（按估计耗时蛇形分配），`summary` 合并分片、输出均值表、配对检验（Wilcoxon）、一致性检查与中英文图，`smoke` 本地冒烟 |
| `experiments/scheme1_e4.py` | E4：联合优化收益与实例特征的分层 Spearman 相关与线性模型（读 E1–E3 汇总产物，本地运行） |
| `experiments/scheme1_e5.py` | E5：与精确解的差距（单机穷举）、求解时间随规模、停靠动态规划与枚举对拍；`lbgap` 用 E1 数据算与下界的差距 |
| `experiments/scheme1_e6.py` | E6：事先声明的敏感性（站点数、覆盖半径、时效窗、电池、机数、上传速率），每次改变一个因素 |
| `experiments/scheme1_e7.py` | E7：火线案例（读 E1 汇总产物，本地运行）：按事先写定的规则选典型与收益最大两个实例，出航线图、逐份时间线、AoI ÷ δ 累积分布与各机任务时长；`--verify` 重算所选实例并与记录逐位比对 |
| `experiments/scheme1_e8.py` | E8：更强搜索对照。在 N = 50/80/120 的实例上，用多起点 + 扰动的迭代局部搜索在 P2 评估次数的 10 倍预算内继续搜索，按 29_ 写定的规则判定局部搜索是否足够；每个实例还逐步复现一次 P2，核对重写的跨机阶段与冻结求解器相同，N = 50、80 的 P2 与 E1 比对（参考值 `experiments/scheme1_e8_e1_p2_ref.csv`） |
| `experiments/scheme1_e8_fill.py` | E8 补跑：E8 中超时的分片 13 缺 6 个实例，把实例内的任务（P2、P2 复现、冷启动初始求解、4 条链）拆到不同作业运行；列任务与组装都调用 `run_instance` 本身（`ReplayPool` 代替进程池），结果除耗时外与实例内并行逐位相同；另取 3 个已完成的轻实例走同样流程，与 E8 原记录逐位比对 |
| `experiments/scheme1_supp.py` | E2、E6 补跑三个基线（B1、B3、B4），使这两组图与主对比用同一组 7 种方法：沿用原实验的实例生成，每个实例另跑 B2 并与参考值（`experiments/scheme1_supp_b2_ref.csv`，由 `ref` 子命令从原产物写出）逐位比对；`figures` 在本地把补跑记录并入原实验的结果并出图 |
| `experiments/scheme1_paper.py` | 论文图表整理（本地运行）：`collect` 把各实验重画的图按 29_ 的编号（F1–F20、X1–X17，含 E8 的 X16、X17）复制改名并写清单；`tables` 生成表 1 关键参数（从冻结配置读出）、表 2 方法一览、表 3 主结果（E1 默认场景的均值 ± 95% 置信区间），各出 Markdown、CSV 与 LaTeX；给出 E8 的产物（`--e8`）时，表 3 加 SCOUT+ 一行（按 E8 记录的方案重算），并写表 4（增强阶段的收益与规划耗时）；`schematics` 画示意图 |
| `experiments/scheme1_schematics.py` | 示意图 S1–S4：场景（E7 典型案例的几何）、一架机的时间线与 AoI 定义、算法框架、实验流程 |
| `experiments/scheme1_algo_check.py` | 回归（与第三道检验逐位比对）与提速检查 |
| `tests/test_scheme1_algorithm.py`、`tests/test_scheme1_experiment.py` | 单元测试 |

`.github/workflows/scheme1-algo.yml` 在改动上述文件时运行：`test` 跑单元测试，`check` 跑回归与提速检查，`figures` 跑作图示例并上传数据与图。`.github/workflows/scheme1-experiments.yml`、`scheme1-e5.yml`、`scheme1-e6.yml`、`scheme1-e8.yml` 分别在推送 `scheme1-exp-*`、`scheme1-e5-*`、`scheme1-e6-*`、`scheme1-e8-*` 标签时运行 E1–E3、E5、E6、E8（标签即冻结的代码版本），汇总作业把表格写进 Summary，数据、记录与图作为产物保留 90 天。`scheme1-e8-fill.yml` 在推送 `scheme1-e8fill-*` 标签时运行 E8 补跑（标签不能以 `scheme1-e8-` 开头，否则会同时触发整套 E8），合并作业跨运行取回 E8 的记录，与补跑结果一起重新汇总。`scheme1-supp.yml` 在推送 `scheme1-supp-*` 标签时运行 E2、E6 的基线补跑（4 个分片），汇总作业做检查并上传记录。本地出示例图：`python experiments/scheme1_plots.py demo --out 目录 --workers 4`；只改样式时加 `--plot-only`，用已有的 CSV 与 JSON 重画。
