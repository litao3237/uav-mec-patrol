"""P7 shadow recorder: is original ALNS exploration losing feasible intermediates?

Original 100-iteration ALNS (not ESI elite) is replayed with EXACT same
destroy/repair, RNG, RRT, evaluator objective and original physical
P1-R resource solver. A wrapper records every NEW generated D's
optimistic prechecks and a bounded collection of candidate structures,
WITHOUT changing the returned scalar objective or search trajectory.

This diagnoses a critical earlier-work limitation: every P1-P6b rescue
was applied only AFTER the original B-ALNS endpoint had already failed.
If no screened-necessary-passing solution was ever generated, changing
the post-hoc shortlist cannot solve the true underlying search failure.
Conversely, if several candidates did pass but the final B-state did
not, a candidate archive may be a better mechanism than new neighborhoods.

Archives are assessed with EXTRA, post-search Stage1 CVX & Stage2
qualification only for diagnosis, never used as equal-time performance
proof. All source scenarios already inspected, not independent holdouts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
    UavMecALNSConfig,build_greedy_initial_solution,
    build_mec_assisted_initial_solution,run_uav_mec_alns,
)
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource import fast_feasibility_precheck
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

K80_CASES=(
    (89,"deadline_x0p9",128),
    (91,"compute_x1p5",128),
    (93,"compute_x1p5",130),
    (94,"compute_x1p5",129),
    (95,"compute_x2p0",130),
    (96,"deadline_x0p9",130),
)
ARCHIVE_CAPACITY=10


class ShadowPrecheckArchive:
    """An EXACT scalar evaluator wrapper with read-only post-call observation."""

    def __init__(self,exact_evaluator,*,max_saved=ARCHIVE_CAPACITY):
        if max_saved<=0:raise ValueError("Positive archival cap expected")
        self.exact_evaluator=exact_evaluator
        self.max_saved=max_saved
        self.stats=exact_evaluator.stats
        self.seen=set()
        self.counters=Counter()
        self.q_archive=[]
        self.cpu_archive=[]
        self.joint_archive=[]
        self.shadow_wall_s=0.0

    def __call__(self,instance,solution):
        # Original ALNS objective is computed before ANY observation, and
        # returned unchanged (including original 1e9 penalties).
        score=float(self.exact_evaluator(instance,solution))
        self.counters["objective_calls"]+=1
        signature=solution_signature(solution)
        if signature in self.seen:return score
        self.seen.add(signature)
        started=perf_counter()
        self.counters["unique_generated"]+=1
        info=build_event_info(instance,solution)
        old=fast_feasibility_precheck(instance,solution,info)
        if not old.feasible:
            self.counters["old_fast_precheck_failed"]+=1
            self.shadow_wall_s+=perf_counter()-started
            return score
        self.counters["old_fast_precheck_passed"]+=1
        queue=queue_aware_feasibility_precheck(instance,solution,info)
        if not queue.feasible:
            self.counters["new_queue_failed_after_fast_pass"]+=1
            self.shadow_wall_s+=perf_counter()-started
            return score
        self.counters["queue_necessary_pass"]+=1
        self._record(self.q_archive,solution,score)
        cpu=station_cpu_share_necessary_bound(
            instance,solution,info=info,queue=queue)
        if cpu["certified_cpu_share_failure"]:
            self.counters["static_cpu_failed_after_queue_pass"]+=1
            self.shadow_wall_s+=perf_counter()-started
            return score
        self.counters["static_cpu_necessary_pass"]+=1
        self._record(self.cpu_archive,solution,score)
        joint=joint_station_bw_cpu_necessary_bound(
            instance,solution,info=info,queue=queue,n_bins=48)
        if joint["joint_necessary_reject"]:
            self.counters["joint_bw_cpu_failed_after_static_pass"]+=1
        else:
            self.counters["joint_bw_cpu_necessary_pass"]+=1
            self._record(self.joint_archive,solution,score)
        self.shadow_wall_s+=perf_counter()-started
        return score

    def _record(self,archive,solution,score):
        original_sha=content_hash(solution)
        if any(x["sha256"]==original_sha for x in archive):return
        archive.append({
            "sha256":original_sha,
            "score":float(score),
            "solution":deepcopy(solution),
        })
        archive.sort(key=lambda r:(r["score"],r["sha256"]))
        if len(archive)>self.max_saved:archive.pop(-1)

    def summary(self):
        return {
            "counters":dict(self.counters),
            "shadow_observation_wall_s":self.shadow_wall_s,
            "max_saved_per_gate":self.max_saved,
            "archive_lengths":{
                "queue":len(self.q_archive),
                "cpu":len(self.cpu_archive),
                "joint":len(self.joint_archive),
            },
            "original_evaluator_stats":{
                k:getattr(self.stats,k) for k in (
                    "calls","cache_hits","feasible_calls",
                    "infeasible_calls","precheck_rejects",
                    "ambiguous_proxy_calls","cvx_refinements")
            },
        }


def _strict_check_one(instance,entry):
    oracle=Stage1CVXObjectiveOracle()
    res=oracle.solve(instance,entry["solution"])
    passed=bool(stage1_is_qualified(res))
    row={
        "solution_sha256":entry["sha256"],
        "original_ALNS_scalar_score":entry["score"],
        "stage1_status":res.diagnostics.get("stage1_status"),
        "stage1_strict":passed,
        "stage1_CVX_calls":oracle.calls,
        "Stage2_strict":None,
        "strict_both":False,
        "energy_j":None,
    }
    if passed:
        full=finalize(
            instance,entry["solution"],
            method="P7_shadow_archive_only",
            seed=None,initialization_s=0.,search_s=0.,
            diagnostics={"source":"posthoc shadow diagnostic"},
        )
        row["Stage2_strict"]=bool(full["stage2"]["qualified"])
        row["strict_both"]=bool(
            full["stage1"]["qualified"] and full["stage2"]["qualified"])
        if row["strict_both"]:
            row["energy_j"]=float(full["resources"].energy_stage1_j)
    return row


def run(input_path:Path,output_path:Path,*,profiles_seeds):
    if output_path.exists():raise FileExistsError(output_path)
    data=json.loads(input_path.read_text(encoding="utf-8"))
    p=data["protocol"]
    scene=int(p["independent_scenario_seed"])
    if (not data.get("complete") or
        p["id"]!="uav_mec_one_factor_coupling_sensitivity_v1"
        or int(p["task_scale"])!=80):
        raise ValueError("Required original K80 physical source archive")
    cases=[(profile,seed) for profile,seed in profiles_seeds
           if (scene,profile,seed) in K80_CASES]
    if not cases:raise ValueError("No preregistered P7 cases for this archive")
    idx={(r["profile"],int(r["seed"]),r["method"]):r for r in data["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"P7_exact_replay_shadow_candidate_feasibility_archive_v1",
            "scene":scene,
            "source_sha256":content_hash(data),
            "pre_registered_cases":list(K80_CASES),
            "B_ALNS_100_iterations_original_operators_unmodified":True,
            "original_screened_proxy_score_always_returned_unchanged":True,
            "purely_shadow_observation_does_not_affect_RNG":True,
            "Stage1_Stage2_archive_checks_postpaid_and_diagnostic_only":True,
            "already_inspected_scenarios_not_new_holdout":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output_path,payload)
    for profile,seed in cases:
        instance=restore_instance(data["profiles"][profile]["instance"])
        if content_hash(instance)!=data["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Physical instance hash mismatch")
        old=idx[profile,seed,"B-ALNS"]
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "original_B_solution_sha256":old["solution_sha256"],
            "original_B_stage1_strict":bool(old["stage1_qualified"]),
            "original_B_status":(
                ((old.get("resources") or {}).get("diagnostics") or {}).get(
                    "stage1_status")),
            "archive_exact_rechecks":{},
        }
        payload["rows"].append(row)
        write_json(output_path,payload)
        try:
            start=perf_counter()
            init=build_mec_assisted_initial_solution(
                instance,base_solution=build_greedy_initial_solution(instance))
            wrapper=ShadowPrecheckArchive(
                ScreenedProxyObjectiveEvaluator(),max_saved=ARCHIVE_CAPACITY)
            result=run_uav_mec_alns(
                instance,
                initial_solution=deepcopy(init),
                config=UavMecALNSConfig(
                    iterations=100,seed=seed,
                    enable_problem_operators=False,
                ),
                evaluator=wrapper,
            )
            row["original_ALNS_total_with_shadow_s"]=perf_counter()-start
            row["replayed_B_sha256"]=content_hash(result.best_solution)
            row["original_best_reproduced"]=(
                row["replayed_B_sha256"]==old["solution_sha256"])
            row["shadow"]=wrapper.summary()
            if not row["original_best_reproduced"]:
                raise RuntimeError("Shadow observer changed original ALNS trajectory")
            seen_checked=set()
            for name,archive in (
                ("queue",wrapper.q_archive),
                ("joint",wrapper.joint_archive),
            ):
                results=[]
                for entry in archive[:3]:
                    if entry["sha256"] in seen_checked:
                        row["archive_exact_rechecks"].setdefault(
                            "reuse_metadata",[]).append(entry["sha256"])
                        continue
                    seen_checked.add(entry["sha256"])
                    results.append(_strict_check_one(instance,entry))
                    write_json(output_path,payload)
                row["archive_exact_rechecks"][name]=results
            row["original_best_archive_member"]=any(
                item["sha256"]==row["replayed_B_sha256"]
                for item in wrapper.q_archive+wrapper.joint_archive)
            print("P7_ALNS_SHADOW_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,
                "original_status":row["original_B_status"],
                "exact_replay":row["original_best_reproduced"],
                "counters":row["shadow"]["counters"],
                "archive_stage1_strict":sum(
                    v["stage1_strict"] for label,rr in row["archive_exact_rechecks"].items()
                    if label!="reuse_metadata" for v in rr),
            },ensure_ascii=False),flush=True)
        except Exception as exc:
            problem={
                "scene":scene,"profile":profile,"seed":seed,
                "type":type(exc).__name__,"message":str(exc),
            }
            row["error"]=problem
            payload["errors"].append(problem)
        write_json(output_path,payload)
    payload["complete"]=True
    payload["summary"]={
        "attempts":len(payload["rows"]),
        "original_B_exact_replayed":sum(
            r.get("original_best_reproduced",False) for r in payload["rows"]),
        "source_original_failed_precheck":sum(
            r["original_B_status"]=="infeasible_precheck"
            for r in payload["rows"]),
        "shadow_any_joint_gate_candidate":sum(
            r.get("shadow",{}).get("counters",{}).get(
                "joint_bw_cpu_necessary_pass",0)>0
            for r in payload["rows"]),
        "strict_Stage1_from_shadow":sum(
            v["stage1_strict"] for r in payload["rows"]
            for name,rr in r["archive_exact_rechecks"].items()
            if name!="reuse_metadata" for v in rr),
        "errors":len(payload["errors"]),
    }
    write_json(output_path,payload)
    print("P7_ALNS_SHADOW_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError("Shadow trajectory mismatch or audit errors: "+
                           str(payload["errors"][:2]))
    return payload


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--profiles-seeds",required=True)
    args=p.parse_args()
    cases=[]
    for token in args.profiles_seeds.split(","):
        prof,seed=token.split(":")
        cases.append((prof,int(seed)))
    run(args.source,args.output,profiles_seeds=cases)
