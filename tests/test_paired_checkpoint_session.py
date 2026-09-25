from __future__ import annotations

from copy import deepcopy

from uav_mec.algorithms import (
    ProxyObjectiveEvaluator,
    UavMecALNSConfig,
    UavMecALNSSession,
)
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.alns.runner import (
    _TimeScaledRecordToRecordTravel,
)
from uav_mec.instances import (
    build_paper_scale_instance,
    load_paper_scale_config,
)


def _small_instance():
    cfg = load_paper_scale_config("configs/baseline.yaml")
    return build_paper_scale_instance(
        cfg,
        num_tasks=8,
        num_uavs=2,
        num_mecs=2,
        scenario_seed=45,
    )


def test_checkpoint_forks_reproduce_same_continuation():
    instance = _small_instance()
    session = UavMecALNSSession(
        instance,
        config=UavMecALNSConfig(
            iterations=20,
            seed=100,
        ),
        evaluator=ProxyObjectiveEvaluator(),
    )

    session.run_segment(max_iterations=5)
    checkpoint = session.checkpoint()

    arm_a = checkpoint.fork()
    arm_b = checkpoint.fork()

    result_a = arm_a.run_segment(max_iterations=6)
    result_b = arm_b.run_segment(max_iterations=6)

    assert result_a.iterations == result_b.iterations == 6
    assert result_a.total_iterations == result_b.total_iterations == 11
    assert result_a.best_objective == result_b.best_objective
    assert result_a.current_objective == result_b.current_objective
    assert (
        solution_signature(result_a.best_solution)
        == solution_signature(result_b.best_solution)
    )
    assert (
        solution_signature(result_a.current_solution)
        == solution_signature(result_b.current_solution)
    )
    assert result_a.operator_pair_counts == result_b.operator_pair_counts
    assert (
        arm_a.rng.bit_generator.state
        == arm_b.rng.bit_generator.state
    )


def test_fork_is_independent_from_other_arm():
    instance = _small_instance()
    session = UavMecALNSSession(
        instance,
        config=UavMecALNSConfig(
            iterations=20,
            seed=101,
        ),
        evaluator=ProxyObjectiveEvaluator(),
    )
    session.run_segment(max_iterations=4)
    checkpoint = session.checkpoint()

    arm_a = checkpoint.fork()
    arm_b = checkpoint.fork()
    b_before = deepcopy(arm_b.rng.bit_generator.state)

    arm_a.run_segment(max_iterations=3)

    assert arm_b.iterations_completed == checkpoint.iterations_completed
    assert arm_b.rng.bit_generator.state == b_before
    assert arm_a.selector is not arm_b.selector
    assert arm_a.evaluator is not arm_b.evaluator


def test_time_scaled_rrt_checkpoint_pauses_wall_clock_progress():
    criterion = _TimeScaledRecordToRecordTravel(
        init_obj=100.0,
        start_gap=0.02,
        end_gap=0.0,
        max_runtime_s=15.0,
    )
    criterion._elapsed_offset_s = 12.0
    criterion.elapsed_s = 12.0

    paused = criterion.checkpoint_copy()

    assert paused is not criterion
    assert paused._started is None
    assert paused._elapsed_offset_s == 12.0
    assert paused.elapsed_s == 12.0
