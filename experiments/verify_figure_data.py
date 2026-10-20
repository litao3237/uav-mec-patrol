"""逐图核对冻结 CSV 与原始实验/场景汇总，验证单位换算和缺失值。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
from statistics import mean

from aggregate_seven_methods import require, scenario_summary
from manage_results import ROOT, verify_recorded_file


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def same(value: str, expected: float | None, context: str) -> None:
    """统一空值表示但不把空值变成零，允许十进制导出中的末位舍入。"""
    actual = float(value) if value else math.nan
    if expected is None:
        require(math.isnan(actual), f"{context} 缺失值被替换")
    else:
        require(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-10),
                f"{context} 图值不一致：{actual} / {expected}")


def check_summary(row: dict, summary: dict, factor: float, context: str) -> None:
    """中心、区间、样本数一并核对；负号变换必须交换区间端点。"""
    value = summary["scenario_equal_mean"]
    same(row["mean"], None if value is None else factor * value, context)
    interval = summary["descriptive_scenario_bootstrap_95"]
    transformed = sorted(factor * v for v in interval) if interval else [None, None]
    for key, val in zip(("ci_low", "ci_high"), transformed):
        same(row[key], val, context + "/" + key)
    require(int(row["independent_scenarios"]) == summary["independent_scenarios"], context)
    if "observations" in row:
        require(int(row["observations"]) == summary["valid_observations"], context)


def verify(main_raw: Path) -> dict:
    main = load(ROOT / "results/main/summary.json")
    extension = load(ROOT / "results/extension/summary.json")
    ablation = load(ROOT / "results/ablation/summary.json")
    reference = load(ROOT / "results/reference/strong.json")
    timings = defaultdict(list)
    for path in sorted(main_raw.glob("K*_S*.json")):
        verify_recorded_file(path, "main/raw/" + path.name)
        for row in load(path)["rows"]:
            if row["method"] == "ESI-ALNS":
                timings[row["tasks"]].append({"scenario_seed": row["scenario_seed"],
                                              "value": row["diagnostics"]["elite_phase_runtime_s"]})
    require(sum(map(len, timings.values())) == 144, "强化耗时原始记录不完整")
    with (ROOT / "results/extension/summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        gis = [r for r in csv.DictReader(stream) if r["study"] == "gis"]
    figures = []
    for path in sorted((ROOT / "figures/data").glob("fig*.csv")):
        number = int(path.name[3:5])
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            context = f"{path.stem}/{row}"
            if number in (5, 6):
                tasks = int(row["tasks"])
                if number == 5:
                    summary, = [r for r in main["paired_esi_differences"] if r["tasks"] == tasks
                                and r["baseline"] == "B-ALNS" and r["metric"] == "stage1_energy_j"]
                else:
                    summary = scenario_summary(timings[tasks])
                check_summary(row, summary, -.001 if number == 5 else 1., context)
            elif number == 13:
                summary, = [r for r in ablation if r["tasks"] == int(row["tasks"])
                            and r["profile"] == row["profile"]]
                check_summary(row, summary, 1., context)
            elif number == 18:
                records = [r for r in reference["rows"] if r["mode"] == "standard"
                           and r["scenario_seed"] == int(row["scenario"])]
                source, = [r for r in records if r["algorithm_seed"] == int(row["algorithm_seed"])]
                same(row["gap_pct"], source["gap_to_best_known_pct"], context)
                same(row["scenario_mean_pct"], mean(r["gap_to_best_known_pct"] for r in records), context)
            elif number >= 20:
                selected = [r for r in gis if int(r["scenario_seed"]) == int(row["scenario_seed"])
                            and r["method"] == row["method"]]
                metric = row["source_metric"]
                values = [float(r[metric]) for r in selected if r[metric]]
                factor = 100. if number == 20 else .001 if number == 21 else 1.
                for key, value in (("mean", mean(values) if values else None),
                                   ("min", min(values) if values else None),
                                   ("max", max(values) if values else None)):
                    same(row[key], factor * value if value is not None else None, context)
                require(int(row["valid_runs"]) == len(values) and int(row["planned_runs"]) == len(selected), context)
            else:
                is_extension = number in (14, 15, 16, 17)
                source = extension if is_extension else main
                matches = [r for r in source[row["subset"]] if r["method"] == row["method"]
                           and r["metric"] == row["source_metric"]]
                if is_extension:
                    study = "contact" if number in (14, 15) else "bandwidth"
                    matches = [r for r in matches if r["study"] == study and r["level"] == float(row["level"])]
                else:
                    matches = [r for r in matches if r["tasks"] == int(row["tasks"])]
                summary, = matches
                factor = (100. if number in (4, 11, 14, 16) else
                          .001 if number in (3, 12, 15, 17) else -1. if number == 10 else 1.)
                check_summary(row, summary, factor, context)
        figures.append({"figure": number, "rows": len(rows), "values_and_sample_counts_verified": True})
    require(len(figures) == 20, "实验图 CSV 不齐全")
    return {"figures": figures, "total_rows": sum(r["rows"] for r in figures)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.main_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
