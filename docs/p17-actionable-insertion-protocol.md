# P17：原 MEC 贪婪代理接受条件一致的低成本任务插入——科学预注册

## 问题定位

经过P12/P13原函数反事实检查，原`_insertion_option`只基于增量距离、周期和单任务乐观期限，无法预测之后`_finish_repair`对MEC接触复用的影响。P14完整Top3 MEC重构预览虽然研发有收益，但首次独立S113–S116原7/40、改5/40，根因每组搜索平均增加约4.7秒完整重构预览，在相同6秒探索预算下迭代数跌近半。P15用轻量虚拟旧contact卸载 FIFO/EDF必要界后，在独立S117–S120使迭代数原422、新`cheap_virtual`422，平均附加评分成本约0.079秒/组，然而真实Stage1+Stage2原10/40、`cheap_virtual`仍10/40，证明“计算便宜”不等于“选择的动作会被原MEC真正采纳”。

P16在真正原 `mec_repair.py` 中识别了更直接可操作的候选条件：对插入后的完整LOCAL结构，原MEC的 `evaluate_initial_proxy`有代理违反，插入任务进入 `_critical_local_tasks(...,8)`，某个后续原旧contact复用候选经原 `_strictly_better`比LOCAL严格好。只有这些被原MEC严格代理评分接受的结构，才可能**在第一贪婪步**由该任务以现有接触复用进入原候选短名单。P16已观察6个原源×2任务×原Top3=36位置，原筛选约3.70ms/结构，完整MEC原重构约73ms/结构；S96/S23旧rank1/2没有可接纳复用、旧rank3有，且原Stage1+2严格合格。但该条件**不是所有可能MEC修复的充分条件，更不是严格资源可行性证明**。

## P17设计：四个计算匹配的候选方法 + 原控制

只修改ALNS原两类repair的**最后一个**重新插入任务在原`_options_for_task` Top3中的位置选择。保留前11项恢复顺序/位置、3个destroy、2个repair算子名称、ALNS roulette/RRT、原目标 `ScreenedProxyObjectiveEvaluator` 和原P1-R/Stage1/Stage2全约束；每次repair只执行一次原`_finish_repair()`，candidate screening时只用 `evaluate_initial_proxy`/原`_critical_local_tasks`/原`_strictly_better`，**不调用Stage1 CVX、不重复完整MEC构造器**。

| arm | 策略 | 消融逻辑 |
|---|---|---|
| `original` | 完全原始 | 论文原控制 |
| `proxy_sham` | Top3每项完整运行同样的廉价代理/关键任务/旧接触候选检查，但仍保留原rank1 | 额外计算时间的负对照；旧100迭代B最终SHA必须6/6复现 |
| `proxy_contact` | Top3中优先旧接触数量多的插入位置，成本与其它proxy组相同 | 排除仅仅“有旧接触机会”就能获得改进 |
| `proxy_critical` | Top3优先插入任务确实属于原MEC critical8、其后有旧contact的位置，不看真实`_strictly_better` | 隔离原候选资格与代理改进 |
| `proxy_actionable` | 原rank1的原MEC proxy violated=0时保留；否则从所有进入原critical8且能严格改善原ProxyScore的旧接触复用候选中选代理key最优位置，没有符合则保留原rank1 | **真正待证伪的动作可采纳性机制** |

需特别区分：严格ProxyScore改善只表示**原贪婪构造器会把该候选纳入下一步枚举考虑**；若其它局部任务、新建MEC接触候选更优，它完全可以拒绝实际选择这一个动作；完整原Stage1/2与独立数值残差是唯一严格可行标准。正常S93/S59旧rank1已乐观队列通过但不被P17规定的`ProxyScore违规=0`自动保护，存在真实丢原成功风险，必须如实报告。

## 冻结实验顺序

**开发样本**：S89/S91/S93/S95/S96六个此前全部观察过的原B源，100迭代，完整严格Stage1/Stage2；原和`proxy_sham`必须都复现历史B最优 SHA256。只用于机制说明，不允许作为未来方法泛化证据。

**独立新场景**：四个未曾用于P0–P17调参的新空间场景 **S121,S122,S123,S124**，原任务数K80、5UAV/2MEC、五组物理压力baseline/compute×1.5/×2/deadline×0.9/×0.8、嵌套随机种子169/170。所有五臂相同初始D与算法seed，每臂原B探索6秒墙钟目标、ESI精英期最多2秒、相同只读 P7 必要条件观察器（计入搜索预算），原Stage1+Stage2全部严格重验。实际无法抢占的CVX及末端资源验收可超过8秒，必须单独记录**实际整流程墙钟**，不能把此称为全流程严格8秒硬限。源算法与物理条件在**首次看见S121–S124任何结果前**冻结并自动在GitHub Actions运行，结果一旦曝光不再用它们进行新的首次独立对照。

**预期证据门槛**：相同搜索时钟下真正 Stage1+Stage2 严格可行率高于 `original`，且不能由`proxy_contact`/`proxy_critical`控制解释；新增合格不能靠破坏更多原合格或付出显著更多CPU成本；配对同源两臂全部严格合格的能耗差同时报告，不混比较不同失败分母。如果研发正样本不能在S121–S124复制或者实际完整墙钟增加/原成功丢失，则拒绝将P17合入正式`develop`，停止类似旧 Top3 重排调参，重新研究多任务恢复/卸载顺序或物理联合可行域本身。即使短期正向，四空间场景太少、K80单尺度，不能当作论文统计证明。

学术背景：Liu et al., *EJOR* 310(1):133–155 (2023), DOI [10.1016/j.ejor.2023.02.028](https://doi.org/10.1016/j.ejor.2023.02.028)，已有高效时窗 feasibility checks 与ALNS修复。P17如有新意也必须归因于**原MEC贪婪接触动作关键任务/改进接受条件与UAV本地FIFO—上传远端EDF—静态带宽/CPU的耦合**，不能说在ALNS中首次设计廉价插入/时间窗检查。

以上代码与结果只在独立GitHub实验分支，原正式 `develop`/七算法论文数据不变。
