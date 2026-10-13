# P15：低成本 MEC 接触复用／FIFO-EDF 虚拟卸载插入机制——事前研发实验协议

**研究目标：** P12 验证原 `_insertion_option` 会因只看飞行距离和单个任务乐观期限，错过原本在 MEC 接触重构后严格可行的插入位置。P13 Top3 独立反事实中，只有执行原 `_finish_repair` 后再核验整个队列才能有效找到部分可行结构；P14 将“每次多次完整MEC重构”插进真实ALNS后，同预算独立S113–S116原ESI严格合格7/40，最好Top3队列方案仅5/40，原 ALNS 迭代数732下降到401，说明 **候选重构的额外墙钟成本吞噬收益**。

P15 测试**先不做任何额外完整MEC重构**，能否在插入时凭借旧 route-only 完整D、旧接触位置与已实现的轻量 FIFO/EDF 时间必要界，为旧 Top3 原插入位置提供可操作的时序预测？这样每次 ALNS 原修复仍只有**一次原 `_finish_repair()`**，理论上比P14节省大量额外完整MEC代理搜索。方法安全性来自完全不修改原 Stage1/2 资格逻辑；**虚拟卸载检查本身只是启发式，不是物理可行性证明**。

## 模型与计算协议

保留整个原 B-ALNS 的 destroy、greedy/regret2前11项任务插入顺序、ALNS原roulette/RRT、原`ScreenedProxyObjectiveEvaluator`、原CPU/带宽/电池/任务deadline硬约束。只在**最后一个重插入任务**恢复全部80任务的状态时，取原`_options_for_task`排序前3位，逐一：
1. 用原 `_apply_local_insertion`得到一个**完整**、其它卸载任务仍保留原方式的离散结构 `D_local`；
2. 用原 `build_event_info` + `queue_aware_feasibility_precheck`（原乐观资源、完整FIFO/EDF）测得必要时限/队列指标；
3. 对每个**当前 UAV 的该新任务之后已存在的 MEC contact**，临时仅把该任务改为卸载至这个 contact，得到虚拟 `D_offload`，再次只运行乐观队列必要条件。立刻恢复任务原LOCAL标志，**不真实增加接触、不运行 build_mec_assisted_initial_solution、不调用 CVX**；
4. 用可达性/队列指标选择原 Top3 插入位置，随后由原始生产 `_finish_repair` **只执行一次**。该MEC构造器仍可能和虚拟预测选择不同卸载方式，因此要经过原代理、原严格Stage1/Stage2验证，不允许把“虚拟队列通过”算作真正可行。

四种预注册对照（加原`original`共五臂）：

| arm | 相同Top3／虚拟检查 | 选择方法 | 因果作用 |
|---|---|---|---|
| `original` | 无 | 原始Top1 | 原论文控制 |
| `cheap_sham` | 全部同样运行 | 仍选原Top1 | 仅比较轻量虚拟评分自身 CPU 开销；原100迭代B最优解 SHA 必须精确重放 |
| `cheap_contact` | 同上 | 按是否有后续现存接触/首次可用接触位置 | 不使用队列数值的负对照 |
| `cheap_virtual` | 同上 | 对局部LOCAL与每个可用旧 contact 临时卸载，选乐观全任务 FIFO/EDF 时间必要评分最优的插入位置 | 假想既有接触复用＋必要排队信息 |
| `cheap_guarded` | 同上 | 原Top1重插入 LOCAL 的必要队列若已通过，则保留rank1；否则用 `cheap_virtual` 选 | 限制没有必要违约时的干预 |

## 预设实验与停止门槛

**第一阶段：** 对此前P12–P14全部看过的 K80 S89、S91、S93（两个profile）、S95、S96 六个源，原100 ALNS 迭代对比。所有原/cheap_sham的 B 最好D必须与原B源SHA一致；单元测试在同seed下检查相同repair、同RNG、原MEC`_finish_repair`只调用一次、临时 TaskDecision 没有被写入真实结构、全部离散路径合法。报告真实CPU时间、ALNS搜得不同 D、queue/staticCPU/jointBWCPU必要通过D、完整原Stage1+Stage2合格率及能耗；这轮**只等迭代，不等总墙钟**，不作为发表结果。

**第二阶段：** 如第一阶段有可信候选，就**冻结所有选择规则、Top3、全时序与回退逻辑**，首次在从未使用的 S117–S120、算法seed161/162、K80五压力配置上进行真正配对，原B探索6秒＋ESI最多2秒，统计全部真实运行墙钟与差异。若没有改善或改变更多原严格成功，应报告负面并停止叠加昂贵重构；后续只研究真实多任务插入候选顺序/初始分配而非同样玩法调权重。S113–S116已经用于P14，不得重复当作独立holdout。

**注意：** P15不是证明 `_insertion_option`存在代码bug；生产原评价指标本来是低成本近似。新方法也非数理上的全可行充分条件。只有相同物理场景层级可靠统计、真正原严格两阶段合格率/配对能耗与单位时间开销改善，才可能讨论为新 ESI-ALNS 方法贡献。原`develop`和论文数据均不改。
