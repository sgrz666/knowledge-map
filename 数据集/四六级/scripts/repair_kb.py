"""Repair v2 artifacts, add official requirement links and usable task schemas.

All automatic labels remain initial labels. No expert-review, calibrated
difficulty or CET/CSE equivalence is asserted by this pipeline.
"""
import argparse, copy, json, re, sys
from collections import defaultdict, Counter
from pathlib import Path
from cet_common import load_jsonl, dedupe_resources, jsonl_dumps, fill_missing

KB = Path(__file__).resolve().parents[1]
ROOT = KB.parents[1]
SRC = ROOT / '英语四六级资料合集（2026年最新）(1)'
sys.stdout.reconfigure(encoding='utf-8')

def dump(path, rows):
    path.write_text('\n'.join(jsonl_dumps(r) for r in rows)+'\n',encoding='utf-8')

class Sources:
    def __init__(self, root=ROOT, src=SRC, kb=KB):
        self.root,self.src,self.kb=root,src,kb
        self.by_name=defaultdict(list)
        for p in list(src.rglob('*'))+list((kb/'scripts/_staging').rglob('*')):
            if p.is_file(): self.by_name[p.name].append(p)
        self.outline_files={level:[p for paths in self.by_name.values() for p in paths if p.suffix=='.xls' and f'大学英语{level}级词汇完整带音标' in p.name and '正序' in p.name] for level in ('四','六')}

    def resolve(self, value, row):
        if not value: return []
        value=str(value).replace('\\','/')
        if '...' in value:
            if 'words_cet4' in row.get('_file','') or row.get('resource_id','').startswith('cet4.w.'):
                return self.outline_files['四']
            if 'words_cet6' in row.get('_file','') or row.get('resource_id','').startswith('cet6.w.'):
                return self.outline_files['六']
            return []
        for base in (self.root,self.src,self.kb/'scripts'):
            p=base/value
            if p.is_file(): return [p]
        return self.by_name.get(Path(value).name, [])

    def repair(self, row, filename):
        source=row.setdefault('source',{})
        source['copyright']=fill_missing(source.get('copyright',{}),{'authorization_status':'unknown','holder':None,'use_scope':'research_non_commercial','expires_at':None,'evidence':[],'review_status':'pending_rights_verification'})
        old=source.get('origin_file')
        if old: source.setdefault('_legacy_origin_file',old)
        files=source.setdefault('files',[]);row['_file']=filename
        ex=row.get('extra') or {}
        anchor=ex.get('word') or ex.get('phrase') or ex.get('source_text') or ex.get('topic_prompt') or ex.get('en') or row.get('text') or ''
        unresolved=[]
        for val in re.split(r';\s*', old or ''):
            if not val: continue
            paths=self.resolve(val,row)
            if not paths: unresolved.append(val);continue
            for p in paths:
                ref={'path':p.relative_to(self.root).as_posix(),'role':'original_content',
                     'locator':{'resource_id':row.get('resource_id') or row.get('question_id'), 'text_anchor':anchor[:160]}}
                if 'question_id' in row:
                    ref['locator']={'question_number':ex.get('number'),'paper':source.get('paper'),'year':source.get('year')}
                # Preserve a previously more precise page/table locator.
                if not any(f.get('path')==ref['path'] and f.get('role')=='original_content' for f in files): files.append(ref)
        row.pop('_file',None)
        originals=[f for f in files if f.get('role')=='original_content']
        if originals: source['origin_file']=originals[0]['path']
        source['local_file_status']='resolved' if files and all((self.root/f['path']).is_file() for f in files) else 'unresolved'
        if unresolved: source['unresolved_legacy_references']=unresolved
        else: source.pop('unresolved_legacy_references',None)
        return source['local_file_status']=='resolved'

NODE_REQ = {
 'listen.gist':[79], 'listen.detail':[5], 'listen.infer':[80],
 'read.locate':[83,20], 'read.synonym':[17,19], 'read.detail':[83],
 'read.infer':[85], 'read.gist':[82,84], 'read.attitude':[15,16],
 'read.cloze':[17,19], 'read.discourse':[18,19],
 'write.structure':[26,86], 'write.argument':[25,87], 'write.coherence':[26,27], 'write.accuracy':[88,89,90,91],
 'trans.topic':[34], 'trans.syntax':[35], 'lang.vocab':[17,34], 'lang.grammar':[19], 'lang':[19],
}
BASE_REQ={'listen':(1,2),'read':(12,13),'write':(21,22),'trans':(30,31)}
TYPE_REQ={'短篇新闻':16,'长对话':17,'听力篇章':18,'讲座/讲话':18,'选词填空':19,'长篇阅读':20,'仔细阅读':21,'短文写作':15,'段落汉译英':22}

def type_requirement(exam, question_type):
    num=TYPE_REQ.get(question_type)
    if exam=='CET-6' and question_type=='长对话': num=16
    if exam=='CET-6' and question_type=='听力篇章': num=17
    lv='cet4' if exam=='CET-4' else 'cet6'
    return f'cet.content.{lv}.r{num:03d}' if num else None

def question_requirement_ids(row, ids, requirements):
    skill={'听力理解':'听力','阅读理解':'阅读'}.get(row.get('module'),row.get('module'))
    return [i for i in ids if i in requirements
            and row.get('exam') in requirements[i].get('level',[])
            and requirements[i].get('module','').replace('理解','').replace('评分','')==skill]

def req_ids(node, requirements):
    lv,suffix=node.split('.',1);exam='CET-4' if lv=='cet4' else 'CET-6'
    nums=NODE_REQ.get(suffix,[])
    if suffix in BASE_REQ: nums=[BASE_REQ[suffix][0 if lv=='cet4' else 1]]
    ids=[f'cet.syllabus.2016.r{n:03d}' for n in nums]
    return [i for i in ids if i in requirements and exam in requirements[i].get('level',[])]

def requirement_links(row, ids, requirements, catalog):
    ids=list(dict.fromkeys(i for i in ids if i in requirements))
    old={m.get('requirement_id'):m for m in row.get('requirement_mappings',[])}
    row['exam_requirement_ids']=ids
    row['requirement_mappings']=[fill_missing(old.get(i,{}),{'requirement_id':i, 'standard_id':requirements[i]['standard_id'],
                                 'locator':requirements[i]['locator'],
                                 'source_url':catalog[requirements[i]['standard_id']]['source_url'],
                                 'method':'CET syllabus skill and official question-type table alignment',
                                 'review_status':'initial_mapping_pending_subject_expert'}) for i in ids]

def reviewer(row):
    ex=row.setdefault('extra',{})
    ex.setdefault('content_review',{'initial_label':{'method':'parser_and_explicit_rules','status':'auto_labeled'},
                                  'expert_review':{'status':'pending','reviewer':None,'reviewed_at':None,'evidence':[]}})
    ex.setdefault('difficulty_metadata',{'status':'pending_calibration','method':None,'estimate':None,
                                        'sample_count':0,'planned_method':'collect response evidence; estimate empirical success rate or fit IRT; subject-expert validation'})
    if ex.get('cse_level') is not None:
        ex.setdefault('_legacy_unverified_cse_level',ex['cse_level']);ex['cse_level']=None
    if row.get('cse_level') is not None:
        row.setdefault('_legacy_unverified_cse_level',row['cse_level']);row['cse_level']=None
    row.setdefault('cse_alignment',{'status':'pending_official_CET_CSE_linking_evidence','cse_level':None})

def deactivate_unreviewed_prerequisites(nodes,edges):
    for node in nodes:
        review=node.setdefault('prerequisite_review',{'status':'proposed_pending_subject_expert','method':'curriculum_concept_dependency_proposal'})
        if review.get('status')=='approved': continue
        node['candidate_prereq']=list(dict.fromkeys(node.get('candidate_prereq',[])+node.get('prereq',[])))
        node['prereq']=[];review['active']=False
    for edge in edges:
        if edge.get('rel')=='prereq_of' and edge.get('review_status')!='approved':
            edge.update({'rel':'prerequisite_candidate','proposed_rel':'prereq_of','active':False,'review_status':'proposed_pending_subject_expert'})
        elif edge.get('rel')=='prerequisite_candidate':
            edge['active']=False

def clean_listening_prompt(row):
    if row.get('module')!='听力理解': return
    extra=row.setdefault('extra',{});value=row.get('content',{}).get('stem')
    if not value or extra.get('content_review',{}).get('expert_review',{}).get('status')=='approved': return
    text=value.strip()
    noise=(bool(re.fullmatch(r'[\d\s.()）]+',text)) or bool(re.fullmatch(r'Section\s+[A-D]',text,re.I))
           or bool(re.match(r'^Questions?\s+\d+\s+(?:to|-)\s+\d+\b',text,re.I)) or bool(re.match(r'^[A-D]\s*[)）.]\s*\S',text)))
    if not noise: return
    entry={'value':value,'reason':'section_label_question_number_instruction_or_option_is_not_a_spoken_question','status':'quarantined_parser_noise'}
    history=extra.setdefault('prompt_parse_history',[])
    if entry not in history: history.append(entry)
    row['content']['stem']=None

def historical_format_evidence(row, cache):
    """Do not assert the 2016 design governed a source labelled 2015."""
    year=str(row.get('source',{}).get('year') or row.get('year') or '')
    if not year or year>='2016': return
    path=row.get('source',{}).get('origin_file')
    if path not in cache:
        evidence={'source_path':path,'source_year':year,'title':None,'listening_direction_excerpt':None}
        if path and (ROOT/path).suffix.lower()=='.docx' and (ROOT/path).is_file():
            from docx import Document
            paras=[p.text for p in Document(ROOT/path).paragraphs if p.text.strip()]
            evidence['title']=paras[0] if paras else None
            index=next((i for i,p in enumerate(paras) if 'Listening Comprehension' in p),None)
            if index is not None:
                direction=next((p for p in paras[index:index+6] if p.lstrip().startswith('Directions:')),None)
                evidence['listening_direction_excerpt']=direction[:450] if direction else None
                evidence['modern_format_terms']=bool(direction and re.search(r'three news reports|two long conversations',direction,re.I))
        cache[path]=evidence
    evidence=cache[path]
    row.setdefault('extra',{})['exam_design_applicability']={'status':'historical_source_year_and_format_pending_authentication','source_evidence':evidence,
        'reference_standard':'cet.syllabus.2016','mapping_scope':'learning_skill_alignment_only_not_proof_of_historical_syllabus_applicability',
        'reason':'Source labelled before 2016; retain source title and actual format. Confirm original official paper and historical syllabus before using current exam design.'}
    for mapping in row.get('requirement_mappings',[]):
        if mapping.get('review_status')=='initial_mapping_pending_subject_expert':
            mapping['historical_applicability']='pending_original_paper_and_historical_syllabus_authentication'

def build_rubrics(requirements,catalog):
    official=json.loads((ROOT/'权威资料/official_cet_rubrics.json').read_text('utf-8'))
    by_type={r['task_type']:r for r in official['rubrics']}
    rubrics=[]
    for kind,nums in [('writing',[66,67]),('translation',[68,69,70])]:
        rid=f'cet.{kind}.holistic.2016'
        isw=kind=='writing'
        original=by_type['写作' if isw else '翻译']
        dims=['切题与信息表达','篇章组织与衔接','语言准确性与词汇'] if isw else ['原文信息准确与完整','句法与用词','语篇清晰与连贯']
        r={'rubric_id':rid,'task_type':'short_essay' if isw else 'paragraph_translation','exams':['CET-4','CET-6'],
           'method':'official_holistic_band_selection','max_raw_score':15,
           'bands':[dict(b,raw_score_min=b['raw_score_range'][0],raw_score_max=b['raw_score_range'][1]) for b in original['bands']],
           'feedback_dimensions':[{'name':d,'required_evidence':'quote from student response and prompt/source; explain impact','aggregation':'feedback_only_no_official_additive_weight'} for d in dims],
           'scoring_output_schema':{'rubric_id':'string','selected_band':'14|11|8|5|2','raw_score':'integer in selected band range',
                                    'dimension_feedback':'list of dimension/evidence/comment','review_status':'ai_practice_feedback|expert_reviewed','reviewer':'nullable string'},
           'review_status':'official_descriptors_transcribed_pending_application_expert_review',
           'official_descriptor_source':'权威资料/official_cet_rubrics.json',
           'official_descriptor_requirement_ids':original['requirement_ids'],
           'score_use':'练习反馈；缺少当次考试评分样卷，不能宣称为正式阅卷结果或报道分。'}
        requirement_links(r,[f'cet.syllabus.2016.r{n:03d}' for n in nums],requirements,catalog)
        rubrics.append(r)
    old=load_jsonl(KB/'ontology/scoring_rubrics.jsonl');by_id={r['rubric_id']:r for r in old}
    for r in rubrics:
        saved=by_id.get(r['rubric_id'],{})
        if saved.get('bands') and saved['bands']!=r['bands']:
            saved.setdefault('descriptor_history',[]).append({'bands':saved['bands'],'reason':'replaced_by_exact_official_descriptor_transcription'})
        merged=fill_missing(saved,r);merged['bands']=r['bands'];by_id[r['rubric_id']]=merged
    dump(KB/'ontology/scoring_rubrics.jsonl',list(by_id.values()))

def audio_index():
    from fill_answers import DATE,PAPER,CN
    index=defaultdict(list)
    for p in sorted(SRC.rglob('*.mp3')):
        name=p.name;dm=DATE.search(name)
        if not dm: continue
        exam='CET-4' if re.search(r'四级|CET4|4级',str(p),re.I) else 'CET-6'
        ym=f'{dm[1]}-{int(dm[2]):02d}';pm=PAPER.search(name)
        if '相同' in name: papers=[1,2,3]
        elif pm: papers=[CN.get(pm[1],int(pm[1]) if pm[1].isdigit() else 0)]
        else: continue
        for paper in papers: index[(exam,ym,paper)].append(p.relative_to(ROOT).as_posix())
    return index

def audio_sharing_evidence(index):
    """Use explicit corpus notices; never infer sharing from missing audio alone."""
    from fill_answers import DATE
    evidence={}
    for p in SRC.rglob('*.txt'):
        note=p.name+' '+p.read_text('utf-8',errors='replace')
        if not re.search(r'共用|相同|一致|一样',note): continue
        dm=None
        for parent in p.parents:
            if parent==SRC: break
            dm=DATE.search(parent.name)
            if dm: break
        if not dm: continue
        exam='CET-4' if '四级' in str(p) else 'CET-6';ym=f'{dm[1]}-{int(dm[2]):02d}'
        source_paper=None;targets=[]
        if '共用一套' in note or '共用一' in note:
            source_paper=1;targets=[2,3]
        elif re.search(r'(?:第三套|第3套).*?(?:第二套|前两套)|第二套.*?第三套',note):
            source_paper=2;targets=[3]
        if not source_paper: continue
        files=index.get((exam,ym,source_paper),[])
        if not files: continue
        for target in targets:
            key=(exam,ym,target)
            if index.get(key): continue
            index[key]=list(files)
            evidence[key]={'path':p.relative_to(ROOT).as_posix(),'role':'audio_sharing_notice','locator':{'text_anchor':note[:300]},
                           'shared_from_paper':source_paper,'review_status':'corpus_explicit_notice_pending_expert'}
    return evidence

def main():
    import migrate_v2_schema as migration
    migration.main()
    resolver=Sources()
    requirements={r['requirement_id']:r for r in load_jsonl(ROOT/'权威资料/requirements.jsonl')}
    catalog={r['standard_id']:r for r in json.loads((ROOT/'权威资料/catalog.json').read_text('utf-8'))['sources']}
    if not requirements: raise RuntimeError('Official requirements must be collected before repair.')
    kn=load_jsonl(KB/'ontology/knowledge_nodes.jsonl');knmap={r['id']:r for r in kn}
    edges=load_jsonl(KB/'ontology/edges.jsonl')
    deactivate_unreviewed_prerequisites(kn,edges)
    for node in kn:
        ids=req_ids(node['id'],requirements)
        requirement_links(node,ids,requirements,catalog)
        reviewer(node)
        node.setdefault('mapping_status','initial_mapping_pending_subject_expert')
        node.setdefault('prerequisite_review',{'status':'proposed_pending_subject_expert','method':'curriculum_concept_dependency_proposal'})
    dump(KB/'ontology/knowledge_nodes.jsonl',kn)
    ab=load_jsonl(KB/'ontology/ability_nodes.jsonl')
    for r in ab:
        requirement_links(r,[i for k in r['knowledge_node_ids'] for i in knmap[k]['exam_requirement_ids']],requirements,catalog);reviewer(r)
    dump(KB/'ontology/ability_nodes.jsonl',ab)
    standards=json.loads((KB/'ontology/standards.json').read_text('utf-8'))
    for s in standards['standards']:
        if s['id']=='std.cse':
            s.update({'authority':'教育部、国家语言文字工作委员会','code':'GF0018-2018','standard_ids':['cse.gf0018-2018']})
            if 'cse.gf0018-2024' in catalog:
                s['standard_ids'].append('cse.gf0018-2024')
                s['code']='GF0018-2024';s['historical_code']='GF0018-2018'
            s['versions']=[catalog[i] for i in s['standard_ids'] if i in catalog]
            s['cet_cse_alignment_status']='pending_official_linking_evidence'
        elif s['id']=='std.cet.syllabus': s['official_source']=catalog.get('cet.syllabus.2016')
        elif s['id']=='std.cet.wordlist':
            s['verification_status']='local_vocabulary_resource_not_authenticated_official_wordlist'
    (KB/'ontology/standards.json').write_text(json.dumps(standards,ensure_ascii=False,indent=2),encoding='utf-8')
    dump(KB/'ontology/edges.jsonl',edges)
    audios=audio_index();shared_audio=audio_sharing_evidence(audios);historical_cache={}
    report={'baseline_resource_counts':{'writing/model_essays.jsonl':177,'translation/items.jsonl':193,'vocabulary/phrases_highfreq.jsonl':1406},'resources':{},'questions':Counter(),'unresolved_sources':[]}
    baseline_ids=set(json.loads((KB/'manifest/review_baseline.json').read_text('utf-8'))['question_answers'])
    for folder in ('questions','passages','writing','translation','vocabulary','listening'):
        for path in sorted((KB/folder).rglob('*.jsonl')):
            if path.name.startswith('_'): continue
            before=load_jsonl(path);rows=dedupe_resources(before) if folder!='questions' else before
            for r in rows:
                if not resolver.repair(r,str(path.relative_to(KB))): report['unresolved_sources'].append(r.get('question_id') or r.get('resource_id'))
                if folder=='passages' and r.get('kind') in ('reading','careful') and any(k.endswith('.read') for k in r.get('knowledge_node_ids',[])):
                    ex=r.setdefault('extra',{});ex.setdefault('_legacy_coarse_knowledge_node_ids',r['knowledge_node_ids'])
                    prefix='cet4' if r.get('exam')=='CET-4' else 'cet6'
                    r['knowledge_node_ids']=list(dict.fromkeys([k for k in r['knowledge_node_ids'] if not k.endswith('.read')]+[prefix+'.read.detail',prefix+'.read.locate']))
                    r['ability_ids']=list(dict.fromkeys(a for k in r['knowledge_node_ids'] for a in knmap[k].get('ability_ids',[])))
                ids=[i for k in r.get('knowledge_node_ids',[]) for i in knmap.get(k,{}).get('exam_requirement_ids',[])]
                if folder=='listening':r['ability_ids']=list(dict.fromkeys(a for k in r.get('knowledge_node_ids',[]) for a in knmap.get(k,{}).get('ability_ids',[])))
                lv='cet4' if r.get('exam')=='CET-4' else 'cet6'
                if 'question_id' in r:
                    if r['question_id'] not in baseline_ids:
                        ex=r['extra'];number=ex.get('number')
                        outside=not isinstance(number,int) or not 1<=number<=55 or r['module']=='听力理解' and number>25
                        ex['source_discovery']={'baseline_member':False,'status':'parser_artifact_outside_CET_number_range' if outside else 'source_number_and_content_recovered_pending_subject_expert' if ex.get('option_parse_method')=='exact_original_word_question_number_and_four_options' or ex.get('original_prompt_recovery') else 'new_source_boundary_pending_verification',
                            'expert_confirmation_status':'pending','counts_as_confirmed_new_exam_question':False}
                        if outside:
                            ex['active']=False;ex['scoring_eligible']=False
                            if r['content'].get('answer'):
                                history=ex.setdefault('answer_history',[]);entry={'answer':r['content']['answer'],'reason':'parser_artifact_outside_CET_number_range','status':'quarantined'}
                                if entry not in history:history.append(entry)
                            r['content']['answer']=None;ex['answer_status']='parser_artifact_outside_CET_number_range'
                    type_id=type_requirement(r.get('exam'),r.get('question_type'))
                    if type_id and str(r.get('source',{}).get('year',''))>='2016': ids.append(type_id)
                    ids=question_requirement_ids(r,ids,requirements)
                    if r.get('question_type') in ('短文写作','段落汉译英'):
                        r['rubric_id']=f"cet.{'translation' if r['question_type']=='段落汉译英' else 'writing'}.holistic.2016"
                    if r['module']=='听力理解':
                        clean_listening_prompt(r)
                        src=r['source'];cn={'第一套':1,'第二套':2,'第三套':3}
                        key=(r['exam'],src['year'],cn.get(src['paper']))
                        group=r['extra'].get('group') or 'unsegmented'
                        files=audios.get(key,[])
                        fresh_audio={'group_id':f"{lv}-{src['year']}-p{key[2]}-{group}",
                                             'files':[{'path':p,'role':'listening_audio'} for p in files],
                                             'start_seconds':None,'end_seconds':None,
                                             'status':'file_linked_segment_pending' if files else 'missing_exact_paper_audio'}
                        old_audio=r['extra'].get('audio',{})
                        r['extra']['audio']=fill_missing(old_audio,fresh_audio)
                        if files and old_audio.get('status')=='missing_exact_paper_audio': r['extra']['audio']['status']=fresh_audio['status']
                        if key in shared_audio: r['extra']['audio']['binding_evidence']=shared_audio[key]
                        if not r.get('content',{}).get('stem'):
                            r['extra']['question_prompt_availability']={'delivery':'spoken_in_audio','printed_stem':False,'linked_audio_file':bool(r['extra']['audio']['files']),
                                'transcript_status':'not_extracted_pending_source_transcription','individual_segment_status':'pending_time_alignment',
                                'status':'full_paper_audio_available_pending_alignment' if r['extra']['audio']['files'] else 'spoken_prompt_unavailable_missing_audio_and_transcript'}
                        report['questions']['with_audio_file']+=bool(files)
                requirement_links(r,ids,requirements,catalog);reviewer(r)
                historical_format_evidence(r,historical_cache)
                if folder in ('writing','translation') and r.get('resource_id') and path.name in ('model_essays.jsonl','items.jsonl'):
                    ex=r['extra'];trans=folder=='translation'
                    r['task_id']=r['resource_id'];r['module']='翻译' if trans else '写作'
                    r['task_type']='paragraph_translation' if trans else 'short_essay'
                    r['content']=fill_missing(r.get('content',{}),{'prompt':ex.get('source_text') if trans else ex.get('topic_prompt'),
                                  'reference_answer':ex.get('reference') if trans else ex.get('model_essay')})
                    r['rubric_id']=f"cet.{'translation' if trans else 'writing'}.holistic.2016"
                    r['task_constraints']=fill_missing(r.get('task_constraints',{}),{'time_limit_minutes':30,'source_language':'zh' if trans else 'en','response_language':'en',
                                           'constraints_status':'official_general_rule; prompt-specific word limits preserved in content.prompt'})
                    r['task_status']='reference_available_pending_expert_review' if r['content']['prompt'] and r['content']['reference_answer'] else 'missing_prompt_or_reference'
                    if trans:
                        zh=ex.get('source_text') or ''
                        topic_rules={'文化':['文化','传统','节日','春节','中秋','茶','戏剧'],'社会经济':['经济','社会','发展','城市','农村','交通'],'科技环境':['科技','技术','环境','能源','污染','科学']}
                        r['annotations']=fill_missing(r.get('annotations',{}),{'themes':[k for k,words in topic_rules.items() if any(w in zh for w in words)],
                                          'syntax_features':[],'vocabulary_features':ex.get('key_phrases') or [],'culture_features':[],
                                          'method':'transparent topic keyword initial labeling; sentence/vocabulary/culture annotation pending expert',
                                          'review_status':'auto_initial'})
            dump(path,rows)
            if folder!='questions': report['resources'][str(path.relative_to(KB))]={'before':len(before),'records':len(rows),'unique_ids':len({r.get('resource_id') for r in rows})}
    build_rubrics(requirements,catalog)
    from repair_passage_references import reconcile
    report['passage_reference_repair'] = reconcile(KB, ROOT)['summary']
    report['questions']=dict(report['questions'])
    report['historical_source_papers_pending_authentication']=list(historical_cache.values())
    (KB/'manifest/repair_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
