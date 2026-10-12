"""First-use independent S93-S96 P5 joint-bandwidth/CPU certificate holdout.

This freezes the P5 conditional repair mechanism (identical old atomic
candidate search/beam, at most 3 CVX Stage1 oracle calls per arm) before
viewing ANY result on S93-S96.  S85-S92 are inspected development data.
Source B-ALNS and ESI-ALNS generation is performed and saved unchanged
with the same code as P1/P3 experiments. Candidate repair is then tested
on only the original B-ALNS precheck-infeasible fixed D, keeping all failed
and numerically uncertain sources visible. The original generation cost
is PREPAID: this is not a complete equal-time ALNS/ESI comparison.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiment_common import provenance,current_source_hashes
from run_model_sensitivity import run_block as make_source
from run_p5_joint_screening_probe import run as run_repair, ARMS
from uav_mec.analysis.experiment_snapshot import (
    content_hash,write_json,
)

FRESH_SCENARIOS=(93,94,95,96)
NESTED_ALGORITHM_SEEDS=(129,130)
PROFILES=("baseline","compute_x1p5","compute_x2p0",
          "deadline_x0p9","deadline_x0p8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario",type=int,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    scene=args.scenario
    if scene not in FRESH_SCENARIOS:
        raise ValueError("Only preregistered unseen S93-S96")
    if args.output_dir.exists() and list(args.output_dir.iterdir()):
        raise FileExistsError("Do not replace previous holdout artifacts")
    args.output_dir.mkdir(parents=True,exist_ok=True)

    source=args.output_dir/f"p5-fresh-source-K80_S{scene}.json"
    result=args.output_dir/f"p5-fresh-repair-K80_S{scene}.json"
    ledger=args.output_dir/f"p5-fresh-protocol-K80_S{scene}.json"
    p={
        "id":"P5_joint_BW_CPU_first_use_independent_S93_S96_v1",
        "complete":False,
        "scenario":scene,
        "tasks":80,
        "independent_scenarios":list(FRESH_SCENARIOS),
        "nested_algorithm_seeds":list(NESTED_ALGORITHM_SEEDS),
        "original_baseline_algorithms":["B-ALNS","ESI-ALNS"],
        "original_ALNS_iterations":100,
        "original_ESI_elite_rounds":2,
        "profiles":list(PROFILES),
        "P5_joint_BW_CPU_48grid_pre_registered":True,
        "P5_joint_BW_CPU_12grid_sensitivity_pre_registered":True,
        "comparators":list(ARMS),
        "each_arm_exact_stage1_CVX_quota":3,
        "all_arm_original_full_stage1_stage2_verification":True,
        "complete_source_generation_prepaid":True,
        "NOT_complete_equal_end_to_end_walltime_ALNS_comparison":True,
        "original_stage1_status_classes_preserved":True,
        "original_physical_model_unchanged":True,
        "source_hashes":current_source_hashes(Path(__file__)),
        "provenance":provenance(),
        "errors":[],
    }
    write_json(ledger,p)
    try:
        from argparse import Namespace
        make_source(Namespace(
            config=Path("configs/baseline.yaml"),
            tasks=80,
            scenario=scene,
            seeds="129,130",
            iterations=100,
            elite_rounds=2,
            profiles=",".join(PROFILES),
            output=source,
        ))
        original=json.loads(source.read_text(encoding="utf-8"))
        if (not original.get("complete")
            or original["protocol"]["id"]!="uav_mec_one_factor_coupling_sensitivity_v1"
            or int(original["protocol"]["independent_scenario_seed"])!=scene
            or list(original["protocol"]["algorithm_seeds"])!=list(NESTED_ALGORITHM_SEEDS)):
            raise RuntimeError("Frozen new physical source protocol unexpected")
        repaired=run_repair(source,result)
        if not repaired.get("complete") or repaired.get("errors"):
            raise RuntimeError("P5 independently checked repairs incomplete")
        p["complete"]=True
        p["original_physical_source_sha256"]=content_hash(original)
        p["source_results"]=len(original["rows"])
        p["original_strict_stage1"]=sum(
            bool(x.get("stage1_qualified",False))
            for x in original["rows"])
        p["original_solver_statuses"]={
            x:sum(
                ((r.get("resources") or {}).get("diagnostics") or {}).get("stage1_status")==x
                for r in original["rows"]
            ) for x in ("optimal","infeasible_precheck","infeasible","optimal_inaccurate")
        }
        p["conditional_repair_failures"]=repaired["summary"]["conditional_failed_D"]
        p["strict_repaired"] = repaired["summary"]["strict"]
        p["strict_stage1_CVX_calls"]=repaired["summary"]["total_stage1_CVX"]
        write_json(ledger,p)
        print("P5_FRESH_HOLDOUT_SUMMARY="+json.dumps({
            "scene":scene,"source_results":p["source_results"],
            "original_stage1_strict":p["original_strict_stage1"],
            "original_statuses":p["original_solver_statuses"],
            "eligible":p["conditional_repair_failures"],
            "repair_strict":p["strict_repaired"],
            "calls":p["strict_stage1_CVX_calls"]
        },ensure_ascii=False),flush=True)
        return p
    except Exception as exc:
        p["errors"].append({
            "type":type(exc).__name__,"message":str(exc),
        })
        write_json(ledger,p)
        raise


if __name__=="__main__":
    main()
