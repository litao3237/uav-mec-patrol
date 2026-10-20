"""原始反例回归，确保状态为 optimal 的违约解不能污染精英和消融。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from uav_mec.algorithms import ProxyObjectiveEvaluator, Stage1CVXObjectiveOracle
from uav_mec.algorithms.alns import UavMecState
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.alns.problem_operators import ProblemOperatorConfig, contact_mode_intensification
from uav_mec.analysis.experiment_snapshot import restore_instance, restore_solution
from uav_mec.analysis.stage1_acceptance import qualify_stage1_result, stage1_is_qualified
from uav_mec.optimization.resource.result import ResourceSolveResult


@pytest.fixture(scope="module")
def cases():
    data = json.loads((Path(__file__).parent / "fixtures/esi_stage1_acceptance_regression.json").read_text(encoding="utf-8"))
    return [(restore_instance(c["instance"]), restore_solution(c["solution"]),
             ResourceSolveResult(**c["result"])) for c in data["cases"]]


def test_real_optimal_candidate_is_rejected_with_original_evidence(cases):
    instance, solution, original = cases[1]
    result = qualify_stage1_result(instance, solution, original)
    assert original.status == "optimal"
    assert result.status == "invalid_residual"
    assert result.diagnostics["stage1_solver_status"] == "optimal"
    assert not stage1_is_qualified(result)
    audit = result.diagnostics["stage1_acceptance_audit"]
    upload = next(c for c in audit["saved"]["constraints"] if c["id"] == "upload_epi::G_U5_3")
    deadline = next(c for c in audit["reconstructed"]["constraints"] if c["id"] == "deadline::S12")
    assert upload["violation"] == pytest.approx(1.050931345)
    assert deadline["violation"] == pytest.approx(2.600863951)
    assert result.stage1_values == original.stage1_values
    assert result.energy_stage1_j == original.energy_stage1_j


def test_invalid_baseline_does_not_start_elite_search(cases):
    instance, solution, original = cases[2]
    oracle = Stage1CVXObjectiveOracle()
    baseline = oracle.prime(instance, solution, original)
    assert not stage1_is_qualified(baseline)
    state = UavMecState(instance, solution, ProxyObjectiveEvaluator())
    final, stats = contact_mode_intensification(state, config=ProblemOperatorConfig(), objective=oracle)
    assert final.solution == solution
    assert stats["rounds"] == stats["candidates_evaluated"] == 0
    assert stats["skipped"] == "initial_objective_not_finite"


def test_invalid_lower_energy_never_replaces_qualified_incumbent(cases, monkeypatch):
    instance, baseline, base_result = cases[0]
    _, candidate, candidate_result = cases[1]

    class FrozenCandidateSolver:
        """返回真实故障快照，测试不依赖再次求解时的机器差异。"""
        calls = 0

        def solve(self, instance, solution, info=None):
            assert solution_signature(solution) == solution_signature(candidate)
            self.calls += 1
            return deepcopy(candidate_result)

    solver = FrozenCandidateSolver()
    oracle = Stage1CVXObjectiveOracle(solver=solver)
    assert stage1_is_qualified(oracle.prime(instance, baseline, base_result))
    monkeypatch.setattr("uav_mec.algorithms.alns.problem_operators._structural_elite_candidates",
                        lambda *args, **kwargs: [("route_compute_relocate::regression", candidate)])
    state = UavMecState(instance, baseline, ProxyObjectiveEvaluator())
    final, stats = contact_mode_intensification(state, config=ProblemOperatorConfig(), objective=oracle)
    assert final.solution == baseline
    assert stats["improvements"] == 0
    assert oracle(instance, candidate) == float("inf")
    assert solver.calls == 1  # 已拒绝的候选也缓存，不能在重复请求时变成合格值。
    assert oracle.solve_records[0]["qualified"] is False
    assert oracle.solve_records[0]["solver_status"] == "optimal"


@pytest.mark.parametrize("change,reason", [
    ("missing", "missing_stage1_values"),
    ("nan", "nonfinite_stage1_energy"),
    ("energy", "stage1_energy_mismatch"),
])
def test_missing_or_inconsistent_energy_cannot_be_accepted(cases, change, reason):
    instance, solution, original = cases[0]
    result = deepcopy(original)
    if change == "missing":
        result.stage1_values = {}
    elif change == "nan":
        result.energy_stage1_j = float("nan")
    else:
        result.energy_stage1_j -= 1000
    qualified = qualify_stage1_result(instance, solution, result)
    assert not stage1_is_qualified(qualified)
    assert qualified.diagnostics["stage1_acceptance_reason"] == reason


def test_reconstructed_success_does_not_hide_invalid_saved_variables(cases):
    instance, solution, original = cases[0]
    bad = deepcopy(original)
    key = next(iter(bad.stage1_values["tau_s"]))
    bad.stage1_values["tau_s"][key] = 0.0
    result = qualify_stage1_result(instance, solution, bad)
    audit = result.diagnostics["stage1_acceptance_audit"]
    assert audit["reconstructed"]["passed"]
    assert not audit["saved"]["passed"]
    assert not stage1_is_qualified(result)


def test_frozen_qualified_baseline_is_not_resolved_or_overwritten(cases):
    instance, solution, result = cases[0]
    oracle = Stage1CVXObjectiveOracle()
    assert stage1_is_qualified(oracle.prime(instance, solution, result))
    assert oracle(instance, solution) == result.energy_stage1_j
    assert oracle.calls == 0 and oracle.seeded_results == 1
    with pytest.raises(ValueError, match="拒绝覆盖"):
        oracle.prime(instance, solution, result)
