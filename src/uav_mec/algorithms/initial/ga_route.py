from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from uav_mec.domain import (
    DiscreteSolution,
    Instance,
    Route,
    RouteStop,
    TaskDecision,
)
from uav_mec.evaluation.validator import validate_solution

from .greedy import build_greedy_initial_solution
from .mec_repair import (
    ProxyEvaluation,
    build_mec_assisted_initial_solution,
    evaluate_initial_proxy,
)


@dataclass(frozen=True)
class GARouteConfig:
    """Classical GA baseline for route assignment/order.

    Each task has two genes:
      1) UAV assignment index;
      2) a continuous route priority key.

    Decoding groups tasks by UAV and sorts each group by priority. The decoded
    all-local route is then passed through the deterministic MEC repair. The GA
    itself does not use ALNS destroy/repair operators or elite neighborhoods.
    """

    population_size: int = 24
    generations: int = 40
    tournament_size: int = 3
    elite_count: int = 2
    crossover_rate: float = 0.90
    assignment_mutation_rate: float = 0.04
    order_swap_rate: float = 0.04
    random_initial_fraction: float = 0.20


@dataclass
class GARouteResult:
    best_solution: DiscreteSolution
    best_proxy: ProxyEvaluation
    generations: int
    evaluations: int
    cache_hits: int
    history_best_score: list[tuple[float, ...]]
    diagnostics: dict[str, Any]


@dataclass
class _Chromosome:
    assignments: np.ndarray
    priorities: np.ndarray

    def copy(self) -> "_Chromosome":
        return _Chromosome(
            assignments=self.assignments.copy(),
            priorities=self.priorities.copy(),
        )


@dataclass
class _Evaluated:
    chromosome: _Chromosome
    solution: DiscreteSolution
    proxy: ProxyEvaluation
    signature: tuple[tuple[str, ...], ...]

    @property
    def fitness(self) -> tuple[float, ...]:
        return tuple(float(value) for value in self.proxy.score.key)


def _validate_config(config: GARouteConfig) -> None:
    if config.population_size < 4:
        raise ValueError("population_size must be at least 4")
    if config.generations <= 0:
        raise ValueError("generations must be positive")
    if not 1 <= config.tournament_size <= config.population_size:
        raise ValueError("invalid tournament_size")
    if not 1 <= config.elite_count < config.population_size:
        raise ValueError("invalid elite_count")
    for name, value in (
        ("crossover_rate", config.crossover_rate),
        ("assignment_mutation_rate", config.assignment_mutation_rate),
        ("order_swap_rate", config.order_swap_rate),
        ("random_initial_fraction", config.random_initial_fraction),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0, 1]")


def _task_ids(instance: Instance) -> list[str]:
    return sorted(instance.tasks)


def _uav_ids(instance: Instance) -> list[str]:
    return sorted(instance.uavs)


def _greedy_seed_chromosome(
    instance: Instance,
    task_ids: list[str],
    uav_ids: list[str],
) -> _Chromosome:
    seed = build_greedy_initial_solution(instance)
    task_index = {task_id: idx for idx, task_id in enumerate(task_ids)}
    uav_index = {uav_id: idx for idx, uav_id in enumerate(uav_ids)}

    assignments = np.zeros(len(task_ids), dtype=np.int64)
    priorities = np.zeros(len(task_ids), dtype=float)

    for uav_id, route in seed.routes.items():
        tasks = route.task_ids()
        denom = max(1, len(tasks))
        for pos, task_id in enumerate(tasks):
            idx = task_index[task_id]
            assignments[idx] = uav_index[uav_id]
            priorities[idx] = (pos + 1) / (denom + 1)

    return _Chromosome(assignments, priorities)


def _randomized_seed(
    seed: _Chromosome,
    *,
    num_uavs: int,
    rng: np.random.Generator,
    fully_random: bool,
) -> _Chromosome:
    n = len(seed.assignments)
    if fully_random:
        return _Chromosome(
            assignments=rng.integers(0, num_uavs, size=n, dtype=np.int64),
            priorities=rng.random(n),
        )

    child = seed.copy()
    assignment_mask = rng.random(n) < 0.08
    if np.any(assignment_mask):
        child.assignments[assignment_mask] = rng.integers(
            0,
            num_uavs,
            size=int(np.sum(assignment_mask)),
            dtype=np.int64,
        )
    child.priorities = child.priorities + rng.normal(0.0, 0.12, size=n)
    return child


def _decode_routes(
    chromosome: _Chromosome,
    *,
    task_ids: list[str],
    uav_ids: list[str],
) -> tuple[tuple[str, ...], ...]:
    groups: list[list[tuple[float, str]]] = [
        [] for _ in uav_ids
    ]
    for idx, task_id in enumerate(task_ids):
        uav_idx = int(chromosome.assignments[idx])
        groups[uav_idx].append(
            (float(chromosome.priorities[idx]), task_id)
        )

    decoded: list[tuple[str, ...]] = []
    for group in groups:
        group.sort(key=lambda item: (item[0], item[1]))
        decoded.append(tuple(task_id for _, task_id in group))
    return tuple(decoded)


def _route_solution(
    instance: Instance,
    *,
    decoded: tuple[tuple[str, ...], ...],
    uav_ids: list[str],
) -> DiscreteSolution:
    solution = DiscreteSolution(
        routes={
            uav_id: Route(
                uav_id,
                (
                    RouteStop.depot(),
                    *(
                        RouteStop.task(task_id)
                        for task_id in decoded[uav_idx]
                    ),
                    RouteStop.depot(),
                ),
            )
            for uav_idx, uav_id in enumerate(uav_ids)
        },
        contact_visits={},
        task_decisions={
            task_id: TaskDecision.local()
            for task_id in instance.tasks
        },
        metadata={
            "builder": "ga_route_decode",
            "phase": "ga_route_all_local",
        },
    )
    validate_solution(instance, solution)
    return solution


def _evaluate(
    instance: Instance,
    chromosome: _Chromosome,
    *,
    task_ids: list[str],
    uav_ids: list[str],
    cache: dict[tuple[tuple[str, ...], ...], _Evaluated],
) -> tuple[_Evaluated, bool]:
    signature = _decode_routes(
        chromosome,
        task_ids=task_ids,
        uav_ids=uav_ids,
    )
    cached = cache.get(signature)
    if cached is not None:
        return _Evaluated(
            chromosome=chromosome.copy(),
            solution=cached.solution,
            proxy=cached.proxy,
            signature=signature,
        ), True

    route_seed = _route_solution(
        instance,
        decoded=signature,
        uav_ids=uav_ids,
    )
    solution = build_mec_assisted_initial_solution(
        instance,
        base_solution=route_seed,
    )
    proxy = evaluate_initial_proxy(instance, solution)
    evaluated = _Evaluated(
        chromosome=chromosome.copy(),
        solution=solution,
        proxy=proxy,
        signature=signature,
    )
    cache[signature] = evaluated
    return evaluated, False


def _tournament(
    population: list[_Evaluated],
    *,
    size: int,
    rng: np.random.Generator,
) -> _Chromosome:
    indices = rng.choice(
        len(population),
        size=size,
        replace=False,
    )
    winner = min(
        (population[int(idx)] for idx in indices),
        key=lambda item: (item.fitness, item.signature),
    )
    return winner.chromosome.copy()


def _crossover(
    left: _Chromosome,
    right: _Chromosome,
    *,
    rate: float,
    rng: np.random.Generator,
) -> tuple[_Chromosome, _Chromosome]:
    if rng.random() >= rate:
        return left.copy(), right.copy()

    n = len(left.assignments)
    mask = rng.random(n) < 0.5

    child_a = left.copy()
    child_b = right.copy()

    child_a.assignments[mask] = right.assignments[mask]
    child_b.assignments[mask] = left.assignments[mask]
    child_a.priorities[mask] = right.priorities[mask]
    child_b.priorities[mask] = left.priorities[mask]

    return child_a, child_b


def _mutate(
    chromosome: _Chromosome,
    *,
    num_uavs: int,
    config: GARouteConfig,
    rng: np.random.Generator,
) -> None:
    n = len(chromosome.assignments)

    assignment_mask = (
        rng.random(n) < config.assignment_mutation_rate
    )
    for idx in np.flatnonzero(assignment_mask):
        current = int(chromosome.assignments[idx])
        if num_uavs <= 1:
            continue
        offset = int(rng.integers(1, num_uavs))
        chromosome.assignments[idx] = (
            current + offset
        ) % num_uavs

    expected_swaps = config.order_swap_rate * n / 2.0
    num_swaps = int(rng.poisson(expected_swaps))
    for _ in range(num_swaps):
        left, right = rng.choice(n, size=2, replace=False)
        chromosome.priorities[left], chromosome.priorities[right] = (
            chromosome.priorities[right],
            chromosome.priorities[left],
        )

    # Tiny jitter breaks priority ties without acting as a large local search.
    chromosome.priorities += rng.normal(0.0, 1.0e-6, size=n)


def run_route_ga(
    instance: Instance,
    *,
    seed: int = 100,
    config: GARouteConfig | None = None,
) -> GARouteResult:
    """Run a route-level GA followed by deterministic MEC repair."""

    cfg = config or GARouteConfig()
    _validate_config(cfg)
    rng = np.random.default_rng(seed)

    task_ids = _task_ids(instance)
    uav_ids = _uav_ids(instance)
    num_uavs = len(uav_ids)
    seed_chromosome = _greedy_seed_chromosome(
        instance,
        task_ids,
        uav_ids,
    )

    chromosomes: list[_Chromosome] = [seed_chromosome]
    random_count = int(
        round(cfg.random_initial_fraction * cfg.population_size)
    )
    random_count = min(
        cfg.population_size - 1,
        max(1, random_count),
    )

    for idx in range(1, cfg.population_size):
        chromosomes.append(
            _randomized_seed(
                seed_chromosome,
                num_uavs=num_uavs,
                rng=rng,
                fully_random=idx <= random_count,
            )
        )

    cache: dict[tuple[tuple[str, ...], ...], _Evaluated] = {}
    evaluations = 0
    cache_hits = 0

    def evaluate_population(
        items: list[_Chromosome],
    ) -> list[_Evaluated]:
        nonlocal evaluations, cache_hits
        result: list[_Evaluated] = []
        for chromosome in items:
            evaluated, cached = _evaluate(
                instance,
                chromosome,
                task_ids=task_ids,
                uav_ids=uav_ids,
                cache=cache,
            )
            if cached:
                cache_hits += 1
            else:
                evaluations += 1
            result.append(evaluated)
        result.sort(
            key=lambda item: (item.fitness, item.signature)
        )
        return result

    population = evaluate_population(chromosomes)
    history = [population[0].fitness]

    for _generation in range(cfg.generations):
        next_chromosomes = [
            item.chromosome.copy()
            for item in population[: cfg.elite_count]
        ]

        while len(next_chromosomes) < cfg.population_size:
            left = _tournament(
                population,
                size=cfg.tournament_size,
                rng=rng,
            )
            right = _tournament(
                population,
                size=cfg.tournament_size,
                rng=rng,
            )
            child_a, child_b = _crossover(
                left,
                right,
                rate=cfg.crossover_rate,
                rng=rng,
            )
            _mutate(
                child_a,
                num_uavs=num_uavs,
                config=cfg,
                rng=rng,
            )
            _mutate(
                child_b,
                num_uavs=num_uavs,
                config=cfg,
                rng=rng,
            )
            next_chromosomes.append(child_a)
            if len(next_chromosomes) < cfg.population_size:
                next_chromosomes.append(child_b)

        population = evaluate_population(next_chromosomes)
        history.append(population[0].fitness)

    best = population[0]
    best_solution = best.solution
    best_solution.metadata.update(
        {
            "builder": "route_ga_with_mec_repair",
            "ga_seed": seed,
            "ga_population_size": cfg.population_size,
            "ga_generations": cfg.generations,
            "ga_evaluations": evaluations,
            "ga_cache_hits": cache_hits,
            "ga_best_proxy_score": best.fitness,
        }
    )

    return GARouteResult(
        best_solution=best_solution,
        best_proxy=best.proxy,
        generations=cfg.generations,
        evaluations=evaluations,
        cache_hits=cache_hits,
        history_best_score=history,
        diagnostics={
            "population_size": cfg.population_size,
            "tournament_size": cfg.tournament_size,
            "elite_count": cfg.elite_count,
            "crossover_rate": cfg.crossover_rate,
            "assignment_mutation_rate": (
                cfg.assignment_mutation_rate
            ),
            "order_swap_rate": cfg.order_swap_rate,
        },
    )
