import {plot} from '../components/common/chart.js';
import {feedback} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {REVIEW, STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

function downloadButton(job, message) {
  const download = button('下载结果 CSV',{class:'quiet','data-testid':'export',onClick:event=>
    handler(download,message,()=>workspace.download(`/runs/${job.id}/export`,`${job.name}-${job.id}.csv`))(event)});
  return download;
}

function progressText(job, replacing) {
  const {done, total} = job.progress || {};
  const progress = total ? `已完成 ${done}/${total} 组` : `已完成 ${done || 0} 组`;
  return replacing ? `${progress}，全部组完成后一并替换上次结果。` : `${progress}，后台正在继续计算。`;
}

function resultBody(job, {message, banner}) {
  const result = job.result;
  return el('section',{class:'analysis','data-testid':'analysis-complete'},
    banner,
    el('div',{class:'result-head'},p(job.name,'eyeline'),h(2,result.headline),p(result.note,'intro-copy'),
      el('div',{class:'actions'},pill(STATUS[job.status],job.status),downloadButton(job,message),message)),
    metrics(result.metrics),
    (result.charts || []).map(plot),
    (result.sections || []).map(item=>panel(item.title,p(item.text))),
    (result.tables || []).map(item=>panel(item.title,table(item.columns,item.rows,{caption:item.title}))));
}

export async function results(route, refresh) {
  const {spec,runs,datasets} = workspace;
  const id = route.id || runs[0]?.id;
  if (!id) return panel(spec.pages[3],empty('还没有可查看的运行结果。','#run','前往运行'));
  const job = await workspace.getRun(id);
  const source = datasets.find(item => item.id === job.dataset_id);
  const message = feedback();
  const finished = item => item.status === 'complete' || item.status === 'failed';
  const history = el('label',{class:'field run-picker',for:'run-picker'},el('span',{},'切换运行记录'),
    el('select',{id:'run-picker',onChange:event=>{location.hash=`#results/${event.target.value}`;}},
      (runs.some(item=>item.id===job.id) ? runs : [job,...runs]).map(item=>el('option',{value:item.id,selected:item.id===job.id},item.name))));
  const inputs = spec.params.length ? el('dl',{class:'dictionary'},spec.params.map(param=>
    el('div',{},el('dt',{},param.label),el('dd',{},value(job.params[param.key]))))) : null;
  const sidebar = el('aside',{class:'sidebar-panel'},panel('运行来源',history,
      source && link(source.name,`#inputs/${source.id}`),p(date(job.finished_at),'subtle'),
      job.baseline_run_id && link(`接续运行 ${job.baseline_run_id}`,`#results/${job.baseline_run_id}`,{class:'quiet'}),
      inputs),
    job.status === 'complete' && panel(spec.decision, pill(REVIEW[job.review],job.review),
      link('打开复核记录',`#review/${job.id}`,{class:'quiet'})));

  if (!finished(job)) {
    const original = location.hash;
    const replacing = Boolean(job.baseline_run_id);
    const banner = el('div',{class:'empty'},
      p(job.status === 'running' ? progressText(job, replacing) : '后台排队中，之后自动开始。'),
      p(replacing ? '重算未完成前保留上次已发布结果；中断后会自动从已完成的组继续。'
        : '计算未完成前不展示结果；中断后会自动从已完成的组继续。','subtle'));
    poll(()=>workspace.getRun(id),finished,()=>location.hash===original)
      .then(found=>{if (found && location.hash===original) refresh();})
      .catch(error=>{if(banner.isConnected) banner.append(p(error.message,'feedback'));});
    if (job.baseline_run_id) {
      const baseline = await workspace.getRun(job.baseline_run_id);
      if (baseline.result) {
        return el('div',{},el('div',{class:'two-col'},el('div',{class:'wide-panel'},
          resultBody(baseline,{message,banner:
            el('div',{class:'empty'},p(progressText(job, true)),p(
              `以下为运行 ${baseline.id} 的上次已发布结果，本次重算完成后整体替换。`,'subtle'))})),sidebar));
      }
    }
    return el('div',{},panel(job.name,pill(STATUS[job.status],job.status),banner,
      button('刷新',{class:'quiet',onClick:refresh})),
      el('div',{class:'two-col'},el('div',{class:'wide-panel'}),sidebar));
  }

  const analysis = job.result ? resultBody(job,{message,banner:null})
    : panel(job.name,pill(STATUS[job.status],job.status),p(job.error,'feedback'),
      link('返回调整参数',`#run/${job.dataset_id}`,{class:'quiet'}));
  return el('div',{},el('div',{class:'two-col'},el('div',{class:'wide-panel'},analysis),sidebar));
}
