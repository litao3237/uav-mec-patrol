from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


METHODS = (
    "legacy_b_alns",
    "legacy_esi",
    "time_b_alns",
    "budget_aware_terminal_first_v5",
    "budget_aware_terminal_first_v5",
)
EXPECTED_K = (50, 80)
EXPECTED_SCENARIOS = tuple(range(85, 93))
EXPECTED_ALGORITHMS = (100, 101, 102)


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
        }
    return {
        "mean": mean(values),
        "median": median(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _load(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result: {path}")
        row = payload.get("row")
        if row is None:
            raise ValueError(f"Missing row: {path}")
        rows.append(row)
    return rows


def _validate(rows: list[dict[str, Any]]) -> None:
    expected = {
        (k, scenario, algorithm)
        for k in EXPECTED_K
        for scenario in EXPECTED_SCENARIOS
        for algorithm in EXPECTED_ALGORITHMS
    }
    keys = [
        (
            int(row["K"]),
            int(row["scenario_seed"]),
            int(row["algorithm_seed"]),
        )
        for row in rows
    ]
    observed = set(keys)
    missing = sorted(expected - observed)
    duplicate = sorted(
        key for key in observed if keys.count(key) > 1
    )
    unexpected = sorted(observed - expected)
    if missing or duplicate or unexpected:
        raise ValueError(
            "Budget-aware terminal-first v5 matrix mismatch: "
            f"rows={len(rows)}, unique={len(observed)}, "
            f"missing={missing}, duplicate={duplicate}, "
            f"unexpected={unexpected}"
        )


def _method_summary(
    rows: list[dict[str, Any]],
    *,
    k: int,
    method: str,
) -> dict[str, Any]:
    records = [
        (row, row["methods"][method])
        for row in rows
        if int(row["K"]) == k
    ]
    strict = [
        (row, record)
        for row, record in records
        if (
            record.get("stage1_status") == "optimal"
            and record.get("energy_j") is not None
        )
    ]

    energies = [
        float(record["energy_j"])
        for _, record in strict
    ]
    runtimes = [
        float(record["search_runtime_s"])
        for _, record in records
    ]
    overruns = [
        float(record["budget_overrun_s"])
        for _, record in records
    ]

    strict_by_scenario: dict[int, int] = defaultdict(int)
    energy_by_scenario: dict[int, list[float]] = defaultdict(list)
    for row, record in strict:
        scenario = int(row["scenario_seed"])
        strict_by_scenario[scenario] += 1
        energy_by_scenario[scenario].append(
            float(record["energy_j"])
        )

    cvs: list[float] = []
    spreads: list[float] = []
    for values in energy_by_scenario.values():
        if len(values) >= 2:
            center = mean(values)
            if abs(center) > 1e-12:
                cvs.append(
                    100.0 * stdev(values) / abs(center)
                )
                spreads.append(
                    100.0
                    * (max(values) - min(values))
                    / abs(center)
                )

    return {
        "K": k,
        "method": method,
        "runs": len(records),
        "strict": len(strict),
        "strict_rate": len(strict) / len(records),
        "fully_strict_scenarios": sum(
            strict_by_scenario.get(scenario, 0) == 3
            for scenario in EXPECTED_SCENARIOS
        ),
        "energy_j": _stats(energies),
        "search_runtime_s": _stats(runtimes),
        "budget_overrun_s": _stats(overruns),
        "within_scenario_cv_pct": _stats(cvs),
        "within_scenario_spread_pct": _stats(spreads),
    }


def _paired(
    rows: list[dict[str, Any]],
    *,
    k: int,
    baseline: str,
) -> dict[str, Any]:
    gains: list[float] = []
    by_scenario: dict[int, list[float]] = defaultdict(list)

    for row in rows:
        if int(row["K"]) != k:
            continue
        base = row["methods"][baseline]
        v4 = row["methods"]["budget_aware_terminal_first_v5"]
        if (
            base.get("stage1_status") != "optimal"
            or v4.get("stage1_status") != "optimal"
            or base.get("energy_j") is None
            or v4.get("energy_j") is None
        ):
            continue

        gain = (
            100.0
            * (
                float(base["energy_j"])
                - float(v4["energy_j"])
            )
            / max(1.0, abs(float(base["energy_j"])))
        )
        gains.append(gain)
        by_scenario[int(row["scenario_seed"])].append(gain)

    scenario_means = {
        scenario: mean(values)
        for scenario, values in sorted(by_scenario.items())
    }
    scenario_values = list(scenario_means.values())
    return {
        "K": k,
        "baseline": baseline,
        "common_strict": len(gains),
        "better": sum(value > 1e-9 for value in gains),
        "equal": sum(abs(value) <= 1e-9 for value in gains),
        "worse": sum(value < -1e-9 for value in gains),
        "run_gain_pct": _stats(gains),
        "scenario_gain_pct": _stats(scenario_values),
        "scenario_means_pct": scenario_means,
        "positive_scenarios": sum(
            value > 1e-9 for value in scenario_values
        ),
        "equal_scenarios": sum(
            abs(value) <= 1e-9 for value in scenario_values
        ),
        "negative_scenarios": sum(
            value < -1e-9 for value in scenario_values
        ),
    }


def _v5_diagnostics(
    rows: list[dict[str, Any]],
    *,
    k: int,
) -> dict[str, Any]:
    records = [
        row["methods"]["budget_aware_terminal_first_v5"]
        for row in rows
        if int(row["K"]) == k
    ]
    diags = [record["diagnostics"] for record in records]
    selection_counts = Counter(
        str(diag.get("selection_source", "unknown"))
        for diag in diags
    )

    def values(name: str) -> list[float]:
        return [
            float(diag.get(name, 0.0))
            for diag in diags
        ]

    return {
        "selection_counts": dict(
            sorted(selection_counts.items())
        ),
        "strict_incumbent_available": sum(
            bool(
                diag.get(
                    "strict_incumbent_found",
                    False,
                )
            )
            for diag in diags
        ),
        "checkpoint_attempted": sum(
            bool(diag.get("checkpoint_attempted", False))
            for diag in diags
        ),
        "checkpoint_succeeded": sum(
            bool(diag.get("checkpoint_succeeded", False))
            for diag in diags
        ),
        "checkpoint_runtime_s": _stats(
            values("checkpoint_runtime_s")
        ),
        "elite_triggers": _stats(values("elite_triggers")),
        "elite_strict_improvements": _stats(
            values("elite_strict_improvements")
        ),
        "elite_injections": _stats(
            values("elite_injections")
        ),
        "elite_runtime_s": _stats(values("elite_runtime_s")),
        "in_search_certification_runtime_s": _stats(
            values("in_search_certification_runtime_s")
        ),
        "terminal_certification_runtime_s": _stats(
            values("terminal_certification_runtime_s")
        ),
        "oracle_calls": _stats(values("oracle_calls")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _load(Path(args.input_dir))
    _validate(rows)

    summaries = [
        _method_summary(rows, k=k, method=method)
        for k in EXPECTED_K
        for method in METHODS
    ]
    paired = [
        _paired(rows, k=k, baseline=baseline)
        for k in EXPECTED_K
        for baseline in (
            "legacy_b_alns",
            "legacy_esi",
            "time_b_alns",
            "terminal_first_esi_v4",
        )
    ]
    diagnostics = {
        str(k): _v5_diagnostics(rows, k=k)
        for k in EXPECTED_K
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "summaries": summaries,
                "paired": paired,
                "v5_diagnostics": diagnostics,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for item in summaries:
        print(
            f"K={item['K']} {item['method']}: "
            f"strict={item['strict']}/{item['runs']} "
            f"fullS={item['fully_strict_scenarios']}/8 "
            f"E={item['energy_j']['mean']} "
            f"CV={item['within_scenario_cv_pct']['mean']} "
            f"runtime={item['search_runtime_s']['mean']} "
            f"overrun={item['budget_overrun_s']['mean']}"
        )

    for item in paired:
        print(
            f"PAIR K={item['K']} v5 vs {item['baseline']}: "
            f"n={item['common_strict']} "
            f"B/E/W={item['better']}/{item['equal']}/{item['worse']} "
            f"scenario_mean={item['scenario_gain_pct']['mean']} "
            f"scenario_std={item['scenario_gain_pct']['std']}"
        )

    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
