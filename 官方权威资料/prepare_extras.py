"""Prepare official supplementary source URLs discovered from MOE pages."""
import json, urllib.parse
from pathlib import Path
from collect_sources import ROOT, Page, decode, fetch

sources=[]
def add(sid,name,url,kind='law',version=None,effective=None,authority='全国人民代表大会及其常务委员会（教育部官方转载）',**other):
    sources.append({'standard_id':sid,'name':name,'authority':authority,'source_url':url,'version':version,'effective_date':effective,'exam_scope':['NTCE'],'kind':kind,**other})

for year,url,slugs in [
 (2021,'https://www.moe.gov.cn/srcsite/A10/s6991/202104/t20210412_525943.html',['zhongxue','xiaoxue','xueqian','zhongzhi','teshu']),
 (2012,'https://www.moe.gov.cn/srcsite/A10/s6991/201209/t20120913_145603.html',['youeryuan','xiaoxue','zhongxue'])]:
    b,_=fetch(url)
    links=[(u,t) for u,t in Page(decode(b)).links if '.doc' in u]
    for slug,(u,t) in zip(slugs,links):
        add(f'teacher.{"competence" if year==2021 else "professional"}.{year}.{slug}',t,urllib.parse.urljoin(url,u),'teacher_standard',f'教师厅〔2021〕2号附件（试行）' if year==2021 else '教师〔2012〕1号附件（试行）',authority='教育部办公厅' if year==2021 else '教育部',landing_url=url,subject='教师职业能力' if year==2021 else '教师专业标准',level={'zhongxue':'中学','xiaoxue':'小学','xueqian':'幼儿园','youeryuan':'幼儿园','zhongzhi':'中等职业教育','teshu':'特殊教育'}[slug])

add('teacher.ethics.2008','中小学教师职业道德规范（2008年修订）','https://www.moe.gov.cn/srcsite/A10/s7002/200809/t20080901_145824.html','teacher_ethics','教师〔2008〕2号（2008年修订）',authority='教育部、中国教科文卫体工会全国委员会',subject='教师职业道德')
add('teacher.behavior.2018','新时代高校、中小学、幼儿园教师职业行为十项准则','https://www.moe.gov.cn/srcsite/A10/s7002/201811/t20181115_354921.html','teacher_ethics','教师〔2018〕16号',authority='教育部',subject='教师职业行为')
add('teacher.curriculum.2011','教师教育课程标准（试行）','https://www.moe.gov.cn/ewebeditor/uploadfile/2011/10/19/20111019100845630.doc','teacher_standard','教师〔2011〕6号附件（试行）',authority='教育部',landing_url='https://www.moe.gov.cn/srcsite/A10/s6991/201110/t20111008_145604.html',subject='教师教育课程')
add('teacher.plan.2022','新时代基础教育强师计划','https://www.moe.gov.cn/srcsite/A10/s7034/202204/t20220413_616644.html','teacher_policy','教师〔2022〕6号',authority='教育部等八部门',subject='教师队伍建设政策')
add('law.education.2021','中华人民共和国教育法（2021年修正）','https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/202107/t20210730_547843.html',version='2021年4月29日第三次修正',effective='2021-04-30')
add('law.compulsory.2018','中华人民共和国义务教育法（2018年修正）','https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/202110/t20211029_575949.html',version='2018年12月29日第二次修正')
add('law.teacher.2009','中华人民共和国教师法（2009年修正）','https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html',version='2009年8月27日修正')
add('law.preschool.2024','中华人民共和国学前教育法','https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/202411/t20241108_1161363.html',version='2024年11月8日通过',effective='2025-06-01')
add('law.minors.2024','中华人民共和国未成年人保护法（2024年修正）','https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_54358c05e57642ab895176413f7cd4d7.html',version='2024年4月26日第二次修正',effective='2024-04-26',authority='全国人民代表大会常务委员会（国家市场监督管理总局官方转载）',original_requested_url='https://wb.flk.npc.gov.cn/flfg/PDF/c49809c4a0ef4721aa156972cc22f5e1.pdf',effective_date_evidence='https://flk.npc.gov.cn/detail?id=ff8081818f197cf001905e567af635a0')
add('law.juvenile_prevention.2020','中华人民共和国预防未成年人犯罪法（2020年修订）','https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_qtxgfl/202110/t20211025_574843.html',version='2020年12月26日修订',effective='2021-06-01')
add('regulation.kindergarten.2016','幼儿园工作规程','https://www.moe.gov.cn/jyb_xxgk/xxgk/zhengce/guizhang/202112/t20211206_585104.html',version='教育部令第39号',effective='2016-03-01',authority='教育部')
add('regulation.school_protection.2021','未成年人学校保护规定','https://www.moe.gov.cn/jyb_xxgk/xxgk/zhengce/guizhang/202112/P020211208553316253863.pdf',version='教育部令第50号',effective='2021-09-01',authority='教育部')
add('regulation.discipline.2020','中小学教育惩戒规则（试行）','https://www.moe.gov.cn/jyb_xxgk/xxgk/zhengce/guizhang/202112/P020211208553109328813.pdf',version='教育部令第49号（试行）',effective='2021-03-01',authority='教育部')
add('cse.gf0018-2024','中国英语能力等级量表（GF 0018—2024）官方描述语数据集','https://www.neea.edu.cn/api/dict/ability.json','language_standard_descriptor_dataset','GF 0018—2024','2025-03-01','教育部、国家语言文字工作委员会（教育部教育考试院官方搜索工具发布）',landing_url='https://www.neea.edu.cn/html1/folder/2503/1-1.htm',published_date='2024-11-26',exam_scope=['英语能力测评，未核验CET分数对接'],full_publication_acquired=False,descriptor_dataset_acquired=True,verification_method='Official CSE 2024 search page identifies version and dates; its public JavaScript calls /api/dict/ability.json; archived JSON preserves official descriptor IDs.')
add('evidence.gbt41671-2022','GB/T 41671-2022对应化学纤维溶剂残留量测定（CSE错误编号纠正证据）','https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=539A94752F8764D4E765BC5930B11004','correction_evidence','GB/T 41671—2022','2023-02-01','国家市场监督管理总局、国家标准化管理委员会',exam_scope=['CSE错误编号纠正证据，非考试规范'])
add('cet.score.interpretation','CET笔试分数解释','https://cet.neea.edu.cn/xhtml1/folder/19081/5124-1.htm','exam_score_interpretation',authority='教育部教育考试院',exam_scope=['CET-4','CET-6'],subject='成绩解释')
(ROOT/'extra_sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('prepared',len(sources),'official supplementary sources')
