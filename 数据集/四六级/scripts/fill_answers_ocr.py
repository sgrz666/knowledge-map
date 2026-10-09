# -*- coding: utf-8 -*-
"""补齐四六级 KB 的答案与逐题解析(第三轮:OCR 修复损坏源 + 证据分级绑定)。

与 fill_answers.py(第二轮)的关系:
1. 文本层可读的解析 PDF/DOCX 沿用 fill_answers.source_candidates 的候选提取;
2. 文本层损坏的解析 PDF(扫描件/字体编码损坏)先经 Windows 内置 OCR(zh-Hans-CN, 200dpi)重建文本,
   OCR 结果缓存在 scripts/_staging/ocr_cache/,重复运行不重扫;
3. 绑定证据分级(全部保持 pending_expert_review,不冒充专家已核):
   - level_a_identity: 题干命中或 >=2 个完整选项命中(与第二轮同标准);
   - level_b_dedicated_source_content_crosscheck: 专用解析册 + 题号 + 块内 >=1 选项片段/题干词条命中;
   - level_b_dedicated_source_qa_structure: 专用解析册 + 题号 + 块内"答案字母+解析标签"结构
     (仅当该源在本套卷覆盖 >=15 个题号,即整册对齐良好时启用);
   - published_answer_grid: 专用解析册内印刷的成段答案表(如 1-5 BACBD)。
4. 已有答案不覆盖(冲突只记录候选);已有解析不覆盖,只补空缺。
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fill_answers as fa  # noqa: E402
from cet_common import jsonl_dumps, load_jsonl  # noqa: E402

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
fitz.TOOLS.mupdf_display_errors(False)

HERE = Path(__file__).resolve().parent
KB_DEFAULT = HERE.parent
ROOT = HERE.parents[2]
STAGE = HERE / '_staging'
SRC = ROOT / '英语四六级资料合集（2026年最新）(1)'
OCR_CACHE = STAGE / 'ocr_cache'
OCR_DPI = 200
OCR_ENGINE = 'Windows.Media.Ocr zh-Hans-CN'
RULE_VERSION = 4

DATE = fa.DATE
CN = fa.CN

CJK = r'\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u2018\u2019\u201c\u201d'
MOJIBAKE = r'\u0900-\u0dff\u0e00-\u0fff\uf900-\ufaff\ue000-\uf8ff\ufffd'
STOP = re.compile(
    r'(?m)^\s*(?:Part\s+[IVX]+\b|Section\s+[ABC]\b|Questions?\s+\d+|'
    r'(?:News Report|Conversation|Passage|Lecture|Recording)\s+(?:One|Two|Three)\b|'
    r'【听力原文】|【答案速查】|【参考答案】)')
GRID = re.compile(r'(?<![0-9])(\d{1,2})\s*[-—–~至]{1,2}\s*(\d{1,2})\s*((?:[A-O][\s,，、]*){2,20})')
PAIR_GRID = re.compile(r'(?<![\d.])(\d{1,2})\s*[.．、]\s*([A-O])(?![A-Za-z])')
QSTART_OCR = re.compile(r'(?m)^\s*(\d{1,2})\s*(?:[.．、,，]\s*|\s+)(?=[A-Za-z一-鿿【\[])')
ROMAN_ONE = re.compile(r'(?m)^\s*I\s*[.．、]\s*(?=[A-Z])')
ANS_HEAD = re.compile(r'(?:【|\[)?\s*(?:答案|正确答案)\s*(?:】|\])?\s*[:：]?\s*为?\s*([A-O])(?![A-Za-z])')
LETTER_LABEL = re.compile(r'([A-O])\s*[)）]?\s*[【\[]\s*(?:精析|解析|定位|听音重点|解题思路|点睛|干扰分析)')
EXPL_LABEL = re.compile(r'(?:【|\[)\s*(?:精析|解析|详解|定位|听音重点|解题思路|点睛|干扰分析|答案解析)\s*[】\]]?\s*[:：]?')
SET_HEADER = re.compile(r'(?:第\s*([一二三1-3])\s*套|（\s*([一二三1-3])\s*）)')
ANS_PATTERNS = fa.ANS_PATTERNS[:4]  # 丢弃“X 项与…相符”:OCR 噪声下误报过高
PROSE_PATTERNS = ANS_PATTERNS + [re.compile(r'(?:正确项|正确选项)\s*(?:为|是)\s*([A-O])(?![A-Za-z])')]
ANSWER_JIEXI = re.compile(r'(?:【|\[)\s*答\s*案\s*精\s*析\s*(?:】|\])?\s*[:：]?\s*([A-O])\s*[)）]?')
JIEXI_LABEL = re.compile(r'(?:【|\[)\s*答\s*案\s*精\s*析\s*(?:】|\])?')


def file_key(name, exam_hints=''):
    # 日期/卷号只从文件名取(父目录里的 2015-2025.06 之类会污染年份);
    # 考试关键词优先文件名,缺失时回退路径(cet4/cet6 目录),“四六级”通用词不算证据
    dm, pm = DATE.search(name), fa.PAPER.search(name)
    if not pm:
        pm = re.search(r'卷\s*([一二三1-3])', name)
    if not dm or not pm:
        return None
    clean = re.sub(r'四六级', '', exam_hints)
    exam = ('CET-4' if re.search(r'四级|4级|CET4', name, re.I) else
            ('CET-6' if re.search(r'(?<!四)六级|(?<!cet)6级|CET6', name, re.I) else None)) or \
           ('CET-4' if re.search(r'四级|4级|CET4', clean, re.I) else
            ('CET-6' if re.search(r'(?<!四)六级|(?<!cet)6级|CET6', clean, re.I) else None))
    if not exam or not 1 <= int(dm[2]) <= 12:
        return None
    return exam, f'{dm[1]}-{int(dm[2]):02d}', CN.get(pm[1], int(pm[1]) if pm[1].isdigit() else 0)


def exam_of(name):
    if re.search(r'四级|4级|CET4', name, re.I):
        return 'CET-4'
    if re.search(r'六级|6级|CET6', name, re.I):
        return 'CET-6'
    return None


# ---------------------------------------------------------------- 文本层质量与 OCR

def pdf_text_quality(path):
    """→ ('good'|'ocr_needed')"""
    try:
        with fitz.open(path) as doc:
            text = ''.join(pg.get_text(sort=True) for pg in doc)
    except Exception:
        return 'ocr_needed'
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    weird = len(re.findall(r'[' + MOJIBAKE + r']', text))
    if cjk >= 200 and weird / max(cjk + weird, 1) < 0.05:
        return 'good'
    return 'ocr_needed'


def ocr_pdf(path, force=False):
    """渲染每页并 OCR;返回 [(page_no, text)],带磁盘缓存。"""
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OCR_CACHE / (re.sub(r'[^\w.-]', '_', path.stem)[:80] + f'.{OCR_DPI}dpi.txt')
    if cache.exists() and not force:
        pages, cur = [], None
        for line in cache.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^===PAGE (\d+)===$', line)
            if m:
                cur = int(m.group(1))
                pages.append((cur, []))
            elif pages:
                pages[-1][1].append(line)
        if pages:
            return [(n, '\n'.join(ls)) for n, ls in pages]
    with fitz.open(path) as doc:
        tmpdir = OCR_CACHE / ('_png_' + re.sub(r'[^\w.-]', '_', path.stem)[:60])
        tmpdir.mkdir(parents=True, exist_ok=True)
        imgs = []
        for i, pg in enumerate(doc):
            out = tmpdir / f'p{i + 1:03d}.png'
            if not out.exists():
                pg.get_pixmap(dpi=OCR_DPI).save(str(out))
            imgs.append(str(out))
    listfile = OCR_CACHE / ('_list_' + re.sub(r'[^\w.-]', '_', path.stem)[:60] + '.txt')
    listfile.write_text('\n'.join(imgs), encoding='utf-8')
    ps = HERE / 'ocr_batch.ps1'
    proc = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps),
         '-ListFile', str(listfile)], capture_output=True, timeout=3600)
    text = proc.stdout.decode('utf-8', errors='replace')
    pages, cur = [], None
    for line in text.splitlines():
        m = re.match(r'^===PAGE (\d+)===$', line)
        if m:
            cur = int(m.group(1))
            pages.append((cur, []))
        elif pages:
            pages[-1][1].append(line)
    pages = [(n, '\n'.join(ls)) for n, ls in pages]
    if proc.returncode != 0 or not pages:
        raise RuntimeError(f'OCR failed rc={proc.returncode}: '
                           + proc.stderr.decode('utf-8', errors='replace')[:300])
    cache.write_text(text, encoding='utf-8')
    return pages


def normalize_ocr_line(line):
    line = unicodedata.normalize('NFKC', line)
    # 各出版社括号风格统一为 【】
    line = line.translate(str.maketrans('〖〗〔〕《》', '【】【】【】'))
    line = re.sub(r'(?<=[' + CJK + r'])[ \t]+(?=[' + CJK + r'])', '', line)
    line = re.sub(r'[ \t]{2,}', ' ', line)
    return line.strip()


def build_ocr_text(pages):
    lines = []
    for pno, txt in pages:
        for raw in txt.splitlines():
            ln = normalize_ocr_line(raw)
            if not ln:
                continue
            ln = ROMAN_ONE.sub('1. ', ln)
            m = re.match(r'^(\d{1,2})\s*[.．、]\s*(.*)$', ln)
            if m and re.match(r'^[A-Za-z【\[]', m.group(2) or ''):
                ln = f'{m.group(1)}. {m.group(2)}'
            lines.append((pno, ln))
    text = '\n'.join(ln for _, ln in lines)
    page_of, pos = [], 0
    for pno, ln in lines:
        page_of.append((pos, pos + len(ln) + 1, pno))
        pos += len(ln) + 1
    return text, page_of


def page_for(page_of, start, end):
    return sorted({p for a, b, p in page_of if b > start and a < end})[:30]


# ---------------------------------------------------------------- 块与候选提取

def ocr_question_blocks(text, page_of):
    anchors = [m for m in QSTART_OCR.finditer(text) if 1 <= int(m[1]) <= 55]
    blocks = []
    for i, m in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        body = text[m.end():end]
        stop = STOP.search(body)
        if stop:
            end = m.end() + stop.start()
        blocks.append({'n': int(m[1]), 'text': text[m.end():end].strip(),
                       'start': m.start(), 'end': end})
    return blocks


FOOTER = re.compile(
    r'\n\s*(?:共\s*\d+\s*页'
    r'|[46四六]\s*级\s*20?\d{0,2}\s*年\s*\d{1,2}\s*月[^\n]{0,24}页?'
    r'|\d{0,2}\s*年\s*\d{1,2}\s*月[46四六]\s*级真题第\s*\d+\s*套详解第\s*\d+\s*页[^\n]{0,8}'
    r'|Quetions\s*\d+\s*[a-z]*\s*\d+\s*[a-z]*\s*\d+[^\n]{0,20}'
    r'|Questions\s*\d+\s*t?o?\s*\d+[^\n]{0,20})\s*(?=\n|$)')


def block_answer_and_explanation(block_text):
    """→ (letters:set, explanation|None, marker, prose_letter|None)
    letters 只收“结构位”字母(块首/字母+解析标签);“【答案】C/答案为 C/故选 B”
    属正文提及,作为 prose 交叉参考:结构位字母 OCR 误读时用来兜底,
    正文提及不参与结构位判定,避免邻近题串扰。"""
    block_text = FOOTER.sub('\n', block_text)
    # prose 匹配用扁平文本:OCR 常把"正确答案"等词劈到两行
    flat = re.sub(r'(?<=[' + CJK + r'])\n(?=[' + CJK + r'])', '', block_text)
    structural, prose = set(), set()
    marker = None
    lines = block_text.split('\n')
    head = lines[0] if lines else ''
    m0 = re.match(r'^([A-O])\s*[)）]\s*(.*)$', head)
    if m0 and len(re.findall(r'[B-D]\s*[)）]', '\n'.join(lines[1:4]))) >= 2:
        m0 = None  # 块首是选项列表(随后还有 B)/C)/D)),不是答案位
    if m0:
        structural.add(m0.group(1))
        marker = 'head_letter'
    lm = LETTER_LABEL.search(block_text)
    if lm:
        structural.add(lm.group(1))
        marker = marker or 'letter_label'
    jm = ANSWER_JIEXI.search(block_text)
    if jm:
        structural.add(jm.group(1))
        marker = 'answer_jiexi_label'
    # 长篇阅读:定位句式给出段落字母(“定位到 E 段”/“EO 由题干关键信息”)
    ploc = (re.search(r'定位到\s*([A-Oa-o])\s*段', block_text)
            or re.search(r'([A-Oa-o])\s*[O0o。]{0,2}\s*由题干关键信息', block_text))
    if ploc:
        structural.add(ploc.group(1).upper())
        marker = marker or 'paragraph_locate'
    am = ANS_HEAD.search(flat)
    if am:
        prose.add(am.group(1))
    for pat in PROSE_PATTERNS:
        for m in pat.finditer(flat):
            prose.add(m[1])
            marker = marker or 'pattern'
    letters = structural or prose
    expl = None
    if jm:
        expl = block_text[jm.end():].strip()
    if expl is None and lm:
        expl = block_text[lm.end():].strip()
    if expl is None:
        em = EXPL_LABEL.search(block_text)
        if em:
            expl = block_text[em.end():].strip()
    if expl is None and ploc:
        expl = block_text[ploc.end():].strip()
    if expl is None and m0 and m0.group(2).strip():
        expl = m0.group(2).strip()
    expl = re.sub(r'^[』」】〕）)〗\s]+', '', expl or '')
    if expl is not None:
        cjk = len(re.findall(r'[\u4e00-\u9fff]', expl))
        weird = len(re.findall(r'[' + MOJIBAKE + r']', expl))
        if cjk < 12 or weird > max(8, cjk // 2):
            expl = None
    prose_letter = next(iter(prose)) if len(prose) == 1 else None
    return letters, expl, marker, prose_letter


def extract_grids(text, page_of, base=0):
    """印刷答案表 → [(题号, 字母, pages)]"""
    found = {}
    for m in GRID.finditer(text):
        lo, hi, span = int(m[1]), int(m[2]), m[3]
        letters = [c for c in re.sub(r'[\s,，、]', '', span) if c in 'ABCDEFGHIJKLMNO']
        if not (1 <= lo <= 55 and lo <= hi <= 55) or len(letters) != hi - lo + 1 or hi - lo + 1 < 3:
            continue
        pages = page_for(page_of, base + m.start(), base + m.end())
        for k, ch in enumerate(letters):
            found.setdefault(lo + k, (ch, pages))
    pair_matches = list(PAIR_GRID.finditer(text))
    pair_kept = []
    for m in pair_matches:
        # “N. A ) 选项内容”是编号选项列表;印刷答案表里字母后不会紧跟右括号
        if re.match(r'\s*[)）]', text[m.end():m.end() + 2]):
            continue
        # 密度过滤:真答案表成片出现(±300字符内>=4处),正文散落的“10. M”不算
        lo, hi = max(0, m.start() - 300), m.end() + 300
        near = sum(1 for x in pair_matches if x is not m and lo <= x.start() < hi)
        if near >= 4:
            pair_kept.append(m)
    for m in pair_kept:
        n, ch = int(m[1]), m[2]
        if 1 <= n <= 55 and n not in found:
            found[n] = (ch, page_for(page_of, base + m.start(), base + m.end()))
    return [(n, ch, pages) for n, (ch, pages) in found.items()]


def multi_set_segments(text):
    """全三套册:按 第X套/（X） 头分段;失败返回 None。"""
    hdrs = [m for m in SET_HEADER.finditer(text)]
    segs, last = [], None
    for h in hdrs:
        cn = h[1] or h[2]
        pnum = CN.get(cn, int(cn) if cn and cn.isdigit() else None)
        if pnum is None or pnum == last:
            continue
        last = pnum
        segs.append([pnum, h.end()])
    if len(segs) < 2:
        return None
    out = []
    for i, (pnum, begin) in enumerate(segs):
        finish = segs[i + 1][1] if i + 1 < len(segs) else len(text)
        out.append((pnum, begin, finish))
    return out


def zhuanxiang_offset(name, n):
    """专项册题号映射:已是全卷编号(26-55)直接透传;按节重编号(1-10)时依据
    文件名中的节名映射回全卷题号。"""
    if 26 <= n <= 55:
        return n
    if not 1 <= n <= 15:
        return None
    if '选词填空' in name:
        return n + 25 if n <= 10 else None
    if '长篇阅读' in name or '信息匹配' in name or '匹配' in name:
        return n + 35 if n <= 10 else None
    if '仔细阅读' in name or '精读' in name:
        return n + 45 if n <= 10 else None
    return None


def collect_source_paths():
    seen = []
    for base in (STAGE, SRC):
        if not base.exists():
            continue
        for path in sorted(base.rglob('*')):
            if path.suffix.lower() not in ('.pdf', '.docx') or not path.is_file():
                continue
            if not re.search(r'解析|答案|详解|精析', path.name):
                continue
            try:
                rp = str(path.resolve().relative_to(ROOT)).replace('\\', '/')
            except ValueError:
                continue
            seen.append((path, rp))
    return seen


def source_candidates_all(progress=None):
    """→ candidates[(exam,ym,pnum)][n]=[item], diagnostics[]"""
    candidates = defaultdict(lambda: defaultdict(list))
    diagnostics = []

    def add(key, n, item):
        if 1 <= n <= 55:
            candidates[key][n].append(item)

    paths = collect_source_paths()
    quality_map = {}
    qcache = OCR_CACHE / 'quality_map.json'
    qcache_data = {}
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    if qcache.exists():
        try:
            qcache_data = json.loads(qcache.read_text(encoding='utf-8'))
        except Exception:
            qcache_data = {}
    dirty = False
    for path, rp in paths:
        if path.suffix.lower() == '.pdf':
            sig = rp + '|' + str(int(path.stat().st_mtime))
            if sig in qcache_data:
                quality_map[rp] = qcache_data[sig]
                continue
            quality_map[rp] = pdf_text_quality(path)
            qcache_data[sig] = quality_map[rp]
            dirty = True
        else:
            quality_map[rp] = 'good'
    if dirty:
        qcache.write_text(json.dumps(qcache_data, ensure_ascii=False), encoding='utf-8')
    diagnostics.append({'step': 'quality_map', 'total': len(quality_map),
                        'ocr_needed': sum(v == 'ocr_needed' for v in quality_map.values())})

    # 1) 文本层可读的源:复用 fill_answers 候选(键为 (exam,ym,pnum,题号))
    fa_cands, fa_diag = fa.source_candidates(SRC, STAGE, ROOT)
    diagnostics += fa_diag
    dropped_text = 0
    text_covered = set()
    for (key, n), items in fa_cands.items():
        kept = False
        for it in items:
            if quality_map.get(it['source']['path']) != 'good':
                dropped_text += 1
                continue
            kept = True
            add(key, n, {'answer': it['answer'], 'expl': it.get('raw'),
                         'block': it.get('block') or '', 'pages': [],
                         'level': 'text', 'path': it['source']['path'],
                         'method': 'text_layer',
                         'source': it['source']})
        if kept:
            text_covered.add((key, n))
    diagnostics.append({'step': 'fa_candidates_dropped_non_good', 'count': dropped_text})

    # 2) OCR 源:损坏文件全量 OCR;文本层良好的专用解析册也补一遍 OCR
    #    (fa 的 sort=True 对双栏/表格排版常错序,OCR 候选只填文本层没覆盖的题号)
    for path, rp in paths:
        if path.suffix.lower() != '.pdf':
            continue
        meta = file_key(path.name, rp)  # 日期/卷号取文件名;考试关键词可回退路径
        is_multi = bool(re.search(r'全\s*[二三23]\s*套|三套全', path.name))
        quality = quality_map[rp]
        if quality == 'good':
            if not meta or is_multi:
                continue  # good 且多套/无卷号的文件继续交给 fa 处理
        if not meta and not is_multi:
            diagnostics.append({'path': rp, 'ocr': 'skipped_no_paper_key'})
            continue
        try:
            pages = ocr_pdf(path)
        except Exception as e:
            diagnostics.append({'path': rp, 'ocr': 'error', 'error': str(e)[:200]})
            continue
        text, page_of = build_ocr_text(pages)
        name = path.name
        if is_multi:
            segs = multi_set_segments(text)
            if not segs:
                diagnostics.append({'path': rp, 'ocr': 'multi_set_segmentation_failed'})
                continue
        elif meta:
            segs = [(meta[2], 0, len(text))]
        else:
            continue
        exam = meta[0] if meta else exam_of(path.name) or exam_of(re.sub(r'四六级', '', rp))
        dm = DATE.search(name)
        ym = meta[1] if meta else (f'{dm[1]}-{int(dm[2]):02d}' if dm else None)
        if not ym:
            diagnostics.append({'path': rp, 'ocr': 'skipped_no_date'})
            continue
        is_zhuanxiang = '专项' in rp  # 专项册按节重排,依据文件名节名映射回全卷题号
        n_blocks_total = []
        for pnum, begin, finish in segs:
            key = (exam, ym, pnum)
            seg = text[begin:finish]
            seg_page_of = [(a - begin, b - begin, p) for a, b, p in page_of
                           if b > begin and a < finish]
            blocks = ocr_question_blocks(seg, seg_page_of)
            nb = 0
            for blk in blocks:
                n_eff = blk['n']
                if is_zhuanxiang:
                    mapped = zhuanxiang_offset(path.name, n_eff)
                    if mapped is None:
                        continue
                    n_eff = mapped
                if quality == 'good' and (key, n_eff) in text_covered:
                    continue
                letters, expl, marker, prose = block_answer_and_explanation(blk['text'])
                if not letters:
                    continue
                nb += 1
                blk_pages = page_for(seg_page_of, blk['start'], blk['end'])
                for ch in letters:
                    if ch not in 'ABCDEFGHIJKLMNO':
                        continue
                    add(key, n_eff, {'answer': ch, 'expl': expl,
                                        'block': blk['text'][:1500], 'pages': blk_pages,
                                        'level': 'ocr_block', 'path': rp,
                                        'method': f'ocr_{marker}',
                                        'prose_answer': prose if prose != ch else None})
            for n0, ch, gpages in extract_grids(seg, seg_page_of):
                n_eff = n0
                if is_zhuanxiang:
                    mapped = zhuanxiang_offset(path.name, n_eff)
                    if mapped is None:
                        continue
                    n_eff = mapped
                if quality == 'good' and (key, n_eff) in text_covered:
                    continue
                add(key, n_eff, {'answer': ch, 'expl': None, 'block': '', 'pages': gpages,
                                 'level': 'ocr_grid', 'path': rp, 'method': 'published_answer_grid'})
            n_blocks_total.append((pnum, nb))
        diagnostics.append({'path': rp, 'ocr': 'ok', 'pages': len(pages),
                            'blocks_per_set': n_blocks_total})
        if progress:
            progress(rp)
    return candidates, diagnostics


# ---------------------------------------------------------------- 身份证据

STEM_STOP = {
    'what', 'which', 'when', 'where', 'does', 'author', 'about', 'according', 'report',
    'news', 'passage', 'that', 'they', 'their', 'them', 'this', 'these', 'those', 'have',
    'will', 'would', 'could', 'should', 'from', 'with', 'were', 'been', 'most', 'likely',
    'mainly', 'following', 'woman', 'women', 'people', 'some', 'such', 'into', 'says',
    'said', 'suggest', 'imply', 'know', 'learn', 'infer', 'give', 'gives', 'achieve'}


def normalized(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def stem_terms(stem):
    return [w.lower() for w in re.findall(r'[A-Za-z]{4,}', stem) if w.lower() not in STEM_STOP]


def identity_level_a(content, block):
    raw = normalized(block)
    target = normalized(content.get('stem') or '')
    if len(target) >= 8 and target in raw:
        return True, 'stem_in_block'
    terms = stem_terms(content.get('stem') or '')
    if len(terms) >= 2:
        hits = sum(normalized(w) in raw for w in terms)
        if hits >= 2 and hits / len(terms) >= 0.7:
            return True, 'stem_terms'
    options = [normalized(v) for v in (content.get('options') or {}).values()
               if len(normalized(v)) >= 12]
    if sum(v in raw for v in options) >= 2:
        return True, 'two_options'
    return False, None


def identity_level_b(content, block):
    raw = normalized(block)
    for v in (content.get('options') or {}).values():
        nv = normalized(v)
        if len(nv) >= 6 and nv in raw:
            return True, 'option_fragment'
    if sum(normalized(w) in raw for w in stem_terms(content.get('stem') or '')[:12]) >= 1:
        return True, 'stem_term'
    return False, None


def identity_level_b2(block):
    """“字母+解析标签”结构本身;配合整册覆盖度使用。"""
    return bool(EXPL_LABEL.search(block)) or bool(LETTER_LABEL.search(block))


# ---------------------------------------------------------------- 入库

def fill_rows(rows, key, candidates, coverage, report):
    by_n = candidates.get(key, {})
    for r in rows:
        ex = r.setdefault('extra', {})
        if ex.get('active') is False:
            continue
        c = r.setdefault('content', {})
        n = ex.get('source_question_number') or ex.get('number')
        if n is None:
            continue
        items = by_n.get(n, [])
        if not items:
            if not c.get('answer') or not r.get('analysis', {}).get('raw'):
                report['still_missing'] += 1
            continue
        # 按题型过滤非法字母:听力/仔细阅读只认 ABCD 且须在选项中;选词填空/长篇阅读 A-O
        probe_row = {'question_type': r.get('question_type', ''), 'content': c}

        def legal(ans):
            if fa.valid_key(probe_row, ans):
                return True
            opts = c.get('options') or {}
            return ans in 'ABCDEFGHIJKLMNO' and not opts and \
                r.get('question_type') in ('选词填空', '长篇阅读')

        usable = []
        for it in items:
            a0 = it['answer']
            if not legal(a0) and it.get('prose_answer') and legal(it['prose_answer']):
                it = dict(it, answer=it['prose_answer'], prose_answer=None,
                          method=it['method'] + '+prose_fallback')
            if legal(it['answer']):
                usable.append(it)
        items = usable
        if not items:
            if not c.get('answer') or not r.get('analysis', {}).get('raw'):
                report['still_missing'] += 1
            continue
        strong, moderate, grids = [], [], []
        for it in items:
            if it['level'] in ('text', 'ocr_block'):
                ok_a, _ = identity_level_a(c, it['block'])
                if ok_a:
                    strong.append((it, 'level_a_identity'))
                    continue
                ok_b, _ = identity_level_b(c, it['block'])
                if ok_b:
                    moderate.append((it, 'level_b_dedicated_source_content_crosscheck'))
                    continue
                # 整册对齐时题号本身即足够证据:专用解析册覆盖>=15个题号;
                # 专项分节册覆盖>=8个题号(每节仅10题,如选词填空26-35)
                cov = coverage.get((key, it['path']), 0)
                if cov >= 15 or ('专项' in it['path'] and cov >= 8):
                    moderate.append((it, 'level_b_dedicated_source_numbering_coverage'))
            elif it['level'] == 'ocr_grid':
                grids.append((it, 'published_answer_grid'))
        chosen, binding = (strong[0][0], strong[0][1]) if strong else \
            ((moderate[0][0], moderate[0][1]) if moderate else
             ((grids[0][0], grids[0][1]) if grids else (None, None)))
        chosen_items = [t[0] for t in (strong or moderate or grids)]
        if not chosen:
            saved = ex.setdefault('unbound_answer_candidates', [])
            for it in items[:4]:
                entry = {'answer': it['answer'],
                         'source': {'path': it['path'], 'pages': it.get('pages')},
                         'reason': 'no_identity_evidence', 'level': it['level']}
                if entry not in saved:
                    saved.append(entry)
            report['unbound'] += 1
            continue
        keys = {it['answer'] for it in chosen_items}
        files = r.setdefault('source', {}).setdefault('files', [])

        def add_file_entry(it):
            loc = dict((it.get('source') or {}).get('locator')
                       or {'question_number': n, 'pages': it.get('pages')})
            loc['binding'] = binding
            loc['extraction'] = it['method']
            entry = {'path': it['path'], 'role': 'answer_analysis', 'locator': loc}
            if entry not in files:
                files.append(entry)

        # 来源指针:最多 3 条(避免逐题堆砌),优先带解析的块级证据
        with_expl_first = sorted(chosen_items, key=lambda it: (not it.get('expl'),
                                                         it['level'] != 'text'))
        for it in with_expl_first[:3]:
            add_file_entry(it)
        if c.get('answer'):
            if keys and c['answer'] not in keys:
                ex['answer_candidates'] = sorted(
                    ({'answer': it['answer'], 'source': it['path'], 'level': it['level']}
                     for it in chosen_items),
                    key=lambda d: (d['answer'], d['source'], d['level']))[:8]
                report['conflicts'] += 1
            elif ex.get('answer_status') in ('legacy_source_pending', 'missing_source', None, ''):
                ex['answer_status'] = 'source_extracted_pending_expert_review'
                ex['answer_extraction'] = {
                    'method': binding, 'rule_version': RULE_VERSION,
                    'source_count': len(chosen), 'binding': binding,
                    'expert_review': {'status': 'pending', 'reviewer': None, 'reviewed_at': None}}
                report['legacy_answer_upgraded'] += 1
        elif len(keys) == 1:
            c['answer'] = next(iter(keys))
            ex['answer_status'] = 'source_extracted_pending_expert_review'
            ex['answer_extraction'] = {
                'method': binding, 'rule_version': RULE_VERSION,
                'source_count': len(chosen), 'binding': binding,
                'expert_review': {'status': 'pending', 'reviewer': None, 'reviewed_at': None}}
            report['new_answers'] += 1
        elif len(keys) > 1:
            ex['answer_candidates'] = sorted(
                ({'answer': it['answer'], 'source': it['path'], 'level': it['level']}
                 for it in chosen_items),
                key=lambda d: (d['answer'], d['source'], d['level']))[:8]
            ex['answer_status'] = 'source_conflict'
            report['conflicts'] += 1
        a = r.setdefault('analysis', {})
        if not a.get('raw'):
            with_expl = [it for it in chosen_items if it.get('expl')]
            if with_expl:
                best = max(with_expl, key=lambda it: len(it['expl']))
                a['raw'] = best['expl']
                a['status'] = 'source_extracted_pending_expert_review'
                a['method'] = 'published_explanation_text_extraction'
                a['source'] = {'path': best['path'], 'role': 'answer_analysis',
                               'locator': {'question_number': n, 'pages': best.get('pages'),
                                           'binding': binding, 'extraction': best['method'],
                                           'ocr_engine': OCR_ENGINE if best['level'] == 'ocr_block' else None}}
                a['trace_back'] = (f"原始解析 {best['path']}，题号 {n}"
                                   + (f"，OCR 页码 {best['pages']}" if best.get('pages') else '')
                                   + f"；绑定证据 {binding}，待专家审核。")
                hint = re.search(r'[【\[](?:做题提示|听前预测|题目定位|解题思路|设题要点)[】\]]\s*(.*?)(?=[【\[][^】\]]+[】\]]|$)',
                                 best['block'], re.S)
                if hint and not a.get('key_info'):
                    a['key_info'] = hint.group(1).strip()
                report['new_analyses'] += 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--kb', default=str(KB_DEFAULT))
    ap.add_argument('--only', default=None,
                    help='调试:仅处理指定 key,如 "CET-4|2016-06|2"')
    ap.add_argument('--no-fa-text', action='store_true', help='跳过文本层源候选(调试 OCR)')
    ap.add_argument('--debug-ocr', default=None, help='调试:仅 OCR 单个 PDF 并打印块解析')
    args = ap.parse_args(argv)

    if args.debug_ocr:
        path = Path(args.debug_ocr)
        pages = ocr_pdf(path, force=True)
        text, page_of = build_ocr_text(pages)
        print(f'pages={len(pages)} chars={len(text)}')
        for blk in ocr_question_blocks(text, page_of)[:12]:
            letters, expl, marker, prose = block_answer_and_explanation(blk['text'])
            print(f"--- Q{blk['n']} letters={sorted(letters)} prose={prose} marker={marker} pages={page_for(page_of, blk['start'], blk['end'])}")
            print('   ', repr(blk['text'][:150]))
            if expl:
                print('   expl:', repr(expl[:120]))
        print('grids:', extract_grids(text, page_of)[:12])
        return

    kb = Path(args.kb).resolve()

    candidates, diagnostics = source_candidates_all(
        progress=lambda rp: print('[ocr]', rp, flush=True))
    if args.no_fa_text:
        for key in list(candidates):
            for n in list(candidates[key]):
                candidates[key][n] = [it for it in candidates[key][n]
                                      if it['level'] not in ('text',)]
    coverage = defaultdict(int)
    for key, by_n in candidates.items():
        for n, items in by_n.items():
            for it in items:
                if it['level'] in ('text', 'ocr_block'):
                    coverage[(key, it['path'])] += 1
    diagnostics.append({'step': 'candidate_keys', 'papers_with_candidates': len(candidates),
                        'candidate_items': sum(len(v) for by_n in candidates.values() for v in by_n.values())})

    report = {'rule_version': RULE_VERSION, 'ocr_engine': OCR_ENGINE, 'dpi': OCR_DPI,
              'papers': {}, 'source_diagnostics': diagnostics}
    only = tuple(int(x) if x.isdigit() else x for x in args.only.split('|')) if args.only else None
    for lv in ('cet4', 'cet6'):
        for path in sorted((kb / 'questions' / lv).glob('*.jsonl')):
            ym, pap = path.stem.split('_p')
            key = ('CET-4' if lv == 'cet4' else 'CET-6', ym, int(pap))
            if only and key != only:
                continue
            rows = load_jsonl(path)
            pr = {'new_answers': 0, 'new_analyses': 0, 'unbound': 0, 'conflicts': 0,
                  'legacy_answer_upgraded': 0, 'still_missing': 0}
            fill_rows(rows, key, candidates, coverage, pr)
            path.write_text('\n'.join(jsonl_dumps(r) for r in rows) + '\n', encoding='utf-8')
            report['papers'][f'{lv}/{path.name}'] = pr
    summary = {k: sum(v.get(k, 0) for v in report['papers'].values())
               for k in ('new_answers', 'new_analyses', 'unbound', 'conflicts',
                         'legacy_answer_upgraded', 'still_missing')}
    report['last_run'] = summary
    out = kb / 'manifest' / 'answers_fill_ocr_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    print('report ->', out.relative_to(ROOT))


if __name__ == '__main__':
    main()
