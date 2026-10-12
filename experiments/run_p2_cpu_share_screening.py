"""P2 controlled fixed-source repair: proven CPU-share screening vs old top3.

No extra CVX quota. Both arms use same frozen K80/S85-S88 source, same
atomic+cross-UAV 4-depth generation, and SAME 3 strict Stage1 call limit.
The only treatment is applying a *necessary* static MEC CPU-share bound
before choosing which queue-admitted candidates receive costly CVX.

This is development-only after inspecting S85-S88; not full-ALNS equal
end-to-end time nor independent new-scene validation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from collections import Counter

from atomic_batch_search import atomic_search
from progressive_bridge_core import PROFILES
from run_seven_methods import finalize
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)
from uav_mec.optimization.resource.station_cpu_share_bound import (
    station_cpu_share_necessary_bound,
)

ARMS=("legacy_top3","necessary_cpu_guard_top3")


def _strict_repair(instance, selected, *, arm):
    oracle=Stage1CVXObjectiveOracle()
    t0=perf_counter()
    examined=[]; eligible=[]
    for c in selected:
        v=oracle.solve(instance,c["sol"])
        ok=bool(stage1_is_qualified(v))
        examined.append({
            "label":c["label"],"candidate_sha256":content_hash(c["sol"]),
            "stage1_qualified":ok,
            "stage1_status":v.diagnostics.get("stage1_status"),
            "stage1_energy_j":float(v.energy_stage1_j) if ok else None,
        })
        if ok:eligible.append((float(v.energy_stage1_j),c))
    strict=False; energy=None; final_label=None; final_state=None
    if eligible:
        _,best=min(eligible,key=lambda row:row[0])
        end=finalize(
            instance,best["sol"],method="diagnostic_"+arm,
            seed=None,initialization_s=0.0,search_s=0.0,
            diagnostics={"source":"P2_static_pair_necessary_screen",
                         "selected_label":best["label"]},
        )
        strict=bool(end["stage1"]["qualified"] and end["stage2"]["qualified"])
        final_label=best["label"]
        final_state={
            "stage1_qualified":bool(end["stage1"]["qualified"]),
            "stage2_qualified":bool(end["stage2"]["qualified"]),
        }
        if strict:energy=float(end["resources"].energy_stage1_j)
    return {
        "strict_both_recovered":strict,
        "strict_energy_j":energy,
        "chosen_label":final_label,
        "final_stage_qualified":final_state,
        "stage1_oracle_calls":oracle.calls,
        "evaluated":examined,
        "exact_and_final_wall_s":perf_counter()-t0,
    }


def run(source_file,previous_file,output):
    if output.exists():raise FileExistsError(output)
    raw=json.loads(source_file.read_text(encoding="utf-8"))
    old=json.loads(previous_file.read_text(encoding="utf-8"))
    s=raw["protocol"]["independent_scenario_seed"]
    if s not in (85,86,87,88) or old["protocol"]["scenario"]!=s:
        raise ValueError("Frozen source scenarios mismatch")
    orig={(r["profile"],int(r["seed"]),r["method"]):r for r in raw["rows"]}
    previous={(r["profile"],int(r["seed"])):r for r in old["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"P2_static_pair_cpu_guard_same_3_exact_budget_dev_v1",
            "scenario":s,
            "original_source_sha256":content_hash(raw),
            "original_p1_sha256":content_hash(old),
            "same_generated_candidate_pool_both_arms":True,
            "max_stage1_oracle_calls_per_arm":3,
            "no_original_evaluator_change":True,
            "development_S85_S88_already_inspected":True,
            "conditional_failed_D_not_whole_ALNS":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,payload)
    for profile in PROFILES:
        x=raw["profiles"][profile]
        instance=restore_instance(x["instance"])
        if content_hash(instance)!=x["instance_sha256"]:
            raise RuntimeError("Physical input SHA mismatch")
        for seed in (125,126):
            old_row=previous[profile,seed]
            if not old_row["eligible"]:continue
            src=orig[profile,seed,"B-ALNS"]
            sol=restore_solution(src["solution"])
            if content_hash(sol)!=old_row["source_solution_sha256"]:
                raise RuntimeError("Frozen D SHA mismatch")
            row={
                "scenario":s,"seed":seed,"profile":profile,
                "source_sha256":content_hash(sol),
                "previous_strict":bool(old_row["arms"][
                    "atomic_offload_and_cross_uav_depth4"]["strict_both_recovered"]),
                "arms":{}, "errors":[],
            }
            payload["rows"].append(row)
            write_json(output,payload)
            try:
                gen=perf_counter()
                candidates,diag=atomic_search(
                    instance,sol,include_atomic=True,include_cross_uav=True,
                    beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.,
                )
                generation_s=perf_counter()-gen
                assert len(candidates)==diag["queue_passed"]
                old_labels=old_row["arms"][
                    "atomic_offload_and_cross_uav_depth4"][
                    "search_diagnostics"]["strict_shortlist_labels"]
                row["legacy_top3_reproduced"]=(
                    [c["label"] for c in candidates[:3]]==old_labels)
                if not row["legacy_top3_reproduced"]:
                    raise RuntimeError("Original top3 labels did not reproduce")
                t0=perf_counter()
                screened=[];rejected=[];pressure_summary=[]
                for c in candidates:
                    if len(screened)>=3:break
                    info=build_event_info(instance,c["sol"])
                    q=queue_aware_feasibility_precheck(instance,c["sol"],info)
                    if not q.feasible:raise RuntimeError("Search emitted old-queue failing candidate")
                    gate=station_cpu_share_necessary_bound(instance,c["sol"],info=info,queue=q)
                    pmax=max((x["min_cpu_pressure_ratio"] or float("inf"))
                             for x in gate["stations"].values())
                    row_info={
                        "candidate":c["label"],"candidate_sha256":content_hash(c["sol"]),
                        "cpu_guard_reject":gate["certified_cpu_share_failure"],
                        "max_required_cpu_capacity_ratio":pmax,
                        "binding_station":next(
                            (mid for mid,x in gate["stations"].items()
                             if x["necessary_capacity_violation"]),None),
                    }
                    pressure_summary.append(row_info)
                    if gate["certified_cpu_share_failure"]:
                        rejected.append(row_info)
                    else:screened.append(c)
                screening_s=perf_counter()-t0
                row["generation_wall_s"]=generation_s
                row["screening_wall_s"]=screening_s
                row["queue_candidates"]=len(candidates)
                row["cpu_screen_examined"]=len(pressure_summary)
                row["cpu_screen_rejected"]=len(rejected)
                row["cpu_rejected_first_few"]=rejected[:5]
                for arm,selection in (
                    ("legacy_top3",candidates[:3]),
                    ("necessary_cpu_guard_top3",screened),
                ):
                    result=_strict_repair(instance,selection,arm=arm)
                    result["selection_labels"]=[r["label"] for r in selection]
                    result["common_generation_wall_s"]=generation_s
                    result["screening_wall_s"]=screening_s if arm=="necessary_cpu_guard_top3" else 0.
                    result["whole_repair_wall_s"]=(
                        generation_s+result["screening_wall_s"]+
                        result["exact_and_final_wall_s"])
                    row["arms"][arm]=result
                    if result["stage1_oracle_calls"]>3:
                        raise RuntimeError("Exceeded frozen strict oracle budget")
                    write_json(output,payload)
                row["legacy_strict_reproduced"]=(
                    row["arms"]["legacy_top3"]["strict_both_recovered"]==
                    row["previous_strict"])
                if not row["legacy_strict_reproduced"]:
                    raise RuntimeError("Original strict qualification did not reproduce")
                if content_hash(sol)!=row["source_sha256"]:
                    raise RuntimeError("Modified original D")
                print("P2_CPU_SCREEN_CASE="+json.dumps({
                    "scenario":s,"profile":profile,"seed":seed,
                    "candidates":len(candidates),
                    "cpu_rejected":len(rejected),
                    "strict":{k:v["strict_both_recovered"] for k,v in row["arms"].items()},
                    "cvx":{k:v["stage1_oracle_calls"] for k,v in row["arms"].items()},
                    "seconds":{k:round(v["whole_repair_wall_s"],3)
                               for k,v in row["arms"].items()},
                },ensure_ascii=False),flush=True)
            except Exception as exc:
                err={"type":type(exc).__name__,"message":str(exc),
                     "scene":s,"profile":profile,"seed":seed}
                row["errors"].append(err)
                payload["errors"].append(err)
                print("P2_CPU_SCREEN_ERROR="+json.dumps(err),flush=True)
            write_json(output,payload)
    payload["complete"]=True
    rows=payload["rows"]
    payload["summary"]={
        "sources":len(rows),
        "strict":{arm:sum(r["arms"].get(arm,{}).get("strict_both_recovered",False)
                          for r in rows) for arm in ARMS},
        "calls":{arm:sum(r["arms"].get(arm,{}).get("stage1_oracle_calls",0)
                         for r in rows) for arm in ARMS},
        "average_wall_seconds":{arm:(
            sum(r["arms"][arm]["whole_repair_wall_s"] for r in rows)/len(rows)
            if rows and all(arm in r["arms"] for r in rows) else None
        ) for arm in ARMS},
        "cpu_rejected_before_quota":sum(r.get("cpu_screen_rejected",0) for r in rows),
        "unexpected_errors":len(payload["errors"]),
    }
    write_json(output,payload)
    print("P2_CPU_SCREEN_SUMMARY="+json.dumps({
        "scenario":s,**payload["summary"],
    },ensure_ascii=False),flush=True)
    if payload["errors"]:
        raise RuntimeError(f"P2 strict replay errors {payload['errors'][:2]}")
    return payload


if __name__=="__main__":
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--source",type=Path,required=True)
    a.add_argument("--previous",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    p=a.parse_args()
    run(p.source,p.previous,p.output)
