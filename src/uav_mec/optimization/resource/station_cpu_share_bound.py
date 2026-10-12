"""Necessary shared-station CPU test for the *fixed* P1-R resource model.

Rationale (and proof sketch):
- Stage1 assigns a time-constant F[(UAV,MEC)] to each active virtual pair,
  and SUM(F_pair) <= station CPU capacity; no per-time redistribution.
- Each pair's batches execute FIFO; tasks within each batch execute EDF.
- For any task j in that compulsory order, all earlier jobs in the same
  pair must finish no later than j. The first batch cannot begin before
  its optimistic upload-complete arrival a_pair.
- Therefore deadline(j) >= a_pair + prefix_work(j)/F_pair, whence
  F_pair >= prefix_work(j)/(deadline(j)-a_pair).
- Summing the *maximum* necessary F_pair over a station yields a safe
  necessary station CPU-capacity test.

This is NOT a generic energetic-reasoning theorem for time-varying
processors. It relies critically on the paper's fixed per-pair F variable,
compulsory FIFO/EDF order, and release_s=0 semantics. Passing is NOT proof
of continuous Stage1 feasibility; numerical 'infeasible' alone is not a
formal certificate. Never silently replace the official feasibility test.
"""
from __future__ import annotations

import math
from collections import defaultdict

from uav_mec.domain import Instance, DiscreteSolution
from uav_mec.evaluation import build_event_info, visit_mec_id
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


def station_cpu_share_necessary_bound(
    instance: Instance,
    solution: DiscreteSolution,
    *,
    info=None,
    queue=None,
    tolerance_ghz: float = 1e-4,
) -> dict:
    if tolerance_ghz < 0:
        raise ValueError("Negative certificate tolerance")
    if info is None:
        info = build_event_info(instance, solution)
    if queue is None:
        queue = queue_aware_feasibility_precheck(instance, solution, info)
    if set(queue.min_upload_s_by_visit) != set(solution.contact_visits):
        raise ValueError("Expected all frozen MEC upload visits")

    by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    first_batch: dict[tuple[str, str], str] = {}
    for uid, visits in info.contact_order.items():
        for vid in visits:
            key = (uid, visit_mec_id(instance, solution, vid))
            by_pair[key].append(vid)
            first_batch.setdefault(key, vid)
    if set(by_pair) != set(info.active_uav_mec_pairs):
        raise ValueError("Mismatch between event-info resource pairs")

    pair_rows = {}
    per_station = defaultdict(list)
    for (uid, mid), visits in by_pair.items():
        first = first_batch[uid, mid]
        optimistic_first_start = float(queue.earliest_batch_start_lb_s[first])
        # min 1e-4 GHz is an *actual hard lower bound* in the frozen P1-R.
        minimum_f = 1e-4
        prefix = 0.0
        binding = None
        impossible_window = False
        ntasks = 0
        for vid in visits:
            for tid in info.batch_edf_order[vid]:
                ntasks += 1
                t = instance.tasks[tid]
                prefix += t.workload_gcycles
                remaining = t.release_s + t.deadline_s - optimistic_first_start
                if remaining <= 0.0 and prefix > 0.0:
                    impossible_window = True
                    need = math.inf
                else:
                    need = prefix / max(remaining, 1e-300)
                if need > minimum_f:
                    minimum_f = need
                    binding = {
                        "task_id": tid,
                        "visit_id": vid,
                        "deadline_s": float(t.release_s + t.deadline_s),
                        "prefix_work_gcycles": float(prefix),
                        "first_batch_start_lower_s": optimistic_first_start,
                        "available_compute_window_s": float(remaining),
                    }
        station_cpu = float(instance.mecs[mid].cpu_ghz)
        key = f"{uid}::{mid}"
        pair_rows[key] = {
            "pair": [uid, mid],
            "needed_cpu_ghz_lb": minimum_f if math.isfinite(minimum_f) else None,
            "impossible_before_first_batch": impossible_window,
            "deadline_binding": binding,
            "n_offloaded_tasks": ntasks,
            "station_id": mid,
            "cpu_station_capacity_ghz": station_cpu,
        }
        per_station[mid].append((minimum_f, key))
    stations={}
    rejected = False
    for mid,mec in instance.mecs.items():
        required=sum(n for n,_ in per_station[mid])
        over = not math.isfinite(required) or required > mec.cpu_ghz + tolerance_ghz
        rejected |= over
        stations[mid]={
            "capacity_ghz": float(mec.cpu_ghz),
            "required_cpu_lb_ghz": required if math.isfinite(required) else None,
            "min_cpu_pressure_ratio": required/mec.cpu_ghz if math.isfinite(required) else None,
            "necessary_capacity_violation": bool(over),
            "pairs": [name for _,name in per_station[mid]],
            "excess_cpu_ghz_lb": max(0.,required-mec.cpu_ghz)
                if math.isfinite(required) else None,
        }
    return {
        "passes_necessary_cpu_share_test": not rejected,
        "certified_cpu_share_failure": bool(rejected),
        "pair_demands": pair_rows,
        "stations": stations,
        "scope": "frozen_stage1_static_uav_mec_pair_cpu_only",
        "is_sufficient_for_feasibility": False,
    }
