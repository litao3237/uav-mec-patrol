"""Independent frozen P3 conditional repair holdout, scenarios S89-S92.

S89-S92 and algorithm seeds A127/A128 were not used for P0/P1/P2/P3
operator design. The full source B-ALNS / ESI-ALNS numerical model,
physical stress profiles and four repair arms are FROZEN before reading
new scenario outcomes. Strict Stage1+Stage2 is always the real published
P1-R model and independent residual qualification.

The source generation is pre-paid here, so arm comparisons measure only
the subsequent *conditional failed-D repair*. NOT a full equal-time ALNS
performance comparison. All original solver failures preserved.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from experiment_common import provenance,current_source_hashes
from run_model_sensitivity import run_block as original_source
from run_p3_cpu_certificate_probe import _arm,ARMS
from progressive_bridge_core import PROFILES
from uav_mec.analysis.experiment_snapshot import (
    content_hash,restore_instance,restore_solution,write_json,
)

NEW_SCENARIOS=(89,90,91,92)
ALGORITHM_SEEDS=(127,128)
PROFILE_SEQUENCE=("baseline",)+PROFILES


def run(scene,output_dir):
    if scene not in NEW_SCENARIOS:
        raise ValueError("Only four pre-registered unseen P3 scenarios")
    if output_dir.exists() and list(output_dir.iterdir()):
        raise FileExistsError("Never replace a prior frozen holdout attempt")
    output_dir.mkdir(parents=True,exist_ok=True)
    original_path=output_dir/f"p3-fresh-source-K80_S{scene}.json"
    result_path=output_dir/f"p3-fresh-rescue-K80_S{scene}.json"
    protocol_path=output_dir/f"p3-fresh-protocol-K80_S{scene}.json"
    control={
        "complete":False,
        "id":"P3_frozen_CPU_certificate_holdout_S89_S92_v1",
        "scenario":scene,
        "tasks":80,
        "independent_scenario_seeds":list(NEW_SCENARIOS),
        "nested_algorithm_seeds":list(ALGORITHM_SEEDS),
        "original_B_ALNS_iterations":100,
        "original_ESI_elite_rounds":2,
        "same_physical_profiles":list(PROFILE_SEQUENCE),
        "four_frozen_repair_arms":list(ARMS),
        "repair_beam_width":2,
        "repair_max_depth":4,
        "repair_candidate_generation_soft_cap_s":4.,
        "repair_strict_Stage1_CVX_quota":3,
        "frozen_source_generation_prepaid":True,
        "not_a_full_equal_end_to_end_time_ALNS_comparison":True,
        "all_failed_and_uncertain_B_ESI_outcomes_preserved":True,
        "source_code_hashes":current_source_hashes(Path(__file__)),
        "provenance":provenance(),
        "errors":[],
    }
    write_json(protocol_path,control)
    raw=None
    try:
        from argparse import Namespace
        original_source(Namespace(
            config=Path("configs/baseline.yaml"),
            tasks=80,
            scenario=scene,
            seeds="127,128",
            iterations=100,
            elite_rounds=2,
            profiles=",".join(PROFILE_SEQUENCE),
            output=original_path,
        ))
        raw=json.loads(original_path.read_text(encoding="utf-8"))
        proto=raw["protocol"]
        if (not raw.get("complete") or
            proto["id"]!="uav_mec_one_factor_coupling_sensitivity_v1" or
            int(proto["independent_scenario_seed"])!=scene or
            list(proto["algorithm_seeds"])!=list(ALGORITHM_SEEDS)):
            raise ValueError("Original source identity mismatch")
        source_idx={
            (r["profile"],int(r["seed"]),r["method"]):r
            for r in raw["rows"]
        }
        payload={
            "complete":False,
            "protocol":{
                "id":"P3_CPU_certificate_independent_conditional_repair_v1",
                "scenario":scene,"tasks":80,
                "nested_seeds":list(ALGORITHM_SEEDS),
                "frozen_original_source_sha256":content_hash(raw),
                "frozen_original_P1R_unchanged":True,
                "strict_stage1_stage2_saved_reconstructed_audit":True,
                "same_failed_D_across_all_arms":True,
                "each_arm_max_CVX_quota":3,
                "sample_roles":"new_holdout_first_use",
                "four_pre_registered_arms":list(ARMS),
                "frozen_candidate_generation_cap_s":4.,
                "not_equal_walltime_full_algorithm":True,
                "source_hashes":current_source_hashes(Path(__file__)),
            },
            "rows":[],
            "errors":[],
        }
        write_json(result_path,payload)
        for profile in PROFILES:
            s=raw["profiles"][profile]
            instance=restore_instance(s["instance"])
            if content_hash(instance)!=s["instance_sha256"]:
                raise RuntimeError("Original instance checksum changed")
            for seed in ALGORITHM_SEEDS:
                old=source_idx[profile,seed,"B-ALNS"]
                original_diag=((old.get("resources") or {}).get("diagnostics") or {})
                status=original_diag.get("stage1_status")
                if "solution" not in old:
                    raise RuntimeError("B source discrete structure missing")
                sol=restore_solution(old["solution"])
                baseline_sha=content_hash(sol)
                if baseline_sha!=old["solution_sha256"]:
                    raise RuntimeError("Source B-ALNS discrete SHA mismatch")
                row={
                    "scenario":scene,"profile":profile,"seed":seed,
                    "source_solution_sha256":baseline_sha,
                    "source_stage1_status":status,
                    "source_stage1_qualified":bool(old["stage1_qualified"]),
                    "source_stage2_qualified":bool(old["stage2_qualified"]),
                    "eligible_for_fixed_D_repair":status=="infeasible_precheck",
                    "arms":{},
                }
                payload["rows"].append(row)
                write_json(result_path,payload)
                if not row["eligible_for_fixed_D_repair"]:
                    continue
                for arm in ARMS:
                    try:
                        attempt=_arm(instance,sol,arm)
                        if content_hash(sol)!=baseline_sha:
                            raise RuntimeError("Frozen B source mutated")
                        if attempt["oracle_calls"]>3:
                            raise RuntimeError("Strict oracle quota exceeded")
                        row["arms"][arm]=attempt
                        print("P3_FRESH_RESCUE="+json.dumps({
                            "scene":scene,"profile":profile,"seed":seed,
                            "arm":arm,"strict":attempt["strict_both_recovered"],
                            "calls":attempt["oracle_calls"],
                            "wall":round(attempt["total_wall_s"],4),
                        },ensure_ascii=False),flush=True)
                    except Exception as exc:
                        problem={
                            "profile":profile,"seed":seed,"arm":arm,
                            "type":type(exc).__name__,"message":str(exc),
                        }
                        row["arms"][arm]={"error":problem,
                                          "strict_both_recovered":False}
                        payload["errors"].append(problem)
                        control["errors"].append(problem)
                    write_json(result_path,payload)
        payload["complete"]=True
        payload["summary"]={
            "original_pressure_sources":len(payload["rows"]),
            "eligible_precheck_failures":sum(r["eligible_for_fixed_D_repair"]
                                             for r in payload["rows"]),
            "original_status_counts":dict(Counter(r["source_stage1_status"]
                                                  for r in payload["rows"])),
            "strict_recovery":{
                arm:sum(
                    bool(r["arms"].get(arm,{}).get("strict_both_recovered",False))
                    for r in payload["rows"]
                ) for arm in ARMS
            },
            "unexpected_errors":len(payload["errors"]),
        }
        write_json(result_path,payload)
        control["complete"]=True
        control["original_source_methods"]=len(raw["rows"])
        control["eligible_failed_sources"]=payload["summary"]["eligible_precheck_failures"]
        control["recovered"]=payload["summary"]["strict_recovery"]
        write_json(protocol_path,control)
        print("P3_FRESH_SCENE_SUMMARY="+json.dumps({
            "scene":scene,**payload["summary"]
        },ensure_ascii=False),flush=True)
        if payload["errors"]:
            raise RuntimeError(f"Unresolved P3 holdout failures {payload['errors'][:2]}")
        return payload
    except Exception as exc:
        control["errors"].append({
            "type":type(exc).__name__,"message":str(exc),
        })
        write_json(protocol_path,control)
        raise


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario",type=int,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    run(args.scenario,args.output_dir)
