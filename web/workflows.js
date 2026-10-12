'use strict';

const scopeIdentity=()=>JSON.stringify(context());
const scopedKey=name=>'learning:'+name+':'+scopeIdentity();
let knowledgeRows=[];

async function trackedCall(path,body) {
  const key='pending-action:'+path+':'+scopeIdentity();
  let pending;
  try{pending=JSON.parse(localStorage.getItem(key)||'null');}catch{}
  const signature=JSON.stringify(body);
  if(!pending||pending.signature!==signature)pending={signature,request_id:crypto.randomUUID()};
  try{localStorage.setItem(key,JSON.stringify(pending));}catch{}
  const data=await api(path,{...body,request_id:pending.request_id});
  try{localStorage.removeItem(key);}catch{}
  return data;
}

async function loadSavedPlan() {
  const scope=scopeIdentity(),data=await api('web/learning/plan/current',context());
  if(scope!==scopeIdentity())return;
  if(data.plan)renderPlan(data.plan);
  else if(!state.plan)replace('plan-summary',notice('当前范围还没有保存的计划。填写可用时间，制定第一份计划。'));
}
async function runPlanTask(plan,task) {
  try{
    const data=await api('web/learning/task/start',{...context(),plan_id:plan.plan_id,task_id:task.task_id});
    renderPlan(data.plan);
    const saved=await api('web/paper/'+encodeURIComponent(data.paper.paper_id)+'?user_id='+encodeURIComponent(context().user_id));
    show('practice');renderPaper(saved.paper,saved.submissions);
    $('exam-controls').append(button('完成后更新学习计划',()=>completePlanTask(data.plan,data.task)),notice('完成这份任务卷的实际作答后，再核对完成。已完成记录会保留，后续任务依据新学情重排。'));
  }catch(e){toast(e.message);}
}
async function completePlanTask(plan,task) {
  try{
    const data=await api('web/learning/task/complete',{...context(),plan_id:plan.plan_id,task_id:task.task_id});
    renderPlan(data.plan);show('plan');toast('任务已完成，后续任务已按最新学情更新。');
  }catch(e){toast(e.message);}
}
$('replan').addEventListener('click',e=>busy(e.target,async()=>{
  if(!state.plan?.plan_id)return;
  const data=await trackedCall('web/learning/plan/replan',{...context(),plan_id:state.plan.plan_id});renderPlan(data.plan);
}));

$('diagnostic-form').addEventListener('submit',e=>{e.preventDefault();busy(e.submitter,async()=>{
  const data=await trackedCall('web/learning/diagnostic/start',{...context(),item_count:Number($('diagnostic-count').value)});
  localStorage.setItem(scopedKey('diagnostic'),JSON.stringify({diagnostic_id:data.diagnostic_id,paper_id:data.paper.paper_id}));
  show('practice');renderPaper(data.paper);$('exam-controls').append(button('查看本次摸底结果',viewDiagnostic));
  $('paper-notices').append(notice('这是当前范围的抽样摸底。完成后将分别展示已覆盖与未覆盖考点，不推测未测水平。'));
});});
async function viewDiagnostic() {
  let saved;try{saved=JSON.parse(localStorage.getItem(scopedKey('diagnostic'))||'null');}catch{}
  if(!saved){toast('当前范围还没有摸底记录，请先开始摸底。');return;}
  try{
    const data=await api('web/learning/diagnostic/result',{...context(),diagnostic_id:saved.diagnostic_id});
    show('profile');const c=data.coverage;
    const box=el('div',undefined,'surface');box.append(el('h2',data.status==='completed'?'本次摸底已完成':'本次摸底进度'),
      notice(`已提交 ${data.submitted_count} / ${data.total_items} 题 · 已测 ${c.covered_node_count} / ${c.scope_node_count} 个考点`),
      notice(`尚未覆盖 ${(c.uncovered_node_ids||[]).length} 个考点；其中 ${(c.unavailable_node_ids||[]).length} 个没有符合条件的客观题。`),
      notices(data.notices),el('p',data.diagnostic?.disclaimer||''));
    for(const row of data.diagnostic?.radar_chart||[])box.append(bar(row.module_name,row.mastery_rate,`${row.correct_count} / ${row.question_count}`));
    if(data.submitted_count<data.total_items)box.append(button('继续摸底 →',e=>busy(e.currentTarget,async()=>{const p=await api('web/paper/'+encodeURIComponent(saved.paper_id)+'?user_id='+encodeURIComponent(context().user_id));show('practice');renderPaper(p.paper,p.submissions);$('exam-controls').append(button('查看本次摸底结果',viewDiagnostic));})));
    box.append(button('据此安排学习计划 →',()=>show('plan')));replace('diagnostic-summary',box);
  }catch(e){toast(e.message);}
}
$('diagnostic-result').addEventListener('click',viewDiagnostic);

async function loadKnowledge() {
  const scope=scopeIdentity();replace('knowledge-tree',el('p','正在读取考点…','muted'));
  const data=await api('web/knowledge/tree',context());if(scope!==scopeIdentity())return;
  knowledgeRows=data.nodes;renderKnowledgeTree();
}
function renderKnowledgeTree() {
  const term=$('node-search').value.trim().toLowerCase(),byId=new Map(knowledgeRows.map(n=>[n.id,n]));
  const depth=node=>{let level=0,p=node.parent_id;const seen=new Set();while(p&&byId.has(p)&&!seen.has(p)){seen.add(p);level++;p=byId.get(p).parent_id;}return level;};
  const rows=knowledgeRows.filter(n=>!term||(n.name+' '+n.description+' '+n.id).toLowerCase().includes(term));
  replace('knowledge-tree',...(rows.length?rows.map(n=>{const b=button('',()=>loadNode(n.id).catch(e=>toast(e.message)),'node-row');b.style.setProperty('--depth',depth(n));b.append(el('span',n.name),el('small',`${n.mastery?Math.round(n.mastery.mastery_score*100)+'%':'未练习'} · ${n.question_count} 题${n.guide_available?' · 有学习指南':''}`));return b;}):[notice('当前范围没有匹配考点。')]));
}
$('node-search').addEventListener('input',renderKnowledgeTree);
async function loadNode(nodeId) {
  const scope=scopeIdentity(),data=await api('web/knowledge/node',{...context(),node_id:nodeId});if(scope!==scopeIdentity())return;
  const box=el('div');box.append(el('div','KNOWLEDGE NOTE','eyebrow'),el('h2',data.node.name||nodeId),el('p',data.node.description||''));
  const actions=el('div',undefined,'form-actions');actions.append(button('进入考点专练 →',()=>{show('practice');assemble({practice_mode:'point_focus',target_node:nodeId,rotation:0,avoid_question_ids:[]}).catch(e=>toast(e.message));}),button('请助手讲解',()=>{show('chat');chat(`请解释${data.node.name}，结合学科情境说明作答思路。`,null,{node_id:nodeId,intent:'general_chat'});},'text-button'));box.append(actions);
  const guide=data.guide;
  if(guide){box.append(notice(guide.notice||'原创研究草稿 · 待教研核定'));
    box.append(el('h3','理解这个考点'));for(const p of guide.concept_explanation||[])box.append(el('p',p,'study-prose'));
    box.append(el('h3','放进教学情境'),el('p',guide.subject_context,'study-prose'),el('h3','组织作答'));const steps=el('ol');for(const p of guide.answer_structure||[])steps.append(el('li',p));box.append(steps);
    box.append(el('h3','先尝试，再对照参考要点'));
    for(const [i,q] of (guide.self_checks||[]).entries()){const item=el('div',undefined,'study-check');item.append(el('h3',`自测 ${i+1}`),el('p',q.prompt,'study-prose'));const label=el('label','我的思路（本页草稿）'),answer=el('textarea');answer.rows=3;label.append(answer);item.append(label);const details=el('details');details.append(el('summary','展开参考要点 · 研究草稿'));const list=el('ul');for(const p of q.reference_points||[])list.append(el('li',p));details.append(list,el('p',q.explanation,'study-prose'));item.append(details);box.append(item);}
    if(guide.source_audit?.notes)box.append(notice(Array.isArray(guide.source_audit.notes)?guide.source_audit.notes.join('\n'):guide.source_audit.notes));
  }else box.append(notice('该考点暂未编写专属学习指南。可先阅读下面的真实考纲与例题，再向助手提问。'));
  box.append(el('h3','考纲依据'));
  for(const source of data.sources){const d=el('details',undefined,'source-card');d.append(el('summary',source.title||source.id),el('p',source.text,'study-prose'),el('small',source.id),el('pre',JSON.stringify(source.locator,null,2)));box.append(d);}
  if(!data.sources.length)box.append(notice('当前没有具体考纲条款绑定，等待补齐来源。'));
  if(data.examples.length){box.append(el('h3','相关题目'));for(const q of data.examples){const d=el('details');d.append(el('summary',q.stem.slice(0,100)||q.question_id),el('p',q.stem,'study-prose'),button('请助手讲解此题',()=>{show('chat');chat('请结合这道题讲解考点与作答依据。',q.question_id);},'text-button'));box.append(d);}}
  if(data.related.length){const d=el('details');d.append(el('summary','相关概念与先修线索'));for(const link of data.related)d.append(el('p',`${link.id} · ${link.relation} · ${link.active_for_learning_path?'已启用':'待核定，未用于前置阻断'}`));box.append(d);}
  box.append(notices(data.notices));replace('knowledge-detail',box);
}

async function startExam() {
  const data=await trackedCall('web/exam/start',context());renderExam(data.session||data);
}
async function restoreExam() {
  // 进"练习与模考"时会顺手接回服务端计时的模考；这期间学习者若已经组出新卷（错题重做、继续摸底、换一批），
  // 让新卷留在屏上，别用一场旧模考盖掉他刚点出来的题。
  const scope=scopeIdentity(),paperAtStart=state.paper;
  const data=await api('web/exam/latest',context());
  if(scope!==scopeIdentity()||(state.paper&&state.paper!==paperAtStart))return;
  if(data.session?.status==='active')renderExam(data.session);
}
async function refreshExam() {
  if(!state.exam)return;
  const id=state.exam.session_id,scope=scopeIdentity();
  const data=await api('web/exam/'+encodeURIComponent(id)+'/state',context());
  if(scope===scopeIdentity()&&state.exam?.session_id===id)renderExam(data.session||data);
}
function renderExam(session) {
  state.exam=session;
  const allowed=new Set(session.allowed_question_ids||[]),active=session.status==='active';
  const paper={...session.paper,questions:session.paper.questions.filter(q=>!active||allowed.has(q.question_id))};
  paper.total_items=paper.questions.length;
  renderPaper(paper,session.submissions||[]);clearInterval(state.timer);state.exam=session;
  const controls=el('div',undefined,'surface');controls.append(el('h2',active?'模考进行中':'模考已结束'),
    notice(active?`当前阶段：${session.current_stage?.name||session.current_stage?.stage||'整卷'} · 全卷 ${session.paper.total_items} 题。当前仅开放本阶段作答。`:'已收卷。下方展示本次提交的讲评，未作答题保持未作答。'),notices(session.notices));
  const clock=el('span','', 'timer');controls.append(clock,button('刷新阶段',()=>refreshExam().catch(e=>toast(e.message))));
  if(active)controls.append(button('提前交卷并查看结果',async()=>{if(!window.confirm('提前交卷后将结束本次模考，不能继续作答。确定交卷？'))return;try{const data=await api('web/exam/'+encodeURIComponent(session.session_id)+'/finish',context());renderExam(data.session||data);}catch(e){toast(e.message);}},'text-button'));
  replace('exam-controls',controls);
  if(active){const server=Date.parse(session.server_now),arrival=Date.now(),end=Date.parse(session.current_stage?.ends_at||session.ends_at);let refreshing=false;
    const tick=()=>{const remaining=Math.max(0,Math.ceil((end-server-(Date.now()-arrival))/1000));clock.textContent=`剩余 ${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`;if(!remaining&&!refreshing){refreshing=true;document.querySelectorAll('#paper-questions input,#paper-questions textarea,#paper-questions button[type="submit"]').forEach(e=>e.disabled=true);refreshExam().catch(e=>{toast(e.message);refreshing=false;});}};tick();state.timer=setInterval(tick,1000);
  }else{document.querySelectorAll('#paper-questions input,#paper-questions textarea,#paper-questions button[type="submit"]').forEach(e=>e.disabled=true);if(session.results)controls.append(rawDetails(session.results));}
}

// The existing selector keeps ordinary practice modes; the final mode now enters a server-timed session.
// 教资整卷只有一个阶段，逐节收卡只在四六级规格里存在，所以标签跟着考试类型走，不能一律写"分阶段"。
function syncExamModeLabel() {
  const cet=$('exam').value.startsWith('CET');
  $('practice-mode').querySelector('option[value="mock_exam"]').textContent=cet?'分阶段模考 · 服务端计时':'整卷计时模考 · 服务端计时';
}
syncExamModeLabel();
$('exam').addEventListener('change',syncExamModeLabel);

// 面试训练会话：阶段、题面与追问依据都由后端从库内资产生成，页面只展示与提交。
// 与练习提交同一口径：首次提交即冻结参数并落本地，重试沿用原参数——改答案就是另一次作答，后端会拒（409）。
let interviewSession=null;
const INTERVIEW_STATE_LABEL={pending:'待作答',awaiting_follow_up:'待回答追问',done:'已完成'};
const interviewPendingKey=(task,slot)=>'pending-interview-answer:'+interviewSession.session_id+':'+task.task_id+':'+slot;

function interviewDimension(d) {
  const box=el('div',undefined,'dimension-feedback');
  box.append(el('h3',d.dimension_name||d.name||'反馈维度'),el('p',d.feedback_comment||d.feedback||d.rationale||d.status||'待人工核对','study-prose'));
  if(d.evidence_quote)box.append(el('blockquote','你的原文：'+d.evidence_quote));
  if(d.descriptor){const ref=el('details');ref.append(el('summary','查看量规档位描述 · 待签署'),el('p',d.descriptor),el('small','匹配文字仅用于练习反馈，不表示获得该档位或分数。'));box.append(ref);}
  return box;
}
function interviewFeedbackBox(feedback,title) {
  if(!feedback)return el('span');
  const box=el('div',undefined,'dimension-feedback');
  box.append(el('h3',title||'作答与库内依据的比对'));
  if(feedback.points){const mark={hit:'✓ 命中',partial:'△ 部分命中',missed:'○ 未比对到'};
    for(const p of feedback.points)box.append(el('p',`${mark[p.status]||p.status} ${p.point_text} · ${p.evidence}`,'task-state'));
    box.append(el('p',`要点重合率约 ${Math.round((feedback.coverage_ratio||0)*100)}% · 要点来源：${feedback.points_from||'库内参考框架'}`,'muted'));}
  if(feedback.measured){const m=feedback.measured;
    box.append(el('p',`转写语速约 ${(m.words_per_minute||0).toFixed(0)} 字 / 分钟（${m.speed_evaluation||'—'}）· 迟疑停顿 ${m.hesitation_pause_count||0} 处 · 环节覆盖 ${Math.round((m.phase_coverage_rate||0)*100)}%`,'muted'));
    for(const phase of m.teaching_phases||[])box.append(el('p',`${phase.covered?'✓':'○'} ${phase.phase_name}：${phase.evidence_snippet||'转写中未发现明确证据'}`,'task-state'));
    if(feedback.coaching_feedback)box.append(el('p',feedback.coaching_feedback,'study-prose'));}
  for(const d of feedback.dimensions||[])box.append(interviewDimension(d));
  if((feedback.missed_elements||[]).length)box.append(el('p','简案缺项：'+feedback.missed_elements.join('、'),'task-state'));
  for(const s of feedback.improvement_suggestions||[])box.append(el('p','改进建议：'+s,'task-state'));
  box.append(el('p',feedback.total_score===null
    ?(feedback.score_basis==='measured_from_transcript'?'本次不出分数：只报转写文本的实测值。':'本次不出分数：量规未签署，也不给通过概率。')
    :`得分 ${feedback.total_score}${feedback.max_score?` / ${feedback.max_score}`:''} · 依据 ${feedback.score_basis}`,'task-state'));
  box.append(notices(feedback.notices),rawDetails(feedback));
  return box;
}
function interviewEvidence(task) {
  const e=task.evidence||{},rows=[];
  if(e.resource_id)rows.push('库内情境资源 '+e.resource_id);
  if(e.source)rows.push('出处 '+e.source);
  if((e.requirement_ids||[]).length)rows.push('考纲条款 '+e.requirement_ids.join('、'));
  if((e.node_ids||[]).length)rows.push('考点 '+e.node_ids.join('、'));
  if((e.ability_ids||[]).length)rows.push('能力 '+e.ability_ids.join('、'));
  if(e.review_status)rows.push('所选真题的审核状态 '+e.review_status);
  if(e.use_scope)rows.push('用途口径 '+e.use_scope);
  if(!rows.length)return el('span');
  const d=el('details');d.append(el('summary','题面出处与绑定'),...rows.map(r=>el('p',r,'task-state')));return d;
}
function interviewAnswerNote(task,key) {
  if(!task[key])return el('span');
  const box=el('div');box.append(el('h3',key==='follow_up_answer'?'你对追问的回答':'你的作答'),el('p',task[key],'study-prose'));return box;
}
function interviewInput(task,slot) {
  let frozen=null;try{frozen=JSON.parse(localStorage.getItem(interviewPendingKey(task,slot))||'null');}catch{}
  const form=el('form'),label=el('label',slot==='follow_up'?'补充这一步的作答':'现场作答'),area=el('textarea');
  area.rows=7;area.maxLength=20000;area.required=true;if(frozen){area.value=frozen.answer_text;area.disabled=true;}
  label.append(area);form.append(label);
  let duration=null;
  if(task.kind==='trial_teaching'){
    const l=el('label','试讲时长（秒）');duration=el('input');duration.type='number';duration.min='1';duration.max='7200';duration.required=true;
    duration.value=String(frozen?.duration_seconds??600);if(frozen)duration.disabled=true;l.append(duration);form.append(l);
  }
  const actions=el('div',undefined,'form-actions'),submit=el('button',frozen?'重试提交（沿用上次作答参数）':'提交并查看比对 →','primary');
  submit.type='submit';actions.append(submit);form.append(actions);
  if(frozen)form.append(el('p','上次提交的参数已冻结：请求可能已在后端写入，重试只把结果补回本机。改答案或改时长会被拒绝（409），那等于另一次作答。','task-state'));
  form.addEventListener('submit',async e=>{
    e.preventDefault();let payload=frozen;
    if(!payload){
      const text=area.value.trim();if(!text){toast('请先写下作答。');return;}
      payload={...context(),session_id:interviewSession.session_id,task_id:task.task_id,answer_text:text,request_id:crypto.randomUUID()};
      if(duration)payload.duration_seconds=Number(duration.value)||600;
      try{localStorage.setItem(interviewPendingKey(task,slot),JSON.stringify(payload));}catch{}
      area.disabled=true;if(duration)duration.disabled=true;submit.textContent='重试提交（沿用上次作答参数）';
    }
    await busy(submit,async()=>{
      const data=await api('web/learning/interview/session/answer',payload);
      try{localStorage.removeItem(interviewPendingKey(task,slot));}catch{}
      interviewSession=data;renderInterviewSession();
    });
  });
  return form;
}
function interviewTaskCard(task) {
  const card=el('div',undefined,'study-check');
  card.append(el('h3',`${task.title||task.kind} · ${INTERVIEW_STATE_LABEL[task.state]||task.state}`),el('p',task.prompt,'study-prose'));
  if(task.exam_focus)card.append(el('p','高频考察点：'+task.exam_focus,'task-state'));
  card.append(interviewEvidence(task));
  if(task.state==='pending'){card.append(interviewInput(task,'answer'));return card;}
  card.append(interviewAnswerNote(task,'answer'),interviewFeedbackBox(task.feedback));
  if(task.follow_up){
    card.append(el('p','追问：'+task.follow_up.question,'study-prose'),el('p',task.follow_up.basis,'task-state'));
    if(task.state==='awaiting_follow_up')card.append(interviewInput(task,'follow_up'));
    else card.append(interviewAnswerNote(task,'follow_up_answer'),interviewFeedbackBox(task.follow_up_feedback,'追问后的比对'));
  }
  if((task.missed_points||[]).length)card.append(el('p','仍未比对到的框架步骤：'+task.missed_points.join('、'),'task-state'));
  return card;
}
function renderInterviewSession() {
  const box=$('interview-session'),start=$('interview-session-start');
  if($('exam').value!=='NTCE'){box.replaceChildren(notice('面试是教师资格考试的环节，四六级没有面试训练。把备考方向切到 NTCE 即可开始会话。'));start.disabled=true;return;}
  start.disabled=false;
  if(!interviewSession){
    start.textContent='开始训练会话 →';
    box.replaceChildren(notice('还没有训练会话。会话按三个阶段记录：结构化问答（提交后先比对库内参考框架，再追问一处）→ 试讲转写测算 → 20 分钟简案设计。参考框架在作答提交前不显示，避免透题。'));
    return;
  }
  const s=interviewSession,root=el('div');
  start.textContent=s.status==='completed'?'开始新的训练会话 →':'继续当前会话';
  root.append(el('div','INTERVIEW RUN','eyebrow'),el('h2',s.status==='completed'?'本次训练会话已完成':'训练进行中'),
    el('p',`已完成 ${s.answered_tasks} / ${s.total_tasks} 个任务 · 范围 ${levels[s.school_level]||s.school_level}${s.subject?' · '+(subjects[s.subject]||s.subject):''} · 内容档位 ${s.trust_tier}`,'muted'));
  for(const stage of s.stages){
    const part=el('div',undefined,'surface');
    part.append(el('h3',`${stage.title} · ${stage.completed?'已完成':'进行中'}`),el('p',stage.notice,'task-state'));
    for(const task of stage.tasks)part.append(interviewTaskCard(task));
    root.append(part);
  }
  root.append(notices(s.notices));
  replace('interview-session',root);
}
async function startInterviewSession() {
  const data=await trackedCall('web/learning/interview/session',context());
  interviewSession=data.session||data;renderInterviewSession();
}
async function loadInterviewSession() {
  const scope=scopeIdentity(),data=await api('web/learning/interview/session/current',context());
  if(scope!==scopeIdentity())return;
  interviewSession=data.session||null;renderInterviewSession();
}
function clearInterviewSession() {interviewSession=null;renderInterviewSession();}
$('interview-session-start').addEventListener('click',e=>busy(e.target,()=>startInterviewSession()));
$('interview-session-reload').addEventListener('click',e=>busy(e.target,()=>loadInterviewSession()));
