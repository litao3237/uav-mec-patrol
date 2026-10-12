"""P11 global physical INSTANCE necessary feasibility bounds, independent of D.

Unlike P2/P5 which reject a *fixed ALNS discrete D*, these
inequalities use only original physical tasks, UAV/MEC hardware, depot,
deadlines and geometry. A violation CERTIFIES no route/offloading choice
can satisfy the original problem. Passing DOES NOT prove feasibility.

1. Per-task earliest optimistic collection+computing:
    min_u ||depot-task||/v_u + collect_i + work_i/max(all CPU rates)
    <= deadline_i.
   Ignore all earlier tasks, all uploading, contention: optimistic.

2. Pooled computational energetic reasoning on arbitrary interval [a,b]:
   Every task with r_i^LB >= a and d_i <= b must execute all its
   W_i Gcycles inside [a,b], because no real compute can begin before
   its earliest-possible completed collection r_i^LB. All UAV-local
   and all MEC CPUs pooled as if infinitely shareable: total rate
   C_pool=sum_u local_cpu_u+sum_e mec_cpu_e. Hence
     sum W_i <= C_pool*(b-a).
   Evaluate all distinct lower-release times a and deadlines b;
   a=0 included. This is still an optimistic necessary bound.

3. Deadline-prefix geometric workload:
   Every task with d_i<=t must have been VISITED/COLLECTED by t.
   The union of route prefixes started at the common depot connects
   all such points, so their total flight length >= Euclidean MST of
   depot and that prefix. Flight rate at most v_max and collections
   cannot occur concurrently on a single UAV. All N UAVs can
   optimistically work in parallel, so:
     MST_length/v_max + sum(collect_i in prefix) <= N*t.
   This gives a global route-service lower-bound certificate even
   without any allocation to UAVs. Multiple tasks can share a point;
   MST handles duplicate coordinates.

4. The cycle version of (3) includes ALL tasks and requires total
   flight+collection <= N*cycle_s. This ignores the mandatory return
   flight and all contact/upload time, therefore remains optimistic.

The proofs rely on tasks each being collected and processed once,
shared depot and original time units. Do not use if a future model
allows multicast, parallel subdivision of collection, processing
before collection, or departure from separate depots without reproof.

These simple necessary bounds are established energetic/scheduling
ideas, NOT a novel mathematical contribution. They are used to
separate global physical impossible instances from weak ALNS searches.
"""
from __future__ import annotations

import math
from typing import Any

from uav_mec.domain import Instance
from uav_mec.evaluation.geometry import distance


def _euclidean_mst_length(points):
    """Prim O(n²) in metres, including origin even if zero tasks."""
    if not points:return 0.0
    n=len(points)
    seen=[False]*n
    d=[math.inf]*n
    d[0]=0.0
    total=0.0
    for _ in range(n):
        v=min((j for j in range(n) if not seen[j]),key=d.__getitem__)
        if not math.isfinite(d[v]):raise ValueError("Invalid Euclidean geometry")
        seen[v]=True
        total+=d[v]
        for j in range(n):
            if not seen[j]:
                cost=distance(points[v],points[j])
                if cost<d[j]:d[j]=cost
    return total


def global_physical_necessary_bounds(instance:Instance,*,tol_rel=1e-9)->dict:
    if tol_rel<0 or not math.isfinite(tol_rel):
        raise ValueError("Tolerance must be nonnegative/finite")
    tasks=list(instance.tasks.items())
    if not tasks or not instance.uavs:
        raise ValueError("Require tasks and UAV resources")
    rates=[float(u.local_cpu_ghz) for u in instance.uavs.values()]
    rates.extend(float(e.cpu_ghz) for e in instance.mecs.values())
    if any(r<=0 for r in rates):raise ValueError("Nonpositive original CPU capacity")
    C_pool=sum(rates)
    fastest=max(rates)
    uavs=len(instance.uavs)
    vmax=max(float(u.speed_mps) for u in instance.uavs.values())
    depot=instance.depot_xy
    if vmax<=0:raise ValueError("Nonpositive UAV max speed")
    rows=[]
    for tid,t in tasks:
        r=min(
            distance(depot,(t.x,t.y))/u.speed_mps
            for u in instance.uavs.values()
        )+t.collect_s
        d=t.release_s+t.deadline_s
        lb=r+t.workload_gcycles/fastest
        rows.append({
            "id":tid,
            "earliest_collect_complete_s":float(r),
            "deadline_absolute_s":float(d),
            "optimistic_single_task_end_s":float(lb),
            "work_gcycles":float(t.workload_gcycles),
            "collect_s":float(t.collect_s),
            "xy":(float(t.x),float(t.y)),
        })
    bad=[r for r in rows if r["optimistic_single_task_end_s"]>
         r["deadline_absolute_s"]+tol_rel*max(1.0,r["deadline_absolute_s"])]
    # Full energetic necessary bound using all interval endpoint events.
    releases=sorted({0.0,*[r["earliest_collect_complete_s"] for r in rows]})
    deadlines=sorted({r["deadline_absolute_s"] for r in rows})
    worst_compute={
        "demand_ratio":0.0,
        "interval_start_s":None,"interval_end_s":None,
        "required_cpu_work_gcycles":0.0,
        "available_cpu_work_gcycles":0.0,
        "tasks_in_interval":0,
        "violates":False,
    }
    for a in releases:
        for b in deadlines:
            if b<=a:continue
            forced=[r for r in rows
                    if r["earliest_collect_complete_s"]>=a
                    and r["deadline_absolute_s"]<=b]
            demand=sum(x["work_gcycles"] for x in forced)
            supply=C_pool*(b-a)
            ratio=demand/supply if supply>0 else math.inf
            if ratio>worst_compute["demand_ratio"]:
                worst_compute={
                    "demand_ratio":float(ratio),
                    "interval_start_s":float(a),
                    "interval_end_s":float(b),
                    "required_cpu_work_gcycles":float(demand),
                    "available_cpu_work_gcycles":float(supply),
                    "tasks_in_interval":len(forced),
                    "violates":ratio>1.+tol_rel,
                }
    worst_geometry={
        "demand_ratio":0.0,"deadline_s":None,"tasks_before_deadline":0,
        "mst_distance_m":0.0,"total_collect_s":0.0,
        "necessary_uav_service_s":0.0,
        "available_uav_service_s":0.0,
        "violates":False,
    }
    for t in deadlines:
        prefix=[r for r in rows if r["deadline_absolute_s"]<=t]
        min_distance=_euclidean_mst_length(
            [depot]+[r["xy"] for r in prefix])
        min_service=min_distance/vmax+sum(r["collect_s"] for r in prefix)
        possible=uavs*t
        ratio=min_service/possible if possible>0 else math.inf
        if ratio>worst_geometry["demand_ratio"]:
            worst_geometry={
                "demand_ratio":float(ratio),
                "deadline_s":float(t),
                "tasks_before_deadline":len(prefix),
                "mst_distance_m":float(min_distance),
                "total_collect_s":float(sum(r["collect_s"] for r in prefix)),
                "necessary_uav_service_s":float(min_service),
                "available_uav_service_s":float(possible),
                "violates":ratio>1.+tol_rel,
            }
    route_mst=_euclidean_mst_length(
        [depot]+[r["xy"] for r in rows])
    cycle_service=route_mst/vmax+sum(r["collect_s"] for r in rows)
    cycle_capacity=uavs*instance.cycle_s
    cycle={
        "mst_distance_m":float(route_mst),
        "minimum_flight_collection_s":float(cycle_service),
        "total_available_uav_cycle_s":float(cycle_capacity),
        "demand_ratio":float(cycle_service/cycle_capacity),
        "violates":cycle_service>cycle_capacity*(1.+tol_rel),
    }
    any_conflict=bool(
        bad or worst_compute["violates"] or
        worst_geometry["violates"] or cycle["violates"])
    return {
        "globally_infeasible_certified":any_conflict,
        "scope":"entire_original_physical_instance_not_fixed_D",
        "sufficient_for_global_feasibility":False,
        "assumes_common_depot_single_task_collection_and_processing":True,
        "optimistically_pooled_all_local_and_MEC_cpu_ghz":float(C_pool),
        "UAV_count":uavs,
        "single_task_necessary":{
            "impossible_count":len(bad),
            "first_bad_tasks":[x["id"] for x in bad[:10]],
            "worst_end_over_deadline":max(
                r["optimistic_single_task_end_s"]/r["deadline_absolute_s"]
                for r in rows),
        },
        "pooled_CPU_energetic_interval":worst_compute,
        "UAV_collection_MST_deadline_prefix":worst_geometry,
        "UAV_collection_MST_patrol_cycle":cycle,
        "proof_status":"necessary_conditions_with_ignore_all_communication_and_queueing",
    }
