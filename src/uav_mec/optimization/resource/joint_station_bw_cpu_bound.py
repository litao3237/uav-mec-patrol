"""Rigorous *necessary* joint bandwidth/CPU feasibility test for frozen P1-R.

P1-R has fixed b_(u,e) and F_(u,e) for each UAV/MEC virtual pair:
sum_u b_(u,e) <= B_e and sum_u F_(u,e) <= C_e.

All contact upload durations satisfy tau_v >= D_v/R_v(b_(u,e))
with R_v(b)=b*log2(1+gamma_v/b). Within a UAV/MEC virtual pair,
MEC batches execute FIFO and tasks within each batch execute EDF.
For each task i and every preceding same-pair batch anchor h, the
original model implies
    d_i >= A_h(b_pair) + W_(h..i)/F_pair,
where A_h is an *optimistic* upload-complete arrival time, computing
other MEC contacts with their *full* station bandwidth. Therefore
F_pair >= max_(h,i) W_(h..i)/(d_i-A_h(b_pair)), with hard F>=1e-4.
This pair CPU lower bound is MONOTONE NONINCREASING in b_pair.

We require a necessary joint test, not a solver-dependent heuristic:
- Partition the physical station bandwidth B into N equal bins delta.
- Round every feasible REAL b_pair UP to its bin endpoint k_pair*delta.
- The sum of such rounded endpoints is < B+p*delta where p is the
  number of active UAV/MEC pairs.
- A small deterministic dynamic program MINIMIZES the total optimistic
  CPU lower demand across ALL bin choices satisfying sum(k)<=N+p.
- If even this optimistically enlarged BANDWIDTH budget demands more
  CPU than the physical MEC cap, the original fixed D is impossible.

A rounded-up b is always *larger* than the real b, hence its lower
CPU requirement can only be smaller. The enlarged bin budget can
admit otherwise impossible allocations, never exclude a true one.
Thus we can only false-*accept*, not false-*reject*, mathematically
(subject to floating-point tolerance).

Passing is NOT sufficient, and no constraint of the paper's P1-R
model or original Stage1+Stage2 acceptance is changed. This
certificate specifically needs time-constant per-pair bandwidth+CPU,
the original store-carry-contact events, FIFO/EDF, and zero releases.
Do NOT apply to a dynamically reallocating station without reproof.
"""
from __future__ import annotations

from collections import defaultdict
import math
from time import perf_counter

from uav_mec.domain import DiscreteSolution, Instance
from uav_mec.evaluation import build_event_info, gamma_mhz, visit_mec_id
from uav_mec.optimization.resource.analytic import rate_mbps
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)


def _pair_cpu_lower_at_bandwidth(
    instance: Instance,
    solution: DiscreteSolution,
    info,
    pair: tuple[str, str],
    bandwidth_mhz: float,
    *,
    full_station_min_upload: dict[str, float],
    visit_gamma_mhz: dict[str, float],
    visit_data_mbit: dict[str, float],
    deadline_optimism_s: float,
) -> tuple[float, dict | None]:
    """Optimistic CPU lower demand given an UPPER-bound share of bandwidth."""
    if bandwidth_mhz<=0.0 or deadline_optimism_s<0.0:
        raise ValueError("Invalid positive bandwidth or time optimism")
    uid,mid=pair
    arrivals={}
    completed_upload_s=0.0
    for visit in info.contact_order[uid]:
        belongs_here=visit_mec_id(instance,solution,visit)==mid
        if belongs_here:
            upload=visit_data_mbit[visit]/rate_mbps(
                bandwidth_mhz,visit_gamma_mhz[visit])
            # Tiny optimistic decrease counters rate float rounding.
            upload*=1.0-1e-12
        else:
            upload=full_station_min_upload[visit]
        completed_upload_s+=upload
        if belongs_here:
            arrivals[visit]=(
                float(info.base_contact_arrival_s[uid,visit])
                +completed_upload_s
            )
    pair_visits=[visit for visit in info.contact_order[uid] if visit in arrivals]
    work_before={}
    cumulative_work=0.0
    for visit in pair_visits:
        work_before[visit]=cumulative_work
        cumulative_work+=sum(
            instance.tasks[task].workload_gcycles
            for task in info.batch_edf_order[visit]
        )
    min_cpu=1e-4
    binding=None
    prefix_all=0.0
    for visit in pair_visits:
        for task_id in info.batch_edf_order[visit]:
            task=instance.tasks[task_id]
            prefix_all+=task.workload_gcycles
            deadline=float(task.release_s+task.deadline_s)+deadline_optimism_s
            for anchor in pair_visits:
                if anchor not in work_before:continue
                # Only earlier or same batch can be a compulsory predecessor.
                if work_before[anchor]>work_before[visit]:
                    break
                due_window=deadline-arrivals[anchor]
                required_work=prefix_all-work_before[anchor]
                if required_work<=0.0:continue
                needed=(math.inf if due_window<=0.0 else
                        required_work/due_window)
                if needed>min_cpu:
                    min_cpu=needed
                    binding={
                        "task_id":task_id,
                        "anchor_visit":anchor,
                        "current_visit":visit,
                        "prefix_work_gcycles":float(required_work),
                        "optimistic_arrival_s":float(arrivals[anchor]),
                        "deadline_s":float(task.release_s+task.deadline_s),
                        "optimistic_cpu_window_s":float(due_window),
                    }
    return min_cpu,binding


def joint_station_bw_cpu_necessary_bound(
    instance: Instance,
    solution: DiscreteSolution,
    *,
    info=None,
    queue=None,
    n_bins: int = 24,
    cpu_tolerance_ghz: float = 1e-4,
    deadline_optimism_s: float = 1e-4,
) -> dict:
    """Safe DP-lower test: reject only if EVEN OPTIMISTIC shared CPU fails.

    The number of bins trades cost vs bound strength; it does not change
    the soundness of rejection at ANY positive integer resolution.
    """
    if (not isinstance(n_bins,int) or isinstance(n_bins,bool)
            or n_bins<2 or n_bins>256):
        raise ValueError("n_bins must be an integer between 2 and 256")
    if cpu_tolerance_ghz<0.0 or deadline_optimism_s<0.0:
        raise ValueError("Margins must be nonnegative")
    t0=perf_counter()
    if info is None:
        info=build_event_info(instance,solution)
    if queue is None:
        queue=queue_aware_feasibility_precheck(instance,solution,info)

    full_upload={v:float(s) for v,s in queue.min_upload_s_by_visit.items()}
    if set(full_upload)!=set(solution.contact_visits):
        raise ValueError("Missing frozen MEC contact in optimistic queue model")
    gammas={v:gamma_mhz(instance,solution,v) for v in info.batch_tasks}
    data={v:sum(instance.tasks[task].data_mbit
                for task in tasks) for v,tasks in info.batch_tasks.items()}
    by_station=defaultdict(list)
    for pair in info.active_uav_mec_pairs:
        by_station[pair[1]].append(pair)

    stations={}
    rejected=False
    for mid,mec in instance.mecs.items():
        pairs=sorted(by_station[mid])
        if not pairs:
            stations[mid]={
                "active_pairs":[],"pair_count":0,
                "physical_bandwidth_mhz":float(mec.bandwidth_mhz),
                "physical_cpu_ghz":float(mec.cpu_ghz),
                "optimistic_min_total_cpu_ghz":0.0,
                "joint_necessary_violation":False,
                "best_optimistic_bin_allocation":{},
                "oversubscription_cpu_ghz":0.0,
                "time_cost_s":0.0,
            }
            continue
        station_start=perf_counter()
        B=float(mec.bandwidth_mhz)
        C=float(mec.cpu_ghz)
        p=len(pairs)
        step=B/n_bins
        max_rounded_bins=n_bins+p
        demand={}
        witness={}
        for pair in pairs:
            needed=[]
            bindings=[]
            for k in range(1,n_bins+1):
                b=k*step
                f,bind=_pair_cpu_lower_at_bandwidth(
                    instance,solution,info,pair,b,
                    full_station_min_upload=full_upload,
                    visit_gamma_mhz=gammas,
                    visit_data_mbit=data,
                    deadline_optimism_s=deadline_optimism_s,
                )
                needed.append(f)
                bindings.append(bind)
            demand[pair]=needed
            witness[pair]=bindings
        # Finite, exact (over the *optimistic* quantized choices) dynamic
        # program. Key is total upper-bin index consumed. Values are minimum
        # necessary static CPU share across all pairs at that bin budget.
        states={0:(0.0,())}
        for pair in pairs:
            next_states={}
            for used,(cpu_total,assignment) in states.items():
                for k,f in enumerate(demand[pair],start=1):
                    total=used+k
                    if total>max_rounded_bins:break
                    value=cpu_total+f
                    old=next_states.get(total)
                    if old is None or value<old[0]:
                        next_states[total]=(value,assignment+(k,))
            states=next_states
        if not states:
            best_cpu=math.inf
            bin_assignment=()
        else:
            best_cpu,bin_assignment=min(states.values(),key=lambda v:v[0])
        capacity_issue=(p*1e-3>B+1e-12 or p*1e-4>C+1e-12)
        impossible=capacity_issue or not math.isfinite(best_cpu)
        rejected_here=bool(impossible or best_cpu>C+cpu_tolerance_ghz)
        rejected|=rejected_here
        allocation={}
        for pair,k in zip(pairs,bin_assignment):
            idx=k-1
            allocation[f"{pair[0]}::{pair[1]}"]={
                "optimistically_rounded_bandwidth_mhz":float(k*step),
                "bin_index":k,
                "needed_static_cpu_ghz_lb":(
                    float(demand[pair][idx])
                    if math.isfinite(demand[pair][idx]) else None),
                "limiting_deadline_task":witness[pair][idx],
            }
        stations[mid]={
            "active_pairs":[f"{u}::{e}" for u,e in pairs],
            "pair_count":p,
            "physical_bandwidth_mhz":B,
            "physical_cpu_ghz":C,
            "n_bins":n_bins,
            "upper_rounded_bandwidth_budget_mhz":float(max_rounded_bins*step),
            "optimistic_min_total_cpu_ghz":(
                float(best_cpu) if math.isfinite(best_cpu) else None),
            "joint_necessary_violation":rejected_here,
            "best_optimistic_bin_allocation":allocation,
            "oversubscription_cpu_ghz":(
                max(0.0,best_cpu-C) if math.isfinite(best_cpu) else None),
            "static_minimum_pair_capacity_impossible":capacity_issue,
            "time_cost_s":perf_counter()-station_start,
        }
    return {
        "passes_joint_necessary_test":not rejected,
        "joint_necessary_reject":rejected,
        "stations":stations,
        "n_bins":n_bins,
        "cpu_tolerance_ghz":float(cpu_tolerance_ghz),
        "deadline_optimism_s":float(deadline_optimism_s),
        "joint_test_wall_s":perf_counter()-t0,
        "scope":"original_static_pair_bandwidth_CPU_FIFO_EDF_necessary_only",
        "sufficient_for_Stage1_feasibility":False,
        "numerical_solver_oracle_calls":0,
    }
