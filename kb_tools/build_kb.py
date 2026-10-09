# -*- coding: utf-8 -*-
"""教资真题 CSV → RAG 友好知识库 构建脚本
用法:
  python build_kb.py inventory   # 只跑文件名解析,输出归一结果与未识别清单
  python build_kb.py sample N    # 解析抽样卷并打印样例(不落盘)
  python build_kb.py build       # 全量构建 KB
"""
import csv
import json
import os
import re
import sys
import hashlib
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / '教资' / '真题'
OUT = ROOT / '数据集' / '教资'

sys.stdout.reconfigure(encoding='utf-8')

LEVEL_DIR = {'幼儿真题': 'youer', '小学真题': 'xiaoxue', '初中真题': 'chuzhong', '高中真题': 'gaozhong'}

SAFE_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def safe_part(s):
    """路径组件白名单校验(允许文件扩展名中的点,拒绝路径穿越)"""
    s = str(s)
    if not s or '..' in s or '/' in s or '\\' in s or not re.match(r'^[a-zA-Z0-9_.-]+$', s):
        raise ValueError('非法路径组件: %r' % s)
    return str(s)


def _contained(p, base):
    rp = os.path.normpath(os.path.abspath(str(p)))
    rb = os.path.normpath(os.path.abspath(str(base)))
    if not rp.startswith(rb + os.sep):
        raise ValueError('路径越界: %r' % rp)
    return Path(rp)


def out_file(*rel):
    """在 OUT 下构造输出路径:组件白名单 + 目录越界校验"""
    parts = [safe_part(x) for x in rel]
    return _contained(OUT.joinpath(*parts), OUT)


VALID_DIRS = set(LEVEL_DIR) | {d.replace('真题', '真题答案') for d in LEVEL_DIR}


def src_file(dir_name, file_name):
    """在 SRC 下构造输入路径:目录/文件名白名单 + 目录越界校验"""
    if dir_name not in VALID_DIRS:
        raise ValueError('非法目录: %r' % dir_name)
    if not re.match(r'^[\u4e00-\u9fa5A-Za-z0-9（）()《》 、．.·_-]+\.csv$', file_name):
        raise ValueError('非法文件名: %r' % file_name)
    return _contained(SRC.joinpath(dir_name, file_name), SRC)


def sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- S1 文件名解析

DISCIPLINES = [
    (r'思想品德|思想政治|政治', 'zhengzhi', '政治(思想品德/思想政治)'),
    (r'体育与健康|体育', 'tiyu', '体育与健康'),
    (r'信息技术', 'xinxi', '信息技术'),
    (r'语文', 'yuwen', '语文'),
    (r'数学', 'shuxue', '数学'),
    (r'英语', 'yingyu', '英语'),
    (r'物理', 'wuli', '物理'),
    (r'化学', 'huaxue', '化学'),
    (r'生物', 'shengwu', '生物'),
    (r'历史', 'lishi', '历史'),
    (r'地理', 'dili', '地理'),
    (r'美术', 'meishu', '美术'),
    (r'音乐', 'yinyue', '音乐'),
]

CN_HALF = {'上': 'a', '下': 'b'}


def parse_meta(d, fn):
    name = fn[:-4].strip()
    m = re.search(r'《(.+?)》', name)
    raw = m.group(1).strip() if m else None
    if not raw:  # 2020年下半年教师资格证考试（初中历史）题 —— 圆括号科目
        m2 = re.search(r'（([^（）]{2,20})）', name)
        if m2:
            raw = m2.group(1).strip()

    meta = {
        'dir': d, 'file': fn, 'raw_subject': raw,
        'system': '省考' if re.search(r'四川|辽宁|江西', name) else '国考',
        'variant': '精选' if '精选' in name else '全卷',
        'paper': None, 'category': 'written',
    }
    mp = re.search(r'[(（]([AB])级[)）]', name)
    if mp:
        meta['paper'] = mp.group(1) + '级'
    mc = re.search(r'第([一二三四五六七八九十]+)章(.+?)真题', name)
    if mc:
        meta['paper'] = '第%s章%s' % (mc.group(1), mc.group(2))

    ym = re.search(r'(\d{4})\s*年?(?:\s*(\d{1,2})\s*月)?', name)
    mh = re.search(r'(上|下)半年', name)
    part = None
    mpart = re.search(r'\((\d)\)$', name)
    if mpart:
        part = mpart.group(1)
    if ym:
        year = ym.group(1)
        month = ym.group(2)
        half = mh.group(1) if mh else None
        if half:
            session = year + CN_HALF[half]
        elif month:
            session = year + 'm' + month
        else:
            session = year
    else:
        year = 'na'
        session = 'na'
        if part:
            session += '-p' + part
    meta['session'] = session
    meta['year'] = year

    lvl_paren = None
    if re.search(r'初级中学', name):
        lvl_paren = 'chuzhong'
    elif re.search(r'高级中学', name):
        lvl_paren = 'gaozhong'
    elif re.search(r'[（(]中学[)）]', name):
        lvl_paren = 'zhongxue'

    def prefix_level(text):
        for pre, lv in (('初中', 'chuzhong'), ('高中', 'gaozhong'),
                        ('幼儿园', 'youer'), ('幼儿', 'youer'),
                        ('小学', 'xiaoxue'), ('中学', 'zhongxue')):
            if text.startswith(pre):
                return lv, text[len(pre):]
        return None, text

    r = raw or ''
    level = subject = None
    if r and '结构化面试' in r:
        meta['category'] = 'interview'
        subject = 'mianshi'
        if '中小学' in r:
            level = 'zhongxiaoxue'
        elif '幼儿' in r:
            level = 'youer'
        else:
            level = LEVEL_DIR[d]
    elif r and '综合素质' in r:
        subject = 'zonghe'
        level = lvl_paren or prefix_level(r)[0]
    elif r and '保教知识与能力' in r:
        subject, level = 'baojiao', 'youer'
    elif r and '教育教学知识与能力' in r:
        subject, level = 'jiaoxue', 'xiaoxue'
    elif r and '教育知识与能力' in r:
        subject, level = 'jiaoyuzhishi', 'zhongxue'
    elif r and '学科知识与' in r:
        for pat, code, cn in DISCIPLINES:
            if re.search(pat, r):
                subject = code
                meta['subject_cn'] = cn
                break
        level = lvl_paren or prefix_level(r)[0]
    elif r:
        lv, rest = prefix_level(r)
        suffix = r'(真题)?(（精选）)?(\(精选\))?(（考生回忆版）)?'
        for pat, code, cn in DISCIPLINES:
            if lv and re.fullmatch(pat + suffix, rest.strip()):
                subject = code
                meta['subject_cn'] = cn
                level = lv
                break
        if subject is None:  # 省考: 教育学 / 教育心理学
            if '教育心理学' in r:
                subject, meta['subject_cn'] = 'jiaoyuxinlixue', '教育心理学'
            elif '教育学' in r:
                subject, meta['subject_cn'] = 'jiaoyuxue', '教育学'
            if subject:
                level = lv or LEVEL_DIR[d]
    if level is None:
        level = LEVEL_DIR[d]
    meta['level'] = level
    meta['subject'] = subject
    if 'subject_cn' not in meta:
        meta['subject_cn'] = {'zonghe': '综合素质', 'baojiao': '保教知识与能力', 'jiaoxue': '教育教学知识与能力',
                              'jiaoyuzhishi': '教育知识与能力', 'mianshi': '结构化面试'}.get(subject, subject)
    meta['unparsed'] = subject is None
    return meta


def build_inventory():
    metas = []
    for d in LEVEL_DIR:
        for fn in sorted((SRC / d).iterdir()):
            if fn.suffix.lower() == '.csv':
                metas.append(parse_meta(d, fn.name))
    return metas


# ---------------------------------------------------------------- S2/S3 文本解析

WS = {'\u3000': ' ', '\xa0': ' ', '\u2003': ' ', '\u2002': ' ', '\u2007': ' ', '\t': ' '}


def norm_ws(text):
    for k, v in WS.items():
        text = text.replace(k, v)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r' ?\n ?', '\n', text)
    return text


def load_text(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    text = '\n'.join(''.join(cell for cell in row) for row in rows)
    return norm_ws(text)


SECTION_WORDS = ['不定项选择题', '多项选择题', '单项选择题', '简答题', '辨析题', '材料分析题',
                 '案例分析题', '论述题', '写作题', '教学设计题', '活动设计题', '诊断题', '解答题']
TYPE_MAP = {'单项选择题': '单选', '多项选择题': '多选', '不定项选择题': '多选', '简答题': '简答',
            '辨析题': '辨析', '材料分析题': '材料分析', '案例分析题': '材料分析', '论述题': '论述',
            '写作题': '写作', '教学设计题': '教学设计', '活动设计题': '活动设计', '诊断题': '诊断',
            '解答题': '解答'}
SEC_HEAD = re.compile(r'[一二三四五六七八九十]{1,2}\s*[、.．:：]')


def find_sections(text):
    heads = []
    for m in SEC_HEAD.finditer(text):
        after = text[m.end():m.end() + 16]
        for w in SECTION_WORDS:
            if after.startswith(w):
                heads.append((w, m.start(), m.end() + len(w)))
                break
    sections = []
    for i, (w, s, e) in enumerate(heads):
        nxt = heads[i + 1][1] if i + 1 < len(heads) else len(text)
        header_zone = text[s:min(e + 130, nxt)]
        decl_end = e
        pm = re.search(r'[（(]', text[e:min(e + 3, nxt)])
        if pm:
            open_ch = text[e + pm.start()]
            close = text.find('）', e + pm.end()) if open_ch == '（' else text.find(')', e + pm.end())
            if close != -1 and close < nxt:
                decl_end = close + 1
        cm = re.search(r'(?:共|本大题)\s*(\d{1,2})\s*小?题', header_zone)
        sm = re.search(r'每\s*小?\s*题\s*(\d{1,2})\s*分', header_zone)
        tm = re.search(r'共\s*(\d{1,3})\s*分', header_zone)
        sections.append({
            'title': w, 'start': s, 'decl_end': decl_end, 'end': nxt,
            'decl_count': int(cm.group(1)) if cm else None,
            'per_score': int(sm.group(1)) if sm else None,
            'total_score': int(tm.group(1)) if tm else None,
        })
    return sections


NUM_CAND_SKIP_AFTER = re.compile(r'^(?:分|年|岁|月|日|个|名|位|条|套|次|章|节|页|人|题)')
SUB_MARK = re.compile(r'^\s*[)）]')


def find_k(text, pos, hi, k):
    """在 text[pos:hi] 中精确定位题号 k。返回 (start, is_recovery) 或 None"""
    for m in re.finditer(r'(?<![0-9-])%d(?![0-9])' % k, text[pos:hi]):
        s = pos + m.start()
        prev1 = text[s - 1] if s > 0 else ''
        prev2 = text[s - 2:s] if s >= 2 else ''
        after = text[pos + m.end():]
        if prev1 == '（' and (SUB_MARK.match(after) or after.startswith('分')):
            continue  # （1）（2）小问 / （10分）分值
        if prev1 in '图表式' or prev2 == '第':
            continue  # 图3/表2/式(1)/第3问 等正文引用
        if NUM_CAND_SKIP_AFTER.match(after) or re.match(r'^[.．]\d', after):
            continue
        return s, False
    return None


def find_k_recover(text, pos, hi, k):
    """题号粘连/变形的恢复:33.(重复数字)、3+50°(量度粘连)、23+1905年(年份粘连)、19+年号(年字粘连)"""
    if k <= 9:
        m = re.search(r'(?<![0-9])%d{2}\s*[.．、]' % k, text[pos:hi])
        if m:
            return pos + m.start(), True
    m = re.search(r'(?<![0-9])%d(?=\d{1,4}\s*[°%%‰℃])' % k, text[pos:hi])
    if m:
        return pos + m.start(), True
    m = re.search(r'(?<![0-9])%d(?=\d{4}年)' % k, text[pos:hi])
    if m:
        return pos + m.start(), True
    m = re.search(r'(?<![0-9])%d(?=年[^月])' % k, text[pos:hi])
    if m:
        return pos + m.start(), True
    return None


def find_resync(text, pos, hi, expected, decl_count):
    """向后寻找 v,使 v、v+1、v+2 的题号成链(处理重新编号/大段缺号)"""
    limit = expected + (decl_count or 40) + 10
    for v in range(expected + 1, min(limit, 99)):
        hit = find_k(text, pos, hi, v)
        if not hit:
            continue
        p = hit[0] + 1
        ok = True
        for kk in (v + 1, v + 2):
            h2 = find_k(text, p, hi, kk)
            if not h2:
                ok = False
                break
            p = h2[0] + 1
        if ok:
            return v
    return None


def scan_section(text, lo, hi, from_pos, start_expected, decl_count):
    """逐题扫描:精确题号 → 缺号跳过 → 粘连恢复 → 链式重同步。
    返回 ([(cut_pos, 题号)...], next_expected, flags)"""
    cuts, flags = [], []
    pos, expected = from_pos, start_expected
    max_k = start_expected + (decl_count or 80) + 8
    while expected <= max_k and pos < hi:
        hit = find_k(text, pos, hi, expected)
        if hit is None:
            hit = find_k_recover(text, pos, hi, expected)
            if hit and hit[1]:
                flags.append('题号%d按粘连/重复形态恢复' % expected)
        if hit:
            cuts.append((hit[0], expected))
            pos = hit[0] + 1
            expected += 1
            continue
        # 缺号容错:k+1 / k+2
        jumped = False
        for kk in (expected + 1, expected + 2):
            h2 = find_k(text, pos, hi, kk)
            if h2:
                flags.append('题号%d缺失,从%d对齐' % (expected, kk))
                cuts.append((h2[0], kk))
                pos, expected = h2[0] + 1, kk + 1
                jumped = True
                break
        if jumped:
            continue
        # 链式重同步
        v = find_resync(text, pos, hi, expected, decl_count)
        if v:
            flags.append('题号重新同步(从%d起)' % v)
            expected = v
            continue
        break
    return cuts, expected, flags


OPT_MARK = re.compile(r'([A-GＡ-Ｇ])\s*[、.．:：]')
FW = str.maketrans('ＡＢＣＤＥＦＧ', 'ABCDEFG')


def parse_question_text(qno, body):
    body = body.strip()
    body = re.sub(r'^%d\s*' % qno, '', body, count=1)
    q = {'stem': body, 'options': []}
    # CSV 常出现 A、A、；字母串 A、B、C三个状态是题干，不能充当选项。
    repeated = re.compile(r'([A-GＡ-Ｇ])\s*[、.．:：]\s*\1\s*[、.．:：]')
    body = repeated.sub(r'\1、', body)
    q['stem'] = body
    candidates = [(m.group(1).translate(FW), m.start(), m.end()) for m in OPT_MARK.finditer(body)]
    chains = []
    for i, candidate in enumerate(candidates):
        if candidate[0] != 'A':
            continue
        chain = [candidate]
        for key, start, end in candidates[i + 1:]:
            if key == chr(ord(chain[-1][0]) + 1):
                chain.append((key, start, end))
            elif key <= chain[-1][0]:
                break
        if len(chain) >= 2:
            chains.append(chain)
    # 取首个最完整序列；残留的后续题目不能覆盖当前题目的选项。
    marks = max(chains, key=lambda chain: (len(chain), -chain[0][1]), default=[])
    if len(marks) >= 2 and marks[0][0] == 'A':
        opts = []
        for i, (key, s, e) in enumerate(marks):
            nxt = marks[i + 1][1] if i + 1 < len(marks) else len(body)
            opts.append({'key': key, 'text': body[e:nxt].strip()})
        q['stem'] = body[:marks[0][1]].strip()
        q['options'] = opts
    pm = re.search(r'问题\s*[:：]', q['stem'])
    if pm and pm.start() > 500:
        q['material_text'] = q['stem'][:pm.start()].strip()
        q['stem'] = q['stem'][pm.start():].strip()
    return q


def classify_answer(s):
    s = (s or '').strip().rstrip('。').strip()
    if not s or s in ('缺', '略', '暂缺', '暂无', '待补', '省略', '答案略', '解析略'):
        return 'missing', None
    if '问题与答案不符' in s or '答案与问题不符' in s:
        return 'source_conflict', None
    if re.fullmatch(r'[A-G]{1,7}', s):
        return 'letter', s
    if s in ('正确', '错误', '对', '错', '√', '×', 'T', 'F'):
        return 'letter', s
    if '参见解析' in s or '见解析' in s:
        return 'reference', None
    return 'brief', s


# classify_answer 描述答案文件的形状；落库时按附录 A.1 归约为五态可用性，
# 形状本身存入 extra.answer_provenance 供教研回溯，不参与诊断判分。
ANSWER_CONTRACT = {
    'letter': ('letter_only', 'letter'),
    'reference': ('reference_only', 'reference'),
    'brief': ('reference_only', 'brief'),
    'missing': ('missing', 'missing'),
    'source_conflict': ('source_conflict', 'source_conflict'),
}


def parse_answers(text):
    text = norm_ws(text.replace('\n', ' '))
    ans = {}
    ms = list(re.finditer(r'(?<![0-9])(\d{1,2})\s*[、.．:：]', text))
    if len(ms) < 3:  # 兜底: 1A2C 连写
        ms = list(re.finditer(r'(?<![0-9])(\d{1,2})(?=[A-G对错√×])', text))
    for i, m in enumerate(ms):
        s = text[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(text)]
        ans[int(m.group(1))] = s.strip()
    return ans


def resolve_answer_path(meta):
    base = meta['file'][:-4]
    adir_name = meta['dir'].replace('真题', '真题答案')
    for cand in (base + '（答案）.csv', base + ' （答案）.csv'):
        p = src_file(adir_name, cand)
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------- 试卷解析主流程

def parse_paper(meta):
    """→ (questions, qa, full_text)"""
    text = load_text(src_file(meta['dir'], meta['file']))
    qa = {'file': meta['dir'] + '/' + meta['file'], 'flags': [], 'sections': []}

    sections = find_sections(text)
    if not sections:
        sections = [{'title': None, 'start': 0, 'decl_end': 0, 'end': len(text),
                     'decl_count': None, 'per_score': None, 'total_score': None}]
        qa['flags'].append('无大题标题,整卷单段解析')

    expected = 1
    questions = []
    for sec in sections:
        cuts, expected, scan_flags = scan_section(text, sec['start'], sec['end'], sec['decl_end'], expected,
                                                  sec['decl_count'])
        for sf in scan_flags:
            qa['flags'].append('%s:%s' % (sec['title'] or '整卷', sf))
        start_num = cuts[0][1] if cuts else None
        bounds = [c[0] for c in cuts] + [min(sec['end'], len(text))]
        sec_questions = []
        for i in range(len(cuts)):
            body = text[bounds[i]:bounds[i + 1]]
            qno = int(re.match(r'\d+', body).group(0))
            pq = parse_question_text(qno, body)
            pq['section'] = sec['title']
            pq['_num'] = cuts[i][1]
            pq['_score'] = sec['total_score'] if sec['decl_count'] == 1 else sec['per_score']
            sec_questions.append(pq)
        questions.extend(sec_questions)
        declared, actual = sec['decl_count'], len(sec_questions)
        flag = '声明%d题/实际%d题' % (declared, actual) if declared and actual != declared else None
        qa['sections'].append({'title': sec['title'], 'declared': declared, 'actual': actual,
                               'start_num': start_num, 'flag': flag})
        if flag:
            qa['flags'].append('%s:%s' % (sec['title'], flag))

    apath = resolve_answer_path(meta)
    answers = parse_answers(load_text(apath)) if apath and apath.exists() else {}
    if not answers:
        qa['flags'].append('答案文件缺失或为空')

    for i, q in enumerate(questions):
        raw = answers.get(q.get('_num', i + 1))
        shape, content = classify_answer(raw)
        status, provenance = ANSWER_CONTRACT[shape]
        q['answer'] = content
        q['answer_status'] = status
        q['answer_provenance'] = provenance
        if shape == 'brief':
            q['analysis'] = content
        if len(q['options']) == 1:
            qa['flags'].append('q%d 仅1个选项,疑似切分异常' % (i + 1))
        if len(q['stem'].strip()) < 10 or '暂缺' in q['stem']:
            qa['flags'].append('q%d 题干过短或疑似源文缺失' % (i + 1))
        if len(q['options']) >= 2 and status == 'letter_only' and content and len(content) == 1 \
                and content not in [o['key'] for o in q['options']]:
            qa['flags'].append('q%d 答案%s不在选项中' % (i + 1, content))
    qa['question_count'] = len(questions)
    extra_ans = [k for k in answers if k > len(questions)]
    if extra_ans:
        qa['flags'].append('答案编号超出题数:%s' % extra_ans[:8])
    return questions, qa, text


# ---------------------------------------------------------------- S5 落库

def paper_session(meta):
    session = meta['session'] + ('-jx' if meta['variant'] == '精选' else '')
    if meta['paper'] in ('A级', 'B级'):
        session += '-' + ('a' if meta['paper'] == 'A级' else 'b')
    return session


def norm_stem(s):
    return re.sub(r'[\s，。、；：？！“”‘’"\'（）()【】\[\]《》,.;:?!]', '', s)


def render_card(rec, material_text):
    is_choice = rec['question_type'] in ('单选', '多选')
    ans = rec['content']['answer']
    ans_disp = ans if ans else '未提供'
    lines = [
        '---',
        'id: %s' % rec['question_id'],
        'exam: %s' % rec['exam'],
        'level: %s' % rec['level'],
        'school_level: %s' % rec.get('school_level', rec.get('level')),
        'subject: %s' % rec['subject'],
        'session: "%s"' % rec['source']['session'],
        'section: %s' % (rec['section'] or '未标注'),
        'question_type: %s' % rec['question_type'],
        'score: %s' % (rec['score'] if rec['score'] else 'null'),
    ]
    if rec.get('material_id'):
        lines.append('material_id: %s' % rec['material_id'])
    lines.extend([
        'answer: %s' % (ans_disp if is_choice else ('有' if ans else 'null')),
        'answer_status: %s' % rec['content']['answer_status'],
        'knowledge_nodes: [%s]' % ', '.join(rec.get('knowledge_node_ids', [])),
        'ability_ids: [%s]' % ', '.join(rec.get('ability_ids', [])),
        'exam_requirement_ids: [%s]' % ', '.join(rec.get('exam_requirement_ids', [])),
        'review_status: %s' % rec['review']['status'],
        'content_verified: %s' % str(rec['review'].get('content_verified', False)).lower(),
        'copyright_scope: %s' % rec.get('source', {}).get('copyright', {}).get('use_scope', 'research_non_commercial'),
        'source_nature: %s' % rec.get('source', {}).get('copyright', {}).get('source_nature', 'official_exam'),
    ])
    if rec.get('rubric_id'):
        lines.append('rubric_id: %s' % rec['rubric_id'])
    if rec['extra'].get('duplicate_of'):
        lines.append('duplicate_of: %s' % rec['extra']['duplicate_of'])
    lines += ['---', '']
    lines.append('【%s · %s·%s · %s · 第%d题】' % (
        rec['source']['session'], rec['level'], rec['subject'],
        rec['question_type'], rec['extra']['paper_order']))
    lines.append('')
    if material_text:
        lines += ['**材料:**', material_text, '']
    lines += [rec['content']['stem'], '']
    lines += ['- %s. %s' % (o['key'], o['text']) for o in rec['content']['options']]
    if rec['content']['options']:
        lines.append('')
    lines.append('**答案:%s**' % ans_disp if is_choice else '**答案:** %s' % ans_disp)
    lines.append('')
    # 结构化三段解析（题眼定位、选项对比/得分点、溯源）
    analysis = rec.get('analysis')
    if isinstance(analysis, dict) and any(analysis.get(k) for k in ('key_info', 'option_compare', 'trace_back')):
        lines.append('**【结构化解析】**')
        if analysis.get('key_info'):
            lines.append('**考点剖析与关键信息:** %s' % analysis['key_info'])
        if analysis.get('option_compare'):
            lines.append('**选项深度对比/得分点:** %s' % analysis['option_compare'])
        if analysis.get('trace_back'):
            lines.append('**考点溯源与理论依据:** %s' % analysis['trace_back'])
        if analysis.get('explanation') and not (analysis.get('key_info') and analysis.get('option_compare')):
            lines.append('**补充说明:** %s' % analysis['explanation'])
    elif rec['content'].get('analysis'):
        value = rec['content']['analysis']
        lines.append('**解析:** %s' % (json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value))
    else:
        lines.append('**解析:**(原库未提供,待补充)')
    return '\n'.join(lines) + '\n'



def build():
    # 已有知识库的build是安全复算入口，避免重新按顺序分配ID并覆盖人工修订。
    if any((OUT / 'questions').glob('*/*/*.jsonl')):
        from ntce_repair import repair
        repair()
        return
    metas = build_inventory()
    unparsed = [m for m in metas if m['unparsed']]
    print('文件总数 %d, 未识别科目 %d' % (len(metas), len(unparsed)))
    for sub in ('questions', 'materials', 'cards'):
        out_file(sub).mkdir(parents=True, exist_ok=True)

    text_hash_seen = {}   # 全文指纹 → 首次出处(跨目录重复卷)
    stem_hash_seen = {}   # 题干指纹 → 首个 question_id(去重)
    session_seen = Counter()
    all_qa, stats = [], []
    id_seen = Counter()
    q_total = m_total = dup_total = folder_dup = 0

    for meta in metas:
        if meta['unparsed']:
            all_qa.append({'file': meta['dir'] + '/' + meta['file'],
                           'flags': ['科目未识别,跳过'], 'sections': []})
            continue
        questions, qa, full_text = parse_paper(meta)
        fp = sha(norm_stem(full_text))
        if fp in text_hash_seen:
            folder_dup += 1
            qa['flags'].append('与 %s 内容相同,跳过' % text_hash_seen[fp])
            all_qa.append(qa)
            continue
        text_hash_seen[fp] = meta['dir'] + '/' + meta['file']
        if not questions:
            qa['flags'].append('未解析出任何题目')
            all_qa.append(qa)
            continue

        prefix = 'shengkao' if meta['system'] == '省考' else 'ntce'
        level, subject = safe_part(meta['level']), safe_part(meta['subject'])
        skey = (level, subject, paper_session(meta))
        session_seen[skey] += 1
        if session_seen[skey] > 1:
            session = safe_part(paper_session(meta) + '-k%d' % session_seen[skey])
            qa['flags'].append('场次冲突改用 %s' % session)
        else:
            session = safe_part(paper_session(meta))

        mat_recs = []
        for q in questions:
            if q.get('material_text'):
                mid = '%s.%s.%s.%s.m%02d' % (prefix, level, subject, session, len(mat_recs) + 1)
                mat_recs.append({'material_id': mid, 'text': q['material_text']})
                q['material_id'] = mid
                del q['material_text']

        # 复核分级(题级):严重异常与一般瑕疵都是 needs_fix，靠 review_priority 分级；无标记=auto_parsed
        major = False
        for f in qa['flags']:
            if any(h in f for h in ('未解析', 'ID 冲突', '科目未识别', '缺失或为空', '不在选项中')):
                major = True
            mm = re.search(r'声明(\d+)题/实际(\d+)题', f)
            if mm and (abs(int(mm.group(1)) - int(mm.group(2))) > 3 or int(mm.group(2)) == 0):
                major = True
        if major:
            review_status, review_priority = 'needs_fix', 'low_confidence'
        elif qa['flags']:
            review_status, review_priority = 'needs_fix', 'flagged_general'
        else:
            review_status, review_priority = 'auto_parsed', 'none'
        q_severe = ('仅1个选项', '不在选项中', '题干过短')
        out_q = []
        for i, q in enumerate(questions):
            qid = '%s.%s.%s.%s.q%02d' % (prefix, level, subject, session, i + 1)
            id_seen[qid] += 1
            if id_seen[qid] > 1:
                qa['flags'].append('ID 冲突改用 %s_%d' % (qid, id_seen[qid]))
                qid += '_%d' % id_seen[qid]
            ns = sha(norm_stem(q['stem']))
            dup_of = stem_hash_seen.get(ns)
            if dup_of:
                dup_total += 1
            else:
                stem_hash_seen[ns] = qid

            qtype = TYPE_MAP.get(q['section'] or '', '未标注')
            opts = q.get('options') or []
            if len(opts) >= 2 and opts[0]['key'] == 'A' and qtype not in ('单选', '多选', '未标注'):
                qtype = '单选'
                qa['flags'].append('q%d 有选项但大题为%s,题型改判单选' % (i + 1, q['section']))
            # 题级复核状态:本题自身的严重异常优先于整卷评级
            qflagged = [f for f in qa['flags'] if f.startswith('q%d ' % (i + 1))]
            if any(h in f for f in qflagged for h in q_severe):
                q_status, q_priority = 'needs_fix', 'low_confidence'
            elif qflagged or review_status != 'auto_parsed':
                q_status = 'needs_fix'
                q_priority = review_priority if review_status != 'auto_parsed' else 'flagged_general'
            else:
                q_status, q_priority = review_status, review_priority
            rec = {
                'question_id': qid,
                'exam': 'NTCE' if meta['system'] == '国考' else '省考',
                'level': level, 'subject': subject,
                'source': {'type': '真题', 'system': meta['system'], 'session': session,
                           'paper': meta['paper'], 'variant': meta['variant'],
                           'origin_file': '教资/真题/%s/%s' % (meta['dir'], meta['file']),
                           'verified': False,
                           'raw_file_verification': {'status': 'file_exists', 'content_alignment': 'pending'},
                           'content_verification': {'status': 'not_reviewed'}},
                'section': q['section'], 'question_type': qtype,
                'material_id': q.get('material_id'),
                'score': q.get('_score'),
                'content': {'stem': q['stem'], 'options': opts, 'answer': q['answer'],
                            'answer_status': q['answer_status'], 'analysis': q.get('analysis')},
                'knowledge_node_ids': [], 'difficulty': None,
                'review': {'status': q_status, 'review_priority': q_priority, 'tagger': None,
                           'checked_by': None, 'content_verified': False},
                'extra': {'duplicate_of': dup_of, 'paper_order': i + 1,
                          'answer_provenance': q.get('answer_provenance')},
            }
            out_q.append(rec)

            out_file('cards', level, subject, session).mkdir(parents=True, exist_ok=True)
            if not dup_of:  # 重复题不落卡片,避免污染向量库
                mat_text = next((m['text'] for m in mat_recs if m['material_id'] == q.get('material_id')), None)
                card_name = 'q%02d.md' % (i + 1)
                out_file('cards', level, subject, session, card_name).write_text(
                    render_card(rec, mat_text), encoding='utf-8')

        qtext = '\n'.join(json.dumps(rec, ensure_ascii=False) for rec in out_q) + '\n'
        qjsonl = '%s.jsonl' % session
        out_file('questions', level, subject).mkdir(parents=True, exist_ok=True)
        out_file('questions', level, subject, qjsonl).write_text(qtext, encoding='utf-8')
        if mat_recs:
            mtext = '\n'.join(json.dumps(m, ensure_ascii=False) for m in mat_recs) + '\n'
            out_file('materials', level, subject).mkdir(parents=True, exist_ok=True)
            out_file('materials', level, subject, qjsonl).write_text(mtext, encoding='utf-8')
            m_total += len(mat_recs)
        q_total += len(out_q)
        all_qa.append(qa)
        stats.append({'level': level, 'subject': subject, 'session': session,
                      'n': len(out_q), 'flags': len(qa['flags'])})

    write_reports(metas, all_qa, stats, q_total, m_total, dup_total, folder_dup, unparsed)
    print('完成:题目 %d, 材料 %d, 标记重复题 %d, 跳过跨目录重复卷 %d' %
          (q_total, m_total, dup_total, folder_dup))
    from ntce_repair import repair
    repair()


def write_reports(metas, all_qa, stats, q_total, m_total, dup_total, folder_dup, unparsed):
    sm = {}
    for m in metas:
        key = '%s|%s' % (m['raw_subject'], m['level'])
        if key not in sm:
            sm[key] = {'raw': m['raw_subject'], 'level': m['level'], 'subject': m['subject'],
                       'subject_cn': m.get('subject_cn'), 'count': 0}
        sm[key]['count'] += 1
    out_file('subject_map.json').write_text(
        json.dumps(sorted(sm.values(), key=lambda x: -x['count']), ensure_ascii=False, indent=1),
        encoding='utf-8')

    lv_c, sub_c = Counter(), Counter()
    for s in stats:
        lv_c[s['level']] += s['n']
        sub_c['%s/%s' % (s['level'], s['subject'])] += s['n']
    manifest = {
        'name': '教资真题知识库 v1',
        'generated': '2026-10-02',
        'source_dir': '教资/真题',
        'source_files': len(metas),
        'questions': q_total,
        'materials': m_total,
        'duplicate_questions_marked': dup_total,
        'folder_duplicates_skipped': folder_dup,
        'by_level': dict(lv_c),
        'by_level_subject': dict(sorted(sub_c.items())),
        'known_limitations': [
            '原库基本无解析:answer_status=letter_only/reference_only 占多数,analysis 字段多为空',
            '结构切分为规则解析,低置信卷与异常题见 qa_report.md',
            '省考老卷(四川/辽宁)单独标记 exam=省考',
        ],
        'field_dict': '见 教资知识库整理方案.md 3.1',
    }
    out_file('MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                         encoding='utf-8')

    lowconf = [q for q in all_qa if q.get('flags')]
    lines = ['# 教资KB 质检报告', '',
             '- 试卷文件:%d,解析出题:%d,材料:%d' % (len(metas), q_total, m_total),
             '- 标记重复题:%d,跨目录重复卷跳过:%d' % (dup_total, folder_dup), '',
             '## 未识别科目的文件(%d)' % len(unparsed), '']
    for m in unparsed:
        lines.append('- %s/%s (raw=%r)' % (m['dir'], m['file'], m['raw_subject']))
    lines += ['', '## 带标记的试卷(%d)' % len(lowconf), '']
    for q in lowconf:
        lines.append('- **%s**:%s' % (q['file'], ';'.join(q['flags'])))
    out_file('qa_report.md').write_text('\n'.join(lines), encoding='utf-8')


# ---------------------------------------------------------------- 命令

def cmd_inventory():
    metas = build_inventory()
    unparsed = [m for m in metas if m['unparsed']]
    print('总数:%d  未识别:%d' % (len(metas), len(unparsed)))
    for m in unparsed:
        print('  ?', m['dir'] + '/' + m['file'])
    c = Counter((m['level'], m['subject'], m['system']) for m in metas)
    for k, v in sorted(c.items(), key=lambda x: (str(x[0][0]), str(x[0][1]), str(x[0][2]))):
        print('%-14s %-16s %s: %d' % (k[0], str(k[1]), k[2], v))
    seen = defaultdict(list)
    for m in metas:
        seen[m['file']].append(m['dir'])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    print('跨目录同名文件:%d 个' % len(dups))
    for k, v in list(dups.items())[:5]:
        print('  ', k, v)


def cmd_sample(n):
    metas = [m for m in build_inventory() if not m['unparsed']]
    picks = metas[::max(1, len(metas) // n)][:n]
    for meta in picks:
        questions, qa, _ = parse_paper(meta)
        print('=' * 30, meta['dir'] + '/' + meta['file'],
              '| level=%s subject=%s session=%s' % (meta['level'], meta['subject'], meta['session']))
        print('  sections:', [(s['title'], s['declared'], s['actual']) for s in qa['sections']])
        if qa['flags']:
            print('  flags:', qa['flags'])
        for q in questions[:2]:
            print('  --- q:', (q['stem'] or '')[:80].replace('\n', '⏎'))
            for o in q['options'][:4]:
                print('      %s. %s' % (o['key'], o['text'][:30]))
            print('      答案:', q['answer'], '| 状态:', q['answer_status'])
        if questions:
            q = questions[-1]
            print('  --- 末题:', (q['stem'] or '')[:80].replace('\n', '⏎'), '| 答案:', q['answer'])


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'inventory'
    if cmd == 'inventory':
        cmd_inventory()
    elif cmd == 'sample':
        cmd_sample(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif cmd == 'build':
        build()
    else:
        print(__doc__)
