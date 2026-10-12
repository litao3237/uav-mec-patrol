"""Frozen FIRST-USE S97-S100 whole-MEC-batch repair holdout.

The complete P6b operator/move selection and all budgets are frozen
before inspecting any new S97-S100 result. This code generates original
B-ALNS/ESI-ALNS physical source results, then uses only original
B-ALNS 'infeasible_precheck' fixed D for conditional paired repairs.
S89-S96 were already inspected for development. NEW_SCENES are
independent physical scenarios; algorithm seeds are nested within.
The original baseline's time is prepaid, so this is NOT a full
equal-end-to-end-time ESI-ALNS benchmark or publishable energy claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from experiment_common import provenance,current_source_hashes
from run_model_sensitivity import run_block as original_algorithm
from run_p6b_station_batch_probe import ARMS,evaluate
from progressive_bridge_core import PROFILES
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)

NEW_SCENES=(97,98,99,100)
SEEDS=(133,134)
SOURCE_PROFILES=("baseline",)+PROFILES


def run(scene:int,output_dir:Path):
    if scene not in NEW_SCENES:
        raise ValueError("Only preregistered first-use S97-S100")
    if output_dir.exists() and list(output_dir.iterdir()):
        raise FileExistsError("Immutable first-use holdout destination")
    output_dir.mkdir(parents=True,exist_ok=True)
    source_path=output_dir/f"p6b-fresh-source-K80_S{scene}.json"
    repaired_path=output_dir/f"p6b-fresh-repairs-K80_S{scene}.json"
    protocol_path=output_dir/f"p6b-fresh-protocol-K80_S{scene}.json"
    protocol={
        "id":"P6b_frozen_contact_batch_station_swap_first_use_S97_S100_v1",
        "complete":False,
        "scene":scene,
        "task_scale":80,
        "preregistered_independent_scenes":list(NEW_SCENES),
        "nested_algorithm_seeds":list(SEEDS),
        "source_methods":["B-ALNS","ESI-ALNS"],
        "original_iterations":100,
        "original_elite_rounds":2,
        "original_physical_profiles":list(SOURCE_PROFILES),
        "all_paused_num_statuses_retained":True,
        "same_frozen_old_atomic_candidate_pool":True,
        "same_P5_joint48_necessary_screen":True,
        "same_complete_Stage1_Stage2_residual_audit":True,
        "four_batch_selection_controls":["station_all_contacts",
            "joint_binding_pairs_2","heaviest_batches_2","lexical_contacts_2"],
        "strict_Stage1_CVX_oracle_limit":3,
        "batch_postrepair_seed_limit":4,
        "batch_postrepair_soft_wall_cap_s":3.,
        "batch_postrepair_move_eval_max":100,
        "full_original_B_ALNS_time_prepaid":True,
        "not_a_full_equal_time_ALNS_benchmark":True,
        "source_hashes":current_source_hashes(Path(__file__)),
        "provenance":provenance(),
        "errors":[],
    }
    write_json(protocol_path,protocol)
    try:
        from argparse import Namespace
        original_algorithm(Namespace(
            config=Path("configs/baseline.yaml"),
            tasks=80,scenario=scene,
            seeds="133,134",iterations=100,
            elite_rounds=2,profiles=",".join(SOURCE_PROFILES),
            output=source_path,
        ))
        snapshot=json.loads(source_path.read_text(encoding="utf-8"))
        if (not snapshot.get("complete") or
                snapshot["protocol"]["id"]!="uav_mec_one_factor_coupling_sensitivity_v1" or
                snapshot["protocol"]["independent_scenario_seed"]!=scene or
                list(snapshot["protocol"]["algorithm_seeds"])!=list(SEEDS)):
            raise RuntimeError("P6b original frozen source generation mismatch")
        original_sha=content_hash(snapshot)
        indexed={
            (r["profile"],int(r["seed"]),r["method"]):r
            for r in snapshot["rows"]
        }
        payload={
            "complete":False,
            "protocol":{
                "id":"P6b_station_contact_relocation_first_use_conditional_holdout_v1",
                "scene":scene,"tasks":80,
                "original_source_sha256":original_sha,
                "four_pre_registered_stress_profiles":list(PROFILES),
                "nested_algorithm_seeds":list(SEEDS),
                "same_B_ALNS_failed_D_all_arms":True,
                "candidate_beam_depth4_width2":True,
                "candidate_search_4second_soft_cap":True,
                "same_strict_stage1_quota_3_and_final_Stage2":True,
                "original_P1R_physics_and_tolerances_unchanged":True,
                "original_search_time_prepaid_not_whole_algorithm_budget":True,
                "first_use_scene_before_any_operator_tuning":True,
                "arms":list(ARMS),
            },
            "rows":[],"errors":[],
        }
        write_json(repaired_path,payload)
        for profile in PROFILES:
            entry=snapshot["profiles"][profile]
            instance=restore_instance(entry["instance"])
            if content_hash(instance)!=entry["instance_sha256"]:
                raise RuntimeError("Original physical stress config SHA mismatch")
            for seed in SEEDS:
                old=indexed[profile,seed,"B-ALNS"]
                diag=((old.get("resources") or {}).get("diagnostics") or {})
                status=diag.get("stage1_status")
                row={
                    "scene":scene,"profile":profile,"seed":seed,
                    "original_stage1_status":status,
                    "original_stage1_strict_qualified":bool(old["stage1_qualified"]),
                    "original_stage2_strict_qualified":bool(old["stage2_qualified"]),
                    "source_solution_sha256":old["solution_sha256"],
                    "eligible":status=="infeasible_precheck",
                    "arms":{},
                }
                payload["rows"].append(row)
                write_json(repaired_path,payload)
                if not row["eligible"]:continue
                try:
                    sol=restore_solution(old["solution"])
                    h=content_hash(sol)
                    if h!=row["source_solution_sha256"]:
                        raise RuntimeError("Original source D hash mismatch")
                    outcomes=evaluate(instance,sol)
                    if content_hash(sol)!=h:
                        raise RuntimeError("Source B/ALNS structure mutated")
                    if any(x["oracle_calls"]>3 for x in outcomes.values()):
                        raise RuntimeError("Modified CVX oracle quota")
                    row["arms"]=outcomes
                    print("P6B_FRESH_STRICT_CASE="+json.dumps({
                        "scene":scene,"profile":profile,"seed":seed,
                        "strict":{a:x["strict_both_recovered"] for a,x in outcomes.items()},
                        "calls":{a:x["oracle_calls"] for a,x in outcomes.items()},
                        "new_joint":{a:x["postbound"]["extra_joint_passing"]
                                     for a,x in outcomes.items()},
                    },ensure_ascii=False),flush=True)
                except Exception as exc:
                    err={"profile":profile,"seed":seed,
                         "type":type(exc).__name__,"message":str(exc)}
                    row["error"]=err
                    payload["errors"].append(err)
                    protocol["errors"].append(err)
                write_json(repaired_path,payload)
        payload["complete"]=True
        payload["summary"]={
            "source_pressure_attempts":len(payload["rows"]),
            "eligible_failed_D":sum(r["eligible"] for r in payload["rows"]),
            "original_source_stage1_statuses":dict(Counter(
                r["original_stage1_status"] for r in payload["rows"])),
            "strict_restorations":{a:sum(
                bool(r["arms"].get(a,{}).get("strict_both_recovered",False))
                for r in payload["rows"]) for a in ARMS},
            "total_Stage1_exact_calls":{a:sum(
                r["arms"].get(a,{}).get("oracle_calls",0)
                for r in payload["rows"]) for a in ARMS},
            "unexpected_errors":len(payload["errors"]),
        }
        write_json(repaired_path,payload)
        protocol["complete"]=True
        protocol["original_sources"]=len(snapshot["rows"])
        protocol["original_source_sha256"]=original_sha
        protocol["eligible_failed_D"]=payload["summary"]["eligible_failed_D"]
        protocol["strict_restorations"]=payload["summary"]["strict_restorations"]
        write_json(protocol_path,protocol)
        print("P6B_FRESH_SCENE_SUMMARY="+json.dumps({
            "scene":scene,**payload["summary"]
        },ensure_ascii=False),flush=True)
        if payload["errors"]:
            raise RuntimeError(f"P6b frozen holdout errors {payload['errors'][:2]}")
        return payload
    except Exception as exc:
        protocol["errors"].append({
            "type":type(exc).__name__,"message":str(exc)})
        write_json(protocol_path,protocol)
        raise


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene",type=int,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args()
    run(a.scene,a.output_dir)
