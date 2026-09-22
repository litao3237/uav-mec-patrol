# 论文实验结果与图表冻结方案（Draft v1）

> 适用算法：最终冻结的 ESI-ALNS。
>
> 正文只呈现论文所需证据；v5–v7 的预算公平性与 paired-checkpoint 研发过程仅作为内部审计和必要时的补充材料来源，不进入主文算法叙事。

## 1. 正文实验叙事顺序

实验章节按以下证据链组织：

1. **总体性能**：ESI-ALNS 与四类基线比较；
2. **增量价值**：在同一 B-ALNS exploration 上验证 ESI 的单调后强化作用；
3. **机制消融**：识别 ESI 中真正起作用的结构操作；
4. **系统机理**：分析负载、接触机会、带宽、MEC/UAV 数量对结果的影响；
5. **求解质量与计算预算**：用 iteration sensitivity 和 strong reference 说明有限预算下的质量–开销权衡；
6. **真实地理案例**：验证方法在 GIS 驱动林区任务分布下仍可工作。

正文不以 v5/v6/v7 作为算法版本展开，也不讨论开发集/hold-out 的调参历史。

## 2. 正文核心结果

### 2.1 K=50 主比较

正式设置：

- 8 个独立场景：S45–S52；
- stochastic methods 每场景 3 个 algorithm seeds：A100/A101/A102；
- B-ALNS / ESI-ALNS：100 iterations；
- ESI：2 elite rounds。

| Method | Strict | Mean energy (J) | Median energy (J) |
|---|---:|---:|---:|
| GR-MR | 7/8 | 226449.279 | 227768.558 |
| FTR-NM | 8/8 | 227825.225 | 227281.171 |
| RGA-MR | 24/24 | 227955.557 | 227001.502 |
| B-ALNS | 24/24 | 165966.950 | 166786.002 |
| ESI-ALNS | 24/24 | **163189.844** | **165558.602** |

ESI-ALNS 相对：

- FTR-NM：24/24 paired lower，mean paired advantage 28.378%；
- RGA-MR：24/24 paired lower，mean paired advantage 28.341%；
- B-ALNS：14 better / 10 equal / 0 worse，mean paired improvement 1.549%。

按独立场景聚合，ESI-ALNS 相对 B-ALNS 为 7 个场景改善、1 个场景相同。

### 2.2 K=80 主比较

| Method | Strict |
|---|---:|
| GR-MR | 1/8 |
| FTR-NM | 1/8 |
| RGA-MR | 3/24 |
| B-ALNS | 21/24 |
| ESI-ALNS | 21/24 |

21 个 common-strict B-ALNS / ESI-ALNS pairs 中：

- ESI-ALNS better：17；
- equal：4；
- worse：0；
- mean paired energy reduction：0.673%；
- mean strict energy：226006.074 J → 224416.886 J。

K=80 主要用于说明 ALNS family 的 strict-feasibility robustness，以及 ESI 对同一 exploration incumbent 的进一步改善；RGA-MR 仅 3/24 strict，因此不使用其条件能耗做广泛质量结论。

## 3. Figure 最终分工

### Fig. 1 — System Model

**正文必留。**

Visio 矢量图。说明：

- fixed monitoring nodes；
- multiple UAVs；
- intermittent MEC coverage；
- task collection / carrying；
- local computation；
- contact-based batch offloading。

### Fig. 2 — ESI-ALNS Framework

**正文必留。**

建议正式采用固定框架版或图形机制版中的一版，不同时放两版。

主流程统一命名：

Greedy Route Seed → MEC Repair → B-ALNS Exploration → Elite Structural Intensification → Strict Stage-1 CVX Acceptance。

### Fig. 3 — Dense Workload Performance

**正文建议保留。**

K=30–80，3 scenarios × 3 seeds。

(a) B-ALNS vs ESI-ALNS mean strict energy；  
(b) ESI-ALNS paired improvement。

作用：展示 ESI 增量价值随任务规模变化，而不是替代正式 8×3 baseline。

### Fig. 4 — Workload Structural Evolution

**可放正文，也可根据版面移至补充。**

Offload ratio、contacts/UAV、route distance 随 K 变化。

作用：解释负载增加为何强化 Route–Contact–Offloading coupling。

### Fig. 5 — Formal Baseline Comparison

**正文必留，必须按 8×3 数据重绘。**

(a) K=50 run-level strict energy：GR-MR / FTR-NM / RGA-MR / B-ALNS / ESI-ALNS；  
(b) K=80 strict-feasibility rate。

当前绘图数据接口已切换到正式 S45–S52 主比较。

### Fig. 6 — B-ALNS vs ESI-ALNS Paired Comparison

**正文必留，必须按 8×3 数据重绘。**

不再绘制 24 条拥挤的 seed-level slope，而采用 **8 个独立场景的场景内 strict mean paired plot**：

- K=50：7 better / 1 equal / 0 worse scenarios；
- K=80：8 better / 0 equal / 0 worse scenarios。

正文同时报告 run-level paired counts：

- K=50：14/10/0；
- K=80：17/4/0。

### Fig. 7 — Elite-Family Ablation

**正文必留。**

- w/o Route：Full advantage 0.709%，6/3/0；
- w/o Contact：0.302%，3/5/1；
- w/o Explicit Batch：0.009%，2/6/1；
- w/o Progressive Widening：0.000%，0/9/0。

结论：route-compute relocation 是主导机制；contact family 提供辅助增益；batch 与 widening 在当前设置下 aggregate contribution 较小。

### Fig. 8 — MEC/UAV Sensitivity

**正文可留；版面紧张时可移补充。**

MEC count：

- E=2/3/4 strict = 3/9, 8/9, 8/9；
- CPU utilization 随 MEC 数增加总体下降；
- energy 对 E 不呈单调下降。

UAV count：

- M=3/5/8 strict = 0/9, 9/9, 9/9；
- M=5→8 energy 约下降 1.01%；
- delay 与 contacts/UAV 同时下降。

### Fig. 9 — Contact-Opportunity Sensitivity

**正文重点图，必留。**

Cmax=1/2/3/4：

- strict = 6/9, 7/9, 9/9, 9/9；
- energy = 239095.092, 234636.497, 226768.196, 227632.234 J；
- contacts/UAV = 0.733, 1.029, 1.044, 1.222。

核心结论：接触机会不足会缩小可行域并提高条件能耗；约 3 次/UAV 后出现明显边际收益递减。

### Fig. 10 — Bandwidth Sensitivity + Shadow Price

**正文重点图，必留。**

Bandwidth scale 0.5/1.0/1.5：

- strict = 8/9, 9/9, 9/9；
- energy = 230892.958, 226768.196, 227432.750 J；
- BW relative shadow = 0.011, 0.005, 0.005；
- CPU relative shadow = 0.000, 0.000, 0.008。

结论应表述为资源压力随容量配置转移，而不是简单声称 bandwidth 越多能耗越低。

### Fig. 11 — Iteration-Budget Sensitivity

**建议放补充材料；正文可用一段文字概述。**

25/50/100/200 iterations：

- strict = 6/9, 8/9, 9/9, 7/9；
- conditional energy = 245028.040, 238428.651, 226768.196, 217985.012 J；
- runtime = 20.798, 26.343, 50.011, 88.577 s。

100 iterations 是质量、strict robustness 与时间之间的 operating point，不称“收敛点”。

### Fig. 12 — Strong Reference

**建议放补充材料或正文末尾。**

K=28, M=2, E=2。

Standard ESI-ALNS 相对 empirical best-known：

- mean gap 5.968%；
- median 8.610%；
- strong reference 36/36 strict；
- 不能称 global optimum gap。

### Fig. 13 — Stanislaus Real-Geography Case

**正文必留。**

GIS-driven case：

- GR-MR：0/3 strict；
- FTR-NM：0/3 strict；
- B-ALNS：8/9 strict；
- ESI-ALNS：8/9 strict；
- common strict pairs：2 better / 6 equal / 0 worse；
- mean ESI-ALNS advantage：0.543%。

作用：证明真实地理分布适用性，不宣称为实飞验证，也不强调大量 MEC offloading。

### Fig. S1 / S2

放 Supplement：

- spatial distribution robustness；
- MEC coverage-radius sensitivity。

## 4. 正文推荐的图数量

若版面充足，正文使用：

Fig. 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13。

Fig. 11、12、S1、S2 放 supplementary。

若版面较紧，优先进一步把 Fig. 4、8 移补充，正文核心图缩减为：

**Fig. 1 / 2 / 3 / 5 / 6 / 7 / 9 / 10 / 13。**

## 5. 正文不呈现的研发证据

以下不进入主文结果章节：

- v1–v4 稳定性改造；
- v5 dynamic reserve；
- v6 Energy-Guided ESI；
- v7 paired-checkpoint fork；
- S85–92 development；
- S93–100 v6 hold-out；
- S101–108 v7 unseen。

这些证据只用于支持一个结论边界：

> 本文不声称 ESI 在相同追加 wall-clock 下稳定优于 continued B-ALNS。

正文若需要计算公平性说明，只保留 matched-runtime 的简短结论：同一总时间预算下，B-ALNS 与 ESI-ALNS 的解质量整体接近，因而 ESI 被定位为固定 exploration 后的结构精修阶段，而不是计算效率上全面支配 B-ALNS 的替代算法。

## 6. 统计口径

正文所有实验统一遵守：

- 主能耗：strict Stage-1 CVX only；
- QoS/resource：strict Stage-2 subset；
- deterministic baseline：scenario 为独立样本；
- stochastic algorithm：algorithm seeds 是 scenario 内重复；
- 主比较的独立单位是 8 个 scenarios，不把 24 runs 写成 24 个独立场景；
- paired gain 使用逐 pair 百分比后再求均值；
- non-strict 不填 0；
- empirical best-known 不称 global optimum；
- real geography 不称 field test。

## 7. 当前需要重新生成的图

由于正式主比较从旧 3×3 扩展为 8×3，目前需要重新生成：

1. **Fig. 5**；
2. **Fig. 6**；
3. 依赖 baseline/paired 数据的 overview 与 combined PDF；
4. 相应英文 captions / figure registry / verification。

其他实验图的数据口径没有因 v5–v7 改变，可继续沿用已冻结结果，只统一算法显示名为 B-ALNS / ESI-ALNS。
