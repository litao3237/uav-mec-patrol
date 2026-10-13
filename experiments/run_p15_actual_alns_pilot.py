"""P15 100-iteration original-ALNS cheap virtual MEC reuse insertion pilot.

Original ALNS/ESI code, physical model, destroy operators, roulette,
RRT and exact Stage1+Stage2 residuals are UNCHANGED. A scoped make_repair_operators hook replaces ONLY original cheapest/regret2
repair slots with cheap FIFO/EDF and hypothetical reuse checks on the
FINAL task. Every arm uses exactly ONE actual MEC builder per repair.

Original B endpoint SHA256 MUST reproduce the frozen source archive;
cheap_sham MUST reproduce it as well. It computes the same cheap
physical features without changing the original rank1 selection.
Frozen S89/S91/S93/S95/S96 are all PREVIOUSLY SEEN development cases.

This same-100-iteration pilot reports actual search/preview time, not
matched end-to-end runtime. The follow-on fully new physical scenarios
must instead use matched exploration/elite wall budgets.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from p15_cheap_virtual_contact_repair import (
    POLICIES,CheapCounters,build_cheap_repair_list,
)
from run_p7_alns_shadow_archive import ShadowPrecheckArchive
from run_p12_insertion_finish_audit import CASES
from run_seven_methods import finalize
from uav_mec.algorithms import (
    ScreenedProxyObjectiveEvaluator,Stage1CVXObjectiveOracle,
    UavMecALNSConfig,build_greedy_initial_solution,
    build_mec_assisted_initial_solution,run_uav_mec_hybrid_alns,
)
from uav_mec.algorithms.alns import runner as alns_runner
from uav_mec.analysis.experiment_snapshot import (
    restore_instance,content_hash,write_json,
)

ARMS=("original",)+POLICIES


def run_arm(instance,initial,seed,arm,*,clock_budget_s=None):
    if arm not in ARMS:raise ValueError(arm)
    observer=ShadowPrecheckArchive(
        ScreenedProxyObjectiveEvaluator(),max_saved=3)
    exact=Stage1CVXObjectiveOracle()
    counters=(CheapCounters(arm) if arm!="original" else None)
    scope=(nullcontext() if arm=="original" else
           patch.object(
               alns_runner,"make_repair_operators",
               return_value=build_cheap_repair_list(arm,counters)))
    cfg=UavMecALNSConfig(
        iterations=100 if clock_budget_s is None else 100000,
        seed=seed,enable_problem_operators=False,
        max_runtime_s=clock_budget_s,
        time_scaled_rrt=clock_budget_s is not None,
    )
    t0=perf_counter()
    with scope:
        hybrid=run_uav_mec_hybrid_alns(
            instance,initial_solution=deepcopy(initial),
            config=cfg,evaluator=observer,
            elite_rounds=2,elite_oracle=exact,
            exploration_max_runtime_s=clock_budget_s,
            elite_max_runtime_s=(2.0 if clock_budget_s is not None else None),
        )
    search_wall_s=perf_counter()-t0
    verified={}
    for key,solution in (
        ("B",hybrid.exploration.best_solution),
        ("ESI",hybrid.best_solution),
    ):
        out=finalize(
            instance,solution,method="P15_"+arm+"_"+key,
            seed=seed,initialization_s=0.,search_s=search_wall_s,
            diagnostics={"source":"P15 unchanged original_Stage1_Stage2"},
        )
        strictly=bool(out["stage1"]["qualified"] and out["stage2"]["qualified"])
        verified[key]={
            "sha256":content_hash(solution),
            "strict_stage1":bool(out["stage1"]["qualified"]),
            "strict_stage2":bool(out["stage2"]["qualified"]),
            "strict_both":strictly,
            "solver_stage1_status":out["resources"].diagnostics.get("stage1_status"),
            "energy_j":(
                float(out["resources"].energy_stage1_j)
                if strictly else None),
            "independent_resource_wall_s":float(
                out["timing"]["resource_recompute_s"]+
                out["timing"]["independent_audit_s"]),
        }
    return {
        "arm":arm,"B":verified["B"],"ESI":verified["ESI"],
        "preview":counters.snapshot() if counters is not None else None,
        "read_only_funnel":observer.summary(),
        "B_search_iterations":max(
            0,len(getattr(hybrid.exploration.raw_result.statistics,
                          "objectives",[]))-1),
        "hybrid_B_exploration_wall_s":hybrid.exploration_runtime_s,
        "hybrid_ESI_elite_wall_s":hybrid.elite_phase_runtime_s,
        "hybrid_total_wall_s":search_wall_s,
        "Stage1_Stage2_final_audit_wall_s":sum(
            out["independent_resource_wall_s"] for out in verified.values()),
        "complete_run_wall_s":(
            search_wall_s+sum(
                out["independent_resource_wall_s"] for out in verified.values())),
        "elite_skipped":hybrid.elite_stats.get("skipped"),
        "elite_CVX_oracle_calls":exact.calls,
        "same_clock_budget":clock_budget_s is not None,
    }


def run(source:Path,output:Path,selected):
    if output.exists():raise FileExistsError(output)
    original=json.loads(source.read_text(encoding="utf-8"))
    protocol=original["protocol"]
    scene=int(protocol["independent_scenario_seed"])
    if (not original.get("complete") or
        protocol["id"]!="uav_mec_one_factor_coupling_sensitivity_v1" or
        scene not in CASES):
        raise ValueError("Only frozen original paper-model source snapshots")
    cases=[(p,int(s)) for p,s in selected]
    if not cases or any(pair not in CASES[scene] for pair in cases):
        raise ValueError("Only preregistered already observed P12 research cases")
    source_rows={(r["profile"],int(r["seed"]),r["method"]):r
                 for r in original["rows"]}
    document={
        "complete":False,
        "protocol":{
            "id":"P15_cheap_hypothetical_contact_queue_preview_original_ALNS_100steps_dev_v1",
            "scene":scene,"source_sha256":content_hash(original),
            "arms":list(ARMS),
            "only_original_repair_slots_replaced":True,
            "original_destroy_roulette_RRT_score_and_CVX_unchanged":True,
            "original_top3_cheap_virtual_queue_cost_counted":True,
            "original_full_MEC_builder_once_per_repair":True,
            "original_and_cheap_sham_B_endpoint_SHA_must_replay":True,
            "same_100_iterations_NOT_equal_wall":True,
            "already_inspected_development_cases":True,
            "all_strict_outcomes_original_Stage1_Stage2":True,
        },
        "rows":[],"errors":[],
    }
    write_json(output,document)
    for profile,seed in cases:
        inst=restore_instance(original["profiles"][profile]["instance"])
        assert content_hash(inst)==original["profiles"][profile]["instance_sha256"]
        old=source_rows[profile,seed,"B-ALNS"]
        initial=build_mec_assisted_initial_solution(
            inst,base_solution=build_greedy_initial_solution(inst))
        frozen_init=content_hash(initial)
        row={
            "scene":scene,"profile":profile,"seed":seed,
            "frozen_B_endpoint_sha256":old["solution_sha256"],
            "original_frozen_initial_sha256":frozen_init,
            "arms":{},
        }
        document["rows"].append(row)
        write_json(output,document)
        for arm in ARMS:
            try:
                r=run_arm(inst,initial,seed,arm)
                if content_hash(initial)!=frozen_init:
                    raise RuntimeError("P15 mutated original initial D")
                if arm in ("original","cheap_sham") and (
                    r["B"]["sha256"]!=old["solution_sha256"]):
                    raise RuntimeError(
                        f"Original/sham identity drift: {arm}, S{scene}, "
                        f"{profile} A{seed} B={r['B']['sha256']} "
                        f"expected {old['solution_sha256']}")
                row["arms"][arm]=r
                print("P15_CHEAP_REAL_ALNS_CASE="+json.dumps({
                    "scene":scene,"profile":profile,"seed":seed,
                    "arm":arm,
                    "B_strict":r["B"]["strict_both"],
                    "ESI_strict":r["ESI"]["strict_both"],
                    "queue_D":r["read_only_funnel"]["counters"].get(
                        "queue_necessary_pass",0),
                    "joint_D":r["read_only_funnel"]["counters"].get(
                        "joint_bw_cpu_necessary_pass",0),
                    "extra_previews":(
                        r["preview"]["evaluated_positions"] if r["preview"]
                        else 0),
                    "chosen_non_rank1":(
                        r["preview"]["selected_non_top1"] if r["preview"]
                        else 0),
                    "full_wall_s":round(r["complete_run_wall_s"],3),
                },ensure_ascii=False),flush=True)
            except Exception as e:
                err={
                    "scene":scene,"profile":profile,"seed":seed,"arm":arm,
                    "type":type(e).__name__,"message":str(e)}
                row["arms"][arm]={"error":err}
                document["errors"].append(err)
            write_json(output,document)
    document["complete"]=True
    document["summary"]={
        "cases":len(document["rows"]),
        "strict_ESI":{arm:sum(
            bool(row["arms"].get(arm,{}).get("ESI",{}).get("strict_both"))
            for row in document["rows"]) for arm in ARMS},
        "original_B_SHA_reproduced":sum(
            row["arms"].get("original",{}).get("B",{}).get("sha256")
            ==row["frozen_B_endpoint_sha256"]
            for row in document["rows"]),
        "sham_B_SHA_reproduced":sum(
            row["arms"].get("cheap_sham",{}).get("B",{}).get("sha256")
            ==row["frozen_B_endpoint_sha256"]
            for row in document["rows"]),
        "unexpected_errors":len(document["errors"]),
    }
    write_json(output,document)
    print("P15_DEV_SUMMARY="+json.dumps({
        "scene":scene,**document["summary"]},ensure_ascii=False),flush=True)
    if document["errors"]:
        raise RuntimeError(f"P15 unexpected errors: {document['errors'][:3]}")
    return document


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--cases",required=True)
    args=parser.parse_args()
    run(args.source,args.output,[r.split(":") for r in args.cases.split(",")])
