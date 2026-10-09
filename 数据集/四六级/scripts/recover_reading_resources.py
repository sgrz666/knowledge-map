"""Recover explicit original word banks / paragraph labels without inference."""
import json,re,sys
from collections import Counter
from pathlib import Path
from cet_common import load_jsonl,jsonl_dumps
from fill_answers import read_source,ref_for,normalized

KB=Path(__file__).resolve().parents[1];ROOT=KB.parents[1]
LABEL=re.compile(r'(?m)^\s*(?:\[([A-Z])\]|([A-Z])[)）])\s*')

def section(text,kind):
    read=re.search(r'Reading\s+Comprehension',text,re.I)
    if not read:return None
    letter='A' if kind=='cloze' else 'B'
    start=re.search(r'(?im)^\s*Section\s+'+letter+r'\b',text[read.end():])
    if not start:return None
    a=read.end()+start.end()
    end=re.search(r'(?im)^\s*(?:Section\s+[BC]|Part\s*(?:IV|Ⅳ)\b)',text[a:])
    b=a+end.start() if end else len(text)
    return a,b,text[a:b]

def explicit_bank(text):
    first=re.search(r'(?m)^\s*(?:A[)）.．]|\[A\])\s*',text)
    if not first:return None
    text=text[first.start():]
    marks=list(re.finditer(r'(?:^|\s)(?:\[([A-Oa-o])\]|([A-Oa-o])[)）.．]|([A-O])(?=\s+[A-Za-z-]+\s*(?:[A-O][)）.．]|\n|$)))\s*([A-Za-z][A-Za-z-]*)(?=\s*(?:[A-Oa-o][)）.．]|\[[A-Oa-o]\]|[A-O]\s+[A-Za-z]|\n|$))',text))
    values={}
    for m in marks:
        letter=(m[1] or m[2] or m[3]).upper();value=m[4].strip()
        if letter in values and values[letter]!=value:return None
        values[letter]=value
    return values if set(values)==set('ABCDEFGHIJKLMNO') else None

def explicit_paragraphs(text):
    stop=re.search(r'(?m)^\s*3[6-9]\s*[.、．]\s*[A-Za-z]',text)
    body=text[:stop.start()] if stop else text
    marks=list(LABEL.finditer(body));letters=[m[1] or m[2] for m in marks]
    if len(letters)<3 or letters!=[chr(65+i) for i in range(len(letters))]:return None
    result=[]
    for i,m in enumerate(marks):
        value=re.sub(r'\s+',' ',body[m.end():marks[i+1].start() if i+1<len(marks) else len(body)]).strip()
        if len(re.findall(r'[A-Za-z]+',value))<20:return None
        result.append({'letter':letters[i],'text':value})
    return result

def main():
    path=KB/'passages/reading.jsonl';rows=load_jsonl(path);cache={};report=Counter();gaps=[]
    for r in rows:
        kind=r.get('kind');field='word_bank' if kind=='cloze' else 'paragraphs'
        if kind not in ('cloze','matching'):continue
        current=r['extra'].get(field)
        if current and (kind!='cloze' or set(current)==set('ABCDEFGHIJKLMNO')):continue
        candidates=[]
        for source in r.get('source',{}).get('files',[]):
            name=source.get('path')
            if source.get('role')!='original_content' or not name:continue
            if name not in cache:
                try:cache[name]=read_source(ROOT/name)
                except Exception:cache[name]=('',[])
            text,offsets=cache[name];span=section(text,kind)
            if not span:continue
            a,b,raw=span;value=explicit_bank(raw) if kind=='cloze' else explicit_paragraphs(raw)
            if value:candidates.append({'value':value,'source':dict(ref_for(ROOT/name,ROOT,offsets,a,b,None),role='original_'+field),'method':'explicit_original_reading_section_and_complete_letter_labels'})
        keys={json.dumps(c['value'],sort_keys=True) for c in candidates}
        if len(keys)!=1:
            entry={'resource_id':r['resource_id'],'field':field,'status':'original_text_does_not_supply_unique_complete_label_sequence','source_paths':[s['path'] for s in r.get('source',{}).get('files',[]) if s.get('role')=='original_content']}
            r['extra'][field+'_availability']=entry;gaps.append(entry);continue
        ex=r['extra']
        if current:
            history=ex.setdefault(field+'_parse_history',[])
            item={'value':current,'reason':'replaced_by_complete_explicit_original_labels'}
            if item not in history:history.append(item)
        ex[field]=candidates[0]['value'];ex[field+'_recovery']=candidates[0];ex[field+'_availability']={'status':'source_extracted_pending_expert_review'}
        if candidates[0]['source'] not in r['source']['files']:r['source']['files'].append(candidates[0]['source'])
        report[field]+=1
    path.write_text('\n'.join(jsonl_dumps(r) for r in rows)+'\n',encoding='utf-8')
    result={'restored':dict(report),'remaining':gaps}
    (KB/'manifest/reading_resource_recovery_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'restored':dict(report),'remaining_resources':len(gaps)},ensure_ascii=False))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
