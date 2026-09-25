"""取回获准复用的固定Actions归档，核对SHA256并保存本地来源记录。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import zipfile


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """跨主机下载前剥离GitHub令牌，禁止认证头随重定向发送给制品存储。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(source: dict, repo: str, destination: Path, token: str,
             *, allow_nested: bool = False) -> dict:
    """身份认证仅用于GitHub API；默认仅解压单层数据，归档模式也拒绝路径穿越。"""
    base = f"https://api.github.com/repos/{repo}/actions/artifacts/{source['artifact_id']}"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
               "X-GitHub-Api-Version": "2022-11-28"}
    with urllib.request.urlopen(urllib.request.Request(base, headers=headers), timeout=45) as r:
        metadata = json.load(r)
    assert metadata["name"] == source["artifact_name"]
    assert metadata["workflow_run"]["id"] == source["run_id"]
    assert not metadata["expired"], "源归档已过期，须从长期备份恢复"
    assert metadata["digest"] == "sha256:" + source["zip_sha256"]
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(urllib.request.Request(base + "/zip", headers=headers), timeout=45) as r:
            body = r.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 302:
            raise RuntimeError(f"GitHub归档下载失败：HTTP {exc.code}") from None
        location = exc.headers["Location"]
        if not location.startswith("https://"):
            raise RuntimeError("拒绝非HTTPS制品下载")
        # 签名URL仅用于本次下载，不写日志、不写清单。
        with urllib.request.urlopen(location, timeout=60) as r:
            body = r.read()
    digest = hashlib.sha256(body).hexdigest()
    assert digest == source["zip_sha256"], "下载文件SHA256与冻结来源不符"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "artifact.zip").write_bytes(body)
    extracted = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = Path(item.filename.replace("\\", "/"))
            if (name.suffix not in (".json", ".csv", ".zip") or name.is_absolute()
                    or ".." in name.parts or (not allow_nested and name.name != item.filename)):
                raise ValueError("归档包含非预期路径或文件类型")
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("归档路径超出目标目录")
            content = archive.read(item)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            extracted.append({"file": name.as_posix(), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    record = dict(source, repository=repo, verified_zip_sha256=digest, files=extracted,
                  code_commit=metadata["workflow_run"]["head_sha"])
    (destination / "provenance.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("configs/innovation_sources.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("需要GitHub只读Actions访问令牌，禁止将令牌写入命令参数")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        record = download(source, manifest["repository"], args.output_dir / source["key"], token)
        print(source["key"], record["verified_zip_sha256"], len(record["files"]), "files verified", flush=True)


if __name__ == "__main__":
    main()
