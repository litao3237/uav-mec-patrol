"""保证受限搜索仍能到达允许变化的结构，避免仅过滤通用算子导致对照退化。"""
from pathlib import Path
import sys

from uav_mec.algorithms import ProxyObjectiveEvaluator, UavMecALNSConfig
from uav_mec.analysis.mechanism_controls import FrozenDecisions, GuardedEvaluator
from uav_mec.instances import build_small_instance

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from innovation_control_search import run_controlled_exploration


def test_fixed_route_has_direct_structural_search_entry():
    instance, initial = build_small_instance()
    frozen = FrozenDecisions.from_initial("fixed_task_route", initial)
    evaluator = GuardedEvaluator(ProxyObjectiveEvaluator(), frozen, label="screened_proxy")
    result, details = run_controlled_exploration(
        instance, initial, UavMecALNSConfig(seed=100, iterations=100), evaluator, 30.0,
        max_iterations=10,
    )
    assert frozen.allows(result.best_solution)
    assert details["direct_structure_records"]
    assert evaluator.summary()["unique_admissible_structures"] > 1
