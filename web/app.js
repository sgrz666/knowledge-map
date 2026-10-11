'use strict';
const $ = (id) => document.getElementById(id);
const views = {chat:'学习助手',practice:'练习与模考',plan:'学习计划',profile:'学情与复习',interview:'面试练习',audit:'知识库审查',settings:'模型与设置'};
const levels = {xiaoxue:'小学',youer:'幼儿园',zhongxue:'中学公共科目',chuzhong:'初中',gaozhong:'高中',zhongxiaoxue:'中小学面试'};
const subjects = {zonghe:'综合素质',jiaoxue:'教育教学知识与能力',jiaoyuzhishi:'教育知识与能力',baojiao:'保教知识与能力',yuwen:'语文',shuxue:'数学',yingyu:'英语',wuli:'物理',huaxue:'化学',shengwu:'生物',dili:'地理',lishi:'历史',zhengzhi:'思想政治',meishu:'美术',yinyue:'音乐',tiyu:'体育',xinxi:'信息技术',jiaoyuxue:'教育学',jiaoyuxinlixue:'教育心理学',mianshi:'面试任务'};
const state = {bootstrap:null,view:'chat',paper:null,plan:null,history:[],timer:null,submissions:new Map(),
  key:'',token:'',base:'https://api.deepseek.com',model:'deepseek-flash',session:null};
let prefs = {};
try { prefs = JSON.parse(localStorage.getItem('knowledge-map-prefs') || '{}'); } catch {}
state.base = prefs.base || state.base; state.model = prefs.model || state.model;
$('learner-id').value = prefs.user || 'local-learner'; $('trust-tier').value = prefs.tier || 'research_internal';
$('exam').value = prefs.exam || 'NTCE'; $('level').value = prefs.level || 'xiaoxue';
$('base-url').value = state.base; $('model-name').value = state.model;

function el(tag, text, className) { const e=document.createElement(tag); if(text!==undefined)e.textContent=String(text); if(className)e.className=className; return e; }
function button(text, action, cls='secondary') { const e=el('button',text,cls);e.type='button';e.addEventListener('click',action);return e; }
function replace(target, ...children) { $(target).replaceChildren(...children); }
function context() { const ntce=$('exam').value==='NTCE';return {user_id:$('learner-id').value.trim()||'local-learner',exam_type:$('exam').value,trust_tier:$('trust-tier').value,school_level:ntce?$('level').value:null,subject:ntce?$('subject').value||null:null}; }
function config() { return {base_url:state.base,model:state.model,api_key:state.key}; }
function persist() { prefs={user:context().user_id,tier:context().trust_tier,exam:context().exam_type,level:$('level').value,subject:$('subject').value,base:state.base,model:state.model};localStorage.setItem('knowledge-map-prefs',JSON.stringify(prefs)); }
function toast(message) { $('toast').textContent=message;$('toast').hidden=false;clearTimeout(state.toastTimer);state.toastTimer=setTimeout(()=>{$('toast').hidden=true;},4000); }
function notice(text, error=false) { return el('div',text,'notice'+(error?' error':'')); }
function notices(rows) { const unique=[...new Set((rows||[]).filter(Boolean))];const box=el('details',undefined,'raw-details');if(!unique.length)return el('span');box.append(el('summary',`依据与说明 · ${unique.length} 项`),notice(unique.join('\n')));return box; }
function rawDetails(data) { const d=el('details',undefined,'raw-details');d.append(el('summary','查看结构化结果与溯源'),el('pre',JSON.stringify(data,null,2)));return d; }
function busy(btn, work) { const old=btn.textContent;btn.disabled=true;btn.textContent='正在处理…';return Promise.resolve().then(work).catch(e=>toast(e.message)).finally(()=>{btn.disabled=false;btn.textContent=old;}); }
async function api(path, body, method) {
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),180000);
  try {
    const headers={'Content-Type':'application/json'};if(state.token)headers.Authorization=`Bearer ${state.token}`;
    const res=await fetch('/api/v1/'+path,{method:method||(body?'POST':'GET'),headers,body:body?JSON.stringify(body):undefined,signal:controller.signal});
    const data=await res.json();
    if(!res.ok){let detail=data.detail;if(Array.isArray(detail))detail=detail.map(d=>`${d.loc?.slice(-1)}: ${d.msg}`).join('；');throw new Error(res.status===401?'请先在模型与设置中填写本机运行时令牌。':String(detail||'请求未完成'));}return data;
  } catch(e) { if(e.name==='AbortError')throw new Error('请求超时，可检查模型接口或缩小检索范围后重试。');throw e; } finally {clearTimeout(timeout);}
}
function show(view) {state.view=view;for(const key of Object.keys(views))$('view-'+key).hidden=key!==view;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('view-name').textContent=views[view];if(view==='profile')loadProfile().catch(e=>toast(e.message));if(view==='audit'&&state.bootstrap)renderAudit();window.scrollTo({top:0,behavior:'instant'});}
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>show(b.dataset.view)));
$('settings-shortcut').addEventListener('click',()=>show('settings'));
function updateScope(initial=false) {
  const ntce=$('exam').value==='NTCE';$('level-label').hidden=!ntce;$('subject-label').hidden=!ntce;
  if(state.bootstrap&&ntce) {
    const old=initial?prefs.subject:$('subject').value;
    const rows=state.bootstrap.scopes.filter(s=>s.school_level===$('level').value);
    $('subject').replaceChildren(...rows.map(s=>{const o=el('option',subjects[s.subject]||s.label);o.value=s.subject;return o;}));
    if(rows.some(s=>s.subject===old))$('subject').value=old;else if(rows.some(s=>s.subject==='zonghe'))$('subject').value='zonghe';
    const current=rows.find(s=>s.subject===$('subject').value);
    $('scope-count').textContent=current?`${current.total.toLocaleString()} 题 · ${current.usable.toLocaleString()} 题可用于研究练习`:'当前范围没有题目';
    const nodes=state.bootstrap.nodes.filter(n=>n.id.startsWith(`ntce.${$('level').value}.${$('subject').value}.`));
    $('target-node').replaceChildren(el('option','按当前范围自动选择'),...nodes.map(n=>{const o=el('option',`${n.name} · ${n.count} 题`);o.value=n.id;return o;}));$('target-node').firstChild.value='';
  } else if(!ntce) { $('scope-count').textContent='四六级题库 · 写译 / 阅读 / 听力';const nodes=(state.bootstrap?.cet_nodes||[]).filter(n=>n.exams.includes(context().exam_type));$('target-node').replaceChildren(el('option','自动选择当前考试考点'),...nodes.map(n=>{const o=el('option',n.name);o.value=n.id;return o;}));$('target-node').firstChild.value=''; }
  if(!initial){persist();resetWorkspace();}
}
function resetWorkspace() {state.session=null;state.history=[];state.paper=null;clearInterval(state.timer);replace('paper-questions',notice('学习者或备考方向已切换，请为当前范围重新生成练习卷。'));replace('paper-status');replace('paper-notices');state.plan=null;replace('plan-list');replace('plan-summary');$('export-plan').disabled=true;replace('chat-log');replace('chat-sources');replace('interview-result');$('chat-welcome').hidden=false;$('source-placeholder').hidden=false;}
for(const name of ['exam','level'])$(name).addEventListener('change',()=>updateScope());
$('subject').addEventListener('change',()=>updateScope());

function message(role,text) {const e=el('article',undefined,'chat-message '+role);e.append(el('div',role==='user'?'你':'知序 · 学习助手','message-label'),el('div',text,'message-body'));$('chat-log').append(e);return e;}
function renderSources(rows) {
  $('source-placeholder').hidden=rows.length>0;replace('chat-sources',...rows.map(s=>{const d=el('details',undefined,'source-card');d.append(el('summary',(s.kind==='question'?'题目 · ':'条款 · ')+(s.title||s.id)),el('pre',[s.id,s.stem||s.text||'',s.review_status?`复核状态：${s.review_status}`:'',s.locator?JSON.stringify(s.locator,null,2):''].filter(Boolean).join('\n')));if(s.source_url&&/^https?:\/\//.test(s.source_url)){const a=el('a','查看官方来源 ↗');a.href=s.source_url;a.target='_blank';a.rel='noopener noreferrer';d.append(a);}return d;}));
}
async function chat(text,questionId,extras) {
  const btn=$('send-chat');if(btn.disabled)return;message('user',text);$('chat-welcome').hidden=true;$('chat-input').value='';
  $('chat-status').textContent='正在读取题库、查找依据'+(state.key?'并请求模型…':'…');
  await busy(btn,async()=>{
    const data=await api('web/chat',{...context(),message:text,question_id:questionId||null,session_id:state.session,
      history:state.history.slice(-6),model_config_input:config(),action_payload:extras||null});
    state.session=data.session_id;const card=message('assistant',data.reply);
    card.append(el('div',data.model.ok?`模型已参与 · ${data.model.provenance?.response_model||state.model}`:'规则答复 · 模型未参与','message-meta'));
    if(!data.model.ok&&state.key)card.append(notice((data.model.errors||[]).join('\n')||'本次模型答复未通过校验',true));
    card.append(notices(data.notices));
    if(data.tool_result?.questions){renderPaper(data.tool_result);card.append(button('打开练习卷 →',()=>show('practice')));}
    if(data.tool_result?.daily_plans){renderPlan(data.tool_result);card.append(button('查看学习计划 →',()=>show('plan')));}
    if(data.tool_result?.radar_chart)card.append(button('查看学情 →',()=>show('profile')));
    if(data.trace?.length)card.append(rawDetails({agent_trace:data.trace}));
    renderSources(data.sources||[]);state.history.push({role:'user',content:text},{role:'assistant',content:data.reply});
    card.scrollIntoView({behavior:'smooth',block:'nearest'});
  });$('chat-status').textContent='本地知识检索 · 回答附来源';
}
$('chat-form').addEventListener('submit',e=>{e.preventDefault();const text=$('chat-input').value.trim();if(text)chat(text);});
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat-form').requestSubmit();}});
document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>chat(b.dataset.prompt)));

async function assemble(overrides={}) {
  let profile={};const mode=overrides.practice_mode||$('practice-mode').value;
  if(['weakness_breakthrough','error_elimination'].includes(mode))profile=await api('web/profile',context());
  const body={...context(),practice_mode:mode,item_count:Number($('item-count').value),target_node:$('target-node').value||null,
    weak_node_ids:profile.diagnostic?.weak_points_top5||[],wrong_question_ids:profile.due_question_ids||[],...overrides};
  if(mode==='point_focus'&&!body.target_node)throw new Error('请先选择一个具体考点。');
  renderPaper(await api('web/practice',body));
}
$('practice-form').addEventListener('submit',e=>{e.preventDefault();busy($('assemble'),()=>assemble());});
function renderPaper(paper,submissions=[]) {
  state.paper=paper;state.submissions=new Map(submissions.map(s=>[s.question_id,s]));clearInterval(state.timer);
  // 待完成提交的参数只对本卷有意义（页面只能恢复最新一卷），换卷时把旧卷的参数带走，别让它们一直堆在 localStorage 里
  for(let i=localStorage.length-1;i>=0;i--){const key=localStorage.key(i);if(key&&key.startsWith('pending-submit:')&&!key.startsWith(`pending-submit:${paper.paper_id}:`))localStorage.removeItem(key);}
  const bar=el('div',undefined,'paper-bar');bar.append(el('strong',paper.title),el('span',`${paper.total_items} 题 · 题池 ${paper.pool_size} 题`));const timer=el('span','', 'timer');bar.append(timer);replace('paper-status',bar);replace('paper-notices',notices(paper.notices));
  if(!paper.total_items){replace('paper-questions',notice('当前条件下没有可练题目。错题复习需已有到期记录；发布档需人工核定；可调整考点或练习模式。'));return;}
  const cards=paper.questions.map((q,i)=>renderQuestion(q,i));replace('paper-questions',...cards);
  if(paper.time_limit_minutes){const start=Date.parse(paper.created_at||new Date().toISOString());const update=()=>{const seconds=Math.max(0,Math.ceil(paper.time_limit_minutes*60-(Date.now()-start)/1000));timer.textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;if(!seconds){clearInterval(state.timer);timer.textContent='练习时间已到';for(const card of cards)card.querySelectorAll('button[type="submit"],input,textarea').forEach(e=>e.disabled=true);}};update();state.timer=setInterval(update,1000);}else timer.textContent='无库内时长';
}
function renderQuestion(q,i) {
  const card=el('article',undefined,'question-card');card.id='question-'+i;const head=el('div',undefined,'question-head');const title=el('div');title.append(el('span',String(i+1).padStart(2,'0'),'question-number'),el('span',q.question_type||q.section));head.append(title,el('span',`内容状态：${q.review_status} · ${q.difficulty?.label||'无难度值'}`));card.append(head);
  if(q.material_text)card.append(el('div',q.material_text,'material'));
  card.append(el('div',q.stem,'stem'));
  if(q.audio_url){const a=el('audio');a.controls=true;a.preload='none';if(!state.token)a.src=q.audio_url;else card.append(button('加载听力音频',async()=>{try{const res=await fetch(q.audio_url,{headers:{Authorization:`Bearer ${state.token}`}});if(!res.ok)throw new Error('音频加载失败');a.src=URL.createObjectURL(await res.blob());}catch(e){toast(e.message);}}));card.append(a);}
  if(q.audio_notice)card.append(notice(q.audio_notice));
  if(q.media_notice)card.append(notice(q.media_notice,true));
  const form=el('form');const optionList=(q.options||[]);let area;
  if(optionList.length){for(const [index,option] of optionList.entries()){const label=el('label',undefined,'option');const radio=el('input');radio.type=q.question_type==='多选'?'checkbox':'radio';radio.name=q.question_id;radio.value=typeof option==='object'?option.key||String.fromCharCode(65+index):String.fromCharCode(65+index);label.append(radio,el('span',`${radio.value}  ${typeof option==='object'?option.text||'':option}`));form.append(label);}}
  else {const label=el('label','写下你的作答');area=el('textarea');area.rows=5;area.maxLength=12000;area.required=true;label.append(area);form.append(label);}
  const actions=el('div',undefined,'form-actions');const submit=el('button','提交并查看反馈 →','primary');submit.type='submit';actions.append(submit,button('给我一点提示',async()=>{
    try {const data=await api('qa/query',{user_id:context().user_id,question_id:q.question_id,mode:'socratic_hint',hint_turn:1,trust_tier:context().trust_tier});hint.replaceChildren(notice(data.guiding_question+'\n'+data.scaffold_prompt));}catch(e){toast(e.message);}
  },'text-button'));form.append(actions);const hint=el('div');const result=el('div');card.append(form,hint,result);
  let started=Date.now(), flips=0, payload=null;form.addEventListener('change',()=>flips++);
  const pendingKey='pending-submit:'+state.paper.paper_id+':'+q.question_id;
  const readPending=()=>{try{return JSON.parse(localStorage.getItem(pendingKey)||'null');}catch(e){return null;}};
  const savePending=body=>{try{localStorage.setItem(pendingKey,JSON.stringify(body));}catch(e){}};
  const clearPending=()=>{try{localStorage.removeItem(pendingKey);}catch(e){}};
  const echo=v=>{if(area)area.value=v||'';else for(const input of form.querySelectorAll('input'))input.checked=String(v||'').includes(input.value);};
  const lock=label=>{form.querySelectorAll('input,textarea,button[type="submit"]').forEach(e=>e.disabled=true);submit.textContent=label;};
  const apply=data=>{state.submissions.set(q.question_id,data);clearPending();echo(data.user_answer);lock('已提交');renderAnswer(result,data,q);};
  const RETRY_NOTE='上次提交已经计入掌握度和错题记录，但结果没能保存到本机。重试只补写结果：不重新计时、也不能改答案——参数一改就成了另一次作答，后端会拒绝（409）。';
  const pending=readPending();
  if(pending&&!state.submissions.has(q.question_id)){payload=pending;echo(payload.answer);form.querySelectorAll('input,textarea').forEach(e=>e.disabled=true);submit.textContent='重试提交（沿用上次作答参数）';card.append(notice(RETRY_NOTE,true));}
  form.addEventListener('submit',async e=>{
    e.preventDefault();
    if(!payload){
      const answer=area?area.value.trim():[...form.querySelectorAll('input:checked')].map(e=>e.value).join('');
      if(!answer){toast('请先选择或填写答案。');return;}
      // 首次提交就把参数定死：请求一发出，这一题的次数与错题记录就已经落库，重试只是把结果补回本机。
      payload={user_id:context().user_id,trust_tier:context().trust_tier,paper_id:state.paper.paper_id,question_id:q.question_id,answer,time_spent_seconds:(Date.now()-started)/1000,option_flip_count:Math.max(0,flips-1)};
      savePending(payload);
    }
    form.querySelectorAll('input,textarea').forEach(e=>e.disabled=true);
    submit.disabled=true;submit.textContent='正在处理…';
    try{apply(await api('web/submit',payload));}
    catch(err){toast(err.message);submit.disabled=false;submit.textContent='重试提交（沿用上次作答参数）';}
  });
  if(state.submissions.has(q.question_id))apply(state.submissions.get(q.question_id));
  if(q.input_blocked){form.querySelectorAll('input,textarea,button[type="submit"]').forEach(e=>e.disabled=true);submit.textContent='缺原图 · 暂不可提交';}
  return card;
}
function renderAnswer(target,data,q) {
  const box=el('div',undefined,'answer-result'+(data.is_correct===false?' wrong':''));box.append(el('h3',data.is_correct===true?'答对了 · 已更新学习记录':data.is_correct===false?'这次没答对 · 已安排复习':'主观题反馈 · 当前不作对错判断'));
  if(data.review?.attribution)box.append(el('p',`${data.review.attribution.category_name}\n${data.review.attribution.rationale}\n${data.review.attribution.recommended_action}`));
  if(data.review?.next_review_interval_days)box.append(el('p',`下次复习间隔约 ${data.review.next_review_interval_days.toFixed(1)} 天 · 依据本机复习调度`));
  if(data.grading){box.append(el('p',data.grading.evaluation_summary),el('p',data.grading.revision_advice));if(data.grading.total_score!==null)box.append(el('p',`练习分数 ${data.grading.total_score} / ${data.grading.max_score}`));box.append(notices(data.grading.notices));}
  const exp=data.explanation;if(exp){box.append(el('p',exp.explanation_summary||''));if(exp.key_clue_localization)box.append(el('p','题眼定位：'+exp.key_clue_localization));const d=el('details',undefined,'raw-details');d.append(el('summary','选项对比与考点溯源'),el('pre',JSON.stringify({option_discrimination:exp.option_discrimination,knowledge_provenance:exp.knowledge_provenance},null,2)));box.append(d);}
  box.append(button('向助手追问',()=>{show('chat');chat('讲讲这道题的考点，以及如何避免再错。',q.question_id);}),button('反馈内容问题',async()=>{const detail=window.prompt('请描述题面、答案、解析或来源中的具体问题（至少 5 个字）：');if(!detail)return;try{await api('web/feedback',{user_id:context().user_id,question_id:q.question_id,detail});toast('内容问题已进入教研待复核队列。');}catch(e){toast(e.message);}},'text-button'),rawDetails(data));target.replaceChildren(box);
}

$('plan-form').addEventListener('submit',e=>{e.preventDefault();busy(e.submitter,async()=>renderPlan(await api('planner/generate',{...context(),days_until_exam:Number($('plan-days').value),daily_available_minutes:Number($('plan-minutes').value)})));});
function renderPlan(plan) {
  state.plan=plan;$('export-plan').disabled=false;replace('plan-summary',notice((plan.milestones||[]).join('\n')),notices(plan.notices));
  replace('plan-list',...plan.daily_plans.map(day=>{const card=el('article',undefined,'day-card');const title=el('div',`DAY ${String(day.day_index).padStart(2,'0')}`,'day-number');title.append(el('small',`${day.date_str} · ${day.total_minutes} 分钟`));card.append(title);for(const task of day.tasks){const row=el('div',task.title,'day-task');row.append(el('small',`${task.estimated_minutes} 分钟 / ${task.target_question_count} 题`));row.append(button('开始任务 →',async()=>{show('practice');try{await assemble({practice_mode:task.task_type==='fsrs_review'?'error_elimination':task.task_type==='mock_sprint'?'mock_exam':'point_focus',target_node:task.node_id||null,item_count:Math.max(1,task.target_question_count)});}catch(e){toast(e.message);}}));card.append(row);}return card;}));
}
function download(name,data) {const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));const a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export-plan').addEventListener('click',()=>download('知序学习计划.json',state.plan));
function bar(title,rate,extra) {const row=el('div',undefined,'bar-row');const t=el('div',undefined,'bar-title');t.append(el('span',title),el('span',extra||`${Math.round(rate*100)}%`));const track=el('div',undefined,'bar-track');const fill=el('div',undefined,'bar-fill');fill.style.width=`${Math.min(100,Math.max(0,rate*100))}%`;track.append(fill);row.append(t,track);return row;}
async function loadProfile() {
  const data=await api('web/profile',context());const report=data.diagnostic;
  replace('profile-summary',notice(`已提交 ${data.submissions.length} 次作答 · ${data.mastery.length} 个考点有学习记录 · ${data.due_question_ids.length} 道题到期复习\n${report.disclaimer}`));
  replace('radar',...(report.radar_chart.length?report.radar_chart.map(m=>bar(m.module_name,m.mastery_rate,`${m.correct_count} / ${m.question_count}`)):[el('p','完成练习后，这里会显示各模块表现。','muted')]));
  replace('mastery-list',...(data.mastery.length?data.mastery.slice().sort((a,b)=>a.mastery_score-b.mastery_score).slice(0,20).map(m=>{const name=state.bootstrap?.nodes.find(n=>n.id===m.node_id)?.name||m.node_id;const row=bar(name,m.mastery_score,`${Math.round(m.mastery_score*100)}% · ${m.practice_count} 次`);row.append(el('small','到期：'+new Date(m.fsrs_state.due_date).toLocaleDateString('zh-CN'),'muted'));return row;}):[el('p','还没有掌握度记录。先完成几道题，系统会逐次记录。','muted')]));
  const wrong=data.wrong_questions.filter(e=>e.incorrect_count>0);
  replace('wrong-list',...(wrong.length?wrong.slice(0,25).map(e=>{const row=el('div',undefined,'day-task');row.append(el('div',`${e.question_id} · 累计错 ${e.incorrect_count} 次`),el('small',`复习日期：${e.due_at?new Date(e.due_at).toLocaleString('zh-CN'):'待安排'}`),button('重做这道题',async()=>{show('practice');try{await assemble({practice_mode:'error_elimination',wrong_question_ids:[e.question_id],item_count:1});}catch(error){toast(error.message);}}));return row;}):[el('p','当前范围还没有错题。','muted')]));
  if(data.due_question_ids.length)$('wrong-list').prepend(button('复习到期题 →',()=>{show('practice');busy($('assemble'),()=>assemble({practice_mode:'error_elimination',wrong_question_ids:data.due_question_ids}));}));
}
$('refresh-profile').addEventListener('click',e=>busy(e.target,loadProfile));

$('interview-form').addEventListener('submit',e=>{e.preventDefault();busy(e.submitter,async()=>{
  const mode=$('interview-mode').value;let data;const text=$('interview-text').value.trim(),topic=$('interview-topic').value;
  if(mode==='structured'){data=await api('web/chat',{...context(),exam_type:'NTCE',message:`请对我的结构化面试作答提供练习反馈，主题：${topic}，作答：${text}`,model_config_input:config()});replace('interview-result',notice(data.reply),notices(data.model.errors),rawDetails(data));return;}
  data=await api('interview/'+mode,{trust_tier:context().trust_tier,...(mode==='speech'?{transcript_text:text,audio_duration_seconds:Number($('speech-duration').value),lesson_title:topic}:{topic,plan_text:text,subject:subjects[context().subject]||'教育教学知识与能力',grade_level:levels[context().school_level]||'小学'})});
  const result=el('div',undefined,'surface result-section');result.append(el('h2','训练反馈'),el('p',data.coaching_feedback||data.improvement_suggestions));
  if(mode==='speech'){result.append(notice(`转写语速约 ${data.words_per_minute.toFixed(0)} 字 / 分钟 · 教学环节覆盖 ${Math.round(data.phase_coverage_rate*100)}%`));for(const phase of data.teaching_phases)result.append(el('p',`${phase.covered?'✓':'○'} ${phase.phase_name}：${phase.evidence_snippet||'转写中未发现明确证据'}`));}else for(const d of data.dimensions||[]){const box=el('div',undefined,'dimension-feedback');box.append(el('h3',d.dimension_name||d.name||'反馈维度'),el('p',d.feedback||d.rationale||d.status||'待人工核对'));if(d.evidence_snippet)box.append(el('blockquote','文本线索：'+d.evidence_snippet));if(d.descriptor){const ref=el('details');ref.append(el('summary','查看量规描述参照 · 待签署'),el('p',d.descriptor),el('small','匹配文字仅用于练习反馈，不表示获得该档位或分数。'));box.append(ref);}result.append(box);}result.append(notices(data.notices),rawDetails(data));replace('interview-result',result);
});});
const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
if(!SpeechRecognition){$('voice-input').disabled=true;$('voice-status').textContent='当前浏览器未提供语音识别，可粘贴转写文本。';}
else {$('voice-input').addEventListener('click',()=>{const r=new SpeechRecognition();r.lang='zh-CN';r.continuous=false;r.interimResults=false;$('voice-status').textContent='正在聆听，请说话…';r.onresult=e=>{$('interview-text').value+='\n'+e.results[0][0].transcript;$('voice-status').textContent='已添加转写文本，可继续录入。';};r.onerror=()=>{$('voice-status').textContent='语音识别未成功，请检查浏览器麦克风权限或手动输入。';};r.onend=()=>{if($('voice-status').textContent.startsWith('正在'))$('voice-status').textContent='录音已结束。';};r.start();});}

function renderAudit() {const a=state.bootstrap.library;const metrics=[['教资题目',a.total],['研究档可练',a.usable],['缺知识点挂载',a.missing_knowledge],['缺考纲绑定',a.missing_requirement],['答案缺失',a.missing_answer],['答案来源冲突',a.answer_conflict],['具名审核题目',a.signed_questions],['未签署量规',a.unsigned_rubrics]];
  replace('audit-stats',...metrics.map(([label,n])=>{const box=el('div',undefined,'metric');box.append(el('span',label),el('b',n.toLocaleString()));return box;}));replace('audit-notices',notice(a.notices.join('\n')));
  replace('layer-chart',...Object.entries(a.graph_layers).map(([layer,n])=>{const box=el('div',undefined,'layer-box');box.append(el('small',layer),el('b',n.toLocaleString()),el('small','节点'));return box;}));
  replace('audit-table',...a.scopes.map(s=>{const row=el('tr');row.append(el('td',`${levels[s.school_level]||s.school_level} / ${subjects[s.subject]||s.subject}`));for(const k of ['total','usable','missing_knowledge','missing_requirement','missing_answer','answer_conflict'])row.append(el('td',s[k].toLocaleString()));return row;}));
}
$('export-audit').addEventListener('click',()=>download('教资知识库完整性核对.json',state.bootstrap.library));
let activeIdentity=JSON.stringify([context().user_id,context().trust_tier]);
function applySettings() {const identity=JSON.stringify([context().user_id,context().trust_tier]);if(identity!==activeIdentity){resetWorkspace();activeIdentity=identity;}state.key=$('api-key').value.trim();state.token=$('runtime-token').value.trim();state.base=$('base-url').value.trim();state.model=$('model-name').value.trim();persist();$('model-indicator').classList.toggle('configured',!!state.key);$('model-indicator').lastChild.textContent=state.key?'模型配置已就绪':'规则模式';$('settings-shortcut').textContent=state.key?'模型配置 ↗':'连接 DeepSeek ↗';$('tier-badge').textContent=context().trust_tier==='published'?'签署内容':'研究练习';}
$('settings-form').addEventListener('submit',e=>{e.preventDefault();applySettings();toast('配置已应用。Key 仅保存在当前页面内存。');init().catch(()=>{});});
$('test-model').addEventListener('click',e=>{applySettings();busy(e.target,async()=>{const data=await api('web/model/test',config());replace('model-test-result',notice(data.ok?`连接成功 · ${data.provenance.response_model||state.model}\n${data.message}`:(data.errors||[]).join('\n'),!data.ok));});});
$('clear-key').addEventListener('click',()=>{$('api-key').value='';state.key='';applySettings();replace('model-test-result',notice('Key 已清空。现在使用规则模式。'));});
async function init() {
  try {state.bootstrap=await api('web/bootstrap');$('fatal').hidden=true;updateScope(true);$('stat-questions').textContent=state.bootstrap.library.total.toLocaleString();$('stat-nodes').textContent=state.bootstrap.library.knowledge_nodes.toLocaleString();renderAudit();
    if(!state.paper){const profile=await api('web/profile',context());const paper=profile.latest_paper;if(paper&&paper.exam_type===context().exam_type&&paper.trust_tier===context().trust_tier&&(!context().school_level||paper.school_level===context().school_level)&&(!context().subject||paper.subject===context().subject))renderPaper(paper,profile.latest_paper_submissions);}
  } catch(e) {$('fatal').textContent=e.message;$('fatal').hidden=false;$('scope-count').textContent='知识库未连接';throw e;}
}
init().catch(()=>{});
