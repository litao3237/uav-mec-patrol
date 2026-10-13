# P16：原 MEC 贪婪构造器“会不会采纳现有接触复用”的真实动作一致性诊断

## 1. 为什么从 P15 的乐观虚拟卸载转向可操作的“接受条件”？

P14 完整三次 MEC 重构导致ALNS搜索迭代数大减；P15在原ALNS最后一次任务重插入时，通过只读乐观FIFO/EDF检查 `LOCAL` 或“把该任务临时卸载到其后现有接触”的虚拟D，避免额外多次MEC重构，实际只完整重构一次。首用S117–S120原 ESI严格 Stage1+Stage2为 **10/40**，`cheap_virtual`也是10/40（新增0，丢失0），虽然搜索迭代原422、新422，额外廉价评价均值仅约0.079秒/组，已解决 P14 的重大CPU预算浪费。

P15 **没有带来独立严格可行率收益**，这是方法局限，不是实现错误。固定复核[ P15 两个已见反例 ](https://github.com/litao3237/uav-mec-patrol/actions/runs/38336430912) 发现，S96/deadline×0.9/A130的S23在原Top1/Top2/Top3三种插入位置中，只要**假想把任务卸载到后面的现存接触**，原 FIFO/EDF乐观必要界都显示0项违约。所以旧虚拟proxy的最优分数全部打平，按旧排序选择rank1；然而原`_finish_repair`在rank1不采取卸载动作、真正Stage1失败，rank3则重新指向`G_U5_2`并严格Stage1+2成功。

由此得到明确的失配：**“虚拟接触卸载D满足必要条件”并不能推论原生产 `build_mec_assisted_initial_solution` 会选择这项卸载动作。**

## 2. 生产MEC贪婪修复逻辑本身包含的严格可操作性门槛

`src/uav_mec/algorithms/initial/mec_repair.py` 的原实现（从 P0 到现在develop不变）做：
1. 对插入后完整 `D_local` 调用原 `evaluate_initial_proxy`，返回 `ProxyScore=(违反约束数,最大归一化违反,总违反,能耗,路程)`；
2. 如果 `violated_constraints==0`，立刻停止 MEC greedy 重建；
3. 否则仅对 `_critical_local_tasks(...,limit=8)` 中的LOCAL任务，枚举其之后原旧接触及少量可新建物理接触；
4. 对一个候选 `D_{i→v}` 只有当原 `_strictly_better(score(D_{i→v}),score(D_local))` 才可能进入当轮备选；最终以原 `ProxyScore.key` 选择当轮最优移动。

因此，对给定完整 `D_local` 和被插入任务 i，`i∈critical8(D_local)` 且 `score(D_{i→v}) ≺ score(D_local)` 是**该任务的现有接触复用操作能被原MEC构造器在当前轮纳入考虑**的条件。它不是保证全局最终严格可行或保证该项会胜过其它任务的数学充分条件；但比“假想单任务卸载后的乐观期限合格”更接近 **原构造器实际动作域**。

这项判断只需临时生成`D_{i→v}` 并运行 **原数值廉价 `evaluate_initial_proxy`**，没有调用24轮完整的`build_mec_assisted_initial_solution`，更没有调用 Stage1 CVX。初步 S96 样本每个原插入位置约5ms；原真正MEC重构rank3约70ms。代价测量来自Windows不同runner，样本小，不能先宣称固定倍率加速。

## 3. 真正原函数反事实证据（GitHub Actions 已全绿）

[ P16 S96/S93 原函数动作审计 #38336820623 ](https://github.com/litao3237/uav-mec-patrol/actions/runs/38336820623)，原完整源 SHA、原任务、原 Top3与原MEC修复函数均不改，额外CVX只在做完“动作预测”后用于研发单例反事实严验。

| 已观察来源与原排名 | 插入任务在原MEC critical8中? | 可被原 `_strictly_better` 接纳的现有接触卸载动作 | 原 `_finish_repair` 真实动作 | 原严格Stage1+2 |
|---|---|---:|---|---|
| S96/S23 rank1 | 是 | **0** | 不改变卸载 | **失败** |
| S96/S23 rank2 | 是 | **0** | 不改变卸载 | **失败** |
| S96/S23 rank3 | 是 | **1** | `reuse_contact S23→G_U5_2` | **成功** |
| S93/S68 rank1 | 否，原代理违约为0，builder立刻停 | **0** | 不改变卸载 | **成功** |
| S93/S68 rank2 | 是 | **1** | **实际先新建另一接触**（并非一定采用原旧复用） | **失败** |
| S93/S68 rank3 | 否 | 0 | 无接触调整 | 失败 |

一个保守的首轮假设：若原rank1的完整代理已无违约就保留；否则仅当插入任务能够经当前原 `critical8`且有真实 `ProxyScore` 改进的现存接触复用，才优先考虑该位置。这种**原贪婪动作可采纳性证据**在这两个已经观察的例子中恰好选择 S96 rank3 和 S93 rank1。**2个例子完全不足以证明算法改善**，对不同源 D 中其它关键任务、其它虚拟队列及其跨批FIFO复杂竞争可能失效。

## 4. 研发结论和科研红线

不以 P16 两例开发样本直接将“动作用可采纳性预测器”融入论文原ESI-ALNS。下一步正在进行**6个先前观察的原B源×2任务×原Top3 =36个本地完成D**的原MEC一轮代理与真实builder首步关系检验，用完全原 `_critical_local_tasks`/`_strictly_better`，禁止调整已冻结的 `P16` 动作判别逻辑以迎合已观察结果。

如果30余个开发候选中它能覆盖更多真实选择的接触和队列必要可行性，再设计P17 **一换一轻量插入算子**，和`cheap_sham`及原算法在S121以后完全新场景/多K/真正匹配原搜索预算的 Stage1+Stage2严格成功和能耗上验证。必须单列判断器增加的CPU时间，不能因后验额外CVX获得一例严格合格而直接宣布论文创新。

基于同类文献 Liu et al., EJOR 310(1),133–155 (2023), DOI: [10.1016/j.ejor.2023.02.028](https://doi.org/10.1016/j.ejor.2023.02.028)，高效修复可行性检查本身已有成熟先例；真正潜在差异只可能在**静态 UAV–MEC任务卸载、接触复用与 FIFO/EDF 时序耦合下“插入位置对后续修复动作可采纳性”的原模型特化闭环**。
