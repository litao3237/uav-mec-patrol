"""路径模拟退火和离散粒子群基线；解码后复用与RGA相同的MEC修复。

两种方法使用任务指派和优先级编码，不调用ALNS算子或ESI强化。
比较对象是这里明确实现的变体，不声称复现某篇异构模型论文。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
import math
from time import perf_counter

from uav_mec.evaluation.task_objective import task_scalar
from typing import Any

import numpy as np

from uav_mec.domain import DiscreteSolution, Instance
from .ga_route import _Chromosome, _evaluate, _greedy_seed_chromosome, _randomized_seed


@dataclass(frozen=True)
class RouteMetaheuristicConfig:
    """固定搜索配置；时间上限为候选边界停止，不视为硬实时保证。"""

    iterations: int = 207
    population_size: int = 16
    generations: int = 12
    temperature_start_fraction: float = 0.05
    temperature_end_fraction: float = 0.0001
    inertia: float = 0.5
    cognitive_probability: float = 0.35
    social_probability: float = 0.35
    mutation_probability: float = 0.04
    max_runtime_s: float | None = None


@dataclass
class RouteMetaheuristicResult:
    """保留最优方案、实际评价次数和目标轨迹，供独立数值验收。"""

    best_solution: DiscreteSolution
    evaluations: int
    cache_hits: int
    history: list[dict[str, float]]
    diagnostics: dict[str, Any]


def _validate(config: RouteMetaheuristicConfig) -> None:
    if config.iterations < 1 or config.population_size < 2 or config.generations < 1:
        raise ValueError('搜索迭代、种群和代数必须为正，种群至少2个粒子')
    for name in ('inertia', 'cognitive_probability', 'social_probability', 'mutation_probability'):
        value = getattr(config, name)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'{name}必须位于[0,1]')
    if not 0 < config.temperature_end_fraction <= config.temperature_start_fraction < 1:
        raise ValueError('退火温度比例必须满足0<终温<=初温<1')
    if config.max_runtime_s is not None and (
        not math.isfinite(config.max_runtime_s) or config.max_runtime_s < 0
    ):
        raise ValueError('时间上限必须有限且非负')


def _score(evaluated) -> float:
    """沿用构造代理的标量惩罚；最终能耗必须由独立连续求解给出。"""
    score = evaluated.proxy.score
    if score.qos_soft:
        return task_scalar(total_tasks=len(evaluated.proxy.reduced.task_completion_s),
                           physical_violations=score.violated_constraints,
                           on_time=score.on_time_tasks,
                           normalized_lateness=score.normalized_lateness,
                           energy_j=score.total_energy_j, distance_m=score.total_distance_m)
    penalty = 0.0 if score.violated_constraints == 0 else 1e9 * (
        1 + score.violated_constraints + score.max_normalized_violation + score.sum_normalized_violation
    )
    value = float(score.total_energy_j + penalty)
    if not math.isfinite(value):
        raise ValueError('构造代理返回非有限目标，不能进入退火或粒子群更新')
    return value


def run_route_metaheuristic(instance: Instance, *, method: str, seed: int,
                            config: RouteMetaheuristicConfig | None = None) -> RouteMetaheuristicResult:
    """搜索指派及访问顺序，所有候选均经相同解码、修复和代理评分。

    DPSO的离散速度是一组带取值的基因赋值操作：保留旧速度、向个体最优
    和群体最优学习，再用小概率扰动保持多样性。优先级经排序得到离散路径。
    """
    cfg = config or RouteMetaheuristicConfig()
    _validate(cfg)
    if method not in ('SA-MR', 'DPSO-MR'):
        raise ValueError(f'未知路径基线：{method}')
    task_ids, uav_ids = sorted(instance.tasks), sorted(instance.uavs)
    if not task_ids or not uav_ids:
        raise ValueError('路径搜索至少需要一个任务和一架无人机')
    started = perf_counter()
    rng = np.random.default_rng(seed)
    cache = {}
    evaluations = hits = 0
    history = []
    base = _greedy_seed_chromosome(instance, task_ids, uav_ids)

    def expired():
        return cfg.max_runtime_s is not None and perf_counter()-started >= cfg.max_runtime_s

    def evaluate(chromosome):
        nonlocal evaluations, hits
        value, hit = _evaluate(instance, chromosome, task_ids=task_ids, uav_ids=uav_ids, cache=cache)
        evaluations += 1; hits += int(hit)
        return value, _score(value)

    def record(best_score):
        history.append({'elapsed_s': perf_counter()-started, 'evaluations': evaluations,
                        'best_proxy_objective': best_score})

    best, best_score = evaluate(base)
    record(best_score)
    if method == 'SA-MR':
        current, current_score = best, best_score
        # 固定几何降温；温标以初始目标确定，避免按最终性能反向调参。
        scale = max(1.0, abs(current_score))
        for step in range(cfg.iterations):
            if expired():break
            proposal = current.chromosome.copy()
            index = int(rng.integers(len(task_ids)))
            if rng.random() < .5:
                proposal.assignments[index] = int(rng.integers(len(uav_ids)))
            else:
                proposal.priorities[index] = float(rng.random())
            candidate, score = evaluate(proposal)
            fraction = step / max(1, cfg.iterations-1)
            temperature = scale * cfg.temperature_start_fraction * (
                cfg.temperature_end_fraction/cfg.temperature_start_fraction) ** fraction
            delta = score-current_score
            if delta <= 0 or rng.random() < math.exp(-min(745.0, delta/temperature)):
                current, current_score = candidate, score
            if score < best_score:best, best_score = candidate, score
            record(best_score)
    else:
        particles = [base.copy()]
        personal = [best]
        personal_scores = [best_score]
        velocities: list[list[tuple[int, int, float]]] = [[]]
        for index in range(1, cfg.population_size):
            if expired():break
            particle = _randomized_seed(base, num_uavs=len(uav_ids), rng=rng, fully_random=index%5==0)
            evaluated, score = evaluate(particle)
            particles.append(particle); personal.append(evaluated); personal_scores.append(score);velocities.append([])
            if score < best_score:best,best_score=evaluated,score
            record(best_score)
        for _ in range(cfg.generations):
            if expired():break
            # 同代使用冻结的群体最优，避免粒子遍历顺序成为隐式额外信息。
            global_chromosome = best.chromosome.copy()
            for index,particle in enumerate(particles):
                if expired():break
                velocity=[op for op in velocities[index] if rng.random()<cfg.inertia]
                for guide,probability in ((personal[index].chromosome,cfg.cognitive_probability),
                                          (global_chromosome,cfg.social_probability)):
                    for gene in range(len(task_ids)):
                        if particle.assignments[gene]!=guide.assignments[gene] and rng.random()<probability:
                            velocity.append((0,gene,float(guide.assignments[gene])))
                        if particle.priorities[gene]!=guide.priorities[gene] and rng.random()<probability:
                            velocity.append((1,gene,float(guide.priorities[gene])))
                proposal=particle.copy()
                for kind,gene,value in velocity:
                    if kind==0:proposal.assignments[gene]=int(value)
                    else:proposal.priorities[gene]=value
                for gene in range(len(task_ids)):
                    if rng.random()<cfg.mutation_probability:
                        proposal.assignments[gene]=int(rng.integers(len(uav_ids)))
                    if rng.random()<cfg.mutation_probability:proposal.priorities[gene]=float(rng.random())
                # 每个基因只保留最后一项速度，防止重复覆盖使历史操作无限累积。
                unique={(kind,gene):(kind,gene,value) for kind,gene,value in velocity}
                velocities[index]=list(unique.values())
                evaluated,score=evaluate(proposal)
                particles[index]=proposal
                if score<personal_scores[index]:personal[index],personal_scores[index]=evaluated,score
                if score<best_score:best,best_score=evaluated,score
                record(best_score)
    logging.getLogger(__name__).info('%s A%s完成：评价%s次，缓存命中%s，耗时%.3fs',
                                     method,seed,evaluations,hits,perf_counter()-started)
    return RouteMetaheuristicResult(deepcopy(best.solution),evaluations,hits,history,
                                    {'method':method,'seed':seed,'objective':'task_success_lex_scalar_v26' if not instance.qos_hard else 'constructive_proxy_penalty_1e9',
                                     'velocity':'assignment_operations' if method=='DPSO-MR' else None})
