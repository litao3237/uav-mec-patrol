"""P8 paired source-replay pilot: original ALNS versus queue-guided ALNS.

Only previously INSPECTED K80 S89-S96 cases. Equal *100 iterations*,
same route-only/MEC initial solution, source physical instance and nested
random seed, all original operators, RRT and P1-R/Stage2 audit unchanged.
The baseline arm must reproduce original frozen B-ALNS SHA256 exactly.

The intended scientific question is whether guided evaluation changes
the distribution of structures produced DURING ALNS exploration,
rather than just postprocessing the final failed endpoint.

This pilot is NOT a matched wall time full-ALNS benchmark; keep true
search wall, observer time, old CVX inside exploration, and final
Stage1/2 time explicitly separated. No extra archive CVX is counted
as algorithm improvement, and no single candidate's optimistic precheck
pass is misclassified as Stage1/Stage2 strict feasible.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from queue_guided_alns_evaluator import (
    POLICIES,QueueGuidedObjectiveEvaluator)
from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
    UavMecALNSConfig,build_greedy_initial_solution,
    build_mec_assisted_initial_solution,run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,write_json,
)
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

ARMS=("original",)+POLICIES
# These cases were already observed during P7. No independent
# generalization claims from this pilot.
SELECTED=(
    (89,"deadline_x0p9",128),
    (91,"compute_x1p5",128),
    (93,"compute_x1p5",130),
    (93,"baseline",129),
    (94,"compute_x1p5",129),
    (95,"compute_x2p0",130),
    (96,"deadline_x0p9",130),
)


class P8ReadOnlyFunnel:
    """Measure SAME levels on ALL arms, returning evaluator scalar exactly."""
    def __init__(self,evaluator):
        self.evaluator=evaluator
        self.seen=set()
        self.counters=Counter()
        self.observer_wall_s=0.0
        self.initial_best_normalized_gap=None
        self.best_visited_gap=float("inf")
        self.maximal_cpu_pruned=0

    def __call__(self,instance,solution):
        value=float(self.evaluator(instance,solution))
        self.counters["objective_calls"]+=1
        signature=solution_signature(solution)
        if signature in self.seen:return value
        self.seen.add(signature)
        t0=perf_counter()
        info=build_event_info(instance,solution)
        q=queue_aware_feasibility_precheck(instance,solution,info)
        self.counters["unique_visited"]+=1
        excess=sum(
            max(0.,q.task_completion_lb_s[tid]-(task.release_s+task.deadline_s))
            /max(1.,task.deadline_s)
            for tid,task in instance.tasks.items())
        if self.initial_best_normalized_gap is None:
            self.initial_best_normalized_gap=excess
        self.best_visited_gap=min(self.best_visited_gap,excess)
        if not q.feasible:
            self.counters["queue_necessary_failed"]+=1
            self.observer_wall_s+=perf_counter()-t0
            return value
        self.counters["queue_necessary_pass"]+=1
        cpu=station_cpu_share_necessary_bound(
            instance,solution,info=info,queue=q)
        if cpu["certified_cpu_share_failure"]:
            self.counters["CPU_share_necessary_failed"]+=1
            self.observer_wall_s+=perf_counter()-t0
            return value
        self.counters["CPU_share_necessary_pass"]+=1
        joint=joint_station_bw_cpu_necessary_bound(
            instance,solution,info=info,queue=q,n_bins=48)
        if joint["joint_necessary_reject"]:
            self.counters["joint_bw_cpu_necessary_failed"]+=1
        else:
            self.counters["joint_bw_cpu_necessary_pass"]+=1
        self.observer_wall_s+=perf_counter()-t0
        return value

    def summary(self):
        return {
            "counters":dict(self.counters),
            "first_state_normalized_deadline_excess":self.initial_best_normalized_gap,
            "lowest_visited_normalized_deadline_excess":self.best_visited_gap,
            "observer_wall_s":self.observer_wall_s,
            "underlying_evaluator":(
                self.evaluator.summarize() if
                hasattr(self.evaluator,"summarize") else {
                    "name":"ScreenedProxyObjectiveEvaluator",
                    "stats":{k:getattr(self.evaluator.stats,k)
                             for k in ("calls","cache_hits","feasible_calls",
                                       "infeasible_calls","cvx_refinements",
                                       "precheck_rejects")},
                    "solver_statuses":dict(
                        self.evaluator.stats.resource_status_counts),
                }),
        }


def _run_one(inst,initial,seed,arm):
    ev=(ScreenedProxyObjectiveEvaluator() if arm=="original"
        else QueueGuidedObjectiveEvaluator(policy=arm))
    observer=P8ReadOnlyFunnel(ev)
    oracle=Stage1CVXObjectiveOracle()
    start=perf_counter()
    result=run_uav_mec_hybrid_alns(
        inst,initial_solution=deepcopy(initial),
        config=UavMecALNSConfig(
            iterations=100,seed=seed,
            enable_problem_operators=False,
        ),
        evaluator=observer,
        elite_rounds=2,elite_oracle=oracle,
    )
    search_wall_s=perf_counter()-start
    audits={}
    for m,solution in (
        ("B",result.exploration.best_solution),
        ("ESI",result.best_solution),
    ):
        snap=finalize(
            inst,solution,method=f"P8_{arm}_{m}",
            seed=seed,initialization_s=0.,search_s=search_wall_s,
            diagnostics={"pilot_arm":arm,"strict_source":"original_P1R_Stage2"},
        )
        audits[m]={
            "solution_sha256":content_hash(solution),
            "stage1_status":snap["resources"].diagnostics.get("stage1_status"),
            "stage1_strict":bool(snap["stage1"]["qualified"]),
            "stage2_strict":bool(snap["stage2"]["qualified"]),
            "both_strict":bool(snap["stage1"]["qualified"] and snap["stage2"]["qualified"]),
            "strict_energy_j":(
                float(snap["resources"].energy_stage1_j)
                if snap["stage1"]["qualified"] and snap["stage2"]["qualified"] else None),
            "stage1_stage2_audit_wall_s":float(
                snap["timing"]["resource_recompute_s"]+
                snap["timing"]["independent_audit_s"]),
        }
    init_sha=content_hash(initial)
    return {
        "arm":arm,
        "initial_solution_sha256":init_sha,
        "B":audits["B"],"ESI":audits["ESI"],
        "ESI_elite_skipped":result.elite_stats.get("skipped"),
        "elite_extra_CVX_calls":oracle.calls,
        "elite_CVX_solve_records":oracle.solve_records,
        "B_proxy_best_scalar":result.exploration.best_objective,
        "ESI_elite_stats":result.elite_stats,
        "funnel":observer.summary(),
        "search_wall_s":search_wall_s,
        "full_end_to_end_wall_s":(
            search_wall_s+
            audits["B"]["stage1_stage2_audit_wall_s"]+
            audits["ESI"]["stage1_stage2_audit_wall_s"]),
    }


def run(input_file:Path,output:Path,requested):
    if output.exists():raise FileExistsError("Refuse overwrite P8 frozen evidence")
    raw=json.loads(input_file.read_text(encoding="utf-8"))
    p=raw["protocol"]
    scene=int(p["independent_scenario_seed"])
    if not raw.get("complete") or p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1":
        raise ValueError("Require completed original B/ESI physical source")
    controls={(r["profile"],int(r["seed"]),r["method"]):r
              for r in raw["rows"]}
    requested=[(profile,int(seed)) for profile,seed in requested]
    if not requested or any((scene,profile,seed) not in SELECTED
                            for profile,seed in requested):
        raise ValueError("Only pre-registered inspected P7 cases")
    payload={
        "complete":False,
        "protocol":{
            "id":"P8_original_ALNS_100iteration_queue_guided_evaluator_pilot_v1",
            "scene":scene,"original_source_sha256":content_hash(raw),
            "arms":list(ARMS),"fixed_ALNS_iterations":100,
            "same_frozen_route_MEC_seed":True,
            "same_ALNS_destroy_repair_and_RRT":True,
            "same_original_hybrid_elite_2_rounds":True,
            "strict_stage1_stage2_independent_audit":True,
            "all_samples_are_previous_P7_development":True,
            "read_only_observer_on_all_arms":True,
            "NOT_same_total_wall_time_budget":True,
            "method_alpha_parameters_pre_registered":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,payload)
    for profile,seed in requested:
        reference=controls[profile,seed,"B-ALNS"]
        inst=restore_instance(raw["profiles"][profile]["instance"])
        if content_hash(inst)!=raw["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Original physical profile SHA mismatch")
        initial=build_mec_assisted_initial_solution(
            inst,base_solution=build_greedy_initial_solution(inst))
        original_sha=content_hash(initial)
        expected_init=(reference.get("diagnostics") or {}).get("initial_sha256")
        if expected_init is not None and original_sha!=expected_init:
            raise RuntimeError("Original initial state fingerprint changed")
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "original_B_sha256":reference["solution_sha256"],
            "original_B_status":((reference.get("resources") or {}).get(
                "diagnostics") or {}).get("stage1_status"),
            "initial_sha256":original_sha,
            "arms":{},
        }
        payload["rows"].append(row)
        write_json(output,payload)
        for arm in ARMS:
            try:
                result=_run_one(inst,initial,seed,arm)
                if content_hash(initial)!=original_sha:
                    raise RuntimeError("ALNS mutated shared initial state")
                if arm=="original" and result["B"]["solution_sha256"]!=row["original_B_sha256"]:
                    raise RuntimeError("Original ALNS objective changed search endpoint")
                row["arms"][arm]=result
                print("P8_QUEUE_PILOT="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                    "B_stage1_strict":result["B"]["stage1_strict"],
                    "ESI_both_strict":result["ESI"]["both_strict"],
                    "queue_states":result["funnel"]["counters"].get("queue_necessary_pass",0),
                    "joint_states":result["funnel"]["counters"].get("joint_bw_cpu_necessary_pass",0),
                    "search_wall":round(result["search_wall_s"],3),
                    "full_wall":round(result["full_end_to_end_wall_s"],3),
                },ensure_ascii=False),flush=True)
            except Exception as exc:
                err={
                    "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                    "type":type(exc).__name__,"message":str(exc)}
                payload["errors"].append(err)
                row["arms"][arm]={"error":err}
                print("P8_QUEUE_PILOT_ERROR="+json.dumps(err),flush=True)
            write_json(output,payload)
    payload["complete"]=True
    payload["summary"]={
        "cases":len(payload["rows"]),
        "original_B_SHA_reproduced":sum(
            r["arms"].get("original",{}).get("B",{}).get("solution_sha256")
            ==r["original_B_sha256"] for r in payload["rows"]),
        "ESI_strict":{arm:sum(
            bool(r["arms"].get(arm,{}).get("ESI",{}).get("both_strict"))
            for r in payload["rows"]) for arm in ARMS},
        "unexpected_errors":len(payload["errors"]),
    }
    write_json(output,payload)
    print("P8_PILOT_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(str(payload["errors"][:3]))
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--cases",required=True,
                   help="comma-separated profile:seed list, must match frozen P7")
    args=p.parse_args()
    pairs=[x.split(":") for x in args.cases.split(",")]
    run(args.source,args.output,pairs)
