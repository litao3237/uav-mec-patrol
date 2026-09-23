# 最终正文实验图与实验方案对应审计

> 状态：2026-09-23 最终正文插图核验。
>
> 重绘验证运行：GitHub Actions `35814825596`。
>
> 该运行在当前冻结数据文件上重新计算来源哈希，并继续执行 `ExperimentData.validate()` 的正式数值校验。共 109 项逐次重聚合指标与 `paper_results/*.csv` 在其保留精度内一致；配对样本数为 K=50: 24、K=80: 21、real geography: 8。

## 1. 正文采用图

| 论文图号 | 仓库源图 | 实验问题 | 实验设计 | 数据/统计口径 | 核验结论 |
|---|---|---|---|---|---|
| 图3 | `fig03_dense_workload` | ESI 增量价值随任务规模如何变化 | K=30,40,50,60,70,80；每个 K 为 S45-S47 × A100-A102 = 9 runs | B-ALNS/ESI-ALNS 均仅统计 Stage-1 strict；误差条为 run-level sample SD；gain 为 matching pair 百分比的均值 | 与 `dense_workload.csv` 一致 |
| 图4 | `fig05_baseline_comparison` | 正式主比较的解质量与高负载可行性 | S45-S52 共 8 independent scenarios；stochastic methods 每场景 3 seeds | K=50 能耗：GR-MR/FTR-NM 按 scenario 去重，RGA-MR/B-ALNS/ESI-ALNS 为 24 runs；K=80 展示 strict rate | 正式 8×3 主比较，不再使用旧 3×3 图 |
| 图5 | `fig06_paired_comparison` | ESI 在同一 B-ALNS exploration 后是否改善 | 与正式 S45-S52 主比较相同 | 图中每行是独立 scenario 内 common-strict repetitions 的均值；run-level 计数正文另报 K50 14/10/0、K80 17/4/0 | K50 7 scenario better/1 equal；K80 8 better |
| 图6 | `fig07_elite_ablation` | 哪类 ESI 操作产生主要增量 | K=80；共享同一 B-ALNS exploration；9 common-strict pairs/variant | Full ESI-ALNS vs 各消融版本的 paired advantage 和 better/equal/worse | Route 0.709%、Contact 0.302%、Batch 0.009%、Widening 0 |
| 图7 | `fig09_contact_budget` | 间歇连接的接触机会是否是关键约束 | Cmax=1,2,3,4；每设置 9 runs | strict rate + Stage-1-strict conditional energy + realized contacts/UAV；缺失值不补 0 | 6/9→7/9→9/9→9/9；Cmax≈3 后边际收益递减 |
| 图8 | `fig10_bandwidth_shadow` | 通信容量变化如何改变资源压力 | bandwidth scale=0.5,1.0,1.5；每设置 9 runs | Stage-1 strict conditional energy；shadow price 使用 Stage-1 multipliers | 低带宽 BW shadow 更高；带宽放松后部分压力转向 CPU |
| 图9 | `fig13_stanislaus_case` | 方法能否用于真实 GIS 空间分布 | 59 个 USFS 历史火点；3 scenarios × 3 stochastic seeds；地图展示 S45/A100 一条核验路线 | (a) 单个已复现 GIS case；(b) aggregate strict rate；(c) 8 common-strict pairs | 地图复现 869675.431725 J / 47645.919487 m；B/ESI 8/9；2/6/0；mean gain 0.543% |

## 2. 正文未采用图

下列图的数据与实验仍保留，但当前中文初稿正文不插入，以控制图数量：

- `fig04_workload_structure`：负载下 offload/contact/route 结构趋势；
- `fig08_mec_uav_sensitivity`：MEC/UAV 数量敏感性；
- `fig11_iteration_budget`：iteration-budget sensitivity；
- `fig12_strong_reference`：empirical best-known strong reference；
- `figS1_spatial_robustness`、`figS2_coverage_radius`：补充实验。

正文仍可用文字/表格概述其中必要结果；投稿版若版面允许，可将 Fig.4/Fig.8 恢复，Fig.11/Fig.12/S1/S2 优先作为 Supplement。

## 3. 核验规则

- 能耗主指标：仅 Stage-1 `optimal`；
- QoS/resource 指标：仅相应 Stage-2 strict subset；
- deterministic methods：scenario 为独立样本；
- stochastic methods：algorithm seeds 仅为 scenario 内重复；
- 不将 24 stochastic runs 描述为 24 个独立场景；
- paired gain：先对 matching pair 计算百分比，再聚合；
- non-strict/missing 不填 0；
- conditional mean 必须同时展示或说明有效样本数；
- strong reference 只称 empirical best-known，不称 global optimum；
- Stanislaus 只称 GIS-driven real-geography case，不称 field test。

## 4. 当前正文插图命名

所有正文实验图已统一为：

- GR-MR
- FTR-NM
- RGA-MR
- B-ALNS
- ESI-ALNS

已移除正式正文图中的旧显示名 `Generic ALNS`、`Proposed Hybrid`、`Full-Hybrid`。
