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
