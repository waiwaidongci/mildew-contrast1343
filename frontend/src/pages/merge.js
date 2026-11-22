import {feedback, field} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {ATTEMPT, MERGE} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

const PATTERN_COLUMNS = [
  {key:'pattern_id', label:'模式编号'},
  {key:'conditions', label:'伴随条件'},
  {label:'正组命中', render:row=>value(row.positive_count)},
  {label:'负组命中', render:row=>value(row.negative_count)},
  {label:'正组支持度', render:row=>value(row.positive_support)},
  {label:'负组支持度', render:row=>value(row.negative_support)},
  {label:'增长倍数', render:row=>value(row.growth)},
];

const HIT_LABELS = {
  high_humidity:['低于高湿切分点', '高湿'],
  vent_blocked:['风口未遮挡', '风口遮挡'],
  maintenance_pending:['无待结报修', '设施报修待结'],
};

function conditionLabel(key) {
  return key.split('+').map(part => {
    const [name, raw] = part.split(':');
    const pair = HIT_LABELS[name];
    return pair ? pair[raw === 'true' ? 1 : 0] : `${name} ${raw}`;
  }).join('且');
}

function contributionTable(detail) {
  const rows = detail.ledger ? detail.ledger.contributions : (detail.preview?.contributions || []);
  return table([
    {key:'room', label:'库房'},
    {key:'version', label:'包版本'},
    {label:'见霉斑', render:row=>value(row.positive_count)},
    {label:'未见霉斑', render:row=>value(row.negative_count)},
    {label:'样本合计', render:row=>value(row.total_count)},
    {label:'包编号', render:row=>row.reference || '—'},
    {label:'入账时间', render:row=>date(row.received_at)},
  ], rows, {caption:'各库房贡献的计数', empty:'还没有库房入库。'});
}

function hitBreakdown(detail) {
  const rows = detail.ledger ? detail.ledger.contributions : (detail.preview?.contributions || []);
  const keys = detail.pattern_keys || [];
  const columns = [
    {key:'room', label:'库房'},
    ...keys.map(key => ({label:conditionLabel(key), render:row=>{
      const hit = row.pattern_hits?.[key] || {};
      return `${value(hit.positive)} / ${value(hit.negative)}`;
    }})),
  ];
  return table(columns, rows, {caption:'各库房条件命中（正组 / 负组）', empty:'还没有库房入库。'});
}

function leaderboard(detail) {
  const source = detail.ledger || detail.preview;
  if (!source) return null;
  const published = Boolean(detail.ledger);
  return el('div', {},
    el('div', {class:'result-head'}, p(detail.name, 'eyeline'), h(2, source.headline), p(source.note, 'intro-copy'),
      el('div', {class:'actions'}, pill(MERGE[detail.state], detail.state),
        published ? p(`发布于 ${date(detail.published_at)}`, 'subtle')
          : p('尚未发布：以下为已入账计数的预览', 'subtle'))),
    metrics([
      {label:'参与库房', value:source.totals.rooms},
      {label:'见霉斑巡检', value:source.totals.positive_count, detail:'正组支持度的分母'},
      {label:'未见霉斑巡检', value:source.totals.negative_count, detail:'负组支持度的分母'},
      {label:'巡检合计', value:source.totals.total_count, detail:'各库房计数加总'},
    ]),
    panel(published ? '总榜（按原筛查规则排序）' : '总榜预览（按原筛查规则排序）',
      table(PATTERN_COLUMNS, source.patterns, {caption:'合并后总榜'})),
    panel('各库房贡献的计数', contributionTable(detail)),
    panel('条件命中对账', hitBreakdown(detail)));
}

function packageBoard(detail) {
  return table([
    {key:'room', label:'库房'},
    {key:'version', label:'包版本'},
    {label:'状态', render:row=>pill(ATTEMPT[row.state] || row.state, row.state)},
    {label:'见霉斑', render:row=>value(row.positive_count)},
    {label:'未见霉斑', render:row=>value(row.negative_count)},
    {key:'reference', label:'包编号'},
    {label:'摘要', render:row=>row.checksum ? row.checksum.slice(0, 12) + '…' : '—'},
    {label:'入账时间', render:row=>date(row.received_at)},
  ], detail.packages, {caption:'已入账分包', empty:'还没有库房提交分包。'});
}

function attemptLog(detail) {
  return table([
    {key:'room', label:'库房'},
    {key:'version', label:'包版本'},
    {key:'reference', label:'包编号'},
    {label:'结果', render:row=>pill(ATTEMPT[row.outcome] || row.outcome, row.outcome)},
    {key:'detail', label:'说明'},
    {label:'时间', render:row=>date(row.created_at)},
  ], detail.attempts, {caption:'分包到达记录', empty:'还没有分包到达。'});
}

function createForm(refresh, message) {
  const submit = button('建立合并', {class:'primary', type:'submit'});
  return el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    const rooms = String(data.get('rooms') || '').split(/[,，、\n]/).map(item => item.trim()).filter(Boolean);
    if (rooms.length < 2) throw new Error('请至少填写两个参与库房');
    const params = Object.fromEntries(workspace.spec.params.map(param => [param.key, data.get(param.key)]));
    const item = await workspace.createMerge({name:data.get('name'), rooms, params});
    location.hash = `#merge/${item.id}`;
    await refresh();
  })},
    field({key:'name', label:'合并名称', type:'string', max_length:120}),
    el('label', {class:'field', for:'merge-rooms'}, el('span', {}, '参与库房'),
      el('textarea', {id:'merge-rooms', name:'rooms', required:true, rows:2,
        placeholder:'用逗号或换行分隔，如 东一库、东二库、北一库'})),
    el('div', {class:'form-grid'}, workspace.spec.params.map(param => field(param))),
    submit);
}

function packageForm(detail, refresh, message) {
  const submit = button('入账分包', {class:'primary', type:'submit'});
  return el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    let body;
    try {
      body = JSON.parse(String(data.get('payload') || ''));
    } catch {
      throw new Error('分包内容须为有效的 JSON');
    }
    await workspace.submitMergePackage(detail.id, body);
    await refresh();
  })},
    el('label', {class:'field', for:'merge-payload'}, el('span', {}, '计数包 JSON'),
      el('textarea', {id:'merge-payload', name:'payload', required:true, rows:6,
        placeholder:'粘贴库房本地生成的计数包；包可乱序到达，重试不会重复入账。'})),
    submit);
}

function returnForm(detail, refresh, message) {
  const submit = button('退回换包', {class:'quiet', type:'submit'});
  const options = detail.rooms.map(room => el('option', {value:room}, room));
  return el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    await workspace.returnMergeRoom(detail.id, {room:data.get('room'), note:data.get('note')});
    await refresh();
  })},
    el('label', {class:'field', for:'merge-return-room'}, el('span', {}, '退回库房'),
      el('select', {id:'merge-return-room', name:'room'}, options)),
    el('label', {class:'field', for:'merge-return-note'}, el('span', {}, '退回说明'),
      el('textarea', {id:'merge-return-note', name:'note', required:true, maxlength:500, rows:2})),
    submit);
}

export async function mergePage(route, refresh) {
  const {spec} = workspace;
  const merges = await workspace.merges();
  const selected = merges.find(item => item.id === route.id) || merges[0];
  const message = feedback();
  const detail = selected ? await workspace.getMerge(selected.id) : null;

  const picker = merges.length ? el('label', {class:'field', for:'merge-picker'}, el('span', {}, '选择合并'),
    el('select', {id:'merge-picker', onChange:event => { location.hash = `#merge/${event.target.value}`; }},
      merges.map(item => el('option', {value:item.id, selected:item.id === selected?.id},
        `${item.name} · ${MERGE[item.state] || item.state}`)))) : null;

  const conflict = detail?.state === 'conflict' ? el('div', {class:'empty', role:'alert'},
    p(`发现 ${detail.conflicts.credential_count} 条巡检凭据在两个及以上库房重复，涉及 ${detail.conflicts.rooms.join('、')}。发布已暂停，请退回换包后重新核对。`)) : null;

  const controls = [];
  if (detail && session.canWrite) controls.push(panel('入账分包', p('各库房只提交两组样本数、条件命中数和查重凭据；原表和单号留在本地。','subtle'), packageForm(detail, refresh, message)));
  if (detail && session.canReview) {
    const blocked = detail.state === 'conflict' || detail.missing_rooms.length > 0;
    const publish = button(detail.state === 'published' ? '重新核对并发布' : '核对并发布总榜',
      {class:'primary', disabled:blocked});
    publish.addEventListener('click', handler(publish, message, async () => {
      await workspace.publishMerge(detail.id);
      await refresh();
    }));
    controls.push(panel('核对与发布', p('库房齐备且无跨库房重复后，把命中数与样本数加总，按原规则重新排序。','subtle'),
      detail.missing_rooms.length ? p(`尚未入账：${detail.missing_rooms.join('、')}`, 'subtle') : p('全部库房已入账。', 'subtle'),
      conflict, el('div', {class:'actions'}, publish),
      p('如凭据重复或口径不一致，退回后库房换包前保持暂停发布。', 'subtle'),
      returnForm(detail, refresh, message)));
  }

  return el('div', {class:'two-col'},
    el('div', {class:'wide-panel'},
      panel(spec.pages[6], p('各库房离线计算后只上报计数与查重凭据，由保管组统一核对、加总并排出总榜。','subtle'),
        picker, message),
      detail ? leaderboard(detail) : empty('还没有合并。先建立一次合并并冻结参与库房与筛查参数。'),
      detail && panel('已入账分包', p('以包版本为准，重试不重复入账，迟到旧包不覆盖新版本。','subtle'), packageBoard(detail)),
      detail && panel('分包到达记录', attemptLog(detail)),
      ...controls),
    el('aside', {class:'sidebar-panel'},
      panel('建立合并', p('先定好参与库房与筛查参数；各库房按同一口径在本地生成计数包。','subtle'),
        session.canWrite ? createForm(refresh, message) : p('只读角色可查看合并结果。', 'subtle')),
      detail && panel('当前合并', el('dl', {class:'dictionary'},
        el('div', {}, el('dt', {}, '状态'), el('dd', {}, MERGE[detail.state] || detail.state)),
        el('div', {}, el('dt', {}, '参与库房'), el('dd', {}, detail.rooms.join('、'))),
        el('div', {}, el('dt', {}, '已入账'), el('dd', {}, detail.accepted_rooms.join('、') || '—')),
        el('div', {}, el('dt', {}, '未入账'), el('dd', {}, detail.missing_rooms.join('、') || '—')),
        el('div', {}, el('dt', {}, '高湿切分点'), el('dd', {}, value(detail.params.humidity_threshold))),
        el('div', {}, el('dt', {}, '平滑量 α'), el('dd', {}, value(detail.params.smoothing))),
        el('div', {}, el('dt', {}, '正组最少命中'), el('dd', {}, value(detail.params.min_positive_count))),
        el('div', {}, el('dt', {}, '两组合计最少'), el('dd', {}, value(detail.params.min_total_count))),
        el('div', {}, el('dt', {}, '最低增长倍数'), el('dd', {}, value(detail.params.min_growth))))),
      detail && panel('查重凭据口径', p(detail.credential_scheme.help, 'subtle'),
        p('凭据只用于发现跨库房重复的同一巡检，不还原巡检单号。', 'subtle')),
      panel('计算口径', el('ul', {class:'method-list'}, spec.methodology.map(text => el('li', {}, text))))));
}
