# P14 完整 ALNS 内少量 MEC 重构预览：机制消融预注册

**源：** `develop` 论文原始算法不变，研究分支 `experiment/p14-post-mec-preview-in-original-alns` 从 P13 独立发展；原MEC时间/资源约束、Stage1/Stage2和能耗评价未改。P12/P13在已用 S96/S23 找到：原插入Top1（U4@16）严格不合格，而旧排序第3位（U5@15）触发原 MEC 复用接触后严格两阶段合格；纯MEC接触数量评分在正常S93/S68会损失原合格。此前只是“固定单任务候选后额外调用求解器”，**绝非完整ALNS正向结果**。

## 核心研究假设

需要测试真实 ALNS 在每轮**原destroy删除12/80任务，原cheapest/regret2修复**时，能否用成本有限的短期 lookahead 提高完整资源可行的终态。不能对尚有多个未恢复任务的部分路线直接调用完整 FIFO/EDF checker。P14 保持原算法的前面11个任务插入决策与顺序**完全一致**，**仅最后一个被删除任务**使用原 `_options_for_task` 已有的Top3合法位置做重构预览，避免每个插入阶段枚举约90个位置。

每一预览候选原封不动调用 `_apply_local_insertion`、`_finish_repair`（原`build_mec_assisted_initial_solution`），然后由 FIFO/EDF 乐观必要时间下界排序。队列必要界**通过绝不表示 Stage1真正可行**，原 ScreenedProxy 与Stage1/Stage2最终数值残差保留。新机制只通过实验态 runner 中 Scoped `make_repair_operators` 替换原两个repair槽，**destroy总数/repair总数/RRT/roulette/原评价函数/CVX预算均未新增**。原原始`develop`中没有任何代码改动。

## 五组对照（均仅使用原Top3候选池）

1. `original`：完全原始ALNS。
2. `preview_sham`：每次正常检查Top3及原MEC重构，但**永远选原rank1**，明确额外预览本身的纯计算机会成本；100迭代终点SHA必须与原B完全一致。
3. `preview_contact`：与P13相同，只用最后完成解卸载任务数、接触新建量、总接触数量选位置；检验不计全时限的“低信息MEC代理”是否重复S93退化。
4. `preview_queue`：对三项完成MEC重构的固定D按 **必要队列是否通过→违约理由数→归一化截止期总超额→最大超额→飞行距离** 选位置。
5. `preview_guarded`：**如果原rank1经原MEC重构后已经通过必要FIFO/EDF，立即回退并保留rank1**，不预览rank2/rank3；否则使用同样预算和 queue 排序。检验是否减少正常工况误替换和预览成本。

**注意主要机制对照：** `preview_sham` 与 `preview_queue` 在每个选项候选上做相同Top3 MPC重构，但最终动作不同；与 `original` 比较考察额外算法墙钟代价；与 `preview_contact` 比较检查真实队列指标的增量信息。由于预览基于原全部任务完整结构，**不会直接向CVX请求额外精确验收**；原ScreenedProxy还会按原实现对必要预检已过但代理不确定的 D 自动调用原 Stage1，这是原ALNS已有行为，需完整计时。局部队列必要通过不保证全模型严格通过。

## 实验门槛和样本层级

- **P14研发机制阶段**：从先前P12冻结原源 S89/S91/S93/S95/S96 六组物理/随机组合开始，100原B迭代+原ESI两轮，源D SHA不变；特别要求原`original`与`preview_sham` B最优结构哈希 **6/6都与旧归档完全一致**。原严格阶段验收、全部失效和CPU花费完整保存。只有同样100迭代，不是完整时间公平测试。
- **首次独立效能检验**：把上述五臂代码和top3额度在看见任何新场景结果**之前**冻结，场景固定为 S113–S116，随机种子155/156，原K80每场景 baseline、compute×1.5、compute×2、deadline×0.9、deadline×0.8；每臂 **原ALNS探索6s墙钟目标 +原ESI精英最多2s**，只读共同Shadow成本包含在探索6s，另报完整原资源数值验收总CPU墙钟。这个实验不是整流程绝对硬截止6+2s，锥规划求解无法被抢占，后端验收成本有差异。
- **严格成功指标**：最终ESI Stage1+Stage2与各自保存/重构时序残差都合格；按不同物理场景及嵌套算法随机种子统计，不能把40组配对当40个独立空间场景。含正常负载，防止牺牲原成功获得高压偶然收益。
- **时间/能耗**：记录候选Top3预览数、preview调用次数和墙钟、实际运行迭代数、整个B/ESI搜索墙钟、末端Stage1/Stage2验收时间、严格共同成功原/改进能耗差；不同成功分母的能耗均值不可比较为“平均节能率”。
- **停止机制**：若固定预览开销减少迭代且没有真实新严格成功，或者成功完全来自更重计算，禁止宣称P14成功；若contact与queue相同或queue仍有原成功损失，需要回到原插入位置的物理可行性短名单/插入次序，而不是继续加大K。
- **统计边界**：即使新场景可行率略好，只有4个独立场景，仍需多K规模、重复独立物理布局、完整计算预算、B-ALNS/原ESI与新算法能耗的明确消融，才讨论投稿价值。

相关先例：time-window vehicle routing/communication scheduling 中已存在 ALNS 资源感知邻域与 lookahead，因而“Top3重构预览”本身不新颖；只有充分证据支持 UAV路径—MEC接触—FIFO/EDF—固定通信计算容量模型的具体耦合，才可能形成实质性算法贡献。
