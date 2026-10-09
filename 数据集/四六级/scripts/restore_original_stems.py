"""Restore empty statements/questions only from unique original numbered blocks."""
import json,re,sys
from collections import Counter
from pathlib import Path
from cet_common import load_jsonl,jsonl_dumps
from fill_answers import read_source,question_blocks,normalized,ref_for,CN

KB=Path(__file__).resolve().parents[1];ROOT=KB.parents[1]
TITLE=re.compile(r'(?im)^\s*(20\d{2})\s*年\s*(\d{1,2})\s*月(?:大学)?(?:英语)?(四级|六级)(?:考试)?真题[^\n]{0,12}?(?:第\s*([一二三1-3])\s*套|卷\s*([一二三1-3]))')

def source_regions(q,text):
    headers=list(TITLE.finditer(text))
    if len(headers)<=1:return [(0,len(text))]
    result=[]
    for i,m in enumerate(headers):
        exam='CET-4' if m[3]=='四级' else 'CET-6';number=m[4] or m[5];paper=CN.get(number,int(number) if number.isdigit() else 0)
        ym=f'{m[1]}-{int(m[2]):02d}'
        if exam==q['exam'] and ym==q['source']['year'] and paper=={'第一套':1,'第二套':2,'第三套':3}.get(q['source']['paper']):result.append((m.end(),headers[i+1].start() if i+1<len(headers) else len(text)))
    return result

def original_blocks(text,kind):
    if kind=='长篇阅读':return list(question_blocks(text))
    # Original converted Word lines can join the next explicit question onto D).
    # The numeric range and subsequent complete options bound each question.
    marks=list(re.finditer(r'(?<!\S)(4[6-9]|5[0-5])\s*[.、．]\s*(?=[A-Za-z])',text));result=[]
    for i,m in enumerate(marks):
        end=marks[i+1].start() if i+1<len(marks) else len(text);block=text[m.end():end]
        stop=re.search(r'(?im)^\s*(?:Passage\s+(?:One|Two)|Questions?\s+\d+|Part\s*(?:IV|Ⅳ))',block)
        if stop:end=m.end()+stop.start();block=block[:stop.start()]
        result.append((int(m[1]),block.strip(),m.start(),end))
    return result

def original_stem(q,block):
    if q['question_type']=='长篇阅读':
        # Section/next-number bounds are supplied by question_blocks. Refuse
        # oversized fragments instead of truncating a following article.
        lines=[l.strip() for l in block.split('\n') if l.strip() and not re.fullmatch(r'\d{1,3}',l.strip())]
        value=' '.join(lines)
        if 25<=len(value)<=600 and len(re.findall(r'[A-Za-z]{2,}',value))>=5:return value
    elif q['question_type']=='仔细阅读':
        option=re.search(r'(?:^|\n)\s*A[)）.．]\s*',block)
        value=block[:option.start()].strip() if option else block.split('?',1)[0]+'?' if '?' in block else None
        if value and 10<=len(value)<=600 and len(re.findall(r'[A-Za-z]+',value))>=4 and (value.endswith('?') or value.endswith('.') or '____' in value):return re.sub(r'\s+',' ',value).strip()
    return None

def main():
    cache={};report=Counter();gaps=[]
    for path in sorted((KB/'questions').rglob('*.jsonl')):
        rows=load_jsonl(path)
        for q in rows:
            if q['question_type'] not in ('长篇阅读','仔细阅读') or q['content'].get('stem'):continue
            n=q['extra']['number'];candidates=[]
            for source in q.get('source',{}).get('files',[]):
                name=source.get('path')
                if source.get('role')!='original_content' or not name:continue
                if name not in cache:
                    try:cache[name]=read_source(ROOT/name)
                    except Exception:cache[name]=('',[])
                text,offsets=cache[name]
                matches=[(block,begin+a,begin+b) for begin,finish in source_regions(q,text) for num,block,a,b in original_blocks(text[begin:finish],q['question_type']) if num==n and original_stem(q,block)]
                if len(matches)!=1:continue
                block,a,b=matches[0];stem=original_stem(q,block)
                if stem:candidates.append({'text':stem,'source':dict(ref_for(ROOT/name,ROOT,offsets,a,b,n),role='original_task_prompt'),'method':'unique_explicit_original_question_number_or_Word_numbering_XML_and_complete_bounded_statement'})
            keys={normalized(c['text']) for c in candidates}
            if len(keys)!=1:
                gaps.append({'question_id':q['question_id'],'status':'original_prompt_extraction_failure_or_no_unique_boundary','candidate_count':len(candidates)});continue
            q['content']['stem']=candidates[0]['text'];q['extra']['original_prompt_recovery']=candidates[0];report[q['question_type']]+=1
        path.write_text('\n'.join(jsonl_dumps(q) for q in rows)+'\n',encoding='utf-8')
    result={'restored':dict(report),'remaining_empty_prompt_records':gaps}
    (KB/'manifest/original_stem_recovery_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'restored':dict(report),'remaining':len(gaps)},ensure_ascii=False))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
