"""Recover complete source-bounded writing/translation tasks and references."""
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path
import pymupdf as fitz
from cet_common import load_jsonl, merge_jsonl, jsonl_dumps, canonical_id

RE_HDR=re.compile(r'(\d(?:\s*\d){3})\s*年\s*(\d(?:\s*\d)?)\s*月\s*(?:大学\s*)?英语\s*(四级|六级)\s*(写作|作文|翻译)\s*(真题答案|真题|参考范文|范文|参考译文|答案)?\s*[（(]?\s*(?:第|全(?=\s*[一1]\s*套))\s*([一二三\d])\s*套',re.I)
CN={'一':1,'二':2,'三':3}
RE_FOOTER=re.compile(r'\s*英语[四六]级(?:写作|翻译)(?:真题|参考译文|范文)?(?:专项)?\s*$')

def clean_body(text):
    lines=[]
    for line in text.split('\n'):
        if re.search(r'淘宝店|叮当助考|微信号|公众号|https?://|(?:写作|翻译).{0,15}第\s*\d+\s*页',line): continue
        if RE_FOOTER.fullmatch(line) or re.fullmatch(r'\s*(?:第|页|\d{1,3})\s*',line): continue
        lines.append(line)
    return '\n'.join(lines).strip()

def split_by_header(text):
    out={};headers=list(RE_HDR.finditer(text))
    for i,m in enumerate(headers):
        key=('cet4' if m[3]=='四级' else 'cet6',f"{re.sub(r'\s','',m[1])}-{int(re.sub(r'\s','',m[2])):02d}",CN.get(m[6],int(m[6]) if m[6].isdigit() else 0))
        end=headers[i+1].start() if i+1<len(headers) else len(text)
        out[key]=clean_body(text[m.end():end])
    return out

def clean_pdf_en(text):
    text=re.sub(r'(\w)-\s*\n\s*(\w)',r'\1\2',text)
    return re.sub(r'\s+',' ',text.replace('Y ou','You').replace('W hat','What').replace('T he ','The ')).strip()

def source_segments(path,root):
    with fitz.open(path) as doc:
        texts=[p.get_text() for p in doc]
    text='\n'.join(texts);headers=list(RE_HDR.finditer(text));offsets=[];pos=0
    for i,t in enumerate(texts): offsets.append((pos,pos+len(t),i+1));pos+=len(t)+1
    for i,m in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(text)
        key=('cet4' if m[3]=='四级' else 'cet6',f"{re.sub(r'\s','',m[1])}-{int(re.sub(r'\s','',m[2])):02d}",CN.get(m[6],int(m[6]) if m[6].isdigit() else 0))
        ref={'path':path.relative_to(root).as_posix(),'role':'task_reference','locator':{'pages':[n for a,b,n in offsets if b>=m.start() and a<=end],'text_offset':[m.start(),end],'header':m[0]}}
        ref['locator']['header_content_label']=m[5]
        yield key,clean_body(text[m.end():end]),ref

def normalized(text): return re.sub(r'[^a-z0-9\u4e00-\u9fff]','',(text or '').lower())

def apply_task_bindings(data,bindings):
    """Apply source-locator corrections supported by separately saved evidence."""
    applied=[]
    for binding in bindings:
        source_key=tuple(binding['from_task']);target_key=tuple(binding['to_task']);field=binding['field']
        evidence=binding['binding_evidence'];anchor=normalized(binding['text_anchor'])
        if len(anchor)<20 or not evidence.get('exam_answer_path') or not evidence.get('pages'): continue
        for candidate in list(data[source_key][field]):
            ref=candidate['source'];expected=binding['source']
            if ref['path']!=expected['path'] or ref['locator'].get('text_offset')!=expected['locator'].get('text_offset'): continue
            if not normalized(candidate['value']).startswith(anchor): continue
            data[source_key][field].remove(candidate)
            corrected=dict(candidate,source=dict(ref,binding_evidence=evidence,source_header_warning='misprinted task number; independently saved answer-page identity and reference text support correction'),review_status='source_binding_corrected_pending_expert')
            data[target_key][field].append(corrected);applied.append(binding)
    return applied

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--src',required=True);ap.add_argument('--kb',required=True);args=ap.parse_args(argv)
    src,kb=Path(args.src).resolve(),Path(args.kb).resolve();root=kb.parents[1]
    fitz.TOOLS.mupdf_display_errors(False)
    profiles=[]
    for path in sorted(src.rglob('*.pdf')):
        name=path.name
        if '专项' not in str(path): continue
        lv='cet4' if '四级' in name else ('cet6' if '六级' in name else None)
        if not lv: continue
        field=None
        if re.search(r'写作范文',name): field='model_essay'
        elif re.search(r'写作真题',name) and '答案' not in name: field='topic_prompt'
        elif re.search(r'翻译(?:译文|范文)',name): field='reference'
        elif '翻译真题' in name and '答案' not in name: field='source_text'
        elif re.search(r'(?:作文|写作)真题.*(?:答案|范文)',name): field='combined_writing'
        elif '翻译真题' in name and '答案' in name: field='combined_translation'
        if field: profiles.append((lv,field,path))
    data=defaultdict(lambda:defaultdict(list));bad=defaultdict(list);diagnostics=[]
    for lv,field,path in profiles:
        segs=list(source_segments(path,root))
        diagnostics.append({'path':path.relative_to(root).as_posix(),'field':field,'segments':len(segs),'status':'source_headers_extracted' if segs else 'no_complete_headers_pending_ocr'})
        for key,body,ref in segs:
            target_field=field
            if field.startswith('combined_'):
                label=ref['locator']['header_content_label'] or ''
                is_reference='答案' in label or '范文' in label or '译文' in label
                target_field=('model_essay' if is_reference else 'topic_prompt') if field=='combined_writing' else ('reference' if is_reference else 'source_text')
            active_field=target_field
            value=clean_pdf_en(body) if active_field in ('model_essay','reference','topic_prompt') else re.sub(r'\s+',' ',body).strip()
            if not value: continue
            ref['role']='reference_answer' if active_field in ('model_essay','reference') else 'task_prompt'
            if key[0]!=lv:
                bad[(key,active_field)].append((value,ref))
                diagnostics.append({'path':ref['path'],'header':ref['locator']['header'],'status':'header_level_conflicts_with_source_volume','body_preserved':value,'locator':ref['locator']})
                continue
            data[key][active_field].append({'value':value,'source':ref,'review_status':'source_extracted_pending_expert_review'})
    saved_bindings=load_jsonl(kb/'manifest/task_source_bindings.jsonl')
    for b in saved_bindings:
        if not (root/b['binding_evidence']['exam_answer_path']).is_file(): raise ValueError('Missing independent task-binding evidence')
    explicit_bindings=apply_task_bindings(data,saved_bindings)
    for folder,name,field in [('writing','_prompts.jsonl','topic_prompt'),('translation','_from_papers.jsonl','source_text')]:
        for row in load_jsonl(kb/folder/name):
            key=('cet4' if row['exam']=='CET-4' else 'cet6',row['year'],int(row['paper']))
            value=row.get(field)
            if not value: continue
            origin=row.get('source',{}).get('origin_file');path=next((base/origin for base in (root,src,kb/'scripts') if origin and (base/origin).is_file()),None)
            ref={'path':path.relative_to(root).as_posix(),'role':'task_prompt','locator':{'year':row['year'],'paper':row['paper'],'text_anchor':value[:160]}} if path else {'legacy_origin_file':origin,'role':'task_prompt'}
            data[key][field].append({'value':value,'source':ref,'review_status':'source_extracted_pending_expert_review'})
    rebound=[]
    # The paired prompt volume plus an exact match in the independently saved
    # examination paper can resolve a misprinted level, while keeping the warning.
    from fill_answers import read_source,file_meta
    paper_text_cache={}
    for (bad_key,field),items in bad.items():
        if field!='reference': continue
        for value,ref in items:
            source_name=Path(ref['path']).name
            lv='cet4' if '四级' in source_name else 'cet6'
            key=(lv,bad_key[1],bad_key[2]);prompts=data[key]['source_text']
            if not prompts: continue
            prompt=prompts[0];core=normalized(prompt['value'])
            paper=kb/'questions'/lv/f'{key[1]}_p{key[2]}.jsonl'
            files={f['path'] for q in load_jsonl(paper) for f in q.get('source',{}).get('files',[]) if f.get('role')=='original_content' and f.get('path','').lower().endswith('.docx')}
            if not files:
                files={p.relative_to(root).as_posix() for p in src.rglob('*.pdf') if file_meta(p)==('CET-4' if lv=='cet4' else 'CET-6',key[1],key[2]) and '原题' in str(p) and '扫描版' not in str(p)}
            matched=None
            for path in sorted(files):
                if path not in paper_text_cache: paper_text_cache[path]=normalized(read_source(root/path)[0])
                chinese_core=re.sub(r'[^\u4e00-\u9fff]','',core)
                chinese_paper=re.sub(r'[^\u4e00-\u9fff]','',paper_text_cache[path])
                if len(core)>100 and (core in paper_text_cache[path] or len(chinese_core)>100 and chinese_core in chinese_paper): matched=path;break
            if not matched: continue
            bound_ref=dict(ref,source_header_warning='source header names another level; exact prompt match supplies independent binding evidence',
                           binding_evidence={'method':'exact_complete_Chinese_characters_match_in_paired_prompt_volume_and_independent_exam_paper; English gloss/punctuation omitted for identity check','exam_paper_path':matched,'prompt_source':prompt['source'],'year':key[1],'paper':key[2],'review_status':'pending_subject_expert'})
            data[key]['reference'].append({'value':value,'source':bound_ref,'review_status':'source_header_rebound_by_exact_prompt_pending_expert'})
            rebound.append({'task':list(key),'source':bound_ref})
    report={'source_diagnostics':diagnostics,'exact_prompt_rebound_references':rebound,'independent_answer_page_bindings':explicit_bindings,'quarantined_reference_count':0,'quarantined_cross_task_content_count':0,'tasks':{}}
    for folder,prompt_field,ref_field,slug in [('writing','topic_prompt','model_essay','w'),('translation','source_text','reference','t')]:
        outfile=kb/folder/('model_essays.jsonl' if folder=='writing' else 'items.jsonl');old=load_jsonl(outfile)
        for row in old:
            rid=row.get('resource_id') or canonical_id(row);m=re.fullmatch(r'(cet[46])-(\d{4}-\d{2})-p(\d+)-(?:writing|translation)-1',rid)
            if not m: continue
            key=(m[1],m[2],int(m[3]));extra=row.get('extra',row)
            for field in (prompt_field,ref_field):
                value=extra.get(field)
                if value and RE_FOOTER.search(value):
                    entry={'field':field,'value':value,'reason':'volume_footer_included_in_old_task_content','status':'quarantined'}
                    history=extra.setdefault('reference_history',[])
                    if entry not in history: history.append(entry)
                    if extra.get('content_review',{}).get('expert_review',{}).get('status')!='approved':
                        extra[field]=None
                        if isinstance(row.get('content'),dict): row['content']['prompt' if field==prompt_field else 'reference_answer']=None
                        extra.setdefault('_legacy_text',row.get('text'));row['text']=None
                        report['quarantined_cross_task_content_count']+=1
                    value=extra.get(field)
                if value and RE_HDR.search(value):
                    entry={'field':field,'value':value,'reason':'old_header_parser_merged_following_task','status':'quarantined'}
                    history=extra.setdefault('reference_history',[])
                    if entry not in history: history.append(entry)
                    if extra.get('content_review',{}).get('expert_review',{}).get('status')!='approved':
                        extra[field]=None
                        if isinstance(row.get('content'),dict): row['content']['prompt' if field==prompt_field else 'reference_answer']=None
                        extra.setdefault('_legacy_text',row.get('text'));row['text']=None
                        report['quarantined_cross_task_content_count']+=1
            value=extra.get(ref_field)
            for bad_value,bad_ref in bad.get((key,ref_field),[]):
                core=normalized(bad_value)
                if value and len(core)>100 and core in normalized(value):
                    entry={'value':value,'reason':'reference_header_level_conflicts_with_source_volume','source':bad_ref,'status':'quarantined'}
                    history=extra.setdefault('reference_history',[])
                    if entry not in history: history.append(entry)
                    if extra.get('content_review',{}).get('expert_review',{}).get('status')!='approved':
                        extra[ref_field]=None
                        if isinstance(row.get('content'),dict): row['content']['reference_answer']=None
                        extra.setdefault('_legacy_text',row.get('text'));row['text']=None
                        report['quarantined_reference_count']+=1
        outfile.write_text('\n'.join(jsonl_dumps(r) for r in old)+'\n',encoding='utf-8')
        fresh=[]
        for (lv,ym,paper),fields in sorted(data.items()):
            if prompt_field not in fields and ref_field not in fields: continue
            prompt=fields[prompt_field][0]['value'] if fields[prompt_field] else None
            reference=fields[ref_field][0]['value'] if fields[ref_field] else None
            candidates=[dict(c,field=f) for f in (prompt_field,ref_field) for c in fields[f]]
            files=list({json.dumps(c['source'],sort_keys=True):c['source'] for c in candidates if c['source'].get('path')}.values())
            source={'files':files,'origin_file':'; '.join(dict.fromkeys(f['path'] for f in files))}
            exam='CET-4' if lv=='cet4' else 'CET-6'
            r={'id':f'{lv}.{slug}.{ym}_p{paper}','exam':exam,'year':ym,'paper':paper,prompt_field:prompt,ref_field:reference,'reference_candidates':candidates,'source':source,'review':{'status':'auto_parsed'},
               'text':f"【{ym} {exam} 第{paper}套】题目：{prompt or ''}\n参考：{reference or '（尚无来源参考）'}"}
            if folder=='writing': r.update({'word_count':len(reference.split()) if reference else None,'outline':None,'good_expressions':[]})
            else: r.update({'theme':None,'key_phrases':[],'notes':None})
            fresh.append(r)
        rows=merge_jsonl(outfile,fresh)
        report['tasks'][folder]={'records':len(rows),'with_prompt':sum(bool(r.get('extra',r).get(prompt_field)) for r in rows),'with_reference':sum(bool(r.get('extra',r).get(ref_field)) for r in rows)}
    (kb/'manifest/writing_translation_extract_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'tasks':report['tasks'],'quarantined_reference_count':report['quarantined_reference_count'],'quarantined_cross_task_content_count':report['quarantined_cross_task_content_count']},ensure_ascii=False))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
