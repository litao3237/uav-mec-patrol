/**
 * 绘制以操作前后变化为主的 Hybrid ALNS 机制图。
 * 图元最终由 Microsoft Visio 原生绘制；本脚本只生成独立场景，不读取或改写固定版。
 * 路径和资源分配均为机制示意，不对应实验数值，也不预先宣称候选一定节能。
 */
import {writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const C = {
  ink:'#29343D', gray:'#75828B', border:'#BDCAD0', white:'#FFFFFF', faint:'#F6F8FA',
  blue:'#306587', blueFill:'#EFF5F9', orange:'#A46D36', orangeFill:'#FCF6EF',
  teal:'#397B73', tealFill:'#EFF7F4', ghost:'#C1CBD2',
};
const scene = {
  name:'fig02_hybrid_alns_visual', width:1000, height:792, widthMm:183,
  description:'Visual mechanisms of Hybrid ALNS: route destroy/repair, structural candidates, and repeated continuous-resource evaluation.',
  shapes:[],
};
const identifiers = new Set();
function add(type,id,properties) {
  if (identifiers.has(id)) throw new Error(`图形机制版存在重复标识：${id}`);
  identifiers.add(id);
  scene.shapes.push({type,id,group:'structure',...properties});
}
function rect(id,x,y,w,h,fill=C.white,stroke=C.border,group=id,extra={}) {
  add('rect',id,{x,y,w,h,fill,stroke,linePt:0.65,group,...extra});
}
function text(id,x,y,w,h,value,size=8.5,bold=false,group='labels',extra={}) {
  add('text',id,{x,y,w,h,text:value,fontPt:size,bold,align:'center',
    fill:null,stroke:null,color:C.ink,group,...extra});
}
function line(id,points,color=C.ink,arrow=true,group='connections',extra={}) {
  add('polyline',id,{points,stroke:color,fill:null,arrow,linePt:0.85,group,...extra});
}
function circle(id,x,y,r=4,color=C.blue,fill=C.white,group='structure',extra={}) {
  add('ellipse',id,{x:x-r,y:y-r,w:2*r,h:2*r,stroke:color,fill,linePt:0.75,group,...extra});
}
function diamond(id,x,y,r=5.5,group='structure') {
  add('polygon',id,{points:[[x,y-r],[x+r,y],[x,y+r],[x-r,y],[x,y-r]],
    stroke:C.teal,fill:C.white,linePt:0.85,group});
}
function check(id,x,y,size=14,color=C.teal,group='structure') {
  line(id,[[x,y+size*.5],[x+size*.34,y+size*.84],[x+size,y]],color,false,group,{linePt:1.4});
}
function chip(id,x,y,w=34,h=32,group='resources') {
  for (let i=0;i<3;i++) {
    const cy=y+7+i*(h-14)/2;
    line(id+'_pin_l_'+i,[[x-5,cy],[x,cy]],C.blue,false,group,{linePt:0.65});
    line(id+'_pin_r_'+i,[[x+w,cy],[x+w+5,cy]],C.blue,false,group,{linePt:0.65});
  }
  rect(id,x,y,w,h,C.blueFill,C.blue,group);
  rect(id+'_core',x+7,y+7,w-14,h-14,C.white,C.blue,group,{linePt:0.5});
}
function server(id,x,y,w=30,h=40,group='resources') {
  rect(id,x,y,w,h,C.white,C.teal,group);
  for (let i=0;i<3;i++) rect(id+'_rack_'+i,x+5,y+6+i*(h-11)/3,w-10,6,C.tealFill,C.teal,group,{linePt:0.5});
}
function task(id,x,y,label,group,w=18,h=23) {
  rect(id,x,y,w,h,C.orangeFill,C.orange,group);
  text(id+'_label',x,y,w,h,String(label),8.5,false,group);
}
function funnel(id,x,y,w=34,h=28,group='structure') {
  add('polygon',id,{points:[[x,y],[x+w,y],[x+w*.61,y+h*.55],[x+w*.61,y+h],
    [x+w*.39,y+h],[x+w*.39,y+h*.55],[x,y]],fill:C.white,stroke:C.teal,linePt:0.85,group});
}
function heading(id,x,y,w,label,color) {
  rect(id+'_band',x,y,w,35,color,null,id);
  text(id+'_label',x+12,y+4,w-24,27,label,10,true,id,{align:'left',color:C.white});
}

// 同一组编号任务在初始、破坏、修复状态下保持固定位置；仅改变路线和访问集合。
const NODES = [[.10,.80],[.08,.22],[.47,.04],[.93,.25],[.88,.86],[.45,.53]];
const originalOrder = [0,1,2,3,4,5,0];
const repairedOrder = [0,1,5,2,3,4,0];
function route(id,x,y,w,h,order,{numbered=false,removed=[],highlight=[],color=C.blue}={}) {
  const point = n => [x+NODES[n][0]*w,y+NODES[n][1]*h];
  const radius = numbered ? 9 : 3.6;
  // 被移除的任务仍显示在原位置，淡虚线只提示旧边，防止被理解成任务丢失。
  if (removed.length) {
    for (let i=0;i<originalOrder.length-1;i++) {
      const a=originalOrder[i], b=originalOrder[i+1];
      if (removed.includes(a)||removed.includes(b)) {
        line(id+'_old_'+i,[point(a),point(b)],C.ghost,false,id,{dash:2,linePt:0.65});
      }
    }
  }
  for (let i=0;i<order.length-1;i++) {
    const a=order[i],b=order[i+1];
    const emphasized=highlight.includes(a)||highlight.includes(b);
    line(id+'_edge_'+i,[point(a),point(b)],emphasized?C.orange:color,false,id,{linePt:numbered?1:0.85});
  }
  // 在最后一段设置小方向箭头；箭头位于边中部，避免被终点任务圆覆盖。
  const a=point(order.at(-2)), b=point(order.at(-1));
  line(id+'_direction',[[a[0]*.63+b[0]*.37,a[1]*.63+b[1]*.37],
    [a[0]*.40+b[0]*.60,a[1]*.40+b[1]*.60]],color,true,id,{linePt:0.75});
  const depot=point(0);
  rect(id+'_depot',depot[0]-4,depot[1]-4,8,8,C.ink,C.ink,id);
  for (let n=1;n<NODES.length;n++) {
    const [nx,ny]=point(n), emphasized=removed.includes(n)||highlight.includes(n);
    circle(id+'_task_'+n,nx,ny,radius,emphasized?C.orange:color,
      emphasized?C.orangeFill:C.white,id,removed.includes(n)?{dash:2}:{});
    if (numbered) text(id+'_number_'+n,nx-radius,ny-radius,2*radius,2*radius,String(n),8.5,false,id);
  }
}

// 顶部主线表达执行顺序；严格校验节点仅展示校验通过的主路径。
for (const [id,x,w,label,color] of [
  ['initialize',50,122,'Initialize',C.ink],
  ['explore',231,138,'ALNS exploration',C.blue],
  ['validate',427,146,'Strict validation',C.teal],
  ['refine',628,144,'Elite refinement',C.orange],
  ['final',839,123,'Final solution',C.ink],
]) {
  text(id+'_title',x-12,24,w+24,27,label,9.3,true,'main_flow',{color});
  rect(id+'_frame',x,65,w,83,C.white,C.border,'main_flow');
}
route('initial_routes',68,83,83,49,originalOrder);
route('final_routes',855,83,83,49,repairedOrder,{highlight:[2,5]});
for (const [id,start,end] of [['first',172,231],['second',369,427],['third',573,628],['fourth',772,839]]) {
  line('flow_'+id,[[start+5,107],[end-7,107]],C.ink,true,'main_flow',{linePt:1.05});
}
// 循环图标用候选卡片与回箭头表示反复搜索，避免装饰性图片抢占主体。
rect('explore_card_back',267,89,33,28,C.blueFill,C.blue,'main_flow');
rect('explore_card_front',293,102,33,28,C.white,C.blue,'main_flow');
line('explore_loop_top',[[330,93],[330,80],[261,80],[261,92]],C.blue,true,'main_flow');
line('explore_loop_bottom',[[264,125],[264,137],[333,137],[333,123]],C.blue,true,'main_flow');
rect('validation_sheet',477,78,47,58,C.tealFill,C.teal,'main_flow');
check('validation_check',489,91,21,C.teal,'main_flow');
text('validation_cvx',478,115,45,18,'CVX',8.5,true,'main_flow',{color:C.teal});
for (let i=0;i<3;i++) rect('refine_card_'+i,651+i*29,88,19,26,i===1?C.orangeFill:C.white,C.orange,'main_flow');
line('refine_pick',[[660,122],[660,134],[718,134],[718,120]],C.orange,true,'main_flow');
line('top_divider',[[50,173],[962,173]],C.border,false,'main_flow',{linePt:0.6});

// 主体左侧：图形表达破坏与重插入，评价后再接受/更新，不暗示探索严格单调。
rect('exploration_panel',58,199,398,375,C.blueFill,C.border,'exploration');
heading('exploration_heading',58,199,398,'(a) ALNS exploration',C.blue);
for (const [id,x,label] of [['current',82,'Current'],['destroy',208,'Destroy'],['repair',335,'Repair']]) {
  text(id+'_label',x,248,102,25,label,9.2,true,'exploration');
}
route('current_route',87,295,89,77,originalOrder,{numbered:true});
route('destroyed_route',213,295,89,77,[0,1,3,4,0],{numbered:true,removed:[2,5]});
route('repaired_route',340,295,89,77,repairedOrder,{numbered:true,highlight:[2,5]});
line('destroy_transition',[[185,330],[200,330]],C.gray,true,'exploration');
line('repair_transition',[[311,330],[327,330]],C.gray,true,'exploration');
rect('explore_evaluate',285,446,135,40,C.white,C.blue,'exploration');
text('explore_evaluate_label',291,452,123,27,'Evaluate',9,true,'exploration');
rect('explore_accept',100,446,159,40,C.white,C.blue,'exploration');
text('explore_accept_label',105,452,149,27,'Accept / update',8.8,true,'exploration');
line('repair_to_evaluate',[[385,380],[385,446]],C.blue,true,'exploration');
line('evaluate_to_accept',[[285,466],[259,466]],C.blue,true,'exploration');
line('accept_to_current',[[133,446],[133,384]],C.blue,true,'exploration');

// 主体右侧：四种候选独立展示，编号和位置保持一致，箭头不表示必然被接受。
rect('elite_panel',540,199,400,375,C.orangeFill,C.border,'elite');
heading('elite_heading',540,199,400,'(b) Elite refinement',C.orange);
for (const [id,x,y,label] of [
  ['move_route',553,246,'Route'],['move_batch',747,246,'Batch'],
  ['move_contact',553,385,'Contact'],['move_mode',747,385,'Task mode'],
]) {
  rect(id+'_panel',x,y,181,131,C.white,C.border,id,{linePt:0.5});
  text(id+'_title',x+6,y+4,169,25,label,9.2,true,id);
}

// 路线操作仅改变访问顺序，前后绘制同一组固定位置的任务。
route('route_before',568,304,60,51,[0,1,3,2,4,5,0]);
route('route_after',663,304,60,51,[0,1,2,3,4,5,0]);
line('route_change',[[636,329],[653,329]],C.gray,true,'move_route');

// 两个批次合并到较晚接触 c₂：任务 1、2、3 在合并前后各保留一次。
rect('batch_early',778,291,42,30,C.faint,C.border,'move_batch');
rect('batch_late',778,337,42,30,C.faint,C.border,'move_batch');
text('batch_c1',751,294,24,23,'c₁',8.5,false,'move_batch',{italic:true});
text('batch_c2',751,340,24,23,'c₂',8.5,false,'move_batch',{italic:true});
task('batch_1_before',781,295,1,'move_batch',17,22);
task('batch_2_before',801,295,2,'move_batch',17,22);
task('batch_3_before',791,341,3,'move_batch',17,22);
line('batch_join_early',[[820,306],[834,306],[834,328]],C.gray,false,'move_batch');
line('batch_join_late',[[820,352],[834,352],[834,328]],C.gray,false,'move_batch');
line('batch_join',[[834,328],[852,328]],C.gray,true,'move_batch');
rect('batch_combined',854,309,67,37,C.faint,C.border,'move_batch');
for (let i=1;i<=3;i++) task('batch_'+i+'_after',857+(i-1)*21,316,i,'move_batch',18,23);
text('batch_c2_after',873,350,29,23,'c₂',8.5,false,'move_batch',{italic:true});

// 接触点在覆盖区内变化，两个监测任务的位置与访问先后保持不变。
for (const [tag,dx,contactY,label] of [['before',0,438,'c'],['after',95,458,'c′']]) {
  add('ellipse','coverage_'+tag,{x:586+dx,y:423,w:32,h:73,fill:C.tealFill,stroke:C.teal,linePt:0.6,dash:2,group:'move_contact'});
  line('contact_route_'+tag,[[574+dx,486],[602+dx,contactY],[627+dx,486]],C.blue,false,'move_contact');
  circle('contact_start_'+tag,574+dx,486,4,C.blue,C.white,'move_contact');
  circle('contact_end_'+tag,627+dx,486,4,C.blue,C.white,'move_contact');
  diamond('contact_'+tag,602+dx,contactY,5.5,'move_contact');
  text('contact_name_'+tag,555+dx,contactY-18,28,22,label,8.5,false,'move_contact',{italic:true});
}
line('contact_change',[[636,460],[653,460]],C.gray,true,'move_contact');

// 相同任务 1 从机载芯片切换至 MEC，竖向虚线为任务上传而非巡航路线。
task('mode_task_before',784,422,1,'move_mode');
task('mode_task_after',887,422,1,'move_mode');
chip('mode_cpu',779,458,29,29,'move_mode');
server('mode_server',881,455,31,37,'move_mode');
line('mode_to_cpu',[[793,445],[793,457]],C.blue,true,'move_mode');
line('mode_to_server',[[896,445],[896,454]],C.teal,true,'move_mode',{dash:3});
line('mode_change',[[826,462],[859,462]],C.gray,true,'move_mode');
text('mode_local',764,493,60,21,'Local',8.5,false,'move_mode');
text('mode_mec',866,494,61,21,'MEC',8.5,false,'move_mode');

// 精英候选先进入筛选漏斗，严格求值的返回结果再送入有意义收益门槛。
text('shortlist_label',664,523,116,24,'Shortlist',8.8,false,'elite');
funnel('elite_shortlist',789,523,30,22,'elite');
text('elite_acceptance',628,549,215,22,'Accept if ΔE > τ',8.8,true,'elite');

// 下层是可重复调用的评价服务；分配条不带坐标或数值，不冒充实验统计图。
text('resource_heading',58,592,462,29,'(c) Resource evaluation',10,true,'resources',{align:'left'});
rect('screening_panel',58,638,235,123,C.tealFill,C.teal,'screening');
text('screening_title',66,642,219,25,'Screening',9.3,true,'screening');
funnel('screen_filter',122,680,43,36,'screening');
check('screen_check',192,686,20,C.teal,'screening');
text('screen_question',215,678,27,31,'?',13,true,'screening',{color:C.teal});
text('screening_methods',65,729,221,23,'Proxy / precheck',8.8,false,'screening');
line('optional_cvx',[[293,700],[383,700]],C.teal,true,'resource_calls',{dash:2});
line('optional_cvx_return',[[383,740],[293,740]],C.teal,true,'resource_calls',{dash:2});
text('optional_cvx_label',296,668,84,25,'as needed',8.5,false,'resource_calls');
rect('strict_panel',383,638,559,123,C.tealFill,C.teal,'strict_cvx');
text('strict_title',392,642,541,25,'Strict CVX',9.3,true,'strict_cvx');
chip('allocation_cpu',424,688,39,35,'strict_cvx');
for (let i=0;i<3;i++) {
  rect('bandwidth_track_'+i,532,685+i*15,80,9,C.white,C.teal,'strict_cvx',{linePt:0.5});
  rect('bandwidth_share_'+i,533,686+i*15,[49,28,62][i],7,C.teal,null,'strict_cvx');
}
text('allocation_cpu_label',393,734,108,22,'CPU',8.5,false,'strict_cvx');
text('allocation_bandwidth_label',508,734,132,22,'Bandwidth',8.5,false,'strict_cvx');
line('allocation_to_result',[[634,706],[677,706]],C.teal,true,'strict_cvx');
rect('resource_result',690,678,231,75,C.white,C.border,'strict_cvx');
text('resource_energy',703,690,93,28,'E(D)',11,false,'strict_cvx',{italic:true});
check('feasible_symbol',830,694,18,C.teal,'strict_cvx');
line('infeasible_symbol_a',[[879,696],[894,711]],C.gray,false,'strict_cvx',{linePt:1.2});
line('infeasible_symbol_b',[[879,711],[894,696]],C.gray,false,'strict_cvx',{linePt:1.2});
text('resource_return_label',699,727,213,23,'Energy / status',8.5,false,'strict_cvx');

// 请求与返回沿外围分开布线，避免穿过路线、任务和操作小图。
line('exploration_request',[[390,486],[390,536],[24,536],[24,684],[58,684]],C.teal,true,'resource_calls');
line('exploration_response',[[58,722],[42,722],[42,556],[414,556],[414,486]],C.teal,true,'resource_calls');
line('elite_request',[[819,534],[976,534],[976,684],[942,684]],C.teal,true,'resource_calls');
line('elite_response',[[942,726],[958,726],[958,560],[843,560]],C.teal,true,'resource_calls');

// 对图形语义和尺寸做轻量检查，防止后续编辑无意丢失任务或重新堆入长段文字。
const visitedTasks = order => [...new Set(order.filter(n=>n!==0))].sort().join(',');
if (visitedTasks(originalOrder)!==visitedTasks(repairedOrder)) throw new Error('修复图必须保留原任务集合。');
for (const shape of scene.shapes) {
  const points=shape.points??[[shape.x,shape.y],[shape.x+shape.w,shape.y+shape.h]];
  if (points.some(point=>point.some(v=>!Number.isFinite(v))) ||
      points.some(([x,y])=>x<0||y<0||x>scene.width||y>scene.height)) {
    throw new Error(`图元坐标无效或越界：${shape.id}`);
  }
  if (shape.type==='text' && shape.fontPt<8.5) throw new Error(`字号低于论文可读下限：${shape.id}`);
}
const allText=scene.shapes.filter(s=>s.type==='text').map(s=>s.text).join(' ');
const wordCount=(allText.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g)??[]).length;
if (wordCount>80) throw new Error(`英文文字超过 80 词：${wordCount}`);
scene.englishWordCount=wordCount;
scene.semanticChecks={taskSetBefore:[1,2,3,4,5],taskSetAfter:[1,2,3,4,5],
  removedTasks:[2,5],batchBefore:[[1,2],[3]],batchAfter:[1,2,3],
  batchDestination:'later contact c2',modeTaskBefore:1,modeTaskAfter:1};
const output=fileURLToPath(new URL('../visio/assets/fig02_hybrid_alns_visual.scene.json',import.meta.url));
writeFileSync(output,JSON.stringify(scene,null,2)+'\n','utf8');
console.log(`已生成图形机制版构图：${scene.shapes.length} 个原生图元，${wordCount} 个英文词，183 × ${(792*.183).toFixed(3)} mm。`);
