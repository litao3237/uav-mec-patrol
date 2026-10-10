# 复现说明

## 环境与目录

使用 `configs/requirements-frozen.txt` 固定数值依赖，按 README 安装可编辑项目。固定线程数，运行期间避免其他高负载任务影响计时：

```powershell
$env:PYTHONUTF8='1'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
```

新结果统一写入 `outputs/`；发布结果在 `results/`。所有命令在仓库根目录执行。完整残差验收不使用 `python -O`，因为部分继承的验收逻辑使用断言。

## 原始记录与离线复验

```powershell
python experiments/manage_results.py verify
python experiments/manage_results.py extract --output-dir outputs/recorded
python experiments/verify_recorded_results.py --output-dir outputs/reproduction
```

解压会校验 ZIP、CRC、成员 SHA-256 和路径边界。已有文件相同则复用，不同则保留原文件并报错。一键复验包括：

1. 主实验完整矩阵、实例/方案身份、两阶段原始资源与重构时序残差。
2. 扩展实验的新计算/复用身份、完整七算法记录及相同验收标准。
3. 软预算对照的失败记录、完整计时、预算超出量与配对统计。
4. 消融的共享 B-ALNS 起点、180 条强化记录及 16 个场景等权汇总。
5. 与发布摘要的逐字段对比，以及全部 23 幅图四种格式和源数据哈希。

`--archived` 模式绑定 `results/archive_manifest.json` 中原始字节与历史运行身份；它不声称运行时旧目录中的全部源码与整理后的源码集合相同。普通新运行模式继续核对当前源码。旧路径字符串保留作来源证据，离线读取使用命令行提供的目录。

## 主实验全矩阵

首先执行三组先导，再冻结配置执行 48 个正式场景块：

```powershell
foreach ($k in 30,50,80) {
  python experiments/run_seven_methods.py --phase pilot --tasks $k --scenario 45 --output "outputs/current/main/pilot/K${k}_S45.json"
  if ($LASTEXITCODE -ne 0) { throw '先导失败' }
}
python experiments/dispatch_main.py --workers 3 --output-dir outputs/current/main
python experiments/aggregate_seven_methods.py --input-dir outputs/current/main/formal --phase formal --output outputs/current/main/summary.json
```

正式矩阵为 6 个规模 × 8 个场景。确定性方法每场景一次，5 个随机方法使用 100/101/102 三个种子，共 816 条记录。B/ESI 共享探索起点，执行顺序随机化。先导只验证执行和记录完整性，不按观察收益选择场景。

## 接触、带宽及 GIS 扩展

完成新的主实验后执行：

```powershell
python experiments/dispatch_extension.py --workers 3 --main-dir outputs/current/main/formal --output-dir outputs/current/extension
python experiments/aggregate_extension.py --input-dir outputs/current/extension --main-dir outputs/current/main/formal --protocol outputs/current/extension/frozen_protocol.json --output outputs/current/extension/summary.json
```

接触上限为 1/2/3/4，带宽倍数为 0.5/1/1.5，GIS 使用固定地图的三个工作负载场景。接触上限 3 和带宽 1 复用相同主实验记录，不能视为新独立重复。GIS 原始输入已入库；复现不需要重新联网下载。

## 软预算与消融

```powershell
python experiments/run_budget_check.py --output-dir outputs/current/budget/raw
python experiments/aggregate_budget_check.py --input-dir outputs/current/budget/raw --output outputs/current/budget/summary.json
```

预算对照串行执行。15/45 秒为名义端到端预算，单次求解不可抢占，实际超时逐条保留。

论文消融来自冻结 B-ALNS 检查点的后强化重放。先解压归档，再查看以下入口参数：

```powershell
python experiments/replay_esi_acceptance.py --help
python experiments/run_multiscale_ablation.py --help
python experiments/aggregate_ablation.py --input-dir outputs/recorded/ablation --archived --output outputs/ablation_verified.json
```

`replay_esi_acceptance.py` 重放指定输入检查点；`run_multiscale_ablation.py` 从新构造的相同探索起点比较 full、no-route、no-contact、no-batch、no-widening。新运行可能产生不同检查点，须另行报告，不能覆盖论文冻结证据。经验参考执行器为 `run_small_strong_benchmark.py`，其已有结果按历史口径保存于 `results/reference/strong.json`，不纳入当前完整残差证据。

## GitHub Actions

`ci.yml` 在 Windows 和 Linux 上运行测试和归档检查，并在 Windows 上执行全量离线复验。`experiment.yml` 仅手动触发，支持主实验或扩展单场景块；budget 选择运行完整串行预算矩阵。运行成功与否都上传已落盘快照。

同一新实验矩阵应固定同一提交与环境。重跑任务使用新目录或新工件名，保留失败快照；不要将不同源码批次混为一轮实验。

## 工程整理与数值一致性

本次整理未修改当前算法核心数值逻辑。删除旧 adaptive、continuous、terminal、budget-aware、energy-guided 和 checkpoint 变体，精简公共导出；将运行身份/阶段快照、归档末位差异检查提取为独立公共模块。实验运行器只调整了路径、参数和源码清单登记。旧原始 JSON 没有回填或改写源码哈希。
