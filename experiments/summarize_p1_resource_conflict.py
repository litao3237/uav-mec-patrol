"""Summarize immutable development-only P1 resource-conflict audit records."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean


def aggregate(blocks):
    if sorted(blocks)!=[85,86,87,88]:
        raise ValueError("Four frozen scenario files are required")
    cases=[]
    for scene,block in sorted(blocks.items()):
        if (not block.get("complete") or block.get("errors") or
                block["protocol"]["scenario"]!=scene or
                block["protocol"]["id"]!="p1_frozen_resource_conflict_attribution_v1"):
            raise RuntimeError("Incomplete or erroneous resource conflict block")
        cases.extend(block["rows"])
    if len(cases)!=22 or len({(r["scenario"],r["profile"],r["seed"])
                             for r in cases})!=len(cases):
        raise RuntimeError("Expected 22 distinct frozen conditional failures")
    status=Counter()
    qos=Counter()
    capacity=Counter()
    family=Counter()
    first_control_bad=[]
    candidates_by_family=Counter()
    qualified_by_family=Counter()
    extra_cases=[]
    lineage_cases=[]
    case_report=[]
    for row in cases:
        if not row.get("diagnosis_complete"):
            raise RuntimeError("Incomplete case "+str((row["scenario"],row["profile"],row["seed"])))
        short=row["candidate_results"]
        for idx,r in enumerate(short):
            status[r["stage1_solver_status"] or "missing"]+=1
            candidates_by_family[r["family"]]+=1
            if r["stage1_qualified"]:
                qualified_by_family[r["family"]]+=1
            if idx>=3 and r["stage1_qualified"]:
                extra_cases.append({
                    "scene":row["scenario"],"seed":row["seed"],
                    "profile":row["profile"],"rank":idx+1,
                    "strict_both":bool((r.get("stage2_complete_audit") or {}).get("strict_both_qualified")),
                    "energy_j":r.get("stage1_energy_j"),"family":r["family"],
                    "path":r["path"],
                })
            if r.get("elastic"):
                e=r["elastic"]
                x=e.get("qos_only")
                if x is not None:
                    label=("positive_control" if r["stage1_qualified"] else "failed")
                    if not x.get("numerically_credible"):
                        qos[label+"_uncertain"]+=1
                    elif (x.get("normalized_total_elastic_slack") or 0)>0.002:
                        qos[label+"_positive_slack"]+=1
                        top=x.get("top_constraints") or []
                        if top: family[top[0]["family"]]+=1
                        if label=="positive_control":
                            first_control_bad.append({
                                "scene":row["scenario"],"profile":row["profile"],
                                "seed":row["seed"],"rank":idx+1,"qos":x,
                            })
                    else:
                        qos[label+"_near_zero"]+=1
                c=e.get("mec_capacity_only")
                if c is not None:
                    tag=("credible" if c.get("numerically_credible")
                         else ("infeasible" if c.get("status") in (
                                "infeasible","infeasible_inaccurate") else "uncertain"))
                    capacity[tag]+=1
                    if tag=="credible":
                        capacity["positive_capacity_slack" if
                            (c.get("normalized_total_elastic_slack") or 0)>0.002 else
                            "near_zero_capacity_slack"]+=1
        atomic_path=next((r for r in short if r["stage1_qualified"]
                          and r["has_atomic_ancestor"]),None)
        if atomic_path is not None:
            lineage_cases.append({
                "scene":row["scenario"],"seed":row["seed"],
                "profile":row["profile"],"family":atomic_path["family"],
                "rank":atomic_path["rank"],"path":atomic_path["path"],
                "node_hash":atomic_path["node_hash"],
            })
        case_report.append({
            "scenario":row["scenario"],"profile":row["profile"],"seed":row["seed"],
            "source_queue":row["source_queue_certificate"],
            "top3_reproduced":row["frozen_shortlist_reproduced"],
            "saved_success":row["previous_strict_recovered"],
            "stage1_check_count":len(short),
            "stage1_passes_first3":sum(x["stage1_qualified"] for x in short[:3]),
            "stage1_passes_extra":sum(x["stage1_qualified"] for x in short[3:]),
            "queue_passed_states":row["search_summary"]["queue_passed"],
            "top3_labels":[x["label"] for x in short[:3]],
            "top3_paths":[x["path"] for x in short[:3]],
        })
    summary={
        "independent_scenes":4,
        "nested_seed_cases":22,
        "frozen_original_top3_reproduced":sum(x["top3_reproduced"] for x in case_report),
        "frozen_original_top3_changed":sum(not x["top3_reproduced"] for x in case_report),
        "eligible_strict_old_atomic":sum(r["previous_strict_recovered"] for r in cases),
        "source_certificates":{
            "local_deadline_present":sum(
                r["source_queue_certificate"]["deadline_by_mode"].get("local",0)>0
                for r in cases),
            "mec_deadline_present":sum(
                r["source_queue_certificate"]["deadline_by_mode"].get("offload",0)>0
                for r in cases),
            "average_budget_excess_present":sum(
                r["source_queue_certificate"]["avg_delay_excess_s"]>0 for r in cases),
            "cycle_budget_excess_present":sum(
                r["source_queue_certificate"]["cycle_excess_s"]>0 for r in cases),
            "by_profile":dict(Counter(r["profile"] for r in cases)),
        },
        "strict_solver_status":dict(status),
        "exact_stage1_candidate_count":sum(len(r["candidate_results"]) for r in cases),
        "checked_inside_top3":sum(min(3,len(r["candidate_results"])) for r in cases),
        "checked_beyond_top3":sum(max(0,len(r["candidate_results"])-3) for r in cases),
        "stage1_pass_beyond_top3":len(extra_cases),
        "strict_full_stage2_pass_beyond_top3":sum(x["strict_both"] for x in extra_cases),
        "qos_elastic":dict(qos),
        "capacity_only_counterfactual":dict(capacity),
        "positive_qos_top_family":dict(family),
        "examined_by_final_move_family":dict(candidates_by_family),
        "stage1_qualified_by_final_move_family":dict(qualified_by_family),
        "stage1_qualified_with_atomic_ancestor":len(lineage_cases),
        "elastic_positive_control_warnings":first_control_bad,
        "extra_stage1_cases":extra_cases,
        "qualified_with_atomic_ancestor_cases":lineage_cases,
        "case_audit":case_report,
    }
    return summary


def report(a):
    s=a["source_certificates"]
    lines=[
        "# P1 离散候选—连续资源失败归因（原始 S85–S88 的研发重放）",
        "",
        "这是已观察过的四个场景上的**诊断**，不是新的独立样本，也不是端到端等预算 ALNS 对比。",
        "原始 `develop`、原始 P1 两阶段严格验收、物理参数与数据均未修改。",
        "",
        f"原始严格 P1 的 22 个失败 D 中有 {s['local_deadline_present']} 个包含本地任务截止时间的必要下界冲突，{s['mec_deadline_present']} 个包含 MEC 卸载任务截止时间的必要下界冲突；部分重叠。",
        f"全组中 {s['average_budget_excess_present']} 个涉及平均时延必要下界；{s['cycle_budget_excess_present']} 个涉及 UAV 周期必要下界。",
        "",
        f"冻结果前3标签复现 {a['frozen_original_top3_reproduced']}/{a['nested_seed_cases']}；不匹配 {a['frozen_original_top3_changed']}（如不为0，应限制机制结论）。",
        f"扩展诊断最多8次严格Stage1检查，总共 {a['exact_stage1_candidate_count']} 次，其中原限额之外 {a['checked_beyond_top3']} 次。",
        f"名额之外通过Stage1 {a['stage1_pass_beyond_top3']} 次；并完整通过最终Stage1+Stage2 {a['strict_full_stage2_pass_beyond_top3']} 次（**仅为额外诊断上界**）。",
        "",
        "## 固定离散结构弹性模型结果",
        "",
        "QoS-only 松弛模型固定所有 MEC 站点 CPU/带宽容量，只放松截止时间、平均时延、周期、电池；诊断不用于原算法决策与接受。",
        f"- QoS 诊断分布：`{a['qos_elastic']}`。",
        f"- 可信正松弛第1位约束族：`{a['positive_qos_top_family']}`。",
        f"- 保持时序硬约束、仅假设扩充 MEC CPU/带宽的结果：`{a['capacity_only_counterfactual']}`。",
        f"- 已严格通过 Stage1 的数值阳性对照却显示明显QoS冲突：{len(a['elastic_positive_control_warnings'])}（若非0应先排查模型/数值）。",
        "",
        "## 搜索机制",
        "",
        f"被精确检查的候选末步家族分布：`{a['examined_by_final_move_family']}`；其中Stage1合格：`{a['stage1_qualified_by_final_move_family']}`。",
        f"Stage1合格且祖先路径曾使用原子操作：{a['stage1_qualified_with_atomic_ancestor']} 条候选（不是独立成功场景数）。",
        "",
        "**诊断边界：** 超出原前3候选名额的精确评价属于额外算力，只用于发现筛选误差；弹性优化最小松弛不是 IIS/严格因果归因，`infeasible` 状态也不是全问题的数学不可行证明。",
        "正式论文结论及 `develop` 不因这一轮研发样本改变。",
        "",
    ]
    return "\n".join(lines)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    p=ap.parse_args()
    files=sorted(p.input_dir.rglob("p1-resource-S*.json"))
    blocks={}
    for path in files:
        x=json.loads(path.read_text(encoding="utf-8"))
        scene=x["protocol"]["scenario"]
        if scene in blocks: raise ValueError("Duplicate scene "+str(scene))
        blocks[scene]=x
    out=aggregate(blocks)
    p.output_dir.mkdir(parents=True,exist_ok=True)
    (p.output_dir/"summary.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (p.output_dir/"report.md").write_text(report(out),encoding="utf-8")
    print("P1_RESOURCE_AGGREGATE="+json.dumps(
        {k:v for k,v in out.items() if k not in (
            "case_audit","extra_stage1_cases","qualified_with_atomic_ancestor_cases",
            "elastic_positive_control_warnings",
        )},ensure_ascii=False),flush=True)
