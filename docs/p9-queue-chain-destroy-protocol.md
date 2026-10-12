# P9：真正从 ALNS 邻域生成阶段修复 FIFO/EDF 排队时限

**研究起点：** P7 对原 B-ALNS 的只读完整搜索轨迹复现显示，六个高压力失败代表性工况的595个结构只有2个满足必要FIFO/EDF。P8 用“队列时限归一化超额直接替换原标量评分”，在全新 S101–S104 同探索墙钟预算下使原严格 Stage1+Stage2 合格ESI由6/40降至5/40，**未在任何一对原失败案例上新增真实合格**，故仅调惩罚项的思路没有成立。

## 科学假设与隔离消融

P9 不再修改评价函数；保持原 `ScreenedProxyObjectiveEvaluator`、所有旧修复算子、ALNS roulette选算/奖惩、RRT、原严格 P1-R/Stage2 **完全不变**。仅将三个原 destroy 算子之一 `critical_task_removal` 进行**一换一**，其余两项 random / route segment destroy 原样；和原实现使用相同 `DestroyConfig.count(K)` 移除 q 个任务、相同 `critical_pool_factor * q` 候选池、`rng.choice(pool, size=q, replace=False)` 取样，没有增加算子总数或精确CVX预算。

四组：
- `original`：原始proxy-critical任务移除，所有历史B终点SHA必须完全复现；
- `queue_task`：按FIFO/EDF乐观任务完成时间超过deadline的**归一化超额**选违约任务；
- `queue_chain`：对同一违约任务，再给它强制本地FIFO、MEC EDF+跨批FIFO，及UAV此前上传接触造成的**前驱阻塞任务**相应权重；
- `workload_control`：完全相同移除数量与普通修复，仅按任务 `workload/deadline` 择目标，测试“只是多针对重任务”是否同样有效。

关键：选择 `queue_chain` 不等于数学上已证明某个前驱是**唯一因果罪魁**；只是利用原模型必要排队链进行目标选择的可证伪启发式。

## 完整实验路线与结果判定

1. 在已观察 P7 的K80六个高压失败+一个正常严格可行对照上，四臂全部使用原100迭代、原源D/几何与相同seed。使用相同只读shadow记录离散结构新样本数、FIFO/EDF必要通过、共享CPU必要通过、通信+计算联合必要通过，以及**真实Stage1+Stage2严格恢复**。此轮仅**等迭代**，不声称等墙钟。
2. 事先冻结P9目标任务/前驱链和相同毁修算子数量、评价逻辑/随机种子，然后对S105–S108四个首用独立物理场景，每场景K80、5个单因子工况、2个嵌套随机种子141/142，使用原 MaxRuntime=6秒探索和原精英2秒封顶、同一RRT按时冷却、严格原 P1-R Stage1 + Stage2 及残差审计；记录全部真实初始化/搜索/完整资源验收耗时。原始迭代或RRT随机序列允许因任务选择而不同，这是新策略；初始D与算法随机种子保持配对。
3. **成功门槛：** 在高压工况生成更多 queue/joint necessary-passing D **且实际严格Stage1/Stage2提高或配对能耗改善**，并且不能由同算子族 `workload_control` 完全解释，且不能只靠负载正常案例取均值。
4. **停止门槛：** 若四个独立新场景 `queue_task`/ `queue_chain` 没有提高严格合格率、反而破坏正常工况原成功或增加运行时间，拒绝合并P9；下一步需重新研究原ALNS修复算子本身是否只按距离/逐任务乐观时限重插入，或从初始任务划分/卸载批次构造处理可行域难度。

结果统计单位必须是**独立物理场景**，两个算法seed只嵌套重复；`Stage1=infeasible` 本身不是整实例严格不可行证明，任何必要界通过也不是严格可行证明。不改 `develop` 或原论文结果；相关学术创新性需另对比 resource-constrained LNS、route/scheduling with time windows 和多UAV-MEC资源耦合文献。
