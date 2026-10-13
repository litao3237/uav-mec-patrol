"""P24 tests: source immutability, complete legal D, deterministic no-model scoring."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from run_p24_postswap_offload_redistribution import (
    P24_POLICIES, _audit_candidate, _key, _one_task_offload_moves,
)
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation.validator import validate_solution
from uav_mec.instances.small import build_small_instance


def test_legal_redistribution_preserves_original_snapshot_and_complete_tasks():
    instance, source = build_small_instance()
    sha = content_hash(source)
    initial_contacts = len(source.contact_visits)
    candidates, skipped = _one_task_offload_moves(instance, source)
    assert candidates
    assert isinstance(skipped, dict)
    assert content_hash(source) == sha
    labels = []
    for label, tid, candidate in candidates:
        labels.append(label)
        validate_solution(instance, candidate)
        assert content_hash(candidate) != sha
        assert tid in source.task_decisions
        assert set(candidate.task_decisions) == set(source.task_decisions)
        assert len(candidate.contact_visits) <= initial_contacts + 1
    assert any(x.startswith("local::") for x in labels)
    assert len(labels) == len(set(labels))


def test_all_policies_rank_same_audited_physical_pool():
    instance, source = build_small_instance()
    available, _ = _one_task_offload_moves(instance, source)
    pool = []
    for label, tid, candidate in available:
        pool.append({
            "label": label,
            "task_workload_gcycles": instance.tasks[tid].workload_gcycles,
            "audit": _audit_candidate(instance, candidate),
        })
    assert len(P24_POLICIES) == 3
    for policy in P24_POLICIES:
        ranked = sorted(pool, key=lambda item: _key(item, policy))
        assert len(ranked) == len(pool)
        assert {x["label"] for x in ranked} == {x["label"] for x in pool}
        assert sorted(pool, key=lambda item: _key(item, policy)) == ranked
