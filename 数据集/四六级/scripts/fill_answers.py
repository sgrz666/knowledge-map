"""Extract source keys and per-question explanations; conflicts stay pending."""
import argparse, json, re, sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
import pymupdf as fitz
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from cet_common import jsonl_dumps, load_jsonl

if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
fitz.TOOLS.mupdf_display_errors(False)
CN = {'一': 1, '二': 2, '三': 3}
DATE = re.compile(r'(20\d{2})[年.\s-]*([01]?\d)[月.\s-]?')
PAPER = re.compile(r'(?:第|卷)?\s*([一二三1-3])\s*套')
QSTART = re.compile(r'(?m)^[^\S\n]*(\d{1,2})\s*[.、．]\s*(?=[A-Za-z【\[])')
ANS_PATTERNS = [
 re.compile(r'【?答案】?\s*[:：]?\s*为?\s*([A-O])(?![A-Za-z])'),
 re.compile(r'(?:正确答案|答案)\s*(?:为|是|[:：])\s*([A-O])(?![A-Za-z])'),
 re.compile(r'(?:故|应|因此|所以)\s*选\s*([A-O])(?![A-Za-z])'),
 re.compile(r'选项\s*([A-D])\s*(?:为|是)\s*正确答案'),
 re.compile(r'([A-D])\s*项(?:与(?:(?!不|未|无|非)[^。\n]){0,45}相符|(?:为|是)正确(?:答案|选项))'),
]

def file_meta(path):
 n=path.name; dm,pm=DATE.search(n),PAPER.search(n)
 if not pm: pm=re.search(r'卷\s*([一二三1-3])',n)
 if not dm or not pm: return None
 exam='CET-4' if re.search(r'四级|4级|CET4',n,re.I) else ('CET-6' if re.search(r'六级|6级|CET6',n,re.I) else None)
 if not exam or not 1<=int(dm[2])<=12: return None
 return exam,f'{dm[1]}-{int(dm[2]):02d}',CN.get(pm[1],int(pm[1]) if pm[1].isdigit() else 0)

def read_source(path):
 """Return text with page / DOCX body and table-row offset locators."""
 if path.suffix.lower()=='.pdf':
  with fitz.open(path) as doc: units=[(pg.get_text(sort=True),{'page':i+1}) for i,pg in enumerate(doc)]
 else:
  from docx_source import read_docx_units
  units=read_docx_units(path)
 pieces,offsets,pos=[],[],0
 for value,loc in units:
  pieces.append(value);offsets.append((pos,pos+len(value),loc));pos+=len(value)+1
 return '\n'.join(pieces),offsets

def pdf_text(path): return read_source(path)[0]
def docx_text(path): return read_source(path)[0]

def question_blocks(text):
 anchors=[m for m in QSTART.finditer(text) if 1<=int(m[1])<=55]
 for i,m in enumerate(anchors):
  end=anchors[i+1].start() if i+1<len(anchors) else len(text);block=text[m.end():end]
  stop=re.search(r'(?im)^\s*(?:Part\s*[IVX]+\b|Section\s*[ABC]\b|Questions?\s+\d+|(?:News Report|Conversation|Passage|Lecture)\s+(?:One|Two|Three)\b|【听力原文】)',block)
  if stop: end=m.end()+stop.start();block=block[:stop.start()]
  yield int(m[1]),block.strip(),m.start(),end

def block_answers(block):
 result=set()
 first=re.match(r'^([A-O])(?:[)）])?(?=\s*(?:$|[【\[]|[\u4e00-\u9fff]))',block)
 if first: result.add(first[1])
 for pat in ANS_PATTERNS: result.update(m[1] for m in pat.finditer(block))
 return result

def extract_answers(text):
 found=defaultdict(set)
 for n,block,_,_ in question_blocks(text): found[n].update(block_answers(block))
 conflicts=[(n,sorted(v)) for n,v in sorted(found.items()) if len(v)>1]
 return {n:next(iter(v)) for n,v in found.items() if len(v)==1},conflicts

def explanation(block):
 label=re.search(r'(?:【|\[)?\s*(?:解析|详解|解\s*析)\s*(?:】|\])?\s*[:：]?',block)
 raw=block[label.end():].strip() if label else block
 if not label:
  conclusion=re.search(r'对话(?:开头|中|最后)|(?:文章|文中|原文|讲话|讲座|新闻|材料)(?:开头|中|提到|指出)|由此可知|故选|因此答案|根据',raw)
  if not conclusion: return None
  raw=raw[conclusion.start():]
 cjk=len(re.findall(r'[\u4e00-\u9fff]',raw));weird=len(re.findall(r'[\u0080-\u024f\x00-\x08\x0b\x0e-\x1f]',raw))
 if cjk<12 or weird>max(8,cjk//2): return None
 return raw

def structured_explanation(block,raw):
 """Only reorganize published sentences, never generate missing reasoning."""
 hint=re.search(r'【(?:做题提示|听前预测|题目定位|解题思路)】\s*(.*?)(?=【[^】]+】|$)',block,re.S)
 sentences=[s.strip() for s in re.split(r'(?<=[。；])',raw) if s.strip()]
 comparisons=[s for s in sentences if re.search(r'排除|选项|[A-O]\s*(?:项|和\s*[A-O]|、\s*[A-O])',s)]
 return {'key_info':hint[1].strip() if hint else None,
         'option_compare':' '.join(comparisons) if comparisons else None}

def ref_for(path,root,offsets,start,end,n):
 locs=[loc for a,b,loc in offsets if b>=start and a<=end]
 return {'path':path.relative_to(root).as_posix(),'role':'answer_analysis','locator':{'question_number':n,'text_offset':[start,end],'units':locs}}

def normalized(s): return re.sub(r'[^a-z0-9]','',(s or '').lower())

def valid_key(r,key):
 c=r.get('content') or r
 if r.get('question_type') in ('选词填空','长篇阅读'):
  opts=c.get('options') or {}
  # These types may carry their choices in the referenced passage, not per item.
  return key in opts if opts else key in 'ABCDEFGHIJKLMNO'
 return key in 'ABCD' and key in (c.get('options') or {})

def source_identity_matches(row,item):
 c=row.get('content') or row;stem=c.get('stem') or '';body=item.get('block') or '';target=normalized(stem);raw=normalized(body)
 if len(target)>=8 and target in raw:return True
 stop={'what','which','when','where','does','author','about','according','report','news','passage','that','they','their','them','this','these','those','have','will','would','could','should','from','with','were','been','most','likely','mainly','following','woman','women','people','some','such','into','says','said','suggest','imply','know','learn','infer','give','gives','achieve'}
 terms={w.lower() for w in re.findall(r'[A-Za-z]{4,}',stem) if w.lower() not in stop}
 if len(terms)>=2:
  hits=sum(normalized(w) in raw for w in terms)
  if hits>=2 and hits/len(terms)>=.7:return True
 options=[normalized(v) for v in (c.get('options') or {}).values() if len(normalized(v))>=12]
 return sum(v in raw for v in options)>=2

def source_candidates(src,stage,root):
 paths=sorted(set(list(stage.rglob('*.pdf'))+list(stage.rglob('*.docx'))+[p for p in src.rglob('*') if p.suffix.lower() in ('.pdf','.docx') and ('解析' in p.name or '答案' in p.name)]))
 candidates,diagnostics=defaultdict(list),[]
 for path in paths:
  meta=file_meta(path);dm=DATE.search(path.name)
  if not dm: continue
  try: text,offsets=read_source(path)
  except Exception as e:
   diagnostics.append({'path':path.relative_to(root).as_posix(),'status':'read_error','error':str(e)});continue
  if len(text.strip())<80:
   diagnostics.append({'path':path.relative_to(root).as_posix(),'status':'needs_ocr','text_chars':len(text.strip())});continue
  segs=[]
  if '全' in path.name and re.search(r'全\s*[二三23]\s*套',path.name):
   hdr=list(PAPER.finditer(text));exam='CET-4' if '四级' in path.name else 'CET-6';ym=f'{dm[1]}-{int(dm[2]):02d}'
   for i,h in enumerate(hdr):
    pnum=CN.get(h[1],int(h[1]) if h[1].isdigit() else 0)
    segs.append(((exam,ym,pnum),h.end(),hdr[i+1].start() if i+1<len(hdr) else len(text)))
  elif meta: segs=[(meta,0,len(text))]
  for key,begin,finish in segs:
   for n,block,a,b in question_blocks(text[begin:finish]):
    if '专项' in str(path) and n<26: continue
    letters=block_answers(block)
    if len(letters)!=1: continue
    candidates[(key,n)].append({'answer':next(iter(letters)),'raw':explanation(block),'block':block,'stem':block.split('\n',1)[0],'source':ref_for(path,root,offsets,begin+a,begin+b,n)})
  diagnostics.append({'path':path.relative_to(root).as_posix(),'status':'text_extracted','text_chars':len(text),'mapped_papers':len(segs)})
 return candidates,diagnostics

def fill_records(rows,meta,candidates):
 result={'new_answers':0,'new_analyses':0,'invalid_keys_quarantined':0,'conflict_answers_quarantined':0,'unsupported_auto_answers_quarantined':0,'conflicts':[]}
 for r in rows:
  c=r.setdefault('content',{}) if 'question_id' in r else r;ex=r.setdefault('extra',{}) if 'question_id' in r else r
  n=ex.get('number');old_answer=c.get('answer')
  if isinstance(r.get('analysis'),dict) and r['analysis'].get('status') in ('source_support_withdrawn_pending_review','source_conflict_pending_review'):
   quarantine_analysis(r,r['analysis']['status'])
  if old_answer and not valid_key(r,old_answer):
   history=ex.setdefault('answer_history',[]);entry={'answer':old_answer,'reason':'outside_current_option_keys','status':'quarantined'}
   if entry not in history: history.append(entry)
   c['answer']=None;result['invalid_keys_quarantined']+=1
   r.setdefault('tags',{})['审核']='needs_fix'
   ex.setdefault('review',{})['status']='needs_fix'
  proposed=[x for x in candidates.get((meta,n),[]) if valid_key(r,x['answer'])]
  items=[x for x in proposed if source_identity_matches(r,x)]
  if proposed and not items:
   saved=ex.setdefault('unbound_answer_candidates',[])
   for x in proposed:
    item={'answer':x['answer'],'source':x['source'],'reason':'question_number_alone_does_not_prove_question_identity'}
    if item not in saved:saved.append(item)
  target=normalized(c.get('stem'))
  if len(target)>20:
   items=[x for x in items if len(normalized(x['stem']))<10 or SequenceMatcher(None,target,normalized(x['stem'])).ratio()>=.55 or target in normalized(x['block'])]
  keys={x['answer'] for x in items}
  if len(keys)>1 or (keys and c.get('answer') and c['answer'] not in keys):
   result['conflicts'].append({'question_id':r.get('question_id',r.get('id')),'keys':sorted(keys),'existing_answer':c.get('answer'),'sources':[x['source'] for x in items]})
   ex['answer_candidates']=[{'answer':x['answer'],'source':x['source'],'published_explanation':x['raw']} for x in items]
   files=r.setdefault('source',{}).setdefault('files',[])
   for it in items:
    if it['source'] not in files: files.append(it['source'])
   if c.get('answer'):
    entry={'answer':c['answer'],'reason':'source_conflict','status':'quarantined','candidate_keys':sorted(keys),'sources':list(files)}
    history=ex.setdefault('answer_history',[])
    if entry not in history: history.append(entry)
    c['answer']=None;result['conflict_answers_quarantined']+=1
   ex['answer_status']='source_conflict'
   quarantine_analysis(r,'source_conflict_pending_review')
   continue
  if not items:
   if c.get('answer') and ex.get('answer_status')=='source_conflict':
    entry={'answer':c['answer'],'reason':'unresolved_historical_source_conflict','status':'quarantined','sources':r.get('source',{}).get('files',[])}
    history=ex.setdefault('answer_history',[])
    if entry not in history: history.append(entry)
    c['answer']=None;result['conflict_answers_quarantined']+=1
   if not c.get('answer') and ex.get('answer_status')=='source_conflict':
    ex['_previous_answer_status']='source_conflict'
    ex['answer_status']='historical_conflict_without_current_explicit_key_pending_review'
   if c.get('answer') and ex.get('answer_extraction',{}).get('method')=='bounded_question_block_explicit_key_or_published_conclusion' and ex.get('content_review',{}).get('expert_review',{}).get('status')!='approved':
    entry={'answer':c['answer'],'reason':'revised_extraction_rules_found_no_explicit_source_support','status':'quarantined','sources':r.get('source',{}).get('files',[])}
    history=ex.setdefault('answer_history',[])
    if entry not in history: history.append(entry)
    c['answer']=None;result['unsupported_auto_answers_quarantined']+=1
    ex['answer_status']='source_support_withdrawn_pending_review'
   quarantine_analysis(r,'source_support_withdrawn_pending_review')
   ex.setdefault('answer_status','legacy_source_pending' if c.get('answer') else 'missing_source');continue
  selected=max(items,key=lambda x:len(x['raw'] or ''))
  if not c.get('answer'): c['answer']=selected['answer'];result['new_answers']+=1
  files=r.setdefault('source',{}).setdefault('files',[])
  for it in items:
   if it['source'] not in files: files.append(it['source'])
  ex['answer_status']='source_extracted_pending_expert_review'
  ex['answer_extraction']={'method':'bounded_question_block_explicit_key_or_published_conclusion','rule_version':3,'source_count':len(items),'binding':'source_question_text_or_distinctive_terms_or_multiple_complete_options_match','expert_review':{'status':'pending','reviewer':None,'reviewed_at':None}}
  if selected['raw']:
   if 'question_id' in r:
    a=r.setdefault('analysis',{})
    if a.get('raw') and a.get('method')=='published_explanation_text_extraction' and a.get('source') not in [it['source'] for it in items]:
     quarantine_analysis(r,'prior_explanation_source_binding_not_reconfirmed');a=r['analysis']
    if not a.get('raw'):
     a.update({'raw':selected['raw'],'status':'source_extracted_pending_expert_review','method':'published_explanation_text_extraction','source':selected['source'],'trace_back':f"原始解析 {selected['source']['path']}，题号 {n}；定位见 analysis.source.locator。"});result['new_analyses']+=1
    for field,value in structured_explanation(selected['block'],selected['raw']).items():
     if value and not a.get(field): a[field]=value
   elif not r.get('analysis'): r['analysis']=selected['raw'];r['analysis_status']='source_extracted_pending_expert_review';result['new_analyses']+=1
 return result

def quarantine_analysis(row,reason):
 """Unbound automatic explanations remain auditable, never active feedback."""
 import copy
 analysis=row.get('analysis');extra=row.get('extra',{})
 if not isinstance(analysis,dict) or not analysis.get('raw') or extra.get('content_review',{}).get('expert_review',{}).get('status')=='approved':return
 if analysis.get('method')!='published_explanation_text_extraction' and analysis.get('status') not in ('source_support_withdrawn_pending_review','source_conflict_pending_review'):return
 entry={'analysis':copy.deepcopy(analysis),'reason':reason,'status':'quarantined'}
 history=extra.setdefault('analysis_history',[])
 if entry not in history:history.append(entry)
 row['analysis']={'raw':None,'key_info':None,'option_compare':None,'trace_back':None,'status':reason}

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--stage',required=True);ap.add_argument('--src',required=True);ap.add_argument('--kb',required=True);args=ap.parse_args(argv)
 src,stage,kb=map(lambda v:Path(v).resolve(),(args.src,args.stage,args.kb));root=kb.parents[1]
 candidates,diagnostics=source_candidates(src,stage,root)
 report={'method':'explicit source keys and per-question published explanations; no generated answers','papers':{},'source_diagnostics':diagnostics}
 for lv in ('cet4','cet6'):
  for path in sorted((kb/'questions'/lv).glob('*.jsonl')):
   ym,pap=path.stem.split('_p');rows=load_jsonl(path)
   report['papers'][f'{lv}/{path.name}']=fill_records(rows,('CET-4' if lv=='cet4' else 'CET-6',ym,int(pap)),candidates)
   path.write_text('\n'.join(jsonl_dumps(r) for r in rows)+'\n',encoding='utf-8')
 summary={k:sum(v[k] for v in report['papers'].values()) for k in ('new_answers','new_analyses','invalid_keys_quarantined','conflict_answers_quarantined','unsupported_auto_answers_quarantined')};summary['source_conflicts']=sum(len(v['conflicts']) for v in report['papers'].values())
 report['last_run']=summary;oldpath=kb/'manifest/answers_fill_report.json';previous=json.loads(oldpath.read_text('utf-8')) if oldpath.exists() else {}
 report['baseline']=previous.get('baseline',{'question_count':5294,'with_answer':835,'with_analysis':0})
 oldpath.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__': main()
