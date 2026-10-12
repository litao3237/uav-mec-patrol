"""Frozen original failure candidate tie-break audit.

Isolate the *last* lexicographic label key of the original ESI/P1 queue
candidate ranking, without modifying route/beam generation, CVX quota,
original constraints, or final strict Stage1+Stage2 validation.

Three arms: exact original lexical; favor MEC-contact reuse *only on exact
numeric rank ties*; deterministic diverse final-operator families *only on
exact numeric ties*. The S85-S88 samples were already inspected, so any
improvement is hypothesis-generation, NEVER a new independent holdout.
"""
from __future__ import annotations

import argparse
from collections import defaultdict,Counter
import json
from pathlib import Path
from time import perf_counter

from atomic_batch_search import atomic_search
from progressive_bridge_core import PROFILES
from run_seven_methods import finalize
from uav_mec.algorithms import Stage1CVXObjectiveOracle
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,restore_solution,content_hash,write_json
)
from uav_mec.analysis.stage1_acceptance import stage1_is_qualified


POLICIES=("lexical_original","reuse_on_exact_ties","diverse_on_exact_ties")


def primary(row):
    x=row["metric"]
    return (not x["passed"],x["n_reasons"],
            x["total_excess_s"],x["route_distance_m"])


def rearrange(sorted_rows, policy):
    if policy not in POLICIES:
        raise ValueError(policy)
    if policy=="lexical_original":
        return list(sorted_rows)
    groups=defaultdict(list)
    for row in sorted_rows:
        groups[primary(row)].append(row)
    output=[]
    for key in sorted(groups):
        group=groups[key]
        if policy=="reuse_on_exact_ties":
            def pref(r):
                family=r["family"]
                return (0 if family=="bundle_reuse_contact" else
                        1 if family=="bundle_new_contact" else 2,
                        r["label"])
            group=sorted(group,key=pref)
        else:
            # One representative of each family BEFORE multiple identical
            # family choices on exact primary-metric ties.
            selected=[]
            used=set()
            for item in group:
                if item["family"] not in used:
                    selected.append(item)
                    used.add(item["family"])
            group=selected+[r for r in group if r not in selected]
        output.extend(group)
    assert len(output)==len(sorted_rows)
    assert [primary(x) for x in output]==[primary(x) for x in sorted_rows]
    return output


def strict_evaluate(instance,candidates,policy):
    oracle=Stage1CVXObjectiveOracle()
    start=perf_counter()
    valid=[]
    cases=[]
    for rank,cand in enumerate(candidates[:3],1):
        r=oracle.solve(instance,cand["sol"])
        good=stage1_is_qualified(r)
        cases.append({
            "rank":rank,"label":cand["label"],"family":cand["family"],
            "solution_sha256":content_hash(cand["sol"]),
            "stage1_status":r.diagnostics.get("stage1_status"),
            "stage1_qualified":bool(good),
            "stage1_energy_j":float(r.energy_stage1_j) if good else None,
        })
        if good:
            valid.append((float(r.energy_stage1_j),cand))
    success=False
    energy=None
    chosen=None
    stage1_f=None
    stage2_f=None
    if valid:
        _,selected=min(valid,key=lambda x:x[0])
        output=finalize(
            instance,selected["sol"],method="diagnostic_"+policy,
            seed=None,initialization_s=0.,search_s=0.,
            diagnostics={"source":"frozen_tie_break_control","label":selected["label"]},
        )
        stage1_f=bool(output["stage1"]["qualified"])
        stage2_f=bool(output["stage2"]["qualified"])
        success=bool(stage1_f and stage2_f)
        if success:
            energy=float(output["resources"].energy_stage1_j)
        chosen=selected["label"]
    return {
        "policy":policy,"strict_both_recovered":success,
        "strict_energy_j":energy,"chosen_label":chosen,
        "stage1_audit":stage1_f,"stage2_audit":stage2_f,
        "oracle_calls":oracle.calls,"tested_candidates":cases,
        "selection_and_validation_wall_s":perf_counter()-start,
    }


def run(source_path:Path,prior_path:Path,output_path:Path):
    if output_path.exists():raise FileExistsError(output_path)
    source=json.loads(source_path.read_text(encoding="utf-8"))
    prior=json.loads(prior_path.read_text(encoding="utf-8"))
    p=source["protocol"]
    scene=int(p["independent_scenario_seed"])
    if scene not in (85,86,87,88):
        raise ValueError("Only inspected fixed scenarios S85-S88")
    if not source.get("complete") or not prior.get("complete"):
        raise ValueError("Incomplete original source evidence")
    if prior["protocol"]["scenario"]!=scene:
        raise ValueError("Mismatched source / P1")
    previous={(x["profile"],int(x["seed"])):x for x in prior["rows"]}
    index={(x["profile"],int(x["seed"]),x["method"]):x for x in source["rows"]}
    result={
        "complete":False,
        "protocol":{
            "id":"p1_same_cvx_quota_lexical_tie_causal_ablation_v1",
            "scenario":scene,
            "inspected_development_only":True,
            "source_sha256":content_hash(source),
            "original_p1_sha256":content_hash(prior),
            "candidate_beam_and_generation_identical":True,
            "stage1_oracle_quota_per_arm":3,
            "same_original_two_stage_acceptance":True,
            "sort_changes_only_exact_primary_metric_ties":True,
            "policies":list(POLICIES),
        },
        "rows":[],"errors":[],
    }
    write_json(output_path,result)
    for profile in PROFILES:
        inst=restore_instance(source["profiles"][profile]["instance"])
        if content_hash(inst)!=source["profiles"][profile]["instance_sha256"]:
            raise RuntimeError("Original fixed instance changed")
        for seed in (125,126):
            old=previous[profile,seed]
            if not old["eligible"]:
                continue
            original=index[profile,seed,"B-ALNS"]
            sol=restore_solution(original["solution"])
            h=content_hash(sol)
            if h!=old["source_solution_sha256"]:
                raise RuntimeError("Original discrete structure SHA mismatch")
            row={
                "scenario":scene,"profile":profile,"seed":seed,
                "source_hash":h,
                "prior_original_strict":old["arms"][
                    "atomic_offload_and_cross_uav_depth4"]["strict_both_recovered"],
                "arms":{},
            }
            result["rows"].append(row)
            write_json(output_path,result)
            try:
                ordered,info=atomic_search(
                    inst,sol,include_atomic=True,include_cross_uav=True,
                    beam_width=2,depth=4,exact_limit=10000,generation_cap_s=4.,
                )
                assert len(ordered)==info["queue_passed"]
                row["queue_passed"]=len(ordered)
                row["strict_first3_original_names"]=old["arms"][
                    "atomic_offload_and_cross_uav_depth4"][
                    "search_diagnostics"]["strict_shortlist_labels"]
                row["candidate_names_replayed"]=[x["label"] for x in ordered[:3]]
                row["original_rank_reproduced"]=(
                    row["strict_first3_original_names"]==row["candidate_names_replayed"])
                row["primary_tie_at_top"]=sum(
                    primary(x)==primary(ordered[0]) for x in ordered
                ) if ordered else 0
                row["top_primary_key"]=list(primary(ordered[0])) if ordered else None
                for policy in POLICIES:
                    cand=rearrange(ordered,policy)
                    info_pol=strict_evaluate(inst,cand,policy)
                    row["arms"][policy]=info_pol
                    write_json(output_path,result)
                if content_hash(sol)!=h:
                    raise RuntimeError("Source D was mutated")
                row["original_strict_reproduced"]=(
                    bool(row["prior_original_strict"])==
                    bool(row["arms"]["lexical_original"]["strict_both_recovered"]))
                print("P1_TIE_BREAK_CASE="+json.dumps({
                    "s":scene,"profile":profile,"seed":seed,
                    "queue_pass":len(ordered),
                    "top_tie":row["primary_tie_at_top"],
                    "names_match":row["original_rank_reproduced"],
                    "orig_strict_match":row["original_strict_reproduced"],
                    "recovered":{k:v["strict_both_recovered"] for k,v in row["arms"].items()},
                }),flush=True)
            except Exception as exc:
                err={"s":scene,"profile":profile,"seed":seed,
                     "error_type":type(exc).__name__,"message":str(exc)}
                row["error"]=err
                result["errors"].append(err)
                print("P1_TIE_BREAK_ERROR="+json.dumps(err),flush=True)
            write_json(output_path,result)
    result["complete"]=True
    result["summary"]={
        "eligible":len(result["rows"]),
        "strict_recovered":{key:sum(
            row["arms"].get(key,{}).get("strict_both_recovered",False)
            for row in result["rows"]) for key in POLICIES},
        "rank_reproduced":sum(r.get("original_rank_reproduced",False)
                              for r in result["rows"]),
        "strict_reproduced":sum(r.get("original_strict_reproduced",False)
                                for r in result["rows"]),
        "unexpected_errors":len(result["errors"]),
    }
    write_json(output_path,result)
    print("P1_TIE_BREAK_SUMMARY="+json.dumps({"s":scene,**result["summary"]},
                                              ensure_ascii=False),flush=True)
    if result["errors"]:
        raise RuntimeError(str(result["errors"][:3]))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--previous",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    run(a.source,a.previous,a.output)
