"""Build stable source requirement IDs and official interview scoring tables.
No network or changes outside 权威资料. IDs reuse the registry in requirements.jsonl.
"""
from __future__ import annotations
import collections, datetime, hashlib, json, re, unicodedata
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent

def atomic_write(path,text):
    temporary=path.with_name(path.name+'.tmp'); temporary.write_text(text,encoding='utf-8'); temporary.replace(path)

def norm(s): return unicodedata.normalize('NFKC',s).strip()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

class TableParser(HTMLParser):
    def __init__(self,raw):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.feed(raw)
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.row=[]
        if tag in ('td','th') and self.row is not None:
            a=dict(attrs); self.cell={'text':[],'rowspan':int(a.get('rowspan',1)),'colspan':int(a.get('colspan',1))}
    def handle_data(self,data):
        if self.cell is not None: self.cell['text'].append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.cell['text']=''.join(self.cell['text']).strip(); self.row.append(self.cell); self.cell=None
        if tag=='tr' and self.row is not None: self.rows.append(self.row); self.row=None

def cet_content(src):
    raw=(BASE/src['local_path']).read_text(encoding='utf-8-sig'); rows=TableParser(raw).rows
    output=[]; carry={}
    for rn,row in enumerate(rows,1):
        expanded={c:v[0] for c,v in carry.items() if v[1]>0}
        carry={c:(v[0],v[1]-1) for c,v in carry.items() if v[1]>1}
        col=0
        for cell in row:
            while col in expanded: col+=1
            for _ in range(cell['colspan']):
                expanded[col]=cell['text']
                if cell['rowspan']>1: carry[col]=(cell['text'],cell['rowspan']-1)
                col+=1
        if rn==1 or not expanded: continue
        vals=[expanded.get(c,'') for c in range(6)]
        content=f"{src['exam_scope'][0]}：试卷部分{vals[0]}；测试内容{vals[1]}；题型{vals[2]}；题数{vals[3]}；分值比例{vals[4]}；考试时间{vals[5]}。"
        if vals[0]=='总计': content=f"{src['exam_scope'][0]}：题数总计{vals[3]}；总分值比例{vals[4]}；总考试时间{vals[5]}。"
        output.append(entry(src,content,{'html_path':src['local_path'],'table':1,'row':rn,'headers':['试卷结构','测试内容','测试题型','题目数量','分值比例','考试时间']},'试卷结构',level=src['exam_scope'],title=f"{src['exam_scope'][0]} {vals[0]} {vals[1]} {vals[2]}"))
    return output

def entry(src,content,locator,module=None,title=None,**extra):
    return {'standard_id':src['standard_id'],'title':title or norm(content)[:100],
      'content':content,'locator':locator,'module':module,'subject':src.get('subject'),
      'level':src.get('level'),'exam_scope':src['exam_scope'],
      'mapping_status':'official_requirement_unmapped','source_verified':True,**extra}

def ntce(src,lines):
    output=[]; active=False; module='考试要求'; sub=None
    is_interview=src['kind']=='interview_outline'
    start=re.compile(r'^[二三]、(?:考试(?:模块)?内容(?:模块)?(?:与|及)要求|测试内容与要求)')
    for n,line in enumerate(lines,1):
        v=norm(line)
        heading=re.sub(r'\s+','',v)
        if start.match(heading): active=True; continue
        # Original Word headings may contain spaces or omit the Chinese numeral.
        # Test-paper tables and example questions are not general exam requirements.
        if active and re.match(r'^(?:[三四五]、)?(?:试卷结构|测试方法|评分标准|题型示例)(?:$|[（(：:])',heading): active=False
        if not active: continue
        if re.match(r'^\([一二三四五六七八九十]+\)',v) and len(v)<48:
            module=re.sub(r'^\([一二三四五六七八九十]+\)','',v); sub=None; continue
        if re.match(r'^\d+[.、]',v) and len(v)<35 and not re.search(r'[。;]|理解|掌握|了解|熟悉|能够|具有|运用|认识|分析',v):
            sub=re.sub(r'^\d+[.、]','',v); continue
        if len(v)<8: continue
        # Large compound clauses remain locatable in the unchanged source line.
        chunks=re.split(r'(?<=[；;])',line) if len(line)>140 else [line]
        for chunk in chunks:
            if len(chunk.strip())<8: continue
            output.append(entry(src,chunk.strip(),{'text_path':src['text_path'],'line_start':n,'line_end':n,'section':module,'subsection':sub},module,title=(f'{sub}：' if sub else '')+norm(chunk)[:90]))
    return output

def interview_rubrics(src):
    path=ROOT/'text'/f"{src['standard_id']}.tables.json"
    if not path.exists(): return [],[]
    tables=json.loads(path.read_text(encoding='utf-8-sig')); rules=[]; req=[]
    if isinstance(tables,dict): tables=[tables]
    for table in tables:
        cells=table['cells']; headers=[c['text'] for c in cells if c['row']==1]
        if '评分标准' not in headers: continue
        groups=collections.defaultdict(dict)
        for c in cells: groups[c['row']][c['column']]=c['text']
        project=None; weight=None
        for rn,row in sorted(groups.items()):
            if rn==1: continue
            if 2 in row: project=row[2]
            if 3 in row: weight=int(row[3]) if row[3].isdigit() else row[3]
            score=row.get(4); content=row.get(5)
            if not content: continue
            locator={'table_path':str(path.relative_to(BASE)).replace('\\','/'),'table':table['table'],'row':rn,'column':5,'section':'五、评分标准'}
            rule={'standard_id':src['standard_id'],'level':src['level'],'project':project,'weight':weight,'score':int(score) if score and score.isdigit() else score,'criterion':content,'locator':locator,'official':True}
            rules.append(rule)
            req.append(entry(src,content,locator,project,title=f'{project}评分：{content}',requirement_type='official_scoring_criterion',score=rule['score'],project_weight=weight))
    return rules,req

def cet(src,lines):
    output=[]; page=0; current_module=None; section=None; pending=[]; begin=None
    modules={'1.1':'听力','1.2':'阅读','1.3':'写作','1.4':'翻译','1.5':'口语','2.1':'四级笔试','2.2':'四级口试','3.1':'六级笔试','3.2':'六级口试','4.1':'写作评分','4.2':'翻译评分','4.3':'口语评分','5.1':'笔试成绩解释','5.2':'口试成绩解释'}
    def flush(end):
        nonlocal pending,begin
        content='\n'.join(pending).strip()
        if content and len(content)>12 and current_module:
            levels=['CET-4','CET-6']
            if '四级考试:' in norm(content) or (section and section.startswith('2.')): levels=['CET-4']
            elif '六级考试:' in norm(content) or (section and section.startswith('3.')): levels=['CET-6']
            original='\n'.join(lines[begin-1:end])
            output.append(entry(src,content,{'text_path':src['text_path'],'line_start':begin,'line_end':end,'pdf_page':page,'section':section},current_module,level=levels,title=f'{section or current_module} {norm(content)[:80]}',original_text=original,content_type='source_text_with_layout_lines_removed'))
        pending=[]; begin=None
    for n,line in enumerate(lines,1):
        v=norm(line)
        marker=re.match(r'\[\[PDF_PAGE (\d+)\]\]',v)
        if marker:
            flush(n-1); page=int(marker[1]); continue
        # Main examination explanation occupies physical PDF pages 6–18.
        if not 6<=page<=18: continue
        if not v or re.fullmatch(r'[\d\s]+',v) or '全国大学英语四、六级考试大纲' in v or len(v)<2: continue
        head=re.match(r'^(\d+\.\d+(?:\.\d+)?)\s*(.*)',v)
        if head:
            flush(n-1); section=head[1]; current_module=modules.get('.'.join(section.split('.')[:2]),current_module)
            if head[2]: pending=[line]; begin=n
            continue
        if re.match(r'^\d{2}\s',v) or re.match(r'^[四四六]级考试:',v) or re.match(r'^\d+[)]',v) or re.match(r'^[A-D][.．]',v): flush(n-1)
        if begin is None: begin=n
        pending.append(line)
    flush(len(lines))
    output=[r for r in output if not cet_template(r['content'])]
    # Keep the already published valid IDs and locators. Add complete numbered
    # skills separately: very short Chinese clauses are still real requirements.
    existing={(r['content'],json.dumps(r['locator'],sort_keys=True)):r for r in output}
    for skill in cet_skills(src,lines):
        key=(skill['content'],json.dumps(skill['locator'],sort_keys=True))
        if key in existing:
            existing[key].update({k:skill[k] for k in ('skill_code','skill_group','requirement_type')})
        else: output.append(skill)
    return output

def cet_template(content):
    useful=[]
    for line in content.splitlines():
        compact=re.sub(r'\s+','',norm(line))
        if not compact or re.fullmatch(r'\d+',compact): continue
        if compact.startswith('全国大学英语四、六级考试大纲'): continue
        if compact in {'2.2.2考试过程','考试按以下步骤进行:','4.主观题评分'}: continue
        useful.append(compact)
    return not useful

def cet_skills(src,lines):
    """Extract all numbered skills, including short/wrapped/multi-column lines.

    The unchanged text remains the locator authority. Number matches are found
    in the original string so compatibility normalization never changes offsets.
    """
    modules={'1.1.2':'听力','1.2.2':'阅读','1.3.2':'写作','1.4.2':'翻译','1.5.2':'口语'}
    output=[]; page=0; section=None; group=None; current=None
    def flush():
        nonlocal current
        if current:
            content='\n'.join(current['parts']).strip()
            loc={'text_path':src['text_path'],'line_start':current['start'],'line_end':current['end'],'pdf_page':current['page'],'section':current['section']}
            original='\n'.join(lines[current['start']-1:current['end']])
            output.append(entry(src,content,loc,modules[current['section']],title=f"{modules[current['section']]}技能{current['code']}：{norm(content)}",level=['CET-4','CET-6'],original_text=original,content_type='numbered_skill_from_official_text',skill_code=current['code'],skill_group=current['group'],requirement_type='numbered_skill'))
        current=None
    for n,line in enumerate(lines,1):
        v=norm(line); compact=re.sub(r'\s+','',v)
        marker=re.match(r'\[\[PDF_PAGE (\d+)\]\]',v)
        if marker: page=int(marker[1]); continue
        if not 6<=page<=10: continue
        head=re.match(r'^(\d+(?:\.\d+){1,2})\s',v)
        if head:
            flush(); section=head[1] if head[1] in modules else None; group=None; continue
        if not section: continue
        if not compact or compact.startswith('全国大学英语四、六级考试大纲') or re.fullmatch(r'\d+',compact) or len(compact)==1: continue
        category=re.match(r'^([A-D])\.(.+)',v)
        if category: flush(); group=v; continue
        points=list(re.finditer(r'(?<![0-9０-９])([0-9０-９]{2})\s+(?=\S)',line))
        if points:
            for i,point in enumerate(points):
                flush()
                end=points[i+1].start() if i+1<len(points) else len(line)
                current={'parts':[line[point.start():end].strip()],'start':n,'end':n,'page':page,'section':section,'group':group,'code':norm(point[1])}
        elif current:
            # A top-level chapter caption ends the final oral skill.
            if re.match(r'^\d+\.全国大学英语',compact): flush(); section=None; continue
            current['parts'].append(line); current['end']=n
    flush()
    return output

def generic(src,lines):
    output=[]; page=None; module=src.get('subject') or src.get('kind'); current=[]; begin=None; section=None
    if src['kind']=='exam_content':
        return cet_content(src)
    def flush(end):
        nonlocal current,begin
        if current:
            c='\n'.join(current)
            if len(c)>15: output.append(entry(src,c,{'text_path':src['text_path'],'line_start':begin,'line_end':end,'pdf_page':page,'section':section},module,title=section or norm(c)[:100]))
        current=[]; begin=None
    for n,line in enumerate(lines,1):
        v=norm(line); marker=re.match(r'\[\[PDF_PAGE (\d+)\]\]',v)
        if marker: flush(n-1); page=int(marker[1]); continue
        is_section=bool(re.match(r'^第[一二三四五六七八九十百]+条',v)) if src['kind']=='law' else bool(re.match(r'^(?:表\s*\d+[.\-]?\d*|[一二三四五六七八九十]+、|\d+\.\d+\.\d+)',v))
        if is_section: flush(n-1); section=v[:120]
        if begin is None: begin=n
        current.append(line)
    flush(len(lines)); return output

def cse2024(src):
    data=json.loads((BASE/src['local_path']).read_text(encoding='utf-8'))['data']; output=[]
    # The top-level item.content is a search-audience suggestion, not a mapping.
    for i,item in enumerate(data.get('item',[])):
        if item.get('remark'):
            output.append(entry(src,item['remark'],{'json_path':src['local_path'],'json_pointer':f'/data/item/{i}/remark','official_descriptor_id':item['id']},'英语综合能力',title=f"{item['title']}英语综合能力",level=item['title'],standard_version='GF 0018—2024'))
    def walk(node,pointer,module=None):
        title=node.get('title') or module
        for i,item in enumerate(node.get('item',[])):
            if item.get('content'):
                output.append(entry(src,item['content'],{'json_path':src['local_path'],'json_pointer':f'{pointer}/item/{i}/content','official_descriptor_id':item['id'],'scale_title':title},title,title=f"{title} / {item['title']}：{item['content'][:70]}",level=item['title'],standard_version='GF 0018—2024'))
        for i,child in enumerate(node.get('children',[])): walk(child,f'{pointer}/children/{i}',title)
    for i,child in enumerate(data.get('children',[])): walk(child,f'/data/children/{i}')
    return output

def cet_rubrics(requirements):
    refs={'写作':['cet.syllabus.2016.r067'],'翻译':['cet.syllabus.2016.r069','cet.syllabus.2016.r070']}
    ranges={14:[13,15],11:[10,12],8:[7,9],5:[4,6],2:[1,3]}; output=[]
    for task,ids in refs.items():
        text=unicodedata.normalize('NFKC','\n'.join(r['content'] for r in requirements if r['requirement_id'] in ids))
        bands=[]
        for m in re.finditer(r'(14|11|8|5|2)分档\s*(.*?)(?=(?:14|11|8|5|2)分档|$)',text,re.S):
            value=int(m[1]); description=m[2].strip()
            description=re.sub(r'\(续表\)\s*档次\s*档\s*次\s*描\s*述','',description).strip()
            bands.append({'band':value,'raw_score_range':ranges[value],'descriptor':description,'content_type':'NFKC-normalized official extracted text'})
        output.append({'task_type':task,'official':True,'max_raw_score':15,'scoring_method':'总体印象评分','requirement_ids':ids,'bands':bands})
    return {'official':True,'note':'四级和六级采用相同档次描述，但测试难度、考核要求和评分样卷有级别差异；原始15分档次不等于710分报道分。','rubrics':output}

def main():
    catalog=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
    # Remove a discovery bug from the initial unpublished acquisition run.
    catalog['sources']=[x for x in catalog['sources'] if x['standard_id']!='ntce.standard.youeryuan']
    requirements=[]; rubrics=[]
    for src in catalog['sources']:
        text_path=ROOT/'text'/f"{src['standard_id']}.txt"
        if not text_path.exists() or not src['verified']: continue
        src['text_path']=str(text_path.relative_to(BASE)).replace('\\','/'); src['text_sha256']=digest(text_path)
        if src.get('landing_path'):
            raw=(BASE/src['landing_path']).read_text(encoding='utf-8',errors='replace')
            date=re.search(r"ReportIDIssueTime[^>]*>(\d{4}-\d{2}-\d{2})",raw)
            if date: src['published_date']=date[1]
        if src['kind']=='interview_outline': src['version']='试行（原文署二〇一二年五月）'; src['document_date']='2012-05'
        lines=text_path.read_text(encoding='utf-8-sig').splitlines()
        if src['kind'] in ('written_outline','interview_outline'): requirements+=ntce(src,lines)
        elif src['standard_id']=='cet.syllabus.2016': requirements+=cet(src,lines)
        elif src['kind']=='language_standard_descriptor_dataset': requirements+=cse2024(src)
        elif src['kind']!='correction_evidence': requirements+=generic(src,lines)
        if src['kind']=='interview_outline':
            rr,rq=interview_rubrics(src); rubrics+=rr; requirements+=rq
    previous=[]
    if (ROOT/'requirements.jsonl').exists():
        with (ROOT/'requirements.jsonl').open(encoding='utf-8') as stream: previous=[json.loads(l) for l in stream if l.strip()]
    registry={json.dumps([r['standard_id'],r['locator'],r['content']],sort_keys=True,ensure_ascii=False):r['requirement_id'] for r in previous}
    nums=collections.defaultdict(int)
    for r in previous:
        sid=r['standard_id']; nums[sid]=max(nums[sid],int(r['requirement_id'].rsplit('.r',1)[1]))
    retired_path=ROOT/'retired_requirement_ids.json'
    retired=json.loads(retired_path.read_text(encoding='utf-8')) if retired_path.exists() else {'retired':[]}
    for rid in retired.get('retired',[]):
        sid,number=rid.rsplit('.r',1); nums[sid]=max(nums[sid],int(number))
    for r in requirements:
        key=json.dumps([r['standard_id'],r['locator'],r['content']],sort_keys=True,ensure_ascii=False)
        if key not in registry: nums[r['standard_id']]+=1; registry[key]=f"{r['standard_id']}.r{nums[r['standard_id']]:03d}"
        r['requirement_id']=registry[key]
    active_ids={r['requirement_id'] for r in requirements}
    removed=[r for r in previous if r['requirement_id'] not in active_ids]
    if removed:
        old_ids=set(retired.get('retired',[]))
        new_retired=[r['requirement_id'] for r in removed if r['requirement_id'] not in old_ids]
        retired['reason']='抽取边界或结构纠正导致的废弃ID；禁止复用。原文仍保留，废弃条目不能用作通用考试要求。'
        retired['retired']=sorted(old_ids|set(new_retired))
        if new_retired:
            retired.setdefault('batches',[]).append({'retired_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reason':'修正原文抽取边界或模板过滤；Word试卷结构/题型样例及CET版心或无要求的章节标题不能充当通用考试要求。','ids':new_retired})
        atomic_write(retired_path,json.dumps(retired,ensure_ascii=False,indent=2)+'\n')
        archive=ROOT/'retired_requirement_records.jsonl'
        old_records=[]
        if archive.exists():
            with archive.open(encoding='utf-8') as stream: old_records=[json.loads(x) for x in stream if x.strip()]
        archived={r['requirement_id'] for r in old_records}
        old_records.extend({**r,'retirement_reason':'cet_running_header_or_section_template' if r['standard_id']=='cet.syllabus.2016' else 'outside_exam_content_requirements_section'} for r in removed if r['requirement_id'] not in archived)
        atomic_write(archive,''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in old_records))
    atomic_write(ROOT/'requirements.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requirements))
    skill_modules={'听力':9,'阅读':10,'写作':11,'翻译':5,'口语':5}
    skill_rows=[r for r in requirements if r['standard_id']=='cet.syllabus.2016' and r.get('requirement_type')=='numbered_skill']
    coverage={'standard_id':'cet.syllabus.2016','scope':'第1章1.1.2至1.5.2的完整编号技能清单；能力映射仍需教研复核。','modules':{}}
    for module,expected in skill_modules.items():
        found=sorted([r for r in skill_rows if r['module']==module],key=lambda r:int(r['skill_code']))
        codes=[r['skill_code'] for r in found]
        coverage['modules'][module]={'expected_codes':[f'{n:02d}' for n in range(1,expected+1)],'actual_codes':codes,'complete':codes==[f'{n:02d}' for n in range(1,expected+1)],'skills':[{k:r[k] for k in ('skill_code','skill_group','requirement_id','content','locator')} for r in found]}
    coverage['complete']=all(v['complete'] for v in coverage['modules'].values())
    atomic_write(ROOT/'cet_skill_coverage.json',json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
    changes_path=ROOT/'cet_skill_index_changes.json'
    changes=json.loads(changes_path.read_text(encoding='utf-8')) if changes_path.exists() else {'standard_id':'cet.syllabus.2016','reason':'补齐短技能句与多列编号技能，废弃纯版心/章节模板，正确旧ID保持不变。','added':[],'retired':[]}
    previous_ids={r['requirement_id'] for r in previous}
    added_ids={r['requirement_id'] for r in changes['added']}
    changes['added'].extend({k:r[k] for k in ('requirement_id','module','skill_code','content','locator')} for r in skill_rows if r['requirement_id'] not in previous_ids and r['requirement_id'] not in added_ids)
    changes['retired']=sorted(set(changes['retired'])|{r['requirement_id'] for r in removed if r['standard_id']=='cet.syllabus.2016'})
    atomic_write(changes_path,json.dumps(changes,ensure_ascii=False,indent=2)+'\n')
    atomic_write(ROOT/'official_cet_rubrics.json',json.dumps(cet_rubrics(requirements),ensure_ascii=False,indent=2)+'\n')
    bycriterion={(r['standard_id'],r['content'],json.dumps(r['locator'],sort_keys=True)):r['requirement_id'] for r in requirements}
    for rule in rubrics: rule['requirement_id']=bycriterion[(rule['standard_id'],rule['criterion'],json.dumps(rule['locator'],sort_keys=True))]
    atomic_write(ROOT/'official_interview_rubrics.json',json.dumps({'official':True,'criteria':rubrics},ensure_ascii=False,indent=2)+'\n')
    catalog['requirement_count_by_standard']=dict(collections.Counter(r['standard_id'] for r in requirements))
    for source in catalog['sources']:
        if source['standard_id']=='cse.gf0018-2018': source.update(current_status='superseded',superseded_by='cse.gf0018-2024',valid_until='2025-02-28')
        if source['standard_id']=='cse.gf0018-2024': source.update(current_status='current_by_official_revision_notice',supersedes='cse.gf0018-2018')
    catalog['generated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    atomic_write(ROOT/'catalog.json',json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    print('sources',len(catalog['sources']),'requirements',len(requirements),'official interview criteria',len(rubrics))
    print(json.dumps(catalog['requirement_count_by_standard'],ensure_ascii=False,indent=2))
if __name__=='__main__': main()
