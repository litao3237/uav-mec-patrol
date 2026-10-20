"""复验论文消融的 36 个共享 B-ALNS 起点和 180 条强化记录。"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from aggregate_seven_methods import require, scenario_summary
from manage_results import ROOT, sha256, verify_recorded_file
from uav_mec.analysis.archive_audit import assert_audit_equivalent
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import (
    content_hash, restore_instance, restore_solution, write_json,
)

SCALES = (30, 50, 70, 80)
SCENARIOS = (45, 46, 47)
SEEDS = (100, 101, 102)
PROFILES = ("full", "no-route", "no-contact", "no-batch", "no-widening")


def aggregate(root: Path, archived: bool) -> list[dict]:
    """以原共享探索快照复验残差；不以新搜索结果替代机制对照。"""
    index = {}
    for tasks in SCALES:
        for scene in SCENARIOS:
            replay = root / "replay" / f"replay_K{tasks}_S{scene}.json"
            baseline = root / "baselines" / f"metrics_K{tasks}_S{scene}.json"
            if archived:
                for path in (replay, baseline):
                    verify_recorded_file(path, "ablation/" + path.relative_to(root).as_posix())
            block = json.loads(replay.read_text(encoding="utf-8"))
            original = json.loads(baseline.read_text(encoding="utf-8"))
            require(block["complete"] and block["ablation_included"], f"消融块未完成：{replay}")
            require(sha256(baseline) == block["source_sha256"], f"起点字节变化：{baseline}")
            instance = restore_instance(original["instance"])
            require(content_hash(instance) == block["instance_sha256"], "实例身份不一致")
            expected = {(seed, profile) for seed in SEEDS for profile in PROFILES}
            seen = set()
            for row in block["rows"]:
                key = row["algorithm_seed"], row["profile"]
                require(key in expected and key not in seen, f"重复或额外消融记录：{key}")
                seen.add(key)
                require((row["tasks"], row["scenario_seed"]) == (tasks, scene), "消融场景错误")
                solution = restore_solution(row["solution"])
                require(content_hash(solution) == row["solution_sha256"], "方案身份不一致")
                base = next(r for r in original["rows"]
                            if r["method"] == "B-ALNS" and r["algorithm_seed"] == key[0])
                require(row["base_solution_sha256"] == base["solution_sha256"], "共享起点不一致")
                for number in (1, 2):
                    stage = row[f"stage{number}"]
                    if stage is None:
                        require(number == 2 and key[1] != "full", "完整方法缺少阶段记录")
                        continue
                    if not stage["available"]:
                        require(not stage["qualified"], "缺少变量却标记合格")
                        continue
                    # 消融目标为 Stage-1 能耗；仅 full 另存 Stage-2，不能替其他消融补造。
                    limit = (row["resources"]["energy_stage1_j"]
                             + row["resources"]["diagnostics"]["energy_tolerance_j"]) if number == 2 else None
                    audit = audit_both_timelines(instance, solution, stage["values"], energy_limit_j=limit)
                    assert_audit_equivalent(audit, stage["audit"], f"{replay.name}/{key}/{number}")
                    qualified = stage["status"] == "optimal" and all(
                        a["passed"] and a["complete"] for a in audit.values())
                    require(qualified == stage["qualified"], "残差资格被修改")
                require(not row["base_stage1_qualified"] or row["stage1"]["qualified"], "基线合格但强化失效")
                if row["strict_pair"]:
                    require(row["final_energy_j"] <= row["base_energy_j"] + 1e-6, "强化后能耗增加")
                index[tasks, scene, *key] = {k: row[k] for k in ("strict_pair", "final_energy_j")}
            require(seen == expected, "消融矩阵不完整")
            logging.info("复验消融 K%s S%s", tasks, scene)
    summaries = []
    for tasks in SCALES:
        for profile in PROFILES[1:]:
            observations = []
            for scene in SCENARIOS:
                for seed in SEEDS:
                    baseline = index[tasks, scene, seed, profile]
                    full = index[tasks, scene, seed, "full"]
                    if baseline["strict_pair"] and full["strict_pair"]:
                        observations.append({"scenario_seed": scene, "value": 100 * (
                            baseline["final_energy_j"] - full["final_energy_j"]) / baseline["final_energy_j"]})
            summaries.append({"tasks": tasks, "profile": profile, "planned": 9,
                              **scenario_summary(observations)})
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archived", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = aggregate(args.input_dir, args.archived)
    if args.archived:
        expected = json.loads((ROOT / "results/ablation/summary.json").read_text(encoding="utf-8"))
        assert_audit_equivalent(summary, expected, "消融统计")
    write_json(args.output, summary)
    print("180 条消融记录复验通过。")


if __name__ == "__main__":
    main()
