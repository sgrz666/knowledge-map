"""Audit every local PDF/DOCX, recover bounded listening scripts and questions.

Bindings require an explicit volume, an explicit question range, an actual
published spoken question, and all four options matched to the independently
referenced original question. No transcript or question is generated.
"""
import argparse, hashlib, json, re, sys
from collections import defaultdict, Counter
from pathlib import Path
from cet_common import load_jsonl, jsonl_dumps, merge_jsonl
from fill_answers import read_source, file_meta, question_blocks, ref_for, normalized, CN

PART = re.compile(r'(?im)^\s*(?:Part[^\n]{0,50})?Listening\s+Comprehension')
STOP = re.compile(r'(?im)^\s*(?:Part[^\n]{0,50})?Reading\s+Comprehension')
GROUP = re.compile(r'(?im)^\s*(?:News\s+Report|Conversation|Passage|Lecture|Talk)\s+(?:One|Two|Three|Four|[1-9])\s*$')
RANGE = re.compile(r'Questions?\s+(\d{1,2})\s+(?:to|through|and|[-–])\s+(\d{1,2})\s+(?:are|is)\s+based',re.I)
PROMPT = re.compile(r'(?im)^\s*(?:Q(?:uestion)?\s*)?(\d{1,2})\s*[.、:．]\s*((?:What|Why|How|Where|When|Who|Which|Whose|According|For what|To what)[^?？\u4e00-\u9fff]{5,420}[?？])')
VOL = re.compile(r'(20\d{2})\s*年\s*(\d{1,2})\s*月[^\n]{0,35}(四级|六级)[^\n]{0,45}(?:第\s*([一二三1-3])\s*套|卷\s*([一二三1-3]))')

def read_listening_source(path):
    if path.suffix.lower()!='.pdf':return read_source(path)
    import pymupdf
    pieces=[];offsets=[];position=0
    with pymupdf.open(path) as doc:
        for i,page in enumerate(doc):
            # Native content order retains each column's full oral question.
            # Coordinate sorting can interleave Q1/Q2 before either question mark.
            value=page.get_text(sort=False);pieces.append(value)
            offsets.append((position,position+len(value),{'page':i+1,'pdf_text_order':'native_content_order'}));position+=len(value)+1
    return '\n'.join(pieces),offsets

def safe_prompts(text,start=0,end=None):
    return [m for m in PROMPT.finditer(text,start,len(text) if end is None else end)
            if not re.search(r'(?im)^\s*(?:Q(?:uestion)?\s*)?\d{1,2}\s*[.、:．]\s*(?:What|Why|How|Where|When|Who|Which|Whose|According)',m[2])]

def regions(path,text):
    meta=file_meta(path)
    if meta: return [(meta,0,len(text))]
    headers=list(VOL.finditer(text));out=[]
    for i,m in enumerate(headers):
        paper=m[4] or m[5];number=CN.get(paper,int(paper) if paper.isdigit() else 0)
        out.append((('CET-4' if m[3]=='四级' else 'CET-6',f'{m[1]}-{int(m[2]):02d}',number),m.end(),headers[i+1].start() if i+1<len(headers) else len(text)))
    return out

def extract_groups(text, dedicated=False):
    starts=list(PART.finditer(text))
    listening_start=starts[0].end() if starts else (0 if dedicated else None)
    if listening_start is None: return []
    stop=STOP.search(text,listening_start);end=stop.start() if stop else len(text)
    ranges=[m for m in RANGE.finditer(text,listening_start,end) if 1<=int(m[1])<=int(m[2])<=25]
    headers=list(GROUP.finditer(text,listening_start,end))
    if not headers: headers=list(re.finditer(r'【听力原文】',text[listening_start:end]));headers=[(listening_start+m.start(),listening_start+m.end()) for m in headers]
    else: headers=[(m.start(),m.end()) for m in headers]
    out=[]
    for i,rng in enumerate(ranges):
        finish=ranges[i+1].start() if i+1<len(ranges) else end
        qs=safe_prompts(text,rng.end(),finish)
        if not qs:continue
        body_start=rng.end();body_end=qs[0].start();raw=text[body_start:body_end].strip()
        if len(re.findall(r'[A-Za-z]+',raw))<45:
            prior=[(a,b) for a,b in headers if b<=rng.start()]
            if not prior:continue
            body_start=prior[-1][1];body_end=rng.start();raw=text[body_start:body_end].strip()
        if len(re.findall(r'[A-Za-z]+',raw))<45:continue
        nums=list(range(int(rng[1]),int(rng[2])+1));question_rows=[]
        for j,m in enumerate(qs):
            if int(m[1]) not in nums:continue
            qe=qs[j+1].start() if j+1<len(qs) else finish
            question_rows.append({'number':int(m[1]),'text':re.sub(r'\s+',' ',m[2]).strip(),'text_offset':[m.start(),m.end()],'published_context':text[m.start():qe]})
        out.append({'numbers':nums,'transcript':raw,'text_offset':[body_start,body_end],'questions':question_rows})
    for i,(start,body_start) in enumerate(headers):
        finish=headers[i+1][0] if i+1<len(headers) else end
        span=text[body_start:finish];rng=RANGE.search(span)
        if rng:continue # handled above for ranges before or after the script
        qs=safe_prompts(span)
        nums=sorted({int(m[1]) for m in qs if 1<=int(m[1])<=25})
        if not nums or min(nums)<1 or max(nums)>25: continue
        if nums!=list(range(min(nums),max(nums)+1)):continue
        body_end=qs[0].start();raw=span[:body_end].strip()
        if len(re.findall(r'[A-Za-z]+',raw))<45: continue
        question_rows=[]
        for j,m in enumerate(qs):
            n=int(m[1])
            if n in nums: question_rows.append({'number':n,'text':re.sub(r'\s+',' ',m[2]).strip(),'text_offset':[body_start+m.start(),body_start+m.end()],'published_context':span[m.start():qs[j+1].start() if j+1<len(qs) else len(span)]})
        out.append({'numbers':nums,'transcript':raw,'text_offset':[body_start,body_start+body_end],'questions':question_rows})
    return out

def exact_original_option_binding(question,text):
    opts=question.get('content',{}).get('options') or {}
    if set(opts)!=set('ABCD') or any(len(normalized(v))<3 for v in opts.values()):return None
    matches=[]
    for n,block,start,end in question_blocks(text):
        if n!=question['extra']['number']:continue
        raw=normalized(block)
        if all(normalized(value) in raw for value in opts.values()):matches.append((start,end))
    return matches[0] if len(matches)==1 else None

def source_ref(path,root,offsets,start,end,n=None,role='listening_transcript'):
    ref=ref_for(path,root,offsets,start,end,n);ref['role']=role
    return ref

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--src',required=True);ap.add_argument('--kb',required=True);ap.add_argument('--audit-only',action='store_true');args=ap.parse_args(argv)
    src,kb=Path(args.src).resolve(),Path(args.kb).resolve();root=kb.parents[1]
    audit_path=kb/'manifest/source_transcript_audit.jsonl';old={r['path']:r for r in load_jsonl(audit_path)}
    paths=sorted({p for base in (src,kb/'scripts/_staging') for p in base.rglob('*') if p.suffix.lower() in ('.pdf','.docx')})
    audit=[]
    for path in paths:
        rel=path.relative_to(root).as_posix();stat=path.stat();cached=old.get(rel)
        if cached and cached.get('status')!='read_error' and cached.get('size')==stat.st_size and cached.get('mtime_ns')==stat.st_mtime_ns and (path.suffix.lower()=='.pdf' or cached.get('docx_reader_version')==2) and (cached.get('schema_version')==4 or not cached.get('listening_markers') and path.suffix.lower()=='.pdf'):
            cached['schema_version']=4;audit.append(cached);continue
        row={'path':rel,'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'schema_version':4,'docx_reader_version':2 if path.suffix.lower()=='.docx' else None,'groups':[]}
        try:text,offsets=read_listening_source(path)
        except Exception as e:row.update(status='read_error',error=str(e));audit.append(row);continue
        row['text_chars']=len(text.strip());row['listening_markers']=len(re.findall(r'听力原文|Listening\s+Comprehension|News\s+Report|Conversation\s+(?:One|Two)',text,re.I))
        latin=len(re.findall(r'[A-Za-z]',text));extended=len(re.findall(r'[\u0080-\u024f]',text))
        row['status']='needs_ocr_or_text_layer_repair' if len(text.strip())<80 or extended>max(40,latin//6) else 'text_extracted_no_bounded_listening_group'
        for meta,begin,finish in regions(path,text):
            for group in extract_groups(text[begin:finish],dedicated='听力原文' in path.name):
                a,b=group['text_offset'];group['source']=source_ref(path,root,offsets,begin+a,begin+b)
                group['meta']=list(meta)
                for q in group['questions']:
                    a,b=q.pop('text_offset');q['source']=source_ref(path,root,offsets,begin+a,begin+b,q['number'],'spoken_question')
                row['groups'].append(group)
        if row['groups']:row['status']='bounded_listening_groups_extracted'
        audit.append(row)
    audit_path.write_text('\n'.join(jsonl_dumps(r) for r in audit)+'\n',encoding='utf-8')
    report={'audited_files':len(audit),'by_status':dict(Counter(r['status'] for r in audit)),'source_groups':sum(len(r['groups']) for r in audit),'published_spoken_questions':sum(len(g['questions']) for r in audit for g in r['groups'])}
    if args.audit_only:
        print(json.dumps(report,ensure_ascii=False));return
    originals={};qfiles={};qmap=defaultdict(list)
    for path in sorted((kb/'questions').rglob('*.jsonl')):
        rows=load_jsonl(path);qfiles[path]=rows
        for q in rows:
            if q['module']!='听力理解':continue
            match=re.fullmatch(r'cet[46]-(\d{4}-\d{2})-p(\d+)-listening-(\d+)',q['question_id'])
            if match:qmap[(q['exam'],match[1],int(match[2]),int(match[3]))].append(q)
    resources=[];candidates=defaultdict(list);bindings=Counter()
    for row in audit:
        for group in row['groups']:
            exam,ym,paper=group['meta'];prefix='cet4' if exam=='CET-4' else 'cet6'
            digest=hashlib.sha256(normalized(group['transcript']).encode()).hexdigest()[:12]
            rid=f"{prefix}-{ym}-p{paper}-listening-transcript-{group['numbers'][0]}-{group['numbers'][-1]}-{digest}"
            resource={'resource_id':rid,'exam':exam,'module':'听力理解','kind':'listening_transcript','text':group['transcript'],
                      'knowledge_node_ids':[prefix+'.listen.gist',prefix+'.listen.detail',prefix+'.listen.infer'],'ability_ids':[],
                      'source':{'files':[group['source']]},'extra':{'question_numbers':group['numbers'],'year':ym,'paper':paper,
                      'spoken_question_candidates':group['questions'],'extraction_method':'explicit_listening_section_group_and_question_range','extraction_version':4,'review_status':'source_extracted_pending_expert_review'}}
            resources.append(resource)
            for spoken in group['questions']:
                targets=qmap[(exam,ym,paper,spoken['number'])]
                if len(targets)!=1:bindings['no_unique_existing_question']+=1;continue
                q=targets[0];bound=None
                opts=q.get('content',{}).get('options') or {}
                published=normalized(group['transcript']+' '+spoken.get('published_context',''))
                anchors=[v for v in opts.values() if len(normalized(v))>=15 and normalized(v) in published]
                if not anchors:bindings['no_complete_option_anchor_in_published_question_or_script']+=1;continue
                for source in q.get('source',{}).get('files',[]):
                    rawpath=source.get('path')
                    if source.get('role')!='original_content' or not rawpath:continue
                    if rawpath not in originals:
                        try: originals[rawpath]=read_source(root/rawpath)
                        except Exception: originals[rawpath]=('',[])
                    text,offsets=originals[rawpath];anchor=exact_original_option_binding(q,text)
                    if anchor:
                        bound=source_ref(root/rawpath,root,offsets,*anchor,spoken['number'],'original_options_identity');break
                if not bound:bindings['four_original_options_identity_not_established']+=1;continue
                candidates[q['question_id']].append({'text':spoken['text'],'source':spoken['source'],'transcript_resource_id':rid,
                    'extraction_version':4,
                    'binding_evidence':{'method':'explicit_volume_group_range_question_number_exact_complete_option_in_published_script_and_four_options_in_independent_original_question','published_option_anchors':anchors,'original_options_source':bound,'review_status':'pending_subject_expert'}})
    restored=0
    for rows in qfiles.values():
        for q in rows:
            items=candidates.get(q['question_id'],[])
            extra=q['extra'];old_binding=extra.get('spoken_question_source')
            if old_binding and old_binding.get('extraction_version')!=4 and not any(normalized(x['text'])==normalized(old_binding.get('text')) for x in items) and extra.get('content_review',{}).get('expert_review',{}).get('status')!='approved':
                history=extra.setdefault('spoken_question_binding_history',[])
                previous=dict(old_binding,withdrawal_reason='superseded_PDF_text_order_binding_not_reconfirmed_by_current_extraction')
                if previous not in history:history.append(previous)
                if normalized(q['content'].get('stem'))==normalized(old_binding.get('text')):q['content']['stem']=None
                extra.pop('spoken_question_source',None);extra['listening_transcript_ids']=[]
                bindings['previous_automatic_bindings_quarantined']+=1
            if not items:continue
            saved=extra.setdefault('spoken_question_candidates',[])
            saved.extend(x for x in items if x not in saved)
            keys={normalized(x['text']) for x in items}
            if len(keys)!=1:bindings['conflicting_spoken_question_texts']+=1;continue
            chosen=items[0]
            if not q['content'].get('stem'):
                q['content']['stem']=chosen['text'];restored+=1
            if normalized(q['content']['stem'])!=normalized(chosen['text']):continue
            extra['spoken_question_source']=chosen
            extra['listening_transcript_ids']=list(dict.fromkeys(x['transcript_resource_id'] for x in items))
            availability=extra.setdefault('question_prompt_availability',{})
            availability.update({'delivery':'spoken_in_audio','printed_stem':False,'transcript_status':'source_extracted_pending_expert_review',
                'individual_segment_status':'pending_time_alignment','status':'spoken_question_text_and_group_transcript_restored_pending_review'})
    for path,rows in qfiles.items():path.write_text('\n'.join(jsonl_dumps(q) for q in rows)+'\n',encoding='utf-8')
    merged=merge_jsonl(kb/'listening/transcripts.jsonl',resources);current={r['resource_id']:r for r in resources}
    for r in merged:
        if r['resource_id'] in current:
            extra=r.setdefault('extra',{});extra['extraction_version']=4;extra['extraction_status']='current_source_extraction_pending_expert_review'
            extra['spoken_question_candidates']=current[r['resource_id']]['extra']['spoken_question_candidates']
        elif r.get('extra',{}).get('extraction_method')=='explicit_listening_section_group_and_question_range':
            r['extra']['extraction_status']='superseded_text_order_retained_for_audit';r['extra']['active']=False
    (kb/'listening/transcripts.jsonl').write_text('\n'.join(jsonl_dumps(r) for r in merged)+'\n',encoding='utf-8')
    report.update(restored_spoken_questions=restored,bound_question_records=len(candidates),binding_gaps=dict(bindings),transcript_resources=len(load_jsonl(kb/'listening/transcripts.jsonl')))
    (kb/'manifest/listening_recovery_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
