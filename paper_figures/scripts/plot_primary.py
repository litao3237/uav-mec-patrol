"""绘制负载、基线、配对和消融实验，统一采用正式运行记录。"""
from statistics import mean
import numpy as np
from figure_style import *
from experiment_data import number,dense_strict,sample_std


def draw_primary(data,registry):
    # 误差条是每个任务规模 9 次运行的样本标准差；右图采用逐对收益的均值。
    table=data.tables['dense_workload']; x=[int(r['K']) for r in table]
    fig=figure(98); axes=fig.subplots(1,2)
    for method,key,color,marker,ls,label in [('generic','base',BLUE,'o','--','Generic ALNS'),('hybrid','hybrid',ORANGE,'s','-','Proposed Hybrid')]:
        values=[[r[f'{key}_cvx_energy_j']/1000 for r in data.dense_rows(k) if dense_strict(r,method)] for k in x]
        series(axes[0],x,[mean(v) for v in values],color=color,marker=marker,ls=ls,label=label,error=[sample_std(v) for v in values])
    panel(axes[0],'a','Energy versus workload','UAV energy (kJ)','Tasks, K')
    axes[0].legend(loc='upper left')
    gains=[number(r,'hybrid_gain_mean_pct') for r in table]
    series(axes[1],x,gains); axes[1].set_ylim(-.05,2.2)
    panel(axes[1],'b','Paired improvement','Hybrid improvement (%)','Tasks, K')
    counts(axes[1],[x[i] for i in (0,2,5)],[gains[i] for i in (0,2,5)],[f'{gains[i]:.3f}%' for i in (0,2,5)],dy=6)
    fig.supxlabel('3 scenarios × 3 algorithm seeds per K; error bars: ±1 SD',fontsize=8.5)
    save(fig,'fig03_dense_workload','Dense-workload performance',registry)

    fig=figure(88); axes=fig.subplots(1,3)
    for ax,letter,key,scale,title,ylabel in zip(axes,'abc',
        ['offload_ratio_mean','contacts_per_uav_mean','route_distance_km_mean'],[100,1,1],
        ['Offloading','MEC contacts','Route length'],['Offloaded tasks (%)','Contacts per UAV','Route distance (km)']):
        series(ax,x,[number(r,key)*scale for r in table]); panel(ax,letter,title,ylabel,'Tasks, K')
        ax.set_xticks([30,40,50,60,70,80])
    fig.supxlabel('Proposed Hybrid; 9 Stage-1-strict runs at each task scale',fontsize=8.5)
    save(fig,'fig04_workload_structure','Structural evolution with workload',registry)

    draw_baselines(data,registry)

    fig=figure(122); axes=fig.subplots(1,2)
    for ax,k,letter in zip(axes,[50,80],'ab'):
        paired_plot(ax,data.pairs(k),letter,f'K = {k}')
    method_legend(fig)
    fig.supxlabel('K=50: 5 better / 4 equal; K=80: 8 better / 1 equal; no worse pairs',fontsize=8.5)
    save(fig,'fig06_paired_comparison','Paired Generic-versus-Hybrid energy',registry)

    fig=figure(92); axes=fig.subplots(1,2,gridspec_kw={'width_ratios':[3,1.6]},sharey=True)
    rows=[r for r in data.tables['ablation'] if r['variant']!='Full Hybrid']
    values=[number(r,'mean_full_advantage_pct') for r in rows]; y=np.arange(4)
    axes[0].barh(y,values,height=.48,color=ORANGE,edgecolor=ORANGE,zorder=3)
    for yi,v in zip(y,values):
        axes[0].text(v+.014,yi,f'{v:.3f}',va='center',fontsize=8.5)
        if v==0: axes[0].plot(0,yi,'|',color=ORANGE,markersize=9)
    axes[0].set_yticks(y,['w/o Route','w/o Contact','w/o Explicit batch','w/o Widening'])
    axes[0].set_ylim(3.6,-1.0); axes[0].set_xlim(0,.83)
    panel(axes[0],'a','Full-Hybrid advantage',xlabel='Mean paired advantage (%)')
    axes[0].grid(axis='y',visible=False); axes[0].grid(axis='x',color='#E5E9EC',lw=.55)
    axes[1].set_xlim(0,1); axes[1].axis('off'); axes[1].set_title('(b) Paired counts',loc='left')
    for cx,label,key in zip([.15,.50,.85],['Full\nbetter','Equal','Ablated\nbetter'],['full_better','full_equal','ablated_better']):
        axes[1].text(cx,-.75,label,ha='center',va='center',fontsize=8.5)
        for yi,r in enumerate(rows): axes[1].text(cx,yi,r[key],ha='center',va='center',fontsize=9)
    fig.supxlabel('9 common-strict pairs per ablation; zero is reported explicitly',fontsize=8.5)
    save(fig,'fig07_elite_ablation','Elite-family ablation',registry)


def draw_baselines(data,registry):
    """完整展示四种基线和本文方法；条件能耗明确保留严格样本分母。"""
    fig=figure(107); axes=fig.subplots(1,2)
    methods=['greedy_repair','nearest_mec','ga','generic_alns','hybrid']
    colors=[TEAL,GRAY,'#776486',BLUE,ORANGE]
    labels=['Greedy*\n2/3','FR-NM\n3/3','Route-GA\n9/9','Generic\n9/9','Hybrid\n9/9']
    all_values=[]
    for i,(method,color) in enumerate(zip(methods,colors)):
        # Greedy 与 FR-NM 在数据接口按场景去重；未获严格解的场景不绘制能耗点。
        values=np.array(data.baseline_values(method))/1000; all_values.extend(values)
        offsets=np.linspace(-.16,.16,len(values))
        axes[0].scatter(i+offsets,values,s=19,color=color,marker=['v','^','D','o','s'][i],alpha=.85,zorder=3)
        axes[0].hlines(mean(values),i-.24,i+.24,color=INK,lw=1.5,zorder=4)
    axes[0].set_xticks(range(len(methods)),labels); axes[0].set_xlim(-.55,4.55)
    axes[0].set_ylim(min(all_values)-12,max(all_values)+15)
    panel(axes[0],'a','K = 50: run-level energy','UAV energy (kJ)','Method (strict / scheduled)')
    rows=[r for r in data.tables['baseline_summary'] if r['K']=='80']
    rate_bars(axes[1],['Greedy','FR-NM','GA†','Generic','Hybrid'],
        [int(r['strict_count']) for r in rows],[int(r['total_count']) for r in rows],
        colors=colors,hatches=['','','///','',''])
    panel(axes[1],'b','K = 80: strict feasibility','Strict runs (%)')
    fig.supxlabel('* Greedy energy uses 2 strict scenarios; horizontal marks show means.\n† K=80 GA: 3-scenario pilot; search budgets are not matched.',fontsize=8.5)
    save(fig,'fig05_baseline_comparison','Baseline energy and strict feasibility',registry)
