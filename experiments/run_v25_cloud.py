"""在Actions中运行冻结场景块；运行前核对输入，运行后独立重建残差。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'configs/v25_cloud_execution.json'
OUT = ROOT / 'outputs/v25_extension'


def normalize_hashes(hashes: dict) -> dict:
    """不同检出目录使用相对路径，路径分隔符不改变源码字节身份。"""
    return {name.replace('\\', '/'): digest for name, digest in hashes.items()}


def preflight() -> dict:
    """严格锁定算法、依赖和输入；环境不同立即失败，不悄悄降级版本。"""
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    for name, expected in plan['source_hashes'].items():
        actual = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'冻结文件哈希不匹配：{name}')
    for package, expected in plan['dependencies'].items():
        actual = version(package)
        if actual != expected:
            raise ValueError(f'依赖版本不匹配：{package}={actual}，需要{expected}')
    if platform.python_version() != plan['python'] or platform.system() != 'Windows':
        raise ValueError('云端须使用冻结的Windows/Python版本')
    from run_v25_extension import source_hashes
    if normalize_hashes(source_hashes()) != plan['source_hashes']:
        raise ValueError('冻结源码集合不一致，含额外或缺少源文件')
    logging.info('算法源码、GIS输入和运行依赖身份检查通过')
    return plan


def verify(key: str, plan: dict) -> None:
    """逐记录复核两阶段原始变量和重建时序；失败求解仍保留在17条计划记录中。"""
    import aggregate_v25_extension as audit
    from run_v25_extension import source_hashes
    job = next(j for j in plan['jobs'] if j['key'] == key)
    path = OUT/'raw'/f'{key}.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload['instance_sha256'] != job['instance_sha256']:
        raise ValueError(f'云端生成实例偏离冻结输入：{key}')
    audit.WORK = OUT
    rows, source = audit.verify_job(job, {'source_hashes':source_hashes()})
    report = {'key':key, 'complete':True, 'records':len(rows), 'independent_residual_check':True,
              'source':source,'counts':{method:sum(int(r['metrics']['both_stages_qualified_rate'])
               for r in rows if r['method']==method) for method in plan['methods']},
              'checked_at_utc':datetime.now(timezone.utc).isoformat()}
    (OUT/f'{key}.verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    logging.info('%s完整17条记录及独立残差复核通过', key)


def run(key: str, plan: dict) -> None:
    """每场景内顺序执行七算法，只在不同Actions作业之间并行。"""
    job = next(j for j in plan['jobs'] if j['key'] == key)
    (OUT/'raw').mkdir(parents=True,exist_ok=True)
    (OUT/'logs').mkdir(exist_ok=True)
    command = [sys.executable,str(ROOT/'experiments/run_v25_extension.py'),
               '--study',job['study'],'--level',str(job['level']),
               '--scenario',str(job['scenario']),'--output',str(OUT/'raw'/f'{key}.json')]
    with (OUT/'logs'/f'{key}.log').open('w',encoding='utf-8') as log:
        # 子进程逐行转发日志，长时间求解时仍可在Actions查看进度。
        process = subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                   text=True,encoding='utf-8',errors='replace')
        for line in process.stdout:
            log.write(line);log.flush();print(line,end='',flush=True)
        code = process.wait()
    if code:
        raise RuntimeError(f'{key}运行中断，退出码{code}；原始检查点和日志仍上传')
    verify(key,plan)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preflight','run','verify'])
    parser.add_argument('--key')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    plan=preflight()
    if args.action!='preflight':
        if args.key not in {j['key'] for j in plan['jobs']}:
            raise ValueError('请求场景不在冻结的云端迁移清单内')
        (run if args.action=='run' else verify)(args.key,plan)


if __name__=='__main__':
    main()
