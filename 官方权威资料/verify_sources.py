"""Verify archived bytes, stable IDs, exact source locators, and official rubrics."""
import collections, hashlib, json, re, sys, unicodedata
from pathlib import Path
from build_index import cet_content, cet_template
ROOT=Path(__file__).resolve().parent; BASE=ROOT.parent
def h(path): return hashlib.sha256(path.read_bytes()).hexdigest()
catalog=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
sources={s['standard_id']:s for s in catalog['sources']}
with (ROOT/'requirements.jsonl').open(encoding='utf-8') as stream:
    requirements=[json.loads(x) for x in stream if x.strip()]
errors=[]
text_cache={}; json_cache={}
def read_json(path):
    path=str(path)
    if path not in json_cache: json_cache[path]=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return json_cache[path]
def read_lines(path):
    path=str(path)
    if path not in text_cache: text_cache[path]=Path(path).read_text(encoding='utf-8-sig').splitlines()
    return text_cache[path]
outline_boundaries={}; html_requirements={}
for s in sources.values():
    if not s.get('verified'): errors.append({'type':'source_not_verified','id':s['standard_id']})
    for field,hashfield in [('local_path','sha256'),('text_path','text_sha256'),('landing_path','landing_sha256')]:
        if field not in s: continue
        p=BASE/s[field]
        if not p.exists(): errors.append({'type':'missing_file','id':s['standard_id'],'field':field})
        elif h(p)!=s.get(hashfield): errors.append({'type':'hash_mismatch','id':s['standard_id'],'field':field})
    if s.get('kind')=='written_outline':
        lines=read_lines(BASE/s['text_path'])
        stops=[n for n,v in enumerate(lines,1) if re.match(r'^(?:[三四五]、)?(?:试卷结构|题型示例)(?:$|[（(：:])',re.sub(r'\s+','',unicodedata.normalize('NFKC',v)))]
        if not stops: errors.append({'type':'outline_boundary_missing','id':s['standard_id']})
        else: outline_boundaries[s['standard_id']]=stops[0]
    if s['standard_id'] in {'cet.content.cet4','cet.content.cet6'}:
        html_requirements[s['standard_id']]={json.dumps(r['locator'],sort_keys=True):r['content'] for r in cet_content(s)}
ids=[r['requirement_id'] for r in requirements]
for key,n in collections.Counter(ids).items():
    if n>1: errors.append({'type':'duplicate_id','id':key})
retired=read_json(ROOT/'retired_requirement_ids.json').get('retired',[])
for rid in set(ids).intersection(retired): errors.append({'type':'retired_id_reused','id':rid})
for r in requirements:
    rid=r['requirement_id']; loc=r['locator']
    if r['standard_id'] not in sources: errors.append({'type':'dangling_standard','id':rid}); continue
    if r['standard_id']=='cet.syllabus.2016' and cet_template(r['content']): errors.append({'type':'cet_template_not_requirement','id':rid})
    if re.fullmatch(r'[\s\d.%％分钟]+',r['content']): errors.append({'type':'orphan_numeric_requirement','id':rid})
    if 'text_path' in loc:
        lines=read_lines(BASE/loc['text_path'])
        if not isinstance(loc.get('line_start'),int) or not isinstance(loc.get('line_end'),int) or not 1<=loc['line_start']<=loc['line_end']<=len(lines):
            errors.append({'type':'text_locator_range_invalid','id':rid}); continue
        if r['standard_id'] in outline_boundaries and loc['line_end']>=outline_boundaries[r['standard_id']]: errors.append({'type':'outside_exam_requirement_section','id':rid})
        original='\n'.join(lines[loc['line_start']-1:loc['line_end']])
        quote=r.get('original_text',r['content'])
        if quote not in original: errors.append({'type':'text_locator_mismatch','id':rid})
    elif 'json_pointer' in loc:
        obj=read_json(BASE/loc['json_path'])
        for part in loc['json_pointer'].lstrip('/').split('/'):
            obj=obj[int(part)] if isinstance(obj,list) else obj[part.replace('~1','/').replace('~0','~')]
        if obj!=r['content']: errors.append({'type':'json_locator_mismatch','id':rid})
    elif 'table_path' in loc:
        tables=read_json(BASE/loc['table_path'])
        if isinstance(tables,dict): tables=[tables]
        cell=[c['text'] for t in tables if t['table']==loc['table'] for c in t['cells'] if c['row']==loc['row'] and c['column']==loc['column']]
        if cell!=[r['content']]: errors.append({'type':'table_locator_mismatch','id':rid})
    elif 'html_path' in loc:
        if not (BASE/loc['html_path']).exists(): errors.append({'type':'html_locator_file_missing','id':rid})
        elif html_requirements.get(r['standard_id'],{}).get(json.dumps(loc,sort_keys=True))!=r['content']: errors.append({'type':'html_row_content_mismatch','id':rid})
cet_skill_counts={}
for module,count in {'听力':9,'阅读':10,'写作':11,'翻译':5,'口语':5}.items():
    rows=[r for r in requirements if r['standard_id']=='cet.syllabus.2016' and r.get('requirement_type')=='numbered_skill' and r['module']==module]
    codes=sorted(r.get('skill_code','') for r in rows)
    cet_skill_counts[module]=len(rows)
    if codes!=[f'{n:02d}' for n in range(1,count+1)]: errors.append({'type':'cet_numbered_skill_coverage_incomplete','module':module,'codes':codes})
rubrics=json.loads((ROOT/'official_interview_rubrics.json').read_text(encoding='utf-8'))['criteria']
totals=collections.defaultdict(int); group_scores=collections.defaultdict(int); group_weights={}
for rule in rubrics:
    sid=rule['standard_id']; group=(sid,rule['project'])
    totals[sid]+=rule['score']; group_scores[group]+=rule['score']; group_weights[group]=rule['weight']
for sid,total in totals.items():
    if total!=100: errors.append({'type':'rubric_total_not_100','id':sid,'value':total})
for group,score in group_scores.items():
    if score!=group_weights[group]: errors.append({'type':'rubric_group_weight_mismatch','id':str(group),'score':score,'weight':group_weights[group]})
cet=json.loads((ROOT/'official_cet_rubrics.json').read_text(encoding='utf-8'))['rubrics']
for rubric in cet:
    if [b['band'] for b in rubric['bands']] != [14,11,8,5,2]: errors.append({'type':'cet_band_missing','id':rubric['task_type']})
    for rid in rubric['requirement_ids']:
        if rid not in ids: errors.append({'type':'cet_rubric_dangling_requirement','id':rid})
report={'source_count':len(sources),'verified_source_count':sum(s.get('verified',False) for s in sources.values()),'requirement_count':len(requirements),'written_outline_boundary_count':len(outline_boundaries),'retired_requirement_count':len(retired),'cet_numbered_skill_counts':cet_skill_counts,'official_interview_criterion_count':len(rubrics),'official_cet_band_count':sum(len(x['bands']) for x in cet),'interview_totals':dict(totals),'error_count':len(errors),'errors':errors}
(ROOT/'verification_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2)); sys.exit(bool(errors))
