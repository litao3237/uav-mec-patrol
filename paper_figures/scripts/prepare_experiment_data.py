"""下载已核验的正式实验制品，记录来源并保护现有论文图。"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'paper_figures/data'
REPOSITORY = 'litao3237/uav-mec-patrol'
SOURCES = {
    'dense': (10651261069, 35623551801, 'dense_workload_K30-80_M5_E2.json'),
    'baseline': (10640744688, 35606211937, 'core_baseline_K50_E2_S45-46-47_A100-101-102_I100_matrix.json'),
    'ga': (10643135771, 35606683206, 'ga_baseline_K50_E2_S45-46-47_A100-101-102_I100_P24_G40_matrix.json'),
    'strong': (10647510876, 35616968050, 'small_strong_K28_M2_E2_S45-46-47_matrix.json'),
    'geography': (10674531133, 35679546095, 'outputs/results/stanislaus_real_case_K59_M5_E2_S45-46-47_A100-101-102.json'),
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub 签名下载跳转不转发 Authorization，防止凭据泄漏到存储域名。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_token() -> str:
    """复用当前用户已有的 GitHub 凭据；禁止交互提示及打印凭据。"""
    if token := os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'):
        return token
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    result = subprocess.run(['git', 'credential', 'fill'], cwd=ROOT,
                            input='protocol=https\nhost=github.com\n\n',
                            capture_output=True, text=True, env=env, timeout=30)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if not values.get('password'):
        raise RuntimeError('无法读取 GitHub 已保存凭据；正式制品下载需要仓库读取权限。')
    return values['password']


def _api_once(path: str, token: str) -> bytes:
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/{path}',
        headers={'User-Agent': 'uav-mec-paper-figures', 'Authorization': 'Bearer '+token})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(request, timeout=40)
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        # 签名地址只用于下载，不记录到日志或来源清单。
        response = urllib.request.urlopen(exc.headers['Location'], timeout=40)
    with response:
        return response.read()


def api_get(path: str, token: str) -> bytes:
    """只对临时网络故障做有限重试；日志不包含凭据或签名地址。"""
    for attempt in range(4):
        try:
            return _api_once(path, token)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500 and exc.code != 429:
                raise RuntimeError(f'GitHub 读取失败：HTTP {exc.code}，资源 {path}') from None
            if attempt == 3:
                raise RuntimeError(f'GitHub 读取重试耗尽：{path}，{type(exc).__name__}') from exc
            logging.warning('网络暂时失败，重试资源 %s（%d/3）', path, attempt+1)
            time.sleep(2*(attempt+1))
    raise AssertionError('不可到达的重试状态')


def preserve_existing() -> None:
    """首次记录现有图和数据；重复执行只核对，不能把已变化的文件当作新基线。"""
    path = DATA / 'preserved_files.json'
    if path.exists():
        for item in json.loads(path.read_text(encoding='utf-8'))['files']:
            if digest((ROOT/item['path']).read_bytes()) != item['sha256']:
                raise RuntimeError(f"受保护文件已改变：{item['path']}")
        return
    figure_root = ROOT/'paper_figures'
    files = []
    for stem in ('fig01_system_model', 'fig02_hybrid_alns_framework', 'fig02_hybrid_alns_visual'):
        files.extend([figure_root/'visio'/f'{stem}.vsdx',
                      figure_root/'visio/assets'/f'{stem}.scene.json'])
        files.extend(figure_root/f'output/{ext}'/f'{stem}.{ext}' for ext in ('pdf','svg','png'))
    files.extend(figure_root/'scripts'/name for name in (
        'build_algorithm_figure.mjs', 'build_algorithm_visual.mjs', 'render_concept_figures.ps1'))
    files.extend(sorted((ROOT/'paper_results').glob('*.csv')))
    files.extend([ROOT/'uv.lock', ROOT/'outputs/instances/paper_scale_sanity.json'])
    write_json(path, {'files': [{'path': str(p.relative_to(ROOT)).replace('\\','/'),
                                'sha256': digest(p.read_bytes())} for p in files if p.exists()]})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    preserve_existing()
    manifest_file = DATA/'experiment_sources.json'
    existing = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.exists() else {}
    records = existing.get('sources', {})
    token = None
    for label, (artifact_id, run_id, filename) in SOURCES.items():
        destination = DATA/'raw'/f'{label}.json'
        if label in records and destination.exists():
            if digest(destination.read_bytes()) != records[label]['json_sha256']:
                raise RuntimeError(f'原始数据快照哈希不匹配：{label}')
            logging.info('复用已验证的数据快照：%s', label)
            continue
        token = token or github_token()
        archive = api_get(f'actions/artifacts/{artifact_id}/zip', token)
        run = json.loads(api_get(f'actions/runs/{run_id}', token))
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            # 只读取明确命名的 JSON，不按远端路径解压，避免覆盖项目文件。
            raw = bundle.read(filename)
        payload = json.loads(raw)
        if not payload.get('complete') or not payload.get('rows'):
            raise ValueError(f'正式制品未完成或没有运行记录：{label}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        records[label] = {
            'repository': REPOSITORY, 'artifact_id': artifact_id, 'run_id': run_id,
            'commit': run['head_sha'], 'workflow': run['name'], 'run_url': run['html_url'],
            'archive_member': filename, 'archive_sha256': digest(archive),
            'json_path': str(destination.relative_to(ROOT)).replace('\\','/'),
            'json_sha256': digest(raw), 'rows': len(payload['rows']),
        }
        write_json(manifest_file, {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'sources': records})
        logging.info('已保存正式制品：%s，%d 行', label, len(payload['rows']))
    preserve_existing()


if __name__ == '__main__':
    main()
