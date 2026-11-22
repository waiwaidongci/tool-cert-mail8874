import {datasetField, feedback, field} from '../components/common/fields.js';
import {empty, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

function runRequest(data, spec) {
  const baseline = data.get('baseline_run_id');
  return {dataset_id:Number(data.get('dataset_id')),name:data.get('name'),
    baseline_run_id:baseline ? Number(baseline) : null,
    params:Object.fromEntries(spec.params.map(param=>[param.key,data.get(param.key)]))};
}

function progressText(item) {
  if (!item.progress) return null;
  const {done, total} = item.progress;
  return total ? `已完成 ${done}/${total} 组` : `已完成 ${done} 组`;
}

export async function runPage(route, refresh) {
  const {spec,datasets,runs} = workspace;
  const completed = runs.filter(item => item.status === 'complete');
  const error = feedback();
  const submit = button(`执行${spec.run}`,{type:'submit',class:'primary','data-testid':'start-run'});
  const baseline_field = el('label',{class:'field',for:'baseline-run-id'},el('span',{},'接续上次结果'),
    el('select',{id:'baseline-run-id',name:'baseline_run_id'},
      el('option',{value:''},'不接续（全部组重新计算）'),
      completed.map(item=>el('option',{value:item.id},`运行 ${item.id} · ${item.name}`))),
    el('small',{},'接续后只重算内容变化的组，未变化的组沿用上次结果。'));
  const form = el('form',{class:'fields','data-testid':'run-form',
    onSubmit:handler(submit,error,async event=>{
      const item = await workspace.start(runRequest(new FormData(event.target),spec));
      location.hash = `#results/${item.id}`;
    })}, datasetField(datasets,route.id),field({key:'name',label:'运行名称',type:'string',max_length:120},`样本${spec.run}`),
    spec.params.length ? el('div',{class:'form-grid'},spec.params.map(param=>field(param))) : null,
    baseline_field,el('div',{class:'actions'},submit),error);
  const runList = table([
    {label:'运行',render:item=>link(item.name,`#results/${item.id}`)},
    {label:'状态',render:item=>el('span',{},pill(STATUS[item.status],item.status),
      item.status === 'running' && progressText(item) ? ' ' + progressText(item) : '')},
    {label:'接续',render:item=>item.baseline_run_id ? link(`运行 ${item.baseline_run_id}`,`#results/${item.baseline_run_id}`,{class:'quiet'}) : '—'},
    {label:'时间',render:item=>date(item.created_at)},
  ],runs,{caption:'运行记录',empty:'首次运行后将在此显示后台状态。'});
  return el('div',{class:'two-col'}, el('div',{class:'wide-panel'},
    panel(spec.run,session.canWrite ? (datasets.length ? form : empty('请先导入数据。','#inputs','前往导入'))
      : p('只读角色可以查看上方业务流程的历史运行。','empty')),
    panel('运行记录',runList)),
    el('aside',{class:'sidebar-panel'},panel('计算口径',el('ul',{class:'method-list'},spec.methodology.map(text=>el('li',{},text))))));
}
