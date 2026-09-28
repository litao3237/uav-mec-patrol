"""对本轮清单中的图稿执行字号、碰撞、物理尺寸及源文件验收。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from PIL import Image
from prepare_multiscale_plot_data import ROOT, require, sha256, write_json


def audit_job(job: tuple) -> dict:
    """保留每次审计的完整输出；失败带上图名与 stderr，不吞掉诊断上下文。"""
    name, arguments, destination = job
    result = subprocess.run([sys.executable, "-X", "utf8", *map(str, arguments)],
                            capture_output=True, text=True, encoding="utf-8", check=False)
    require(bool(result.stdout), f"{name} 未返回可审计结果：{result.stderr}")
    report = json.loads(result.stdout)
    write_json(destination, report)
    return {"name": name, "returncode": result.returncode, "report": destination.name,
            "summary": report.get("summary", report.get("verdict")), "stderr": result.stderr}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "paper_figures/multiscale_20260928")
    parser.add_argument("--qa-scripts", type=Path, required=True)
    args = parser.parse_args()
    out, scripts = args.output, args.qa_scripts
    manifest = json.loads((out / "figure_manifest.json").read_text("utf-8"))
    jobs = [("source", [scripts / "validate_figure.py", Path(__file__).with_name("plot_multiscale_20260928.py"), "--json"],
             out / "qa/source.json")]
    geometry = []
    for spec in manifest["figures"]:
        name = spec["name"]
        file = out / "pdf" / f"{name}.pdf"
        require(sha256(file) == spec["exports"]["pdf"]["sha256"], f"{name} PDF 已在清单生成后改动")
        with pymupdf.open(file) as doc:
            require(len(doc) == 1, f"{name} 不是单页独立图")
            page = doc[0]
            width, height = page.rect.width * 25.4 / 72, page.rect.height * 25.4 / 72
            require(abs(width - 88.9) < 0.02 and abs(height - 72) < 0.02, f"{name} 物理尺寸错误")
            text = page.get_text()
            require("Number of tasks, K" in text, f"{name} 横轴文字缺失")
            require(all(str(k) in text for k in (30, 40, 50, 60, 70, 80)), f"{name} 不含完整六规模刻度")
            labels = ("ESI-ALNS", "B-ALNS") if spec["kind"] == "paired_bar" else ("GR-MR", "FTR-NM", "RGA-MR", "B-ALNS", "ESI-ALNS")
            require(all(label in text for label in labels), f"{name} 算法图例缺失")
        for ext in ("png", "tiff"):
            with Image.open(out / ext / f"{name}.{ext}") as image:
                dpi = image.info.get("dpi", (0, 0))
                require(all(abs(value - 600) < 0.1 for value in dpi), f"{name} {ext} 不是 600 dpi")
        geometry.append({"figure": name, "width_mm": width, "height_mm": height, "raster_dpi": 600})
        jobs.extend([
            (name + "_font", [scripts / "audit_pdf_text.py", file, "--min-pt", "6.5", "--json"], out / "qa" / f"{name}.font.json"),
            (name + "_collision", [scripts / "audit_figure_collisions.py", file, "--json"], out / "qa" / f"{name}.collision.json"),
        ])
    # 各 PDF 审计相互独立，限制并发为 4，避免字体/几何分析占满本机资源。
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(audit_job, jobs))
    write_json(out / "qa/automated_qa.json", {"audits": results, "geometry": geometry,
               "all_passed": all(result["returncode"] == 0 for result in results)})
    for result in results:
        print(result["name"], result["returncode"], result["summary"])
    require(all(result["returncode"] == 0 for result in results), "存在审计失败，见 qa/automated_qa.json")


if __name__ == "__main__":
    main()
