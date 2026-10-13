"""P28 immutable P27 forensic: E1 overloaded virtual pairs and task predecessors.

Consumes only exact archived P27 Stage1 and credible elastic diagnostic
results. No new posthoc candidate generation, NO model/schedule changes.
Flags the precise per-(UAV,MEC) EDF-prefix binding tasks and the modelled
FIFO predecessors to guide a NEW, independently tested structural repair.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED={(91,"compute_x1p5",128),(93,"baseline",129)}
SITES=("E1","E2")
VARIANTS=("exact_P22_swap","P24_one_offload_change",
          "P26_batch_offload_change")


def audit(collected:Path,output:Path):
    files=sorted(collected.rglob("p27-elastic-S*.json"))
    data=[json.loads(f.read_text(encoding="utf-8")) for f in files]
    errors=[]
    actual={(r["protocol"]["scene"],r["protocol"]["profile"],
             r["protocol"]["seed"]) for r in data}
    if actual!=EXPECTED or len(data)!=2:
        errors.append("Expected both frozen original P27 development sources")
    for r in data:
        if not r.get("complete"):
            errors.append("Incomplete archived P27 strict source")
    records=[]
    for r in data:
        case=(r["protocol"]["scene"],r["protocol"]["profile"],
              r["protocol"]["seed"])
        sample={"scene":case[0],"profile":case[1],"seed":case[2],"variants":{}}
        for variant in VARIANTS:
            a=r["candidates"][variant]
            bound=a["cpu_share_bound"]
            cpu=a["elastic_diagnoses"]["cpu_capacity_only"]
            qos=a["elastic_diagnoses"]["qos_only"]
            if not cpu["numerically_credible"] or not qos["numerically_credible"]:
                errors.append(f"Noncredible expected CPU/QoS elastic for {case} {variant}")
            station_data={}
            for mid in SITES:
                stat=bound["stations"][mid]
                pairs=[]
                for key,item in bound["pair_demands"].items():
                    if item["station_id"]!=mid:
                        continue
                    binding=item.get("deadline_binding") or {}
                    pairs.append({
                        "UAV":item["pair"][0],
                        "station":mid,
                        "pair":key,
                        "offloaded_tasks_on_pair":item["n_offloaded_tasks"],
                        "optimistic_static_F_required_GHz":item["needed_cpu_ghz_lb"],
                        "binding_deadline_task":binding.get("task_id"),
                        "binding_visit":binding.get("visit_id"),
                        "binding_deadline_s":binding.get("deadline_s"),
                        "binding_first_batch_lb_s":binding.get(
                            "first_batch_start_lower_s"),
                        "EDF_prefix_work_Gcycles":binding.get("prefix_work_gcycles"),
                        "available_compute_window_s":binding.get(
                            "available_compute_window_s"),
                    })
                pairs.sort(key=lambda row:(-(row["optimistic_static_F_required_GHz"] or 0),
                                           row["pair"]))
                capacity_top=[
                    v for v in cpu.get("top_constraints",[])
                    if v["constraint"]==f"mec_cpu_cap::{mid}"
                ]
                station_data[mid]={
                    "capacity_original_GHz":stat["capacity_ghz"],
                    "optimistic_total_CPU_required_GHz":stat["required_cpu_lb_ghz"],
                    "cpu_pressure_lower_ratio":stat["min_cpu_pressure_ratio"],
                    "certified_necessary_capacity_violation":stat[
                        "necessary_capacity_violation"],
                    "min_modelled_extra_CPU_GHz_in_credible_elastic_solution":
                        capacity_top[0]["physical_slack"] if capacity_top else 0.,
                    "binding_pair_details":pairs,
                }
            sample["variants"][variant]={
                "strict_original_Stage1_Stage2":a[
                    "original_strict_Stage1_Stage2"]["Stage1_and_Stage2_strict"],
                "CPU_only_elastic_credible":cpu["numerically_credible"],
                "QoS_only_elastic_credible":qos["numerically_credible"],
                "station_CPU_diagnostics":station_data,
                "top_QoS_violations":qos.get("top_constraints",[])[:8],
                "top_Deadline_compulsory_FIFO_EDF_predecessors":qos.get(
                    "top_dependency_context",[])[:8],
            }
        records.append(sample)
    out={
        "original_P1R_physics_unchanged":True,
        "read_only_existing_numerical_evidence_only":True,
        "not_independent_holdout_and_not_new_algorithm":True,
        "scenes":records,
        "errors":errors,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("P28_E1_BOTTLENECK_CHAIN="+json.dumps(out,ensure_ascii=False),flush=True)
    if errors:
        raise RuntimeError("Incomplete immutable archival attribution: "+str(errors[:3]))
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collected",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    x=p.parse_args()
    audit(x.collected,x.output)
