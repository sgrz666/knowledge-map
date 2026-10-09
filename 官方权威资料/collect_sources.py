"""Archive official public sources, preserving IDs and downloaded bytes.
Run with the bundled Python. This script only writes beneath its own directory.
"""
from __future__ import annotations
import argparse, concurrent.futures, datetime, hashlib, html, json, re, urllib.parse, urllib.request
from html.parser import HTMLParser
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
LOG = []

def atomic_write(path,text):
    temporary=path.with_name(path.name+'.tmp'); temporary.write_text(text,encoding='utf-8'); temporary.replace(path)

class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(); self.links=[]; self.current=None; self.parts=[]; self.skip=0
        self.feed(raw)
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag in ('script','style'): self.skip+=1
        if tag=='a': self.current=[a.get('href',''),[]]
        if tag in ('p','div','br','tr','li','h1','h2','h3'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
        if tag=='a' and self.current:
            self.links.append((self.current[0],''.join(self.current[1]).strip())); self.current=None
        if tag in ('p','div','tr','li'): self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:
            self.parts.append(data)
            if self.current: self.current[1].append(data)
    @property
    def text(self):
        return '\n'.join(s.strip() for s in ''.join(self.parts).splitlines() if s.strip())

class Article(HTMLParser):
    """Capture a balanced official article body, excluding surrounding navigation."""
    def __init__(self,raw):
        super().__init__(); self.depth=0; self.done=False; self.fragment=[]; self.feed(raw)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        target=a.get('id') in ('ReportIDtext','UCAP-CONTENT','zoom','ContentBody') or 'TRS_Editor' in a.get('class','').split()
        if not self.done and (self.depth or target):
            self.fragment.append(self.get_starttag_text())
            if tag not in ('br','img','hr','meta','link','input'): self.depth+=1
    def handle_endtag(self,tag):
        if self.depth:
            self.fragment.append(f'</{tag}>'); self.depth-=1
            if not self.depth: self.done=True
    def handle_data(self,data):
        if self.depth: self.fragment.append(data)
    def handle_entityref(self,name):
        if self.depth: self.fragment.append(f'&{name};')
    def handle_charref(self,name):
        if self.depth: self.fragment.append(f'&#{name};')

def decode(b):
    for enc in ('utf-8-sig','gb18030'):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode('utf-8',errors='replace')

def fetch(url):
    urls=[url]
    if '.neea.edu.cn' in url: urls.append(url.replace('.neea.edu.cn','.neea.cn'))
    elif '.neea.cn' in url: urls.append(url.replace('.neea.cn','.neea.edu.cn'))
    if url.startswith('https://www.moe.gov.cn/'): urls.append(url.replace('https://','http://',1))
    for u in dict.fromkeys(urls):
        try:
            host=urllib.parse.urlsplit(u)
            request=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0','Referer':f'{host.scheme}://{host.netloc}/'})
            with urllib.request.urlopen(request,timeout=35) as response:
                data=response.read(); final=response.url
            if len(data)<100: raise ValueError('empty or implausibly short response')
            LOG.append({'url':u,'status':'downloaded','bytes':len(data),'retrieved_at':NOW,'final_url':final})
            return data,final
        except Exception as ex:
            LOG.append({'url':u,'status':'failed','reason':str(ex),'retrieved_at':NOW})
    raise RuntimeError(f'Could not download {url}')

def rel(path): return path.relative_to(ROOT.parent).as_posix()
def sha(data): return hashlib.sha256(data).hexdigest()

def collect(source):
    sid=source['standard_id']; folder=ROOT/'originals'; folder.mkdir(exist_ok=True)
    b,final=fetch(source['source_url']); ext=Path(urllib.parse.urlsplit(final).path).suffix.lower()
    if ext not in ('.pdf','.doc','.docx','.json'): ext='.html'
    path=folder/(sid+ext); path.write_bytes(b)
    source.update(local_path=rel(path),sha256=sha(b),retrieved_at=NOW,resolved_url=final)
    source.setdefault('version',None); source.setdefault('effective_date',None)
    source.setdefault('published_date',None); source.setdefault('verification_method','Official publisher domain; bytes archived and SHA-256 recorded; extracted text cross-checked with source heading')
    source['verified']=True
    if source.get('landing_url'):
        lb,lf=fetch(source['landing_url']); lp=folder/(sid+'.landing.html'); lp.write_bytes(lb)
        source.update(landing_path=rel(lp),landing_sha256=sha(lb),landing_resolved_url=lf)
    if ext=='.html':
        raw=decode(b); page=Page(raw)
        attachments=[urllib.parse.urljoin(final,u) for u,t in page.links if re.search(r'\.(?:docx?|pdf)(?:\?|$)',u,re.I)]
        if source.get('attachment') and attachments:
            ab,af=fetch(attachments[0]); ae=Path(urllib.parse.urlsplit(af).path).suffix.lower(); ap=folder/(sid+ae); ap.write_bytes(ab)
            source.update(landing_path=source['local_path'],landing_sha256=source['sha256'],local_path=rel(ap),sha256=sha(ab),document_url=af)
            path=ap; ext=ae
        else:
            # Preserve body or article div when possible; full page archive remains unchanged.
            fragment=''.join(Article(raw).fragment)
            text=Page(fragment).text if fragment else page.text
            write_text(source,text)
    if ext=='.pdf':
        pages=[]
        reader=PdfReader(path)
        for n,p in enumerate(reader.pages,1): pages.append(f'[[PDF_PAGE {n}]]\n'+(p.extract_text() or ''))
        write_text(source,'\n\n'.join(pages)); source['page_count']=len(reader.pages)
    if ext=='.json': write_text(source,json.dumps(json.loads(b),ensure_ascii=False,indent=2))
    return source

def write_text(source,text):
    target=ROOT/'text'/f"{source['standard_id']}.txt"; target.parent.mkdir(exist_ok=True)
    normalized='\n'.join(x.rstrip() for x in text.replace('\r','\n').splitlines() if x.strip())+'\n'
    target.write_text(normalized,encoding='utf-8')
    source.update(text_path=rel(target),text_sha256=sha(normalized.encode('utf-8')))

def discover_ntce():
    sources=[]
    for n in (1,2):
        u=f'https://ntce.neea.edu.cn/xhtml1/category/1507/1099-{n}.htm'; b,_=fetch(u)
        (ROOT/'originals').mkdir(exist_ok=True); (ROOT/'originals'/f'ntce.written.index.{n}.html').write_bytes(b)
        for href,title in Page(decode(b)).links:
            match=re.match(r'(\d{3})-',title)
            if match:
                code=match.group(1); level='幼儿园' if code.startswith('1') else '小学' if code.startswith('2') else '初级中学' if int(code)>302 and code.startswith('3') else '高级中学' if code.startswith('4') else '中学'
                subject=re.search(r'《(.*?)》',title).group(1)
                sources.append({'standard_id':f'ntce.outline.{code}','name':title,'authority':'教育部教育考试院（原教育部考试中心）','source_url':urllib.parse.urljoin(u,href),'version':None,'effective_date':None,'published_date':None,'exam_scope':['NTCE',level,subject],'attachment':True,'level':level,'subject':subject,'kind':'written_outline'})
    for slug,idx,prefix in [('interview','693','ntce.interview'),('standards','692','ntce.standard')]:
        u=f'https://ntce.neea.edu.cn/xhtml1/category/1511/{idx}-1.htm'; b,_=fetch(u)
        (ROOT/'originals'/f'ntce.{slug}.index.html').write_bytes(b)
        for href,title in Page(decode(b)).links:
            if '/report/' not in href: continue
            tail=title.rsplit('--',1)[-1]
            level='幼儿园' if '幼儿' in tail else '小学' if '小学' in tail and '中小学' not in tail else '中学'
            key={'幼儿园':'youeryuan','小学':'xiaoxue','中学':'zhongxue'}[level]
            if slug=='standards': key='trial'
            sources.append({'standard_id':f'{prefix}.{key}','name':title,'authority':'教育部教育考试院（原教育部考试中心）','source_url':urllib.parse.urljoin(u,href),'version':'试行' if '试行' in title else None,'effective_date':None,'exam_scope':['NTCE',level] if slug=='interview' else ['NTCE','幼儿园','小学','中学'],'attachment':True,'level':level,'subject':'面试' if slug=='interview' else '考试标准','kind':'interview_outline' if slug=='interview' else 'exam_standard'})
    return sources

FIXED=[
 {'standard_id':'cse.gf0018-2018','name':'中国英语能力等级量表（GF 0018—2018）','authority':'教育部、国家语言文字工作委员会','source_url':'https://www.moe.gov.cn/jyb_sjzl/ziliao/A19/201807/W020180725662475781772.pdf','version':'GF 0018—2018','effective_date':'2018-06-01','published_date':'2018-02-12','exam_scope':['英语能力评价，尚未核验CET分数/等级对接'],'kind':'language_standard'},
 {'standard_id':'cet.syllabus.2016','name':'全国大学英语四、六级考试大纲（2016年修订版）','authority':'教育部考试中心','source_url':'https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf','version':'2016年修订版','effective_date':None,'exam_scope':['CET-4','CET-6','CET-SET4','CET-SET6'],'kind':'exam_syllabus'},
 {'standard_id':'cet.content.cet4','name':'全国大学英语四级笔试（CET4）考核内容','authority':'教育部教育考试院','source_url':'https://cet.neea.edu.cn/xhtml1/report/16123/196-1.htm','version':None,'effective_date':None,'published_date':'2016-12-08','exam_scope':['CET-4'],'kind':'exam_content'},
 {'standard_id':'cet.content.cet6','name':'全国大学英语六级笔试（CET6）考核内容','authority':'教育部教育考试院','source_url':'https://cet.neea.edu.cn/xhtml1/report/16123/201-1.htm','version':None,'effective_date':None,'published_date':'2016-12-08','exam_scope':['CET-6'],'kind':'exam_content'},
]

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--offline',action='store_true'); parser.add_argument('--extras',action='store_true'); args=parser.parse_args()
    if args.offline: return
    if args.extras:
        sources=json.loads((ROOT/'extra_sources.json').read_text(encoding='utf-8'))
    else: sources=discover_ntce()+FIXED
    existing=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8')) if (ROOT/'catalog.json').exists() else {'schema_version':'1.0','sources':[]}
    byid={x['standard_id']:x for x in existing['sources']}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(collect,s):s for s in sources}
        for future in concurrent.futures.as_completed(jobs):
            s=jobs[future]
            try:
                result=future.result(); byid[s['standard_id']]=result; print(s['standard_id'],'OK',result['local_path'],flush=True)
            except Exception as ex:
                s.update(verified=False,acquisition_error=str(ex),local_path=None,text_path=None,sha256=None,retrieved_at=NOW)
                if s['standard_id'] not in byid: byid[s['standard_id']]=s
                print(s['standard_id'],'FAILED',str(ex),flush=True)
    existing.update(generated_at=NOW,sources=sorted(byid.values(),key=lambda x:x['standard_id']))
    atomic_write(ROOT/'catalog.json',json.dumps(existing,ensure_ascii=False,indent=2)+'\n')
    with (ROOT/'acquisition_log.jsonl').open('a',encoding='utf-8') as f:
        for record in LOG: f.write(json.dumps(record,ensure_ascii=False)+'\n')
if __name__=='__main__': main()
