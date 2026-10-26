"""机队联合优化：以精确停靠动态规划评估候选航线的局部搜索（机内 + 跨机邻域）

搜索过程与第三道检验（experiments/scheme1/gate3_check.py 的 C 部分）等价：同样的邻域、随机打乱方式、
首次改进规则与评估计数。加速只跳过"时间价格下界已证明不可能改进"的候选，所以开关加速得到完全相同的
搜索轨迹与结果，只是更快
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .instance import Instance, seed_of
from .stops import TOL, best_lambda, exact_stops, lambda_dp, simulate
from .tsp import shortest_tour

# 每次机内搜索的评估次数上限（只计第一次见到的、回路长度可行的候选），与第三道检验相同
DEFAULT_MAX_EVALS = {6: 1000, 7: 1000, 8: 1000, 10: 2000, 13: 3000, 16: 5000}


@dataclass
class SearchConfig:
    """搜索设置；max_evals 未给出的观测点数按 1000 + 500·(n − 8) 取"""

    accelerate: bool = True
    max_evals: dict = field(default_factory=lambda: dict(DEFAULT_MAX_EVALS))
    inter_evals: int = 3000          # 跨机阶段的评估上限
    reopt_evals: int = 300           # 跨机移动被接受后，对两条航线各做一次短局部搜索的上限
    neighbors: int = 5               # 跨机候选：每个观测点最近的 5 个异机观测点

    def evals(self, n: int) -> int:
        return self.max_evals.get(n, 1000 + 500 * max(0, n - 8))


class Budget:
    """飞行时间上限：任务时长预算 (1+ε)·T̂ 与电池二者取严

    悬停时间按航线顺序逐点累加（与检验脚本一致），同一组观测点的不同顺序在浮点末位上可能略有差别
    """

    def __init__(self, inst: Instance, eps: float, t_hat: float):
        self.inst, self.eps, self.t_hat = inst, eps, t_hat

    def cap(self, route) -> float:
        h = self.inst.hover_time(route)
        p = self.inst.params
        return min((1 + self.eps) * self.t_hat - h, (p.battery_j - p.p_hover_w * h) / p.p_fly_w)


LAMBDA_REFRESH = 5        # 每 5 次更换当前航线重新求一次 λ*，其余沿用上一次的 λ（下界仍有效，只是可能略松）
PROBE_EVERY = 50          # 筛选关闭时，每 50 个候选试探一次，以便实例特性变化时重新打开


class Incumbent:
    """局部搜索中当前航线的上下文：精确结果、时间价格 λ 及其 λ 动态规划状态（需要时才计算）"""

    __slots__ = ("route", "val", "lam", "state", "hint")

    def __init__(self, route, val, hint=None):
        self.route, self.val, self.hint = route, val, hint
        self.lam = self.state = None


class RouteEvaluator:
    """航线评估：精确停靠结果与时间价格下界，均按航线缓存

    下界筛选是否值得做取决于实例：预算紧时帕累托标签很少，精确动态规划本身就很便宜。
    因此在线统计精确计算与下界检查的平均耗时和剪枝率，只有预期能省时才启用筛选。
    筛选只跳过可证明不改进的候选，开关与否都不改变搜索结果
    :param inst: 实例
    :param cap_of: 航线 -> 飞行时间上限
    :param accelerate: 是否允许使用时间价格下界筛选
    :param lb_samples: 抽样记录"下界与精确值"成对样本的个数（作图用）；抽到的候选两者都计算，不影响接受判断
    """

    def __init__(self, inst: Instance, cap_of, accelerate: bool = True, lb_samples: int = 0):
        self.inst, self.cap_of, self.accelerate = inst, cap_of, accelerate
        self.exact_cache: dict = {}
        self.lb_cache: dict = {}
        self.seen: set = set()
        self.stats = {"exact": 0, "lambda": 0, "pruned": 0, "incumbent": 0}
        self._t_exact = self._t_filter = 0.0
        self._n_checks = self._n_lambda_updates = 0
        self.lb_samples_left = lb_samples
        self.lb_pairs: list = []          # (观测点数, 下界, 精确值)

    def timing(self) -> dict:
        """精确计算与下界筛选各自的累计耗时（s）"""
        return {"t_exact": self._t_exact, "t_filter": self._t_filter}

    def _filter_on(self) -> bool:
        """预期省时才筛选：下界检查的平均成本 < 剪枝率 × 精确计算的平均成本；样本不足时先筛选以收集统计"""
        if not self.accelerate:
            return False
        self._n_checks += 1
        n_ex, n_lb = self.stats["exact"], self.stats["lambda"]
        if n_ex < 10 or n_lb < 10 or self._n_checks % PROBE_EVERY == 0:
            return True
        return self._t_filter / n_lb < (self.stats["pruned"] / n_lb) * (self._t_exact / n_ex)

    def _ensure_lambda(self, inc: Incumbent) -> None:
        """为当前航线准备 λ 与 λ 动态规划状态，计入筛选成本"""
        if inc.state is not None:
            return
        t0 = time.perf_counter()
        self._n_lambda_updates += 1
        if inc.hint is not None and self._n_lambda_updates % LAMBDA_REFRESH != 1:
            lam = inc.hint
        else:
            self.stats["incumbent"] += 1
            lam = best_lambda(self.inst, list(inc.route), self.cap_of(inc.route), guess=inc.hint)[0]
        inc.lam, inc.state = lam, lambda_dp(self.inst, list(inc.route), lam)
        self._t_filter += time.perf_counter() - t0

    def length_ok(self, route) -> bool:
        """回路长度本身已超上限的航线不可行，不做动态规划，也不计入评估次数"""
        return self.inst.route_length_m(route) / self.inst.params.speed_mps <= self.cap_of(route) + TOL

    def touch(self, route) -> bool:
        """第一次见到这条（回路长度可行的）航线时返回 True，用于评估计数"""
        key = tuple(route)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True

    def exact(self, route):
        key = tuple(route)
        if key not in self.exact_cache:
            t0 = time.perf_counter()
            self.exact_cache[key] = exact_stops(self.inst, list(route), self.cap_of(route))
            self._t_exact += time.perf_counter() - t0
            self.stats["exact"] += 1
        return self.exact_cache[key]

    def incumbent(self, route, val, prev: Incumbent | None = None) -> Incumbent:
        """记录当前航线；λ 与其状态在第一次需要下界时才计算，并以上一条航线的 λ 为提示"""
        hint = None if prev is None else (prev.lam if prev.lam is not None else prev.hint)
        return Incumbent(list(route), val, hint)

    def lower_bound(self, route, inc: Incumbent) -> float:
        """用当前航线的 λ 求候选航线的拉格朗日下界，并复用与当前航线相同前缀的状态"""
        self._ensure_lambda(inc)
        t0 = time.perf_counter()
        key = tuple(route)
        st = lambda_dp(self.inst, list(route), inc.lam, reuse=inc.state)
        self.stats["lambda"] += 1
        lb = st.value - inc.lam * self.cap_of(route)
        if lb > self.lb_cache.get(key, -math.inf):
            self.lb_cache[key] = lb
        self._t_filter += time.perf_counter() - t0
        return self.lb_cache[key]

    def _known(self, key) -> float:
        if key in self.exact_cache:
            v = self.exact_cache[key]
            return math.inf if v is None else v[0]
        return self.lb_cache.get(key, -math.inf)

    def value_if_improving(self, route, inc: Incumbent, threshold: float):
        """候选航线的精确结果；若下界已证明其目标 ≥ threshold，返回 None 而不做精确计算

        下界需比 threshold 高出浮点容差才剪枝，保证与不加速时的接受判断（目标 < threshold − 1e-12）完全一致
        """
        key = tuple(route)
        if key in self.exact_cache:
            return self.exact_cache[key]
        if self.lb_samples_left > 0 and inc.val is not None:
            # 抽样：下界与精确值都算，成对记录；之后按精确值判断，与不抽样时的接受结果相同
            self.lb_samples_left -= 1
            lb = self.lower_bound(route, inc)
            ex = self.exact(route)
            if ex is not None:
                self.lb_pairs.append((len(route), lb, ex[0]))
            return ex
        margin = 1e-9 * max(1.0, abs(threshold))
        lb = self._known(key)
        if lb >= threshold + margin:
            return None                              # 早先算过的下界已足够（当前解只会变好，旧下界仍可用）
        if inc.val is not None and self._filter_on():
            lb = self.lower_bound(route, inc)
            if lb >= threshold + margin:
                self.stats["pruned"] += 1
                return None
        return self.exact(route)

    def pair_values(self, ra, rb, inc_a: Incumbent, inc_b: Incumbent, threshold: float):
        """两条航线的精确结果；若两者下界之和已证明总目标 ≥ threshold，返回 None"""
        ka, kb = tuple(ra), tuple(rb)
        if inc_a.val is not None and inc_b.val is not None and self._filter_on():
            margin = 1e-9 * max(1.0, abs(threshold))
            ba, bb = self._known(ka), self._known(kb)
            if ba + bb < threshold + margin and ka not in self.exact_cache:
                ba = self.lower_bound(ra, inc_a)
            if ba + bb < threshold + margin and kb not in self.exact_cache:
                bb = self.lower_bound(rb, inc_b)
            if ba + bb >= threshold + margin:
                self.stats["pruned"] += 1
                return None
        return self.exact(ra), self.exact(rb)


# ---------- 机内邻域与局部搜索 ----------

def neighborhood(n: int) -> list[tuple]:
    """2-opt、交换与 Or-opt（连续 1–3 个点移到别处，2–3 个点时可反向插入）"""
    out = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            out.append(("2opt", i, j))
            out.append(("swap", i, j))
    for length in (1, 2, 3):
        for s in range(n - length + 1):
            for p in range(n - length + 1):
                if p == s:
                    continue
                for rev in ((False,) if length == 1 else (False, True)):
                    out.append(("or", s, length, p, rev))
    return out


def apply_move(route, mv) -> list:
    r = list(route)
    if mv[0] == "2opt":
        _, i, j = mv
        r[i:j + 1] = r[i:j + 1][::-1]
    elif mv[0] == "swap":
        _, i, j = mv
        r[i], r[j] = r[j], r[i]
    else:
        _, s, length, pos, rev = mv
        blk = r[s:s + length]
        del r[s:s + length]
        if rev:
            blk = blk[::-1]
        r[pos:pos] = blk
    return r


def route_local_search(ev: RouteEvaluator, start, max_evals: int, rng: random.Random, on_improve=None):
    """首次改进的机内局部搜索：每轮随机打乱邻域，找到第一个更优的候选就移动；一整轮无改进即为局部最优

    :param on_improve: 可选回调 (本次搜索的累计评估次数, 新目标)，每次接受改进时调用，用于记录收敛过程
    :return: (航线, 精确结果, 评估次数, 是否在上限内收敛)
    """
    cur = list(start)
    n = len(cur)
    if n < 2:
        return cur, ev.exact(cur), 0, True
    ok = ev.length_ok(cur)
    evals = int(ok and ev.touch(cur))
    cur_val = ev.exact(cur) if ok else None
    inc = ev.incumbent(cur, cur_val)
    moves = neighborhood(n)
    while evals < max_evals:
        rng.shuffle(moves)
        improved = capped = False
        for mv in moves:
            cand = apply_move(cur, mv)
            if not ev.length_ok(cand):
                continue
            evals += ev.touch(cand)
            threshold = cur_val[0] if cur_val is not None else math.inf
            val = ev.value_if_improving(cand, inc, threshold)
            if val is not None and (cur_val is None or val[0] < cur_val[0] - 1e-12):
                cur, cur_val, improved = cand, val, True
                inc = ev.incumbent(cur, cur_val, prev=inc)
                if on_improve is not None:
                    on_improve(evals, cur_val[0])
                break
            if evals >= max_evals:
                capped = True
                break
        if not improved:
            # 整轮没有改进才算收敛；因评估次数用完而中断的不算
            return cur, cur_val, evals, not capped
    return cur, cur_val, evals, False


# ---------- 机队求解 ----------

@dataclass
class FleetResult:
    routes: list            # 每架机的 gid 访问顺序
    plans: list             # 每条航线的 (Σ AoI/δ, 飞行时间, 停靠方案)
    objective: float        # 全部航线的 Σ AoI/δ
    two_stage: float        # 两阶段（最短回路较好方向 + 精确停靠）的 Σ AoI/δ
    per_route: float        # 每机局部搜索之后、跨机移动之前的 Σ AoI/δ
    t_hat: float
    eps: float
    stats: dict
    history: list = field(default_factory=list)          # 收敛过程：(累计评估次数, 当前最好的机队目标, 阶段)
    per_route_routes: list = field(default_factory=list) # 机内搜索结束时（跨机移动之前）的航线，即 P1 的解
    per_route_plans: list = field(default_factory=list)
    lb_pairs: list = field(default_factory=list)         # 下界与精确值的成对样本 (观测点数, 下界, 精确值)


def reference_t_hat(inst: Instance, groups, tours=None) -> float:
    """参考任务时长 T̂：初始分配下各机最短回路不停靠时长（含悬停）的最大值"""
    tours = tours or [shortest_tour(inst, g) for g in groups]
    v = inst.params.speed_mps
    return max(length / v + inst.hover_time(g) for g, (_, length) in zip(groups, tours))


def solve_fleet(inst: Instance, groups, eps: float, cfg: SearchConfig | None = None, tag=("fleet",),
                t_hat: float | None = None, lb_samples: int = 0) -> FleetResult:
    """机队联合优化：两阶段解 → 每机局部搜索（最短回路两个方向起步）→ 跨机移动与交换

    :param inst: 实例
    :param groups: 初始分配（每架机的 gid 列表）
    :param eps: 时长预算 ε
    :param cfg: 搜索设置
    :param tag: 随机种子标签；取 (布点, 种子, ε) 时与第三道检验的随机数流一致，可复现其结果
    :param t_hat: 参考任务时长，缺省为 reference_t_hat
    :param lb_samples: 抽样记录下界与精确值成对样本的个数（作图用，不影响结果）
    :return: 求解结果（含收敛过程与机内搜索阶段结束时的方案）
    """
    cfg = cfg or SearchConfig()
    t0 = time.perf_counter()
    tours = [shortest_tour(inst, g) for g in groups]
    if t_hat is None:
        t_hat = reference_t_hat(inst, groups, tours)
    budget = Budget(inst, eps, t_hat)
    ev = RouteEvaluator(inst, budget.cap, cfg.accelerate, lb_samples)
    # 两阶段：每架机最短回路的较好方向 + 精确停靠
    two_stage = 0.0
    best_known = []
    for tour, _ in tours:
        cands = [tour, tour[::-1]]
        for c in cands:
            if ev.length_ok(c):
                ev.touch(c)
        vals = [ev.exact(c) for c in cands]
        k = min(range(2), key=lambda i: vals[i][0])
        two_stage += vals[k][0]
        best_known.append(vals[k][0])
    # 收敛过程记录"至今最好"的机队目标，累计评估次数包含机内、跨机与跨机后的短搜索
    history = [(0, two_stage, "two_stage")]
    cum = 0
    # 每机局部搜索：从两个方向出发取较好者
    routes, vals = [], []
    for u, (tour, _) in enumerate(tours):
        best = None
        for si, start in enumerate((tour, tour[::-1])):
            def on_improve(e, v, u=u, base=cum):
                if v < best_known[u]:
                    best_known[u] = v
                    history.append((base + e, sum(best_known), "intra"))
            r, v, used, _ = route_local_search(ev, start, cfg.evals(len(tour)),
                                               random.Random(seed_of(*tag, u, si)), on_improve)
            cum += used
            if best is None or v[0] < best[1][0]:
                best = (r, v)
        routes.append(best[0])
        vals.append(best[1])
    per_route = sum(v[0] for v in vals)
    per_route_routes, per_route_plans = [list(r) for r in routes], list(vals)
    history.append((cum, per_route, "intra_end"))
    # 跨机移动：移动一个观测点或交换两点，候选限于最近的异机观测点
    all_g = [g for r in routes for g in r]
    near = {g: sorted(all_g, key=lambda x: inst.dm_tt[x][g])[1:cfg.neighbors * 3 + 1] for g in all_g}
    incs = [ev.incumbent(r, v) for r, v in zip(routes, vals)]
    rng = random.Random(seed_of(*tag, "inter"))
    inter_evals = accepted = reopt_evals = 0
    while inter_evals < cfg.inter_evals:
        where = {g: (u, i) for u, r in enumerate(routes) for i, g in enumerate(r)}
        moves = []
        for g1, (u, i) in where.items():
            cnt = 0
            for g2 in near[g1]:
                w, j = where[g2]
                if w == u:
                    continue
                moves += [("rel", u, i, w, j), ("rel", u, i, w, j + 1), ("swp", u, i, w, j)]
                cnt += 1
                if cnt >= cfg.neighbors:
                    break
        rng.shuffle(moves)
        improved = False
        for kind, u, i, w, j in moves:
            ru, rw = list(routes[u]), list(routes[w])
            if kind == "rel":
                if len(ru) <= 1:
                    continue
                rw.insert(j, ru.pop(i))
            else:
                ru[i], rw[j] = rw[j], ru[i]
            ok_u, ok_w = ev.length_ok(ru), ev.length_ok(rw)
            inter_evals += (ok_u and ev.touch(ru)) + (ok_w and ev.touch(rw))
            if ok_u and ok_w:
                threshold = vals[u][0] + vals[w][0]
                pair = ev.pair_values(ru, rw, incs[u], incs[w], threshold)
                if pair is not None and pair[0] is not None and pair[1] is not None \
                        and pair[0][0] + pair[1][0] < threshold - 1e-12:
                    # 接受后对两条航线各做一次短局部搜索
                    ru, vu, used_u, _ = route_local_search(ev, ru, cfg.reopt_evals,
                                                           random.Random(seed_of(*tag, accepted, "u")))
                    rw, vw, used_w, _ = route_local_search(ev, rw, cfg.reopt_evals,
                                                           random.Random(seed_of(*tag, accepted, "w")))
                    reopt_evals += used_u + used_w
                    routes[u], routes[w], vals[u], vals[w] = ru, rw, vu, vw
                    incs[u] = ev.incumbent(ru, vu, prev=incs[u])
                    incs[w] = ev.incumbent(rw, vw, prev=incs[w])
                    accepted += 1
                    improved = True
                    history.append((cum + inter_evals + reopt_evals, sum(v[0] for v in vals), "inter"))
                    break
            if inter_evals >= cfg.inter_evals:
                break
        if not improved:
            break
    objective = sum(v[0] for v in vals)
    history.append((cum + inter_evals + reopt_evals, objective, "end"))
    stats = dict(ev.stats, inter_evals=inter_evals, accepted=accepted, reopt_evals=reopt_evals,
                 intra_evals=cum, secs=time.perf_counter() - t0, **ev.timing())
    return FleetResult(routes, vals, objective, two_stage, per_route, t_hat, eps, stats, history=history,
                       per_route_routes=per_route_routes, per_route_plans=per_route_plans, lb_pairs=ev.lb_pairs)


def base_only(inst: Instance, groups) -> float:
    """基线 B0：每架机走最短回路（取较好方向），只在返回基地后统一上传；返回 Σ AoI/δ"""
    total = 0.0
    for g in groups:
        tour, _ = shortest_tour(inst, g)
        if not tour:
            continue
        total += min(simulate(inst, r, [(len(r), -1)]).objective for r in (tour, tour[::-1]))
    return total


def verify(inst: Instance, res: FleetResult, budget: Budget | None = None) -> dict:
    """用独立事件模拟校验求解结果：每个观测点恰好访问一次、目标一致、飞行时间与能耗不超上限"""
    budget = budget or Budget(inst, res.eps, res.t_hat)
    seen = sorted(g for r in res.routes for g in r)
    out = {"assigned_once": seen == list(range(inst.n)), "max_obj_gap": 0.0, "feasible": True}
    for r, plan in zip(res.routes, res.plans):
        if not r:
            continue
        sim = simulate(inst, r, list(plan[2]))
        out["max_obj_gap"] = max(out["max_obj_gap"], abs(sim.objective - plan[0]))
        out["feasible"] &= sim.fly_s <= budget.cap(r) + 1e-6 and sim.energy_j <= inst.params.battery_j + 1e-6
    return out
