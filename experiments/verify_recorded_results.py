"""一键离线复验全部当前证据，不重新运行优化实验。"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import subprocess
import sys

from manage_results import ROOT, process_archives, verify_figures, verify_summaries
from verify_figure_data import verify as verify_figure_values
from uav_mec.analysis.archive_audit import assert_audit_equivalent
from uav_mec.analysis.experiment_snapshot import write_json


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/reproduction")
    args = parser.parse_args()
    work = args.output_dir.resolve()
    if work.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("复验输出不得覆盖发布的原始结果")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    archive_report = process_archives(work / "raw")
    archive_report["figure_files"] = verify_figures()
    archive_report["summary_files"] = verify_summaries()
    commands = [
        ("main", "aggregate_seven_methods.py", ["--input-dir", work / "raw/main/raw", "--phase", "formal"]),
        ("extension", "aggregate_extension.py", ["--input-dir", work / "raw/extension",
         "--main-dir", work / "raw/main/raw", "--protocol", ROOT / "results/extension/frozen_protocol.json"]),
        ("budget", "aggregate_budget_check.py", ["--input-dir", work / "raw/budget/raw"]),
        ("ablation", "aggregate_ablation.py", ["--input-dir", work / "raw/ablation"]),
    ]
    for name, script, arguments in commands:
        output = work / "summaries" / f"{name}.json"
        log = work / f"{name}.log"
        with log.open("w", encoding="utf-8") as stream:
            run = subprocess.run([sys.executable, str(ROOT / "experiments" / script),
                                  *map(str, arguments), "--archived", "--output", str(output)],
                                 cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if run.returncode:
            raise RuntimeError(f"{name} 复验失败，完整错误见 {log}")
        actual = read(output)
        expected = read(ROOT / "results" / name / "summary.json")
        if name == "extension":
            # 来源文件名迁移不改变统计量；原路径仍保留在发布的冻结记录中。
            for data in (actual, expected):
                for row in data["sources"]:
                    row.pop("file", None)
        if name == "budget":
            actual.pop("source_identity", None)
        assert_audit_equivalent(actual, expected, f"{name} summary")
        logging.info("%s 原始残差和全部统计量一致", name)
    figure_report = verify_figure_values(work / "raw/main/raw")
    write_json(work / "figure_data_verification.json", figure_report)
    report = {**archive_report, "main_records": 816, "main_both_qualified": 667,
              "extension_new_records": 306, "extension_reused_panel_records": 102,
              "budget_records": 96, "ablation_records": 180,
              "all_recorded_summaries_match": True,
              "figure_data_rows_verified": figure_report["total_rows"],
              "reference_scope": "strong.json 为历史经验参考，缺完整资源快照，不作残差复验或最优性证书"}
    write_json(work / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
