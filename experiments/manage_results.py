"""校验与解压当前论文原始记录；不执行求解，不覆盖不同内容。"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def sha256(path: Path) -> str:
    """流式摘要避免完整实验归档同时驻留内存。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_manifest() -> dict:
    return json.loads((RESULTS / "archive_manifest.json").read_text(encoding="utf-8"))


def safe_target(root: Path, name: str) -> Path:
    """拒绝绝对路径、反斜线和父目录跳转，并检查现有符号链接。"""
    part = PurePosixPath(name)
    if "\\" in name or ":" in name or part.is_absolute() or ".." in part.parts:
        raise ValueError(f"非法归档路径：{name}")
    target = (root / part).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError(f"归档路径越界：{name}")
    return target


def verify_recorded_file(path: Path, logical_path: str) -> None:
    """历史离线复验须绑定发布清单，不能仅凭相同文件名信任任意快照。"""
    entries = [r for a in read_manifest()["archives"] for r in a["files"]
               if r["path"] == logical_path]
    if len(entries) != 1 or sha256(path) != entries[0]["sha256"]:
        raise ValueError(f"原始记录与发布清单不符：{logical_path}")


def process_archives(destination: Path | None = None) -> dict:
    """先核对压缩包和每个成员，再按需写入；不同内容原件一律保留。"""
    count = 0
    total = 0
    seen = set()
    manifest = read_manifest()
    for archive in manifest["archives"]:
        path = safe_target(RESULTS, archive["path"])
        if path.stat().st_size != archive["size"] or sha256(path) != archive["sha256"]:
            raise ValueError(f"压缩包校验失败：{path}")
        with zipfile.ZipFile(path) as stream:
            names = stream.namelist()
            expected = {r["path"]: r for r in archive["files"]}
            if len(names) != len(set(names)) or set(names) != set(expected):
                raise ValueError(f"归档成员重复或缺失：{path}")
            for name in names:
                if name in seen:
                    raise ValueError(f"跨压缩包重复路径：{name}")
                seen.add(name)
                # read 同时触发 ZIP CRC 检查；额外 SHA-256 绑定原文件字节。
                raw = stream.read(name)
                record = expected[name]
                if len(raw) != record["size"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
                    raise ValueError(f"归档成员损坏：{name}")
                if destination is not None:
                    target = safe_target(destination, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if sha256(target) != record["sha256"]:
                            raise FileExistsError(f"保留已有不同内容，停止解压：{target}")
                    else:
                        # 独占创建防止并发任务覆盖用户文件；中断残件下次会被明确拒绝。
                        with target.open("xb") as output:
                            output.write(raw)
                count += 1
                total += len(raw)
        logging.info("校验通过 %s", path.name)
    return {"archives": len(manifest["archives"]), "raw_files": count,
            "uncompressed_bytes": total, "sha256_verified": True}


def verify_figures() -> int:
    """冻结图件、CSV 和地图一并验收；本工具不重新绘制已确认版式。"""
    root = ROOT / "figures"
    rows = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for row in rows:
        path = safe_target(root, row["path"])
        if path.stat().st_size != row["size"] or sha256(path) != row["sha256"]:
            raise ValueError(f"图件或源数据变化：{path}")
    for suffix in ("pdf", "png", "svg", "tiff"):
        if len(list((root / suffix).glob(f"fig*.{suffix}"))) != 23:
            raise ValueError(f"{suffix} 图件不齐全")
    return len(rows)


def verify_summaries() -> int:
    """摘要、冻结协议和经验参考也绑定字节清单，不只保护大文件压缩包。"""
    rows = json.loads((RESULTS / "file_manifest.json").read_text(encoding="utf-8"))
    for row in rows:
        path = safe_target(RESULTS, row["path"])
        if path.stat().st_size != row["size"] or sha256(path) != row["sha256"]:
            raise ValueError(f"发布摘要或协议变化：{path}")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify", "extract"])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/recorded")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = process_archives(args.output_dir if args.command == "extract" else None)
    report["figure_files"] = verify_figures()
    report["summary_files"] = verify_summaries()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
