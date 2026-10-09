"""Lossless incremental writes shared by CET builders."""
import copy, hashlib, json, re
from pathlib import Path

def load_jsonl(path):
    return [json.loads(l) for l in path.read_text('utf-8').split('\n') if l.strip()] if path.exists() else []

def jsonl_dumps(row):
    # Unicode paragraph separators occur in damaged PDF fonts; escape them so
    # every JSONL consumer (including Python splitlines) sees one physical row.
    return json.dumps(row,ensure_ascii=False).replace('\x85','\\u0085').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

def canonical_id(row):
    if row.get('src') and row.get('dst'):
        relation=row.get('proposed_rel') if row.get('rel')=='prerequisite_candidate' else row.get('rel')
        return f"{row['src']}|{relation}|{row['dst']}"
    if row.get('question_id') or row.get('resource_id') or row.get('paper_id'):
        return row.get('question_id') or row.get('resource_id') or row.get('paper_id')
    s = row.get('id', '')
    m = re.fullmatch(r'(cet[46])\.([lr])\.(\d{4}-\d{2})_p(\d)\.q(\d+)', s)
    if m: return f"{m[1]}-{m[3]}-p{m[4]}-{'listening' if m[2]=='l' else 'reading'}-{m[5]}"
    m = re.fullmatch(r'(cet[46])\.([wt])\.(\d{4}-\d{2})_p(\d)', s)
    if m: return f"{m[1]}-{m[3]}-p{m[4]}-{'writing' if m[2]=='w' else 'translation'}-1"
    m = re.fullmatch(r'(cet[46])\.r\.(\d{4}-\d{2})[_-]p(\d)\.(ca|cb|c\d)', s)
    if m: return f"{m[1]}-{m[2]}-p{m[3]}-reading-{ {'ca':'cloze','cb':'matching'}.get(m[4],m[4]) }"
    m = re.fullmatch(r'(cet[46])\.(\d{4}-\d{2})_p(\d)', s)
    if m: return f'{m[1]}-{m[2]}-p{m[3]}'
    return s

def fill_missing(old, fresh):
    """Recursive merge. A generator cannot erase saved review/evidence/extensions."""
    out = copy.deepcopy(old)
    for key, value in fresh.items():
        if key not in out or out[key] is None or out[key] == '' or out[key] == []:
            out[key] = copy.deepcopy(value)
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = fill_missing(out[key], value)
        elif key in ('files','reference_candidates','content_variants') and isinstance(out[key],list) and isinstance(value,list):
            out[key]+=copy.deepcopy([v for v in value if v not in out[key]])
    return out

def approved_by_human(row):
    """没有审核人或证据的 approved 只是脚本自评，不能阻止重跑把它降回候选。"""
    return bool(row.get('reviewed_by') or row.get('reviewer') or row.get('evidence') or (row.get('prerequisite_review') or {}).get('reviewed_by'))

def compatible_fresh(old, fresh):
    if old.get('rel')=='prereq_of' and old.get('review_status')=='approved' and approved_by_human(old) and fresh.get('rel')=='prerequisite_candidate':
        return {k:v for k,v in fresh.items() if k not in ('rel','proposed_rel','active','review_status')}
    if old.get('prerequisite_review',{}).get('status')=='approved' and approved_by_human(old) and 'prerequisite_review' in fresh:
        fresh={k:v for k,v in fresh.items() if k!='prerequisite_review'}
    if 'question_id' in old and 'id' in fresh:
        extra={k: v for k,v in fresh.items() if k not in ('id','exam','module','question_type','source','stem','options','answer','knowledge_nodes','difficulty','analysis','text')}
        if fresh.get('module') in ('听力','听力理解'):
            if extra.get('passage_id'): extra['_legacy_listening_group_reference']=extra['passage_id']
            extra.pop('passage_id',None)
        elif extra.get('passage_id'):
            extra['passage_id']=canonical_id({'id':extra['passage_id']})
            if old.get('extra', {}).get('passage_binding', {}).get('status', '').startswith('quarantined_'):
                # Old parser output cannot reactivate a link withdrawn after a
                # full source identity check. The reconciler owns its recovery.
                extra.pop('passage_id', None)
        return {'content': {k: fresh.get(k) for k in ('stem','options','answer')},
                'source': fresh.get('source', {}),
                'extra': extra}
    if 'resource_id' in old and 'id' in fresh:
        return {'source': fresh.get('source', {}),'text':fresh.get('text'),
                'extra': {k: v for k,v in fresh.items() if k not in ('id','source','exam','year','paper','review','text')}}
    if 'paper_id' in old and 'id' in fresh:
        return {k:v for k,v in fresh.items() if k!='id'}
    return fresh

def merge_jsonl(path, fresh):
    old = load_jsonl(path)
    out, positions = list(old), {canonical_id(r): i for i,r in enumerate(old)}
    for row in fresh:
        key = canonical_id(row)
        if key in positions:
            i=positions[key];previous=out[i];incoming=compatible_fresh(previous,row)
            out[i]=fill_missing(previous,incoming)
            if row.get('option_parse_method')=='exact_original_word_question_number_and_four_options' and previous.get('extra',{}).get('content_review',{}).get('expert_review',{}).get('status')!='approved':
                content=out[i].setdefault('content',{}) if 'question_id' in out[i] else out[i]
                old_content=previous.get('content',previous);old_stem=old_content.get('stem') or '';new_stem=row.get('stem') or ''
                old_options=old_content.get('options') or {}
                if not new_stem and previous.get('extra',{}).get('spoken_question_source') and old_options==row['options']:
                    # A printed listening sheet legitimately contains only options.
                    # Its empty stem cannot erase a separately source-bound oral prompt.
                    new_stem=old_stem
                if old_stem!=new_stem or old_options!=row['options']:
                    extra=out[i].setdefault('extra',{}) if 'question_id' in out[i] else out[i]
                    entry={'content':copy.deepcopy(old_content),'analysis':copy.deepcopy(previous.get('analysis')),'reason':'question_identity_reconstructed_from_original_Word_numbering_and_options','source':copy.deepcopy(row.get('source',{}))}
                    history=extra.setdefault('question_parse_history',[])
                    if entry not in history:history.append(entry)
                    identity_changed=bool(old_options) and any(old_options.get(k)!=v for k,v in row['options'].items() if k in old_options)
                    if identity_changed:
                        if content.get('answer'):
                            ah=extra.setdefault('answer_history',[]);ae={'answer':content['answer'],'reason':'original_question_identity_corrected_requires_source_rebinding','status':'quarantined'}
                            if ae not in ah:ah.append(ae)
                        content['answer']=None;out[i]['analysis']={'raw':None,'key_info':None,'option_compare':None,'trace_back':None,'status':'requires_source_rebinding_after_question_identity_repair'}
                        extra['answer_status']='requires_source_rebinding_after_question_identity_repair'
                    content['options']=copy.deepcopy(row['options']);content['stem']=new_stem or None
                    extra['option_parse_method']=row['option_parse_method']
            # A complete explicit two-column layout is reproducible source evidence.
            # Preserve the previous parse before replacing its missing / concatenated options.
            if row.get('option_parse_method')=='explicit_two_column_C_D_sequence':
                content=out[i].setdefault('content',{}) if 'question_id' in out[i] else out[i]
                old_options=(previous.get('content',previous)).get('options',{})
                if old_options!=row.get('options'):
                    extra=out[i].setdefault('extra',{}) if 'question_id' in out[i] else out[i]
                    entry={'options':copy.deepcopy(old_options),'reason':'replaced_by_complete_explicit_two_column_layout','source':copy.deepcopy(row.get('source',{}))}
                    history=extra.setdefault('option_history',[])
                    if entry not in history: history.append(entry)
                    content['options']=copy.deepcopy(row['options'])
        else:
            positions[key]=len(out);out.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(jsonl_dumps(r) for r in out)+'\n',encoding='utf-8')
    return out

def dedupe_resources(rows):
    """Collapse exact duplicates; distinct wording gets a stable variant ID."""
    out, seen, id_seen = [], set(), set()
    for row in rows:
        rid = row.get('resource_id') or row.get('id')
        # Source and content extensions are preserved in semantic variants as well.
        fingerprint = json.dumps({k:v for k,v in row.items() if k not in ('resource_id','id')},ensure_ascii=False,sort_keys=True)
        key=(rid,fingerprint)
        if key in seen: continue
        seen.add(key)
        if rid in id_seen:
            row=copy.deepcopy(row)
            row['resource_id' if 'resource_id' in row else 'id']=rid+'-variant-'+hashlib.sha256(fingerprint.encode()).hexdigest()[:10]
            row.setdefault('extra',{})['variant_of']=rid
            row['extra']['variant_status']='distinct_source_text_pending_review'
        id_seen.add(row.get('resource_id') or row.get('id'));out.append(row)
    return out
