"""离线跨平台复核只容忍舍入末位，不能容忍状态、约束或实质数值变化。"""
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from aggregate_innovation_mechanism import assert_audit_equivalent  # noqa: E402


def test_platform_rounding_does_not_invalidate_archive():
    archived = {"passed": True, "value": 4.668082130976359e-5,
                "constraints": [{"id": "upload", "normalized_violation": 0.08487422056320652}]}
    recomputed = {"passed": True, "value": 4.668082130998563e-5,
                  "constraints": [{"id": "upload", "normalized_violation": 0.08487422056361023}]}
    assert_audit_equivalent(recomputed, archived)


@pytest.mark.parametrize("recomputed", [
    {"passed": False, "residual": 0.5, "id": "upload"},
    {"passed": True, "residual": 0.5001, "id": "upload"},
    {"passed": True, "residual": 0.5, "id": "deadline"},
    {"passed": True, "residual": float("nan"), "id": "upload"},
    {"passed": True, "residual": 0.5},
])
def test_material_archive_changes_are_rejected(recomputed):
    with pytest.raises(AssertionError):
        assert_audit_equivalent(recomputed, {"passed": True, "residual": 0.5, "id": "upload"})


@pytest.mark.parametrize("maximum,accepted", [(8.1e-13, True), (0.5, False)])
def test_worst_constraint_label_can_only_change_in_near_zero_tie(maximum, accepted):
    archived = {"passed": True, "max_normalized_violation": maximum,
                "worst_constraint": "nonnegative", "constraints": [{"id": "upload"}, {"id": "nonnegative"}]}
    recomputed = {**archived, "worst_constraint": "upload"}
    if accepted:
        assert_audit_equivalent(recomputed, archived)
    else:
        with pytest.raises(AssertionError):
            assert_audit_equivalent(recomputed, archived)


def test_near_zero_tie_cannot_invent_constraint_identifier():
    archived = {"passed": True, "max_normalized_violation": 0.0,
                "worst_constraint": "upload", "constraints": [{"id": "upload"}]}
    with pytest.raises(AssertionError):
        assert_audit_equivalent({**archived, "worst_constraint": "unknown"}, archived)
