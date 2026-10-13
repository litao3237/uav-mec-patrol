"""P26 post-P22 exact MEC offload-BATCH alternative station transfer pilot.

Original physical CPU/bandwidth, original FIFO/EDF virtual (UAV,MEC)
resource model, original Stage1 CVX and independent Stage2 acceptance are
unchanged. Reconstruct SHA-immutable original P22 cross-UAV swap D, then
test transferring 2-6 task EDF/heavy bundles from one original contact
batch to an alternate MEC using a downstream existing visit or exactly
one new physically legal contact. This is a structural change, not
hardware expansion or a solved full ALNS under equal search clock.

All candidate D in the union are shared by queue-only, static CPU-share,
joint BW+CPU necessary-screen and seeded random rankers. The original
strict Stage1+Stage2 solver checks <=6 candidates per arm AFTER selection.
Do not interpret necessary-bound passing as strict feasibility.
Only ALREADY INSPECTED development scenes are used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from run_p12_insertion_finish_audit import CASES, _strict_numerical_check
from run_p22_deadline_cross_uav_exchange import (
    one_cross_uav_exchange, owner_map,
)
from run_p24_postswap_offload_redistribution import _audit_candidate
from uav_mec.algorithms.alns import operators as ops
from uav_mec.algorithms.alns.evaluator import solution_signature
from uav_mec.algorithms.initial.mec_repair import (
    _best_new_contact_locations, _next_visit_id,
)
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)
from uav_mec.domain import ContactVisit, Route, RouteStop, TaskDecision
from uav_mec.evaluation import build_event_info, visit_mec_id
from uav_mec.evaluation.validator import validate_solution
from uav_mec.optimization.resource.joint_station_bw_cpu_bound import (
    joint_station_bw_cpu_necessary_bound,
)

STRICT_PER_POLICY=6
JOINT_BINS=24
POLICIES=("joint_bw_cpu_rank","cpu_lb_rank","queue_rank","random_rank")
BUNDLE_SIZES=(2,3,4,6)
MAX_POINTS_PER_ALT_MEC=2


def _bundles(instance,batch):
    """Fixed predeclared EDF/head, heavy, EDF/tail, complete batch controls."""
    sizes=sorted({*BUNDLE_SIZES,len(batch)})
    unique={}
    for k in sizes:
        if not 2<=k<=len(batch):
            continue
        choices=(
            ("edf_head", batch[:k]),
            ("edf_tail", batch[-k:]),
            ("heavy", sorted(batch,key=lambda t:(
                -instance.tasks[t].workload_gcycles,t))[:k]),
        )
        for why,chosen in choices:
            unique.setdefault(tuple(sorted(chosen)),(why,list(chosen)))
    return list(unique.values())


def generate_batch_moves(instance,source):
    validate_solution(instance,source)
    original_sha=content_hash(source)
    info=build_event_info(instance,source)
    pool=[]
    seen={solution_signature(source)}
    skipped=Counter()
    for old_visit in sorted(info.batch_tasks):
        original_batch=list(info.batch_edf_order[old_visit])
        if len(original_batch)<2:
            skipped["batch_shorter_than_2"]+=1
            continue
        old_mid=visit_mec_id(instance,source,old_visit)
        uav=source.contact_visits[old_visit].uav_id
        route=source.routes[uav]
        positions={tid:ix for ix,stop in enumerate(route.stops)
                   if stop.ref_id in instance.tasks for tid in [stop.ref_id]}
        order={vid:ix for ix,stop in enumerate(route.stops)
               if stop.ref_id in source.contact_visits for vid in [stop.ref_id]}
        for why,tasks in _bundles(instance,original_batch):
            chosen=tuple(sorted(tasks))
            latest=max(chosen,key=lambda t:positions[t])
            after_latest=positions[latest]
            options=[]
            for visit_id,idx in sorted(order.items(),key=lambda x:x[1]):
                if idx>after_latest and visit_mec_id(instance,source,visit_id)!=old_mid:
                    options.append(("existing",visit_id,None,None))

            points=_best_new_contact_locations(
                instance,source,latest,
                limit=max(16,len(instance.contact_points)),
                per_mec=MAX_POINTS_PER_ALT_MEC,
            )
            collected=Counter()
            for detour,point_id,ix in points:
                mid=instance.contact_points[point_id].mec_id
                if mid==old_mid or collected[mid]>=MAX_POINTS_PER_ALT_MEC:
                    continue
                collected[mid]+=1
                options.append(("new",point_id,ix,round(detour,5)))

            for move,target,ix,detour in options:
                alt=deepcopy(source)
                if move=="existing":
                    new_visit=target
                    alternate=visit_mec_id(instance,alt,new_visit)
                else:
                    alternate=instance.contact_points[target].mec_id
                    new_visit=_next_visit_id(alt,uav)
                    stops=list(alt.routes[uav].stops)
                    stops.insert(ix,RouteStop.contact(new_visit))
                    alt.routes[uav]=Route(uav,tuple(stops))
                    alt.contact_visits[new_visit]=ContactVisit(
                        new_visit,uav,target
                    )
                for tid in chosen:
                    alt.task_decisions[tid]=TaskDecision.offload(new_visit)
                try:
                    ops._cleanup_orphan_contacts(alt)
                    validate_solution(instance,alt)
                    signature=solution_signature(alt)
                    if signature in seen:
                        skipped["duplicate_physical_D"]+=1
                        continue
                    seen.add(signature)
                    if content_hash(source)!=original_sha:
                        raise RuntimeError("Frozen parent D mutated")
                    label=f"{why}:{len(chosen)}:{old_visit}->{alternate}:{move}:{target}"
                    pool.append({
                        "label":label,
                        "original_visit":old_visit,
                        "old_station":old_mid,
                        "new_station":alternate,
                        "task_bundle":list(chosen),
                        "batch_total_work_gcycles":sum(
                            instance.tasks[t].workload_gcycles for t in chosen
                        ),
                        "candidate_SHA":content_hash(alt),
                        "D":alt,
                    })
                except (ValueError,KeyError) as exc:
                    skipped[type(exc).__name__]+=1
    return pool,dict(skipped)


def joint_read_only(instance,candidate,queue_pass):
    if not queue_pass:
        return {
            "evaluated":False,
            "passes_joint_necessary_test":False,
            "joint_necessary_reject":True,
            "joint_station_cpu_oversubscription_ghz":None,
        }
    r=joint_station_bw_cpu_necessary_bound(
        instance,candidate,n_bins=JOINT_BINS
    )
    return {
        "evaluated":True,
        "passes_joint_necessary_test":r["passes_joint_necessary_test"],
        "joint_necessary_reject":r["joint_necessary_reject"],
        "joint_station_cpu_oversubscription_ghz":sum(
            s["oversubscription_cpu_ghz"] or 0. for s in r["stations"].values()
        ),
        "stations": {
            mid:{
                "optimistic_min_total_cpu_ghz":s["optimistic_min_total_cpu_ghz"],
                "physical_cpu_ghz":s["physical_cpu_ghz"],
                "joint_necessary_violation":s["joint_necessary_violation"],
            }
            for mid,s in r["stations"].items()
        },
    }


def rank(record,policy):
    q=record["audit"]["queue"]
    cpu=record["audit"]["cpu_lb"]
    joint=record["joint"]
    base=(not q["queue_necessary_pass"],q["queue_reason_count"])
    if policy=="joint_bw_cpu_rank":
        return base+(
            not joint["passes_joint_necessary_test"],
            cpu["certified_cpu_share_failure"],
            float("inf") if joint["joint_station_cpu_oversubscription_ghz"] is None
            else joint["joint_station_cpu_oversubscription_ghz"],
            cpu["sum_station_cpu_excess_lb_ghz"],
            q["total_normalized_all_constraint_excess"],
            record["label"],
        )
    if policy=="cpu_lb_rank":
        return base+(
            cpu["certified_cpu_share_failure"],
            cpu["sum_station_cpu_excess_lb_ghz"],
            cpu["max_station_cpu_pressure_lb_ratio"],
            q["total_normalized_all_constraint_excess"],
            record["label"],
        )
    if policy=="queue_rank":
        return base+(
            q["total_normalized_all_constraint_excess"],
            q["worst_task_deadline_excess_s"],
            q["route_total_distance_m"],
            record["label"],
        )
    if policy=="random_rank":
        raise ValueError("Random rank must use a separately frozen permutation")
    raise ValueError(policy)


def run(source:Path,p22:Path,output:Path,cases):
    if output.exists():
        raise FileExistsError(output)
    frozen=json.loads(source.read_text(encoding="utf-8"))
    previous=json.loads(p22.read_text(encoding="utf-8"))
    scene=int(frozen["protocol"]["independent_scenario_seed"])
    selected=[(p,int(s)) for p,s in cases]
    if (not frozen.get("complete") or not previous.get("complete")
        or previous.get("errors") or scene not in CASES
        or any(item not in CASES[scene] for item in selected)
        or set(selected)!={(r["profile"],int(r["seed"])) for r in previous["rows"]}):
        raise ValueError("P26 accepts only immutable seen P22 original K80 sources")
    bindex={(r["profile"],int(r["seed"]),r["method"]):r
            for r in frozen["rows"]}
    pindex={(r["profile"],int(r["seed"])):r
            for r in previous["rows"]}
    payload={
        "complete":False,
        "protocol":{
            "id":"P26_original_MEC_multi_task_batch_transfer_on_P22_swap_v1",
            "scene":scene,
            "source_B_SHA":content_hash(frozen),
            "source_P22_SHA":content_hash(previous),
            "original_cpu_bandwidth_physics_unchanged":True,
            "only_alternate_MEC_by_legal_contact_route_change":True,
            "multi_task_group_2_to_6_plus_full":True,
            "no_extra_stage1_solver_in_candidate_ranking":True,
            "one_exact_strict_numerical_oracle_after_ranking_per_candidate":True,
            "strict_checks_per_policy":STRICT_PER_POLICY,
            "joint_bins":JOINT_BINS,
            "rankings":list(POLICIES),
            "identical_full_candidate_pool_for_all_policies":True,
            "not_matched_full_ALNS_wall_time":True,
            "not_independent_development_scenes":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,payload)
    for profile,seed in selected:
        inst=restore_instance(frozen["profiles"][profile]["instance"])
        i_sha=frozen["profiles"][profile]["instance_sha256"]
        if content_hash(inst)!=i_sha:
            raise RuntimeError("Physical task/contact/hardware hash mismatch")
        b=bindex[profile,seed,"B-ALNS"]
        B=restore_solution(b["solution"])
        Bsha=b["solution_sha256"]
        if content_hash(B)!=Bsha:
            raise RuntimeError("Frozen original B D SHA changed")
        upstream=pindex[profile,seed]["policies"]["deadline_critical_pairs"]
        pair=tuple(upstream["best"]["task_pair"])
        earlier,D=one_cross_uav_exchange(inst,B,owner_map(B),pair)
        Dsha=content_hash(D)
        if Dsha!=upstream["best"]["finished_D_sha"]:
            raise RuntimeError("Original P22 cross-UAV D SHA drift")
        prior_strict=_strict_numerical_check(inst,deepcopy(D))
        if bool(prior_strict["Stage1_and_Stage2_strict"]) != bool(
            upstream["strict_posthoc"]["Stage1_and_Stage2_strict"]
        ):
            raise RuntimeError("P22 strict stage acceptance changed")
        pool,skipped=generate_batch_moves(inst,D)
        if not pool:
            raise RuntimeError("No valid original-MEC multi-task batch alternatives")
        evaluated=[]
        keep={}
        for item in pool:
            candidate=item.pop("D")
            audit=_audit_candidate(inst,candidate)
            joint=joint_read_only(
                inst,candidate,audit["queue"]["queue_necessary_pass"]
            )
            item["audit"]=audit
            item["joint"]=joint
            evaluated.append(item)
            keep[item["candidate_SHA"]]=candidate
        # Do NOT choose joint-winning candidates after seeing expensive Stage1.
        rng=np.random.default_rng(seed+262600)
        frozen_perm=list(rng.permutation(len(evaluated)))
        strict_cache={}
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "physical_instance_SHA":i_sha,
            "original_B_SHA":Bsha,
            "P22_selected_exchange":list(pair),
            "P22_exact_D_SHA":Dsha,
            "P22_original_strict":prior_strict,
            "P22_queue_CPU_baseline":_audit_candidate(inst,D),
            "generated_legal_unique_batch_transfers":len(evaluated),
            "skipped":skipped,
            "complete_candidate_pool":evaluated,
            "policies":{},
        }
        payload["rows"].append(row)
        write_json(output,payload)
        for policy in POLICIES:
            if policy=="random_rank":
                ordered=[evaluated[int(k)] for k in frozen_perm]
            else:
                ordered=sorted(evaluated,key=lambda z:rank(z,policy))
            selected_now=ordered[:STRICT_PER_POLICY]
            checked=[]
            for candidate in selected_now:
                sha=candidate["candidate_SHA"]
                if sha not in strict_cache:
                    strict_cache[sha]=_strict_numerical_check(
                        inst,deepcopy(keep[sha])
                    )
                strict=strict_cache[sha]
                checked.append({
                    "label":candidate["label"],
                    "candidate_SHA":sha,
                    "batch":candidate["task_bundle"],
                    "old_station":candidate["old_station"],
                    "new_station":candidate["new_station"],
                    "queue_necessary_pass":candidate["audit"]["queue"][
                        "queue_necessary_pass"
                    ],
                    "cpu_necessary_pass":not candidate["audit"]["cpu_lb"][
                        "certified_cpu_share_failure"
                    ],
                    "joint_necessary_pass":candidate["joint"][
                        "passes_joint_necessary_test"
                    ],
                    "strict":strict,
                    "strict_both":strict["Stage1_and_Stage2_strict"],
                })
            row["policies"][policy]={
                "same_full_pool_candidate_SHA":[r["candidate_SHA"] for r in evaluated],
                "checked":checked,
                "any_strict":any(v["strict_both"] for v in checked),
                "strict_selected_n":len(checked),
                "strict_pass_n":sum(v["strict_both"] for v in checked),
            }
            write_json(output,payload)
            print("P26_BATCH_CASE="+json.dumps({
                "scene":scene,"profile":profile,"seed":seed,"policy":policy,
                "pool":len(evaluated),
                "baseline_strict":prior_strict["Stage1_and_Stage2_strict"],
                "passing_joint_candidates_full_pool":sum(
                    rec["joint"]["passes_joint_necessary_test"]
                    for rec in evaluated),
                "checked":[{
                    "label":t["label"],
                    "old":t["old_station"],"new":t["new_station"],
                    "size":len(t["batch"]),
                    "queue":t["queue_necessary_pass"],
                    "cpu":t["cpu_necessary_pass"],
                    "joint":t["joint_necessary_pass"],
                    "strict":t["strict_both"],
                } for t in checked],
            },ensure_ascii=False),flush=True)
        if content_hash(inst)!=i_sha or content_hash(B)!=Bsha or content_hash(D)!=Dsha:
            raise RuntimeError("Original physical hardware or frozen D mutated")
    payload["complete"]=True
    payload["summary"]={
        "physical_cases":len(payload["rows"]),
        "policies":{
            p:{"positive":sum(r["policies"][p]["any_strict"] for r in payload["rows"]),
               "total_checks":sum(r["policies"][p]["strict_selected_n"] for r in payload["rows"])}
            for p in POLICIES
        },
        "errors":len(payload["errors"]),
    }
    write_json(output,payload)
    print("P26_BATCH_SCENE_SUMMARY="+json.dumps({
        "scene":scene,**payload["summary"]
    },ensure_ascii=False),flush=True)
    return payload


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--p22",type=Path,required=True)
    parser.add_argument("--cases",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.source,args.p22,args.output,[v.split(":") for v in args.cases.split(",")])
