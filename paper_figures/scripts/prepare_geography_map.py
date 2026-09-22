"""复现正式 S45/A100 路线，保存可离线绘图的几何、指标及 USGS 底图。"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import math
from pathlib import Path
import platform
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from prepare_experiment_data import DATA, digest, preserve_existing, write_json
from pyproj import Transformer
from PIL import Image
from uav_mec.algorithms import (ScreenedProxyObjectiveEvaluator, UavMecALNSConfig,
    build_greedy_initial_solution, build_mec_assisted_initial_solution, run_uav_mec_hybrid_alns)
from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.evaluation.geometry import stop_xy
from uav_mec.instances import build_stanislaus_real_instance
from uav_mec.instances.real_geography import EARTH_RADIUS_M


def replay_route() -> dict:
    """仅复现一个已完成的正式种子组合；指标不吻合时拒绝输出替代路线。"""
    if sys.version_info[:2] != (3,13):
        raise RuntimeError('正式路线复现要求 Python 3.13；离线绘图可直接使用已核验几何。')
    # 不允许用已改动的算法冒充正式代码，命令同时覆盖工作区未提交修改。
    source_check=subprocess.run(['git','diff','--name-only',
        '846dd1b56c23ede45ee00238623c3bff487bceb0','--','src',
        'configs/real_stanislaus.yaml',
        'data/real_case/stanislaus/usfs_fire_occurrences_selected59_2026-09-22.json'],
        cwd=ROOT,capture_output=True,text=True,check=True)
    if source_check.stdout.strip():
        raise RuntimeError('路线复现代码或场景与正式提交不一致：'+source_check.stdout)
    formal = json.loads((DATA/'raw/geography.json').read_text(encoding='utf-8'))
    expected = next(r for r in formal['rows'] if r['scenario_seed']==45 and r['algorithm_seed']==100)['hybrid']
    snapshot = ROOT/'data/real_case/stanislaus/usfs_fire_occurrences_selected59_2026-09-22.json'
    config_path = ROOT/'configs/real_stanislaus.yaml'
    built = build_stanislaus_real_instance(snapshot, config_path=config_path,
                                         num_tasks=59, num_uavs=5, scenario_seed=45)
    instance = built.instance
    initial = build_mec_assisted_initial_solution(instance,
        base_solution=build_greedy_initial_solution(instance))
    logging.info('复现真实案例 S45/A100：59 个任务、5 架 UAV、100 次探索、2 轮精英改进。')
    result = run_uav_mec_hybrid_alns(instance, initial_solution=initial,
        config=UavMecALNSConfig(iterations=100, seed=100),
        evaluator=ScreenedProxyObjectiveEvaluator(), elite_rounds=2)
    solution = result.best_solution
    events = build_event_info(instance, solution)
    actual = {
        'stage1_status': str(result.final_cvx.diagnostics.get('stage1_status', result.final_cvx.status)),
        'energy_j': float(result.final_cvx.energy_stage1_j),
        'distance_m': sum(events.route_distance_m.values()),
        'contacts': len(solution.contact_visits),
        'offloaded': sum(d.mode is ExecutionMode.OFFLOAD for d in solution.task_decisions.values()),
    }
    energy_rel_error = abs(actual['energy_j']-expected['energy_j'])/expected['energy_j']
    distance_error = abs(actual['distance_m']-expected['solution']['distance_m'])
    if (not result.final_cvx.feasible or actual['stage1_status']!='optimal' or
        actual['contacts']!=1 or actual['offloaded']!=1 or energy_rel_error>1e-6 or distance_error>.01):
        raise RuntimeError(f'路线复现未通过正式指标核验：{actual}，能耗相对误差={energy_rel_error}，距离误差={distance_error}')
    logging.info('路线复现通过：能耗 %.6f J，距离 %.6f m，1 次接触、1 个卸载任务。', actual['energy_j'], actual['distance_m'])

    depot = built.metadata['depot']
    lat0, lon0 = depot['latitude'], depot['longitude']
    transformer = Transformer.from_crs(4326,32610,always_xy=True)

    def position(x: float, y: float) -> dict:
        # 优化器为保证坐标非负先做了平移，必须扣除机库偏移，再反解经纬度。
        # 直接反解存储的 xy 会把全图向东北平移数公里，即使能耗和距离仍能通过核验。
        dx,dy=x-instance.depot_xy[0],y-instance.depot_xy[1]
        lon = lon0 + math.degrees(dx/(EARTH_RADIUS_M*math.cos(math.radians(lat0))))
        lat = lat0 + math.degrees(dy/EARTH_RADIUS_M)
        east, north = transformer.transform(lon,lat)
        return {'x_instance_m':x,'y_instance_m':y,'x_local_m':dx,'y_local_m':dy,
                'longitude':lon,'latitude':lat,'easting_m':east,'northing_m':north}

    def circle_geometry(x, y, radius):
        return [position(x+radius*math.cos(t*math.pi/90),y+radius*math.sin(t*math.pi/90)) for t in range(181)]

    task_data=[]
    for task in instance.tasks.values():
        decision=solution.task_decisions[task.task_id]
        task_data.append({'id':task.task_id, **position(task.x,task.y),
                          'mode':decision.mode.value,'contact_visit_id':decision.contact_visit_id})
    routes=[]
    for uav_id, route in solution.routes.items():
        routes.append({'uav_id':uav_id,'stops':[{'kind':s.kind.value,'ref_id':s.ref_id,
            **position(*stop_xy(instance,solution,s))} for s in route.stops]})
    mecs=[]
    for mec_id,mec in instance.mecs.items():
        mecs.append({'id':mec_id, **position(mec.x,mec.y),'radius_m':mec.radius_m,
                     'coverage':circle_geometry(mec.x,mec.y,mec.radius_m)})
    contacts=[]
    for visit in solution.contact_visits.values():
        point=instance.contact_points[visit.point_id]
        contacts.append({'visit_id':visit.visit_id,'point_id':visit.point_id,'mec_id':point.mec_id,
                         'uav_id':visit.uav_id,**position(point.x,point.y)})
    # 与固定 USFS 坐标逐点比对，防止仅验证能耗而漏掉整体地图错位。
    known={r['task_id']:r for r in built.metadata['tasks']}
    max_geo_error=max(max(abs(t['latitude']-known[t['id']]['latitude']),
                          abs(t['longitude']-known[t['id']]['longitude'])) for t in task_data)
    if max_geo_error>1e-10: raise ValueError(f'USFS 任务坐标反投影不一致：{max_geo_error}')
    visited=[s['ref_id'] for r in routes for s in r['stops'] if s['kind']=='task']
    if len(visited)!=59 or set(visited)!=set(known): raise ValueError('路线未恰好覆盖全部 59 个任务。')
    aoi=circle_geometry(*instance.depot_xy,4000)
    bbox=[min(p['easting_m'] for p in aoi)-150,min(p['northing_m'] for p in aoi)-150,
          max(p['easting_m'] for p in aoi)+150,max(p['northing_m'] for p in aoi)+150]
    versions={name:importlib.metadata.version(name) for name in ('numpy','scipy','cvxpy','clarabel','alns','PyYAML','scs','osqp','matplotlib','pyproj','Pillow','pypdf','pdfplumber')}
    return {'schema_version':2,'case':'Stanislaus / Groveland','scenario_seed':45,'algorithm_seed':100,
            'crs':'EPSG:32610','depot':{'name':depot['name'],**position(*instance.depot_xy)},
            'tasks':task_data,'mecs':mecs,'contacts':contacts,'routes':routes,'aoi':aoi,'bbox_utm':bbox,
            'validation':{'actual':actual,'formal_expected':expected,'energy_relative_error':energy_rel_error,
                          'distance_error_m':distance_error,'coordinate_max_error_deg':max_geo_error,
                          'all_59_tasks_visited_once':True,'passed':True},
            'provenance':{'formal_run_id':35679546095,'formal_commit':'846dd1b56c23ede45ee00238623c3bff487bceb0',
                'current_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'python':platform.python_version(),'formal_python':'3.13.15','versions':versions,
                'snapshot_sha256':digest(snapshot.read_bytes()),'config_sha256':digest(config_path.read_bytes())}}


def cache_basemap(geometry: dict) -> None:
    """缓存公开 USGS 地形底图，常规重绘完全离线，地图叠加层由 Matplotlib 保留为矢量。"""
    path=DATA/'map/usgs_topo_utm10.png'
    record=DATA/'map/basemap_source.json'
    if path.exists() and record.exists():
        source=json.loads(record.read_text(encoding='utf-8'))
        if digest(path.read_bytes())!=source['sha256']:
            raise RuntimeError('USGS 底图缓存哈希不匹配。')
        if 'image_extent_utm' not in source:
            source['image_extent_utm']=read_export_extent(source['url'])
            write_json(record,source)
        return
    bbox=geometry['bbox_utm']
    params={'bbox':','.join(f'{v:.3f}' for v in bbox),'bboxSR':32610,'imageSR':32610,
            'size':'2400,2400','format':'png','transparent':'false','f':'image'}
    url='https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/export?'+urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url,timeout=55) as response: raw=response.read()
            import io
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            break
        except (OSError,ValueError) as exc:
            if attempt==3: raise RuntimeError('USGS 地形底图获取失败，尚未生成替代底图。') from exc
            logging.warning('USGS 底图请求暂时失败，重试 %d/3。',attempt+1)
            time.sleep(2*(attempt+1))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    write_json(record,{'provider':'USGS The National Map / USGSTopo','url':url,'crs':'EPSG:32610',
        'bbox_utm':bbox,'pixels':[2400,2400],'sha256':digest(raw),
        'image_extent_utm':read_export_extent(url),
        'attribution':'USGS The National Map; USFS road data; other contributing national datasets.'})
    logging.info('已缓存 USGS 底图：%d 字节。',len(raw))


def read_export_extent(image_url: str) -> list[float]:
    """记录服务器真实导出范围，防止方形栅格自动扩边导致底图与矢量发生错位。"""
    # ArcGIS 按输出像素比例调整 bbox；必须读取响应 extent，不能直接用请求范围贴图。
    metadata_url=image_url.replace('f=image','f=json')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(metadata_url,timeout=45) as response:
                result=json.load(response)
            if 'error' in result: raise ValueError(f'USGS 范围查询失败：{result["error"]}')
            extent=result['extent']
            if extent['spatialReference']['wkid']!=32610 or result['width']!=2400 or result['height']!=2400:
                raise ValueError('USGS 导出坐标系或像素尺寸不符合请求。')
            return [extent[k] for k in ('xmin','ymin','xmax','ymax')]
        except (OSError,ValueError,KeyError) as exc:
            if attempt==3: raise RuntimeError('无法核验 USGS 底图真实导出范围。') from exc
            logging.warning('USGS 范围查询暂时失败，重试 %d/3。',attempt+1)
            time.sleep(2*(attempt+1))
    raise AssertionError('不可到达的重试状态')


def main() -> None:
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    preserve_existing()
    path=DATA/'map/stanislaus_S45_A100.json'
    if path.exists():
        geometry=json.loads(path.read_text(encoding='utf-8'))
        if not geometry['validation']['passed']: raise ValueError('已有路线尚未通过核验。')
        if geometry.get('schema_version')!=2:
            geometry=replay_route()
            write_json(path,geometry)
    else:
        geometry=replay_route()
        write_json(path,geometry)
    cache_basemap(geometry)
    preserve_existing()


if __name__=='__main__':
    main()
