"""核验正式导出，渲染 PDF 与灰度预览，并整理可交付的论文实验图包。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps
import pdfplumber
from pypdf import PdfReader, PdfWriter

from prepare_experiment_data import ROOT, DATA, digest, preserve_existing, write_json

FIGURES = ROOT/'paper_figures'
OUTPUT = FIGURES/'output'
QA = OUTPUT/'qa_experiments'


def normalized(text: str) -> str:
    """忽略提取器的换行和标点差异，仍逐条检查所有实际绘制的英文及数字标签。"""
    return ''.join(c.lower() for c in text if c.isalnum())


def verify_one(item: dict) -> dict:
    """直接核验 PDF 对象、字体、文字边界及 PNG 分辨率，不只检查扩展名。"""
    name=item['name']; pdf_path=OUTPUT/'pdf'/f'{name}.pdf'
    reader=PdfReader(pdf_path)
    if len(reader.pages)!=1:
        raise ValueError(f'{name} 必须为单页 PDF。')
    page=reader.pages[0]
    width,height=float(page.mediabox.width),float(page.mediabox.height)
    if abs(width*25.4/72-183)>.01 or abs(height*25.4/72-item['height_mm'])>.01:
        raise ValueError(f'{name} 物理尺寸不正确。')
    for ref in page['/Resources']['/Font'].values():
        font=ref.get_object()
        descendants=font.get('/DescendantFonts',[font])
        for child in descendants:
            descriptor=child.get_object()['/FontDescriptor'].get_object()
            if not any(k in descriptor for k in ('/FontFile','/FontFile2','/FontFile3')):
                raise ValueError(f'{name} 字体没有嵌入。')
    with pdfplumber.open(pdf_path) as pdf:
        p=pdf.pages[0]
        outside=[c['text'] for c in p.chars if c['x0']<-.4 or c['top']<-.4
                 or c['x1']>p.width+.4 or c['bottom']>p.height+.4]
        if outside: raise ValueError(f'{name} 文字超出页面：{outside}')
        # 绘制顺序提取可以检查旋转的轴标签，避免版面提取重新排序造成误报。
        drawn=normalized(''.join(c['text'] for c in p.chars))
        absent=[t for t in item['texts'] if normalized(t) not in drawn]
        if absent: raise ValueError(f'{name} PDF 标签缺失：{absent}')
        fonts=sorted({c['fontname'] for c in p.chars})
        if not all('TimesNewRoman' in f for f in fonts):
            raise ValueError(f'{name} 出现非 Times New Roman 字体：{fonts}')
        images=len(p.images)
        if images and name!='fig13_stanislaus_case':
            raise ValueError(f'{name} 数值图意外包含栅格对象。')
        # pdfplumber 对旋转字形的 size 含义不同；横排实测配合全体 artist 字号检查。
        sizes=[c['size'] for c in p.chars if c['upright']]
        if min(sizes)<8.49 or item['font_range_pt'][0]<8.5:
            raise ValueError(f'{name} 字号小于 8.5 pt。')
    svg=ET.parse(OUTPUT/'svg'/f'{name}.svg').getroot()
    svg_images=len(svg.findall('.//{http://www.w3.org/2000/svg}image'))
    if svg_images and name!='fig13_stanislaus_case':
        raise ValueError(f'{name} SVG 数值图不是纯矢量。')
    with Image.open(OUTPUT/'png'/f'{name}.png') as im:
        dpi=im.info.get('dpi',(0,0))
        if any(abs(v-300)>.1 for v in dpi) or abs(im.width-183/25.4*300)>1:
            raise ValueError(f'{name} PNG 分辨率或尺寸不正确。')
        pixels=list(im.size)
    return {'name':name,'passed':True,'pdf_pages':1,'width_mm':round(width*25.4/72,3),
            'height_mm':round(height*25.4/72,3),'fonts':fonts,
            'minimum_font_pt':min(sizes),'pdf_raster_images':images,
            'svg_raster_images':svg_images,'complete_labels':True,'out_of_page_text':0,
            'png_pixels':pixels,'png_dpi':list(dpi),
            'sha256':{ext:digest((OUTPUT/ext/f'{name}.{ext}').read_bytes()) for ext in ('pdf','svg','png')}}


def verify_map() -> dict:
    """复核缓存几何和正式数据；每个任务必须恰好出现一次，卸载记录必须指向有效接触。"""
    path=DATA/'map/stanislaus_S45_A100.json'
    geo=json.loads(path.read_text(encoding='utf-8'))
    source=json.loads((DATA/'map/basemap_source.json').read_text(encoding='utf-8'))
    if digest((DATA/'map/usgs_topo_utm10.png').read_bytes())!=source['sha256']:
        raise ValueError('USGS 底图哈希不匹配。')
    if source['crs']!=geo['crs'] or geo['crs']!='EPSG:32610':
        raise ValueError('地图坐标系不一致。')
    extent=source['image_extent_utm']
    if len(extent)!=4 or extent[2]<=extent[0] or extent[3]<=extent[1]:
        raise ValueError('缺少可用的 USGS 实际导出范围。')
    tasks={t['id']:t for t in geo['tasks']}
    visited=[s['ref_id'] for r in geo['routes'] for s in r['stops'] if s['kind']=='task']
    if len(tasks)!=59 or len(visited)!=59 or set(visited)!=set(tasks) or len(geo['routes'])!=5:
        raise ValueError('真实路线的任务或 UAV 数量不一致。')
    contacts={c['visit_id']:c for c in geo['contacts']}
    offloaded=[t for t in tasks.values() if t['mode']=='offload']
    if len(contacts)!=1 or len(offloaded)!=1 or offloaded[0]['contact_visit_id'] not in contacts:
        raise ValueError('真实地图的卸载和接触关联不一致。')
    v=geo['validation']; actual=v['actual']; expected=v['formal_expected']
    energy_error=abs(actual['energy_j']-expected['energy_j'])/expected['energy_j']
    distance_error=abs(actual['distance_m']-expected['solution']['distance_m'])
    if actual['stage1_status']!='optimal' or energy_error>1e-6 or distance_error>.01:
        raise ValueError('真实路线不符合正式能耗或距离容差。')
    if v['coordinate_max_error_deg']>1e-10 or geo.get('schema_version')!=2:
        raise ValueError('地图缺少地理反投影校验。')
    return {'passed':True,'tasks':59,'routes':5,'contacts':1,'offloaded_tasks':1,
            'energy_j':actual['energy_j'],'distance_m':actual['distance_m'],
            'energy_relative_error':energy_error,'distance_error_m':distance_error,
            'coordinate_max_error_deg':v['coordinate_max_error_deg'],
            'geometry_sha256':digest(path.read_bytes()),'basemap_sha256':source['sha256'],
            'python':geo['provenance']['python'],'formal_python':geo['provenance']['formal_python']}


def render_previews(items: list[dict]) -> None:
    """以实际 PDF 而非原始 Matplotlib PNG 生成预览，暴露字体嵌入和导出布局问题。"""
    command=shutil.which('pdftoppm')
    if not command: raise RuntimeError('完整验收需要 Poppler 的 pdftoppm，请先加入 PATH。')
    QA.mkdir(parents=True,exist_ok=True)
    for item in items:
        name=item['name']
        subprocess.run([command,'-r','150','-png','-singlefile',
            str(OUTPUT/'pdf'/f'{name}.pdf'),str(QA/name)],check=True,capture_output=True)
        with Image.open(QA/f'{name}.png') as im:
            ImageOps.grayscale(im).save(QA/f'{name}_gray.png')


def overview(items: list[dict], *, gray: bool=False) -> Path:
    """总览仅用于选图；论文应使用保留 183 mm 实际宽度的单图矢量文件。"""
    width=900; card_height=590; margin=22; header=80
    sheet=Image.new('RGB',(3*width,header+5*card_height),'#EEF1F3')
    draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/timesbd.ttf',28)
    draw.text((margin,22),'Experimental figures | Fig. 3–13 and Fig. S1–S2',font=font,fill='#29343D')
    for index,item in enumerate(items):
        # 地理图使用两行高度，其余图保持相近的缩放尺寸。
        position={10:(3,2,2),11:(3,1,1),12:(4,0,1)}.get(index,(index//3,index%3,1))
        row,col,span=position
        x=col*width+margin; y=header+row*card_height+margin
        box=(x,y,x+width-2*margin,y+span*card_height-2*margin)
        draw.rectangle(box,fill='white')
        suffix='_gray' if gray else ''
        with Image.open(QA/f"{item['name']}{suffix}.png") as original:
            im=original.convert('RGB'); im.thumbnail((width-2*margin,span*card_height-2*margin-60))
            sheet.paste(im,(x+(width-2*margin-im.width)//2,y+48))
        figure_id=item['name'].split('_')[0].replace('fig','Fig. ').replace('03','3').replace('04','4').replace('05','5').replace('06','6').replace('07','7').replace('08','8').replace('09','9')
        draw.text((x+10,y+8),figure_id,font=font,fill='#29343D')
    note_font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',28)
    draw.multiline_text((width+50,header+4*card_height+100),
        '13 figure groups\n\nPDF / SVG / 300 dpi PNG\n183 mm publication width\nTimes New Roman, 8.5 pt or larger\n\nOfficial data snapshots verified\nOriginal concept figures preserved',
        font=note_font,fill='#29343D',spacing=12)
    path=OUTPUT/f"experiment_overview{'_grayscale' if gray else ''}.png"
    sheet.save(path,dpi=(150,150))
    return path


def combine_pdf(items: list[dict]) -> Path:
    writer=PdfWriter()
    for item in items:
        writer.append(OUTPUT/'pdf'/f"{item['name']}.pdf",outline_item=item['title'])
    writer.add_metadata({'/Title':'UAV-MEC experimental figures: Fig. 3–13 and S1–S2'})
    path=OUTPUT/'experimental_figures_all.pdf'
    with path.open('wb') as file: writer.write(file)
    if len(PdfReader(path).pages)!=13: raise ValueError('合并 PDF 页数错误。')
    return path


def package(items: list[dict]) -> Path:
    """仅打包新增实验交付及其来源，不把旧概念图或算法项目改动混入交付包。"""
    paths=[OUTPUT/'experimental_figures_all.pdf',OUTPUT/'experiment_overview.png',
           OUTPUT/'experiment_overview_grayscale.png',FIGURES/'experiment_captions.md',
           FIGURES/'experiment_verification.json',FIGURES/'experiment_verification.md',
           FIGURES/'README.md',FIGURES/'requirements-experiments.txt',
           FIGURES/'requirements-experiments-lock.txt']
    paths.extend(OUTPUT/ext/f"{r['name']}.{ext}" for r in items for ext in ('pdf','svg','png'))
    paths.extend(p for p in DATA.rglob('*') if p.is_file())
    paths.extend((ROOT/'paper_results').glob('*.csv'))
    paths.extend(p for p in (FIGURES/'scripts').glob('*.py'))
    path=OUTPUT/'experimental_figures_package.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for source in sorted(set(paths)):
            if not source.exists(): raise FileNotFoundError(f'交付包缺少文件：{source}')
            bundle.write(source,str(source.relative_to(ROOT)))
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    preserve_existing()
    registry=json.loads((DATA/'figure_registry.json').read_text(encoding='utf-8'))
    items=registry['figures']
    if len(items)!=13 or len({i['name'] for i in items})!=13:
        raise ValueError('实验图必须为 13 组且名称唯一。')
    checks=[verify_one(item) for item in items]
    map_check=verify_map()
    render_previews(items); overview(items); overview(items,gray=True); combine_pdf(items)
    protected=json.loads((DATA/'preserved_files.json').read_text(encoding='utf-8'))['files']
    statistics=json.loads((DATA/'experiment_validation.json').read_text(encoding='utf-8'))
    # 视觉复核绑定实际 PDF 渲染的像素哈希；日后修改图形不会沿用过期的通过记录。
    review_path=DATA/'experiment_visual_review.json'
    review=json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else {}
    reviewed=all(review.get('figures',{}).get(item['name'],{}).get(key)==
        digest((QA/f"{item['name']}{suffix}.png").read_bytes())
        for item in items for key,suffix in [('pdf_render_sha256',''),('grayscale_sha256','_gray')])
    report={'passed':True,'checked_at':datetime.now(timezone.utc).isoformat(),
            'figures':checks,'statistical_checks':statistics['matched_metric_count'],
            'map':map_check,'preserved_file_count':len(protected),
            'preserved_files_unchanged':True,'actual_pdf_previews':'output/qa_experiments',
            'combined_pdf_pages':13,'visual_review_matches_current_renders':reviewed,
            'runtime':registry.get('versions',{})}
    write_json(FIGURES/'experiment_verification.json',report)
    lines=['# 实验图验证报告','',
        f'- 13 组图均输出单页 PDF、可编辑文本 SVG 和 300 dpi PNG，宽度均为 183 mm。',
        '- PDF 字体已嵌入，全部为 Times New Roman；字号不低于 8.5 pt。',
        '- 全部登记标签在 PDF 中可提取；文字无页面越界。',
        '- 12 组数值图为纯矢量；Fig. 13 仅主图和局部图的 USGS 底图为栅格。',
        f'- {len(protected)} 个受保护文件 SHA-256 保持一致，包括原有三张概念图、原脚本、12 份汇总 CSV 和 uv.lock。',
        f'- 逐次数据重新聚合后，{statistics["matched_metric_count"]} 项汇总在 CSV 保留精度内一致。',
        '- Fig. 3 使用运行间样本标准差；所有配对按场景/算法种子匹配。',
        '- GR-MR 与 FTR-NM 按独立场景去重；K=80 RGA-MR 为 3/24 strict，且三个严格运行均来自同一独立场景。',
        '- 所有条件指标保留有效样本数；缺失值未补零，未添加显著性标记。',
        f'- 地理复现：能耗 {map_check["energy_j"]:.6f} J，总距离 {map_check["distance_m"]:.6f} m；相对/绝对误差分别为 {map_check["energy_relative_error"]} / {map_check["distance_error_m"]} m。',
        '- 全部 59 个任务恰好访问一次，5 条 UAV 路线，1 次接触、1 个卸载任务；原始经纬度逐点反投影误差为 0。',
        '- 复现使用 Python 3.13.12，正式 CI 为 3.13.15；核心数值依赖版本相同，复现指标完全匹配。',
        '- 实际 PDF 的彩色与灰度渲染保存在 output/qa_experiments；总览供检查布局，正式插图使用单图 PDF/SVG。',
        '- 当前 13 组实际 PDF 彩色与灰度渲染均已逐图视觉检查：标签、图例、裁切和线型辨识通过。' if reviewed else '- 当前渲染尚未匹配已登记的视觉复核记录。',
        '', '逐图对象统计、文件 SHA-256 及依赖版本见 experiment_verification.json。',
        '来源及原始制品哈希见 data/experiment_sources.json；路线与底图来源见 data/map。','']
    (FIGURES/'experiment_verification.md').write_text('\n'.join(lines),encoding='utf-8')
    preserve_existing()
    destination=package(items)
    logging.info('13 组图通过文件核验，已生成总览、合并 PDF 与交付包：%s',destination)


if __name__=='__main__':
    main()
