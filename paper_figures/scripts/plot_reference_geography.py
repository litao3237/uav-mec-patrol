"""绘制强参考与真实地理案例，地图只叠加经过复现核验的真实路线。"""
import json
from statistics import mean
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PIL import Image
from figure_style import *
from prepare_experiment_data import DATA

ROUTE_COLORS=[BLUE,ORANGE,TEAL,'#786589','#A45056']
ROUTE_STYLES=['-','--','-.',':',(0,(6,2,1,2,1,2))]


def xy(records):
    return np.array([[p['easting_m'],p['northing_m']] for p in records])


def map_layers(ax,geo,background,basemap_extent,*,focus=False):
    """统一 UTM 米坐标；底图淡化，任务、路径和覆盖区均为矢量叠加。"""
    xmin,ymin,xmax,ymax=geo['bbox_utm']
    bxmin,bymin,bxmax,bymax=basemap_extent
    ax.imshow(background,extent=(bxmin,bxmax,bymin,bymax),alpha=.43,origin='upper',zorder=0)
    aoi=xy(geo['aoi']); ax.plot(*aoi.T,color=GRAY,ls=(0,(2,3)),lw=.7,zorder=1)
    for mec in geo['mecs']:
        coverage=xy(mec['coverage'])
        ax.fill(*coverage.T,color=TEAL,alpha=.07,zorder=1)
        ax.plot(*coverage.T,color=TEAL,lw=.8,ls='--',zorder=2)
        ax.scatter(mec['easting_m'],mec['northing_m'],marker='^',s=35,color=TEAL,zorder=7)
        if not focus:
            label='Depot / E1' if mec['id']=='E1' else 'E2: Smith Peak'
            ax.annotate(label,(mec['easting_m'],mec['northing_m']),xytext=(5,8),
                        textcoords='offset points',fontsize=8.5,zorder=12,
                        bbox={'facecolor':'white','alpha':.9,'edgecolor':'none','pad':1})
    for i,route in enumerate(geo['routes']):
        if focus and route['uav_id']!='U5': continue
        points=xy(route['stops'])
        ax.plot(*points.T,color=ROUTE_COLORS[i],ls=ROUTE_STYLES[i],lw=1.25 if focus else .9,
                alpha=.95,zorder=3)
        # 用路线中间一段的小箭头提示方向，不添加未执行的直达上传连线。
        for j in ([len(points)//2] if not focus else [j for j in range(1,len(points)-1,4)]):
            a,b=points[j],points[j+1]
            ax.annotate('',xy=.6*a+.4*b,xytext=.75*a+.25*b,
                        arrowprops={'arrowstyle':'-|>','mutation_scale':7,'color':ROUTE_COLORS[i],'lw':.8},zorder=4)
    tasks=xy(geo['tasks'])
    ax.scatter(*tasks.T,s=9,facecolors='white',edgecolors=INK,lw=.45,zorder=5)
    for task in geo['tasks']:
        if task['mode']=='offload':
            ax.scatter(task['easting_m'],task['northing_m'],s=65,marker='*',color=ORANGE,edgecolor=INK,lw=.45,zorder=10)
            if focus: ax.annotate('Task '+task['id'],(task['easting_m'],task['northing_m']),
                xytext=(-8,-13),textcoords='offset points',ha='right',fontsize=8.5,zorder=12,
                bbox={'facecolor':'white','alpha':.9,'edgecolor':'none','pad':1})
    depot=geo['depot']; ax.scatter(depot['easting_m'],depot['northing_m'],marker='s',s=20,color=INK,zorder=9)
    for contact in geo['contacts']:
        ax.scatter(contact['easting_m'],contact['northing_m'],s=88,marker='D',
                   facecolors='none',edgecolors=TEAL,lw=1.4,zorder=11)
        if focus: ax.annotate('Contact / E1',(contact['easting_m'],contact['northing_m']),
            xytext=(5,7),textcoords='offset points',fontsize=8.5,zorder=12,
            bbox={'facecolor':'white','alpha':.9,'edgecolor':'none','pad':1})
    ax.set_aspect('equal'); ax.tick_params(length=2,pad=2)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1000:.0f}'))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1000:.0f}'))
    ax.set_xlim(xmin,xmax); ax.set_ylim(ymin,ymax)


def draw_reference_geography(data,registry):
    fig=figure(96); axes=fig.subplots(1,2)
    standard=[r for r in data.raw['strong']['rows'] if r['mode']=='standard' and r['stage1_status']=='optimal']
    for i,scenario in enumerate([45,46,47]):
        values=[r['gap_to_best_known_pct'] for r in sorted(standard,key=lambda r:r['algorithm_seed']) if r['scenario_seed']==scenario]
        axes[0].scatter(i+np.linspace(-.12,.12,3),values,s=23,marker='s',color=ORANGE,zorder=3)
        axes[0].hlines(mean(values),i-.24,i+.24,color=INK,lw=1.3,zorder=4)
    axes[0].set_xticks(range(3),['S45','S46','S47']); axes[0].set_ylim(0,14)
    panel(axes[0],'a','Standard-search quality','Gap to best-known (%)','Scenario')
    modes=['standard','strong']
    values=[mean(r['runtime_s'] for r in data.raw['strong']['rows'] if r['mode']==m) for m in modes]
    axes[1].bar([0,1],values,.5,color=[ORANGE,BLUE],edgecolor=INK,lw=.45,zorder=3)
    counts(axes[1],[0,1],values,[f'{v:.2f} s' for v in values],dy=5)
    axes[1].set_xticks([0,1],['Standard\nn=9','Strong\nn=36']); axes[1].set_ylim(0,40)
    panel(axes[1],'b','Search cost','Mean runtime (s)')
    fig.supxlabel('K=28, M=2, E=2; reference is empirical best-known, not a global optimum.',fontsize=8.5)
    save(fig,'fig12_strong_reference','Strong-reference solution quality and cost',registry)

    geo=json.loads((DATA/'map/stanislaus_S45_A100.json').read_text(encoding='utf-8'))
    if geo.get('schema_version')!=2 or not geo['validation']['all_59_tasks_visited_once']:
        raise ValueError('地理路线必须经过投影校验及 59 任务覆盖核验。')
    background=Image.open(DATA/'map/usgs_topo_utm10.png')
    basemap_extent=json.loads((DATA/'map/basemap_source.json').read_text(encoding='utf-8'))['image_extent_utm']
    fig=figure(220)
    grid=fig.add_gridspec(2,2,height_ratios=[1.3,1],width_ratios=[1,1])
    upper=grid[0,:].subgridspec(1,2,width_ratios=[1.55,1])
    map_ax=fig.add_subplot(upper[0,0]); right=upper[0,1].subgridspec(2,1,height_ratios=[1.2,1])
    inset=fig.add_subplot(right[0,0]); legend_ax=fig.add_subplot(right[1,0])
    map_layers(map_ax,geo,background,basemap_extent)
    map_ax.set_title('(a) Stanislaus: S45/A100',loc='left')
    map_ax.set_xlabel('Easting (km, UTM 10N)'); map_ax.set_ylabel('Northing (km)')
    map_ax.xaxis.set_major_locator(MaxNLocator(4)); map_ax.yaxis.set_major_locator(MaxNLocator(5))
    xmin,ymin,xmax,ymax=geo['bbox_utm']
    # 比例尺使用投影米坐标；方向箭头与地图北向一致。
    sx,sy=xmin+.08*(xmax-xmin),ymin+.08*(ymax-ymin)
    map_ax.plot([sx,sx+1000],[sy,sy],color=INK,lw=1.7,zorder=15)
    map_ax.plot([sx,sx],[sy-65,sy+65],color=INK,lw=1,zorder=15)
    map_ax.plot([sx+1000,sx+1000],[sy-65,sy+65],color=INK,lw=1,zorder=15)
    map_ax.text(sx+500,sy+110,'1 km',ha='center',fontsize=8.5,zorder=15)
    map_ax.annotate('N',xy=(.075,.84),xytext=(.075,.97),xycoords='axes fraction',
                    ha='center',va='center',fontsize=9,fontweight='bold',
                    arrowprops={'arrowstyle':'<|-','color':INK,'lw':.9})
    map_layers(inset,geo,background,basemap_extent,focus=True)
    c=geo['contacts'][0]; t=next(t for t in geo['tasks'] if t['mode']=='offload')
    left=min(c['easting_m'],t['easting_m'])-450; right_edge=max(c['easting_m'],t['easting_m'])+700
    bottom=min(c['northing_m'],t['northing_m'])-550; top=max(c['northing_m'],t['northing_m'])+500
    inset.set_xlim(left,right_edge); inset.set_ylim(bottom,top)
    inset.set_xticks([]); inset.set_yticks([]); inset.set_title('Contact detail (U5)',loc='left',fontsize=9.5)
    map_ax.add_patch(Rectangle((left,bottom),right_edge-left,top-bottom,fill=False,edgecolor=GRAY,ls='--',lw=.75,zorder=6))
    legend_ax.axis('off')
    handles=[Line2D([],[],color=c,ls=s,lw=1.3,label=f'UAV {i+1}') for i,(c,s) in enumerate(zip(ROUTE_COLORS,ROUTE_STYLES))]
    handles.extend([Line2D([],[],marker='o',ls='',markersize=4,markerfacecolor='white',markeredgecolor=INK,label='Task site'),
                    Line2D([],[],marker='s',ls='',color=INK,markersize=4,label='Depot'),
                    Line2D([],[],marker='^',ls='',color=TEAL,markersize=5,label='MEC site'),
                    Line2D([],[],marker='D',ls='',markerfacecolor='white',markeredgecolor=TEAL,markersize=5,label='Contact'),
                    Line2D([],[],marker='*',ls='',color=ORANGE,markersize=7,label='Offloaded task'),
                    Line2D([],[],color=TEAL,ls='--',lw=.8,label='MEC coverage'),
                    Line2D([],[],color=GRAY,ls=(0,(2,3)),lw=.7,label='Study area')])
    legend_ax.legend(handles=handles,loc='upper left',ncols=2,handlelength=1.7,columnspacing=.8,
                     labelspacing=.45,borderaxespad=0,handletextpad=.5)
    legend_ax.text(0,.02,'Basemap: USGS The National Map\nUSFS historical fire locations\nMEC servers are modeled deployments',fontsize=8.5,va='bottom')
    rate_ax=fig.add_subplot(grid[1,0]); pair_ax=fig.add_subplot(grid[1,1])
    rows=[r for r in data.tables['real_geography'] if r['record_type']=='method']
    rate_bars(rate_ax,['Greedy','FR-NM','Generic','Hybrid'],[int(r['strict_count']) for r in rows],
              [int(r['total_count']) for r in rows],colors=[GRAY,GRAY,BLUE,ORANGE])
    panel(rate_ax,'b','Strict feasibility','Strict runs (%)')
    paired_plot(pair_ax,data.pairs(),'c','Common-strict pairs')
    fig.legend(handles=[Line2D([],[],color=BLUE,marker='o',mfc='white',ls='',label='Generic ALNS'),
                        Line2D([],[],color=ORANGE,marker='s',ls='',label='Proposed Hybrid')],
               loc='outside lower center',ncols=2)
    save(fig,'fig13_stanislaus_case','GIS-driven Stanislaus real-geography case',registry)
