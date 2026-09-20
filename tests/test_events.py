from __future__ import annotations

from uav_mec.evaluation import build_event_info
from uav_mec.instances import build_small_instance


def test_event_timeline_and_batches() -> None:
    instance, solution = build_small_instance()
    info = build_event_info(instance, solution)

    assert info.contact_order["U1"] == ["V11"]
    assert info.contact_order["U2"] == ["V21"]
    assert info.batch_tasks["V11"] == ["S1", "S2"]
    assert info.batch_tasks["V21"] == ["S5"]
    assert info.local_order["U1"] == ["S3"]
    assert info.local_order["U2"] == ["S4"]
    assert info.active_uav_mec_pairs == [("U1", "E1"), ("U2", "E1")]

    assert 100.0 < info.base_return_s["U1"] < 110.0
    assert 80.0 < info.base_return_s["U2"] < 95.0
