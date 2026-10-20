"""结果迁移的完整性和解压边界回归检查。"""
import hashlib
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import manage_results


@pytest.mark.parametrize("name", ["../outside.json", "/absolute.json", "C:/file", "a\\..\\file"])
def test_archive_rejects_paths_outside_destination(tmp_path, name):
    with pytest.raises(ValueError):
        manage_results.safe_target(tmp_path, name)


def test_archive_preserves_conflicting_file_and_detects_tampering(tmp_path, monkeypatch):
    archive = tmp_path / "one.zip"
    raw = b'{"complete":true}'
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("main/raw/one.json", raw)
    record = {"path": "main/raw/one.json", "size": len(raw),
              "sha256": hashlib.sha256(raw).hexdigest()}
    manifest = {"archives": [{"path": archive.name, "size": archive.stat().st_size,
                              "sha256": manage_results.sha256(archive), "files": [record]}]}
    monkeypatch.setattr(manage_results, "RESULTS", tmp_path)
    monkeypatch.setattr(manage_results, "read_manifest", lambda: manifest)
    destination = tmp_path / "unpacked"
    assert manage_results.process_archives(destination)["raw_files"] == 1
    # 相同内容允许幂等恢复，不同内容必须保留原件并中止。
    assert manage_results.process_archives(destination)["raw_files"] == 1
    target = destination / record["path"]
    target.write_bytes(b"user changes")
    with pytest.raises(FileExistsError):
        manage_results.process_archives(destination)
    assert target.read_bytes() == b"user changes"
    with pytest.raises(ValueError, match="发布清单"):
        manage_results.verify_recorded_file(target, record["path"])
    with archive.open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="压缩包校验失败"):
        manage_results.process_archives()
