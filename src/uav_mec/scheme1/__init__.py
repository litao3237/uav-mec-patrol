"""方案一：火场态势侦察中的多无人机路线与上传停靠

- params：从 v27 冻结配置推出的模型参数
- instance：实例、预计算矩阵与扇形、火线两种实例生成器
- stops：给定顺序的精确停靠动态规划、时间价格下界与独立事件模拟
- tsp：每架机的最短回路
- search：以精确停靠评估的机队局部搜索（机内 + 跨机邻域）与基线
"""

from .instance import Instance, Task, make_instance, seed_of
from .params import Scheme1Params, candidate_points, load_scheme1_params, params_from_v27, script_constants
from .search import (Budget, FleetResult, RouteEvaluator, SearchConfig, base_only, reference_t_hat,
                     route_local_search, solve_fleet, verify)
from .stops import best_lambda, exact_stops, lambda_dp, pareto_front, simulate
from .tsp import held_karp, shortest_tour

__all__ = [
    "Budget", "FleetResult", "Instance", "RouteEvaluator", "Scheme1Params", "SearchConfig", "Task",
    "base_only", "best_lambda", "candidate_points", "exact_stops", "held_karp", "lambda_dp",
    "load_scheme1_params", "make_instance", "params_from_v27", "pareto_front", "reference_t_hat",
    "route_local_search", "script_constants", "seed_of", "shortest_tour", "simulate", "solve_fleet", "verify",
]
