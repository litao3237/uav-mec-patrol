"""Fresh-scene cross-validation of elastic-guided repair *after policy freeze*.

Runs the exact published B-ALNS/ESI original machinery to construct a
PHYSICAL source archive, then independently builds the QoS elastic diagnosis,
then applies the locked five-arm strict Stage-1/Stage-2 repair trial.

Scenarios S71/S72/S73/S74 and algorithm seeds A117/A118 were NOT used in
the P0 operator, queue-bound or elastic-repair development experiments.
Each method starts from precisely one shared source B-ALNS failed D; no
reoptimization or ESI postprocessing occurs before per-arm rescue.

This is a diagnostic *conditional failure rescue* holdout, NOT a completed
end-to-end ALNS algorithm with a fair common wall-clock search budget.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json

from experiment_common import current_source_hashes, provenance
from run_model_sensitivity import run_block as run_source_block
from run_elastic_diagnosis import run as run_elastic_block
from run_elastic_repair import run as run_repair_block
from uav_mec.analysis.experiment_snapshot import write_json


FRESH_SCENARIOS=(71,72,73,74)
FRESH_SEEDS=(117,118)
PROFILES="baseline,compute_x1p5,compute_x2p0,deadline_x0p9,deadline_x0p8"
STRESS="compute_x1p5,compute_x2p0,deadline_x0p9,deadline_x0p8"


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--scenario",type=int,required=True)
    a.add_argument("--output-dir",type=Path,required=True)
    args=a.parse_args()
    if args.scenario not in FRESH_SCENARIOS:
        raise ValueError("Holdout scenario must be preregistered")
    if args.output_dir.exists() and list(args.output_dir.glob("*.json")):
        raise FileExistsError("Do not overwrite a previous holdout output")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    S=args.scenario
    source=args.output_dir/f"fresh-source-K80_S{S}.json"
    elastic=args.output_dir/f"fresh-elastic-K80_S{S}.json"
    rescue=args.output_dir/f"elastic-repair-K80_S{S}.json"
    record=args.output_dir/f"holdout-protocol-K80_S{S}.json"
    protocol={
        "complete":False,
        "id":"fresh_blinded_scenario_elastic_repair_holdout_v1",
        "tasks":80,
        "scenario":S,
        "nested_algorithm_seeds":list(FRESH_SEEDS),
        "stresses":STRESS,
        "all_methods_share_same_original_failed_D_within_case":True,
        "frozen_comparison_arms":[
            "greedy_mec","old_lb_joint","queue_joint",
            "elastic_rank_same_moves","elastic_targeted_joint",
        ],
        "pilot_development_scenarios":[61,62,63,64],
        "new_unseen_scenarios":list(FRESH_SCENARIOS),
        "max_strict_stage1_candidate_evaluations":3,
        "max_beam_search_depth":2,
        "max_beam_width":2,
        "full_elastic_diagnosis_time_charged_to_elastic_arms":True,
        "formal_equal_wall_time_comparison":False,
        "source_hashes":current_source_hashes(Path(__file__)),
        "provenance":provenance(),
        "errors":[],
    }
    write_json(record,protocol)
    try:
        from argparse import Namespace
        run_source_block(Namespace(
            config=Path("configs/baseline.yaml"),
            tasks=80,
            scenario=S,
            seeds="117,118",
            iterations=100,
            elite_rounds=2,
            profiles=PROFILES,
            output=source,
        ))
        run_elastic_block(Namespace(
            input=source,
            output=elastic,
            profiles=STRESS,
        ))
        outcome=run_repair_block(Namespace(
            source=source,
            elastic=elastic,
            output=rescue,
            profiles=STRESS,
            seeds="117,118",
            depth=2,beam_width=2,exact_limit=3,
        ))
        successes={
            arm:sum(
                bool(r["arms"].get(arm,{}).get("strict_both_recovered"))
                for r in outcome["rows"]
            )
            for arm in protocol["frozen_comparison_arms"]
        }
        protocol["original_source_stages"]=len(
            json.loads(source.read_text(encoding="utf-8"))["rows"]
        )
        protocol["n_eligible_source_failures"]=sum(
            bool(r["eligible"]) for r in outcome["rows"]
        )
        protocol["n_diagnostic_stage1_structures"]=len(
            json.loads(elastic.read_text(encoding="utf-8"))["rows"]
        )
        protocol["recovered_per_arm"]=successes
        protocol["complete"]=True
        write_json(record,protocol)
        print("ELASTIC_HOLDOUT_SUMMARY="+json.dumps({
            "scenario":S,
            "eligible":protocol["n_eligible_source_failures"],
            "recovered":successes,
            "algorithm_seed_count":len(FRESH_SEEDS),
        },ensure_ascii=False),flush=True)
    except Exception as exc:
        protocol["errors"].append({
            "type":type(exc).__name__,"message":str(exc),
        })
        write_json(record,protocol)
        raise


if __name__=="__main__":
    main()
