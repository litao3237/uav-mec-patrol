"""Fresh S85-S88 K80 paired validation of atomic UAV-MEC feasibility repairs.

Independent scenarios S85-S88 and nested seeds A125-A126 are fixed before
examining the S81-S84 atomic-repair pilot. Generate original B-ALNS/ESI
checkpoints, then compare four frozen conditional rescue arms on the same
failed structure: queue2, queue4, atomic double-offload/batch split and
atomic version also allowing paired cross-UAV relocation.

This is NOT yet an equal-end-to-end full ALNS comparison: the original
ALNS exploration checkpoint is common and prepaid, then each repair arm
is timed and audited separately. All original qualification failures
remain in the source archive, including numerical uncertainty.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiment_common import current_source_hashes, provenance
from run_model_sensitivity import run_block as run_source
from run_atomic_batch_study import run as run_rescue
from atomic_batch_search import ARMS
from progressive_bridge_core import PROFILES
from uav_mec.analysis.experiment_snapshot import write_json


FRESH_SCENARIOS=(85,86,87,88)
ALGORITHM_SEEDS=(125,126)
PHYSICAL_PROFILES="baseline,"+",".join(PROFILES)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario",type=int,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    if args.scenario not in FRESH_SCENARIOS:
        raise ValueError("Holdout uses only pre-registered S85-S88")
    if args.output_dir.exists() and list(args.output_dir.glob("*.json")):
        raise FileExistsError("Do not overwrite a previous holdout attempt")
    args.output_dir.mkdir(parents=True,exist_ok=True)

    S=args.scenario
    source=args.output_dir/f"atomic-fresh-source-K80_S{S}.json"
    rescue=args.output_dir/f"atomic-K80_S{S}.json"
    record=args.output_dir/f"atomic-protocol-K80_S{S}.json"
    protocol={
        "complete":False,
        "id":"p1_atomic_uav_mec_fresh_scenarios_v1",
        "tasks":80,"scenario":S,
        "independent_new_scenarios":list(FRESH_SCENARIOS),
        "nested_algorithm_seeds":list(ALGORITHM_SEEDS),
        "original_algorithm_iterations":100,
        "original_elite_rounds":2,
        "fixed_stress_profiles":list(PROFILES),
        "all_arms_same_frozen_original_failed_D":True,
        "infeasible_original_source_structures_only":True,
        "frozen_arm_names":list(ARMS),
        "original_depth2_width2":True,
        "new_arms_depth4_width2":True,
        "strict_cvx_candidate_cap_per_arm":3,
        "soft_generation_time_cap_s":4.0,
        "development_scenarios_S81_S84_not_counted_as_holdout":True,
        "end_to_end_global_ALNS_time_fairness_NOT_established":True,
        "source_hashes":current_source_hashes(Path(__file__)),
        "provenance":provenance(),
        "errors":[],
    }
    write_json(record,protocol)
    try:
        from argparse import Namespace
        run_source(Namespace(
            config=Path("configs/baseline.yaml"),
            tasks=80,
            scenario=S,
            seeds="125,126",
            iterations=100,
            elite_rounds=2,
            profiles=PHYSICAL_PROFILES,
            output=source,
        ))
        result=run_rescue(Namespace(
            input=source,
            output=rescue,
            profiles=",".join(PROFILES),
            seeds="125,126",
            beam_width=2,
            depth=4,
            exact_limit=3,
            generation_cap_s=4.0,
        ))
        protocol["complete"]=True
        protocol["source_original_result_records"]=len(
            json.loads(source.read_text(encoding="utf-8"))["rows"]
        )
        protocol["eligible_failed_source_states"]=sum(
            row["eligible"] for row in result["rows"]
        )
        protocol["strict_restorations"]={
            a:sum(
                bool(r["arms"].get(a,{}).get("strict_both_recovered"))
                for r in result["rows"]
            ) for a in ARMS
        }
        write_json(record,protocol)
        print("ATOMIC_HOLDOUT_SUMMARY="+json.dumps({
            "scenario":S,
            "eligible":protocol["eligible_failed_source_states"],
            "strict_recovered":protocol["strict_restorations"],
            "source_methods":protocol["source_original_result_records"],
        },ensure_ascii=False),flush=True)
    except Exception as exc:
        protocol["errors"].append({
            "type":type(exc).__name__,"message":str(exc),
        })
        write_json(record,protocol)
        raise


if __name__=="__main__":
    main()
