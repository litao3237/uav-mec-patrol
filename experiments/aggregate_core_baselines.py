from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from typing import Any


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result: {path}")
        rows.extend(payload.get("rows", []))
    if not rows:
        raise ValueError(f"No rows found in {input_dir}")
    return rows


def _method_rows(
    rows: list[dict[str, Any]],
    method: str,
) -> list[dict[str, Any]]:
    if method != "greedy_repair":
        return rows

    # Greedy+MEC repair is deterministic for a fixed instance and does not
    # depend on algorithm_seed. Deduplicate repeated matrix copies so its
    # feasibility count reflects unique scenarios rather than pseudo-replicates.
    unique: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in rows:
        key = (
            int(row["K"]),
            int(row["E"]),
            int(row["scenario_seed"]),
        )
        unique.setdefault(key, row)
    return list(unique.values())


def _method_summary(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    effective_rows = _method_rows(rows, method)
    statuses = [
        row[method]["stage1_status"]
        for row in effective_rows
    ]
    energies = [
        float(row[method]["energy_j"])
        for row in effective_rows
        if row[method]["energy_j"] is not None
    ]
    return {
        "runs": len(effective_rows),
        "strict_optimal": sum(status == "optimal" for status in statuses),
        "strict_rate": (
            sum(status == "optimal" for status in statuses)
            / len(effective_rows)
            if effective_rows
            else 0.0
        ),
        "mean_energy_j": mean(energies) if energies else None,
        "median_energy_j": median(energies) if energies else None,
    }


def _paired(rows: list[dict[str, Any]], baseline: str) -> dict[str, Any]:
    gains: list[float] = []
    for row in rows:
        base = row[baseline]["energy_j"]
        hybrid = row["hybrid"]["energy_j"]
        if base is None or hybrid is None:
            continue
        gains.append(
            100.0
            * (float(base) - float(hybrid))
            / max(1.0, abs(float(base)))
        )
    return {
        "comparable": len(gains),
        "hybrid_better": sum(gain > 1e-9 for gain in gains),
        "equal": sum(abs(gain) <= 1e-9 for gain in gains),
        "baseline_better": sum(gain < -1e-9 for gain in gains),
        "mean_hybrid_advantage_pct": mean(gains) if gains else None,
        "median_hybrid_advantage_pct": median(gains) if gains else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _load_rows(Path(args.input_dir))
    aggregate = {
        "methods": {
            method: _method_summary(rows, method)
            for method in (
                "greedy_repair",
                "generic_alns",
                "hybrid",
            )
        },
        "paired": {
            "hybrid_vs_greedy_repair": _paired(
                rows,
                "greedy_repair",
            ),
            "hybrid_vs_generic_alns": _paired(
                rows,
                "generic_alns",
            ),
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "aggregate": aggregate,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(json.dumps(aggregate, indent=2, ensure_ascii=False))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
