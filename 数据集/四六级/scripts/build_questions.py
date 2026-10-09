# -*- coding: utf-8 -*-
"""P3 真题拆题（docx 主管线，含 2015-2016 老格式兼容）。
用法: python build_questions.py --src <资料根目录> --stage <staging目录> --kb <知识库根目录>
产出:
  questions/{cet4,cet6}/{YYYY-MM}_p{n}.jsonl
  passages/reading.jsonl
  writing/_prompts.jsonl  translation/_from_papers.jsonl  (供 P4 合并)
  manifest/papers.jsonl  manifest/parse_report.json
"""
import argparse, json, re, sys
from pathlib import Path
from docx import Document
from cet_common import merge_jsonl

sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--stage", required=True)
ap.add_argument("--kb", required=True)
A = ap.parse_args()
SRC = Path(A.src).resolve()
STAGE = Path(A.stage).resolve()
KB = Path(A.kb).resolve()
for p in (SRC, STAGE, KB):
    if "knowledge_map" not in p.parts:
        raise ValueError(f"path outside allowed root: {p}")

QDIR = KB / "questions"; PDIR = KB / "passages"; MDIR = KB / "manifest"
for d in (QDIR, PDIR, MDIR, KB / "writing", KB / "translation"):
    d.mkdir(parents=True, exist_ok=True)

ROMAN = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "ɪ": "III",
         "ＩＩＩ": "III", "ＩＩ": "II", "Ｉ": "I", "\xa0": " ", "\u3000": " "}
def norm(s):
    for k, v in ROMAN.items():
        s = s.replace(k, v)
    return s

RE_PART = re.compile(r"^Part\s*(IV|III|II|I)\b", re.I)
RE_QHDR = re.compile(r"^Questions?\s+(\d{1,2})\s+(?:and|to|及)\s+(\d{1,2})\s+are\s+based\s+on\s+the\s+(?!following)(\w+)", re.I)
RE_QHDR_P = re.compile(r"^Questions?\s+(\d{1,2})\s+(?:and|to|及)\s+(\d{1,2})\s+are\s+based\s+on\s+the\s+following\s+passage", re.I)
RE_QNUM = re.compile(r"^(\d{1,2})\s*[.、．]\s*(.*)$")
RE_MARK = re.compile(r"(?:^|\s)([A-O])[)）]")
RE_BLANK = re.compile(r"(?<!\d)(2[6-9]|3[0-5])(?!\d)")
RE_CN = re.compile(r"[\u4e00-\u9fff]")

def qtype(exam, module, n):
    if module == "听力":
        if exam == "CET-4":
            return "短篇新闻" if n <= 7 else ("长对话" if n <= 15 else "听力篇章")
        return "长对话" if n <= 8 else ("听力篇章" if n <= 15 else "讲座/讲话")
    return "选词填空" if n <= 35 else ("长篇阅读" if n <= 45 else "仔细阅读")

KNOW = {
    ("听力", "短篇新闻"): ["listen.detail"], ("听力", "长对话"): ["listen.detail", "listen.gist"],
    ("听力", "听力篇章"): ["listen.detail"], ("听力", "讲座/讲话"): ["listen.note", "listen.detail"],
    ("阅读", "选词填空"): ["read.cloze", "read.discourse"], ("阅读", "长篇阅读"): ["read.locate", "read.synonym"],
    ("阅读", "仔细阅读"): ["read.locate", "read.infer"],
}

def qrec(exam, ym, paper, module, n, stem, opts, group, passage_id, src):
    qt = qtype(exam, module, n)
    lv = "cet4" if exam == "CET-4" else "cet6"
    kn = [f"{lv}.{x}" for x in KNOW.get((module, qt), [])]
    opt_s = " ".join(f"{k}) {v}" for k, v in sorted((opts or {}).items()))
    return {
        "id": f"{lv}.{'l' if module=='听力' else 'r'}.{ym}_p{paper}.q{n}",
        "exam": exam, "year": ym, "paper": paper, "module": module, "question_type": qt,
        "number": n, "group": group, "passage_id": passage_id,
        "stem": stem, "options": opts or {}, "answer": None, "analysis": None,
        "option_parse_method": getattr(opts, 'method', None),
        "knowledge_nodes": kn, "difficulty": None, "analysis_status": None,
        "source": src, "review": {"status": "auto_parsed"},
        "text": f"【{ym.replace('-','年')}月{exam}真题第{paper}套·{'听力' if module=='听力' else '阅读'}·{qt}】{n}. {stem or ''} {opt_s}".strip(),
    }

TERM_PUNCT = re.compile(r"[.?!;；。？！]\s*[”’'\)]?\s*$")

def _split_pieces(text):
    """一行 → [(letter|None, seg)]；行首无字母但有内容时产生 (None, pre)。"""
    marks = list(RE_MARK.finditer(text))
    if not marks:
        return [(None, text.strip())] if text.strip() else []
    pieces = []
    pre = text[:marks[0].start()].strip()
    if pre:
        pieces.append((None, pre))
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
        seg = text[m.end():end].strip()
        if seg or True:
            pieces.append((m.group(1), seg))
    return pieces

class ParsedOptions(dict):
    method = 'explicit_two_column_C_D_sequence'

def _two_column_entries(entries, qn_range):
    """Accept only complete explicit A/B rows followed by exactly one C/D pair per row."""
    groups=[]
    for num,text in entries:
        if num is not None: groups.append([num,[]])
        elif not groups: return None
        groups[-1][1].extend(_split_pieces(text))
    if len(groups)<2 or [g[0] for g in groups]!=list(qn_range): return None
    bodies=[]
    for num,pieces in groups:
        leading=[]
        while pieces and pieces[0][0] is None: leading.append(pieces.pop(0)[1])
        # Unlabelled option continuation / missing letters require another parser.
        if any(p[0] is None for p in pieces): return None
        bodies.append((num,' '.join(leading),pieces))
    if any([p[0] for p in ps]!=['A','B'] for _,_,ps in bodies[:-1]): return None
    tail=bodies[-1][2]
    if [p[0] for p in tail]!=['A','B']+['C','D']*len(groups): return None
    pairs=tail[2:];out=[]
    for i,(num,stem,pieces) in enumerate(bodies):
        out.append((num,stem,ParsedOptions(pieces[:2]+pairs[2*i:2*i+2])))
    return out

def parse_question_blocks(lines, qn_range):
    """题块提取 v3：老 docx 题号/选项字母常在转换中丢失。
    切题信号：显式题号 / A) 重现 / 选项片段数已满4。
    组装：字母缺失的选项片段按 A-D 顺序回填；行首裸片段在首个已知字母为 A 时视为题干。"""
    lo = min(qn_range)
    entries = []
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        if "答题卡" in t or t.startswith("注意") or RE_QHDR.match(t) or RE_QHDR_P.match(t):
            continue
        m = RE_QNUM.match(t)
        if m and int(m.group(1)) in qn_range:
            entries.append([int(m.group(1)), m.group(2).strip()])
        else:
            entries.append([None, t])

    two_column = _two_column_entries(entries, qn_range)
    if two_column is not None: return two_column
    blocks = []
    for num, text in entries:
        new = False
        if num is not None or not blocks:
            new = True
        else:
            cur = blocks[-1]
            marks = [p[0] for p in _split_pieces(text) if p[0]]
            complete = cur["nopt"] >= 4
            if "A" in marks and cur["known"].get("A"):
                new = True
            elif complete and not marks:
                new = True
        if new:
            blocks.append({"num": num, "pieces": [], "nopt": 0, "known": {}})
        b = blocks[-1]
        for letter, seg in _split_pieces(text):
            b["pieces"].append((letter, seg))
            if letter:
                b["nopt"] += 1
                b["known"][letter] = True
            elif b["nopt"] > 0 or len(b["pieces"]) > 1:
                b["nopt"] += 1  # 字母丢失的选项片段
            elif seg and TERM_PUNCT.search(seg):
                b["nopt"] += 1  # 无字母可依但成句 → 暂计为选项片段（题干判定在组装时回退）

    # 补号（越界 = 垃圾块，丢弃）
    expect = None
    keep = []
    for b in blocks:
        if b["num"] is None:
            if expect is None:
                expect = lo
            elif expect + 1 in qn_range:
                expect += 1
            else:
                continue  # 超出题号范围 → 非题目内容
            b["num"] = expect
        else:
            expect = b["num"]
        keep.append(b)
    blocks = keep

    # 组装
    out = []
    for b in sorted(blocks, key=lambda x: x["num"]):
        pieces = [p for p in b["pieces"] if p[1] or p[0]]
        if not pieces:
            continue
        known_letters = [p[0] for p in pieces if p[0]]
        first_known = known_letters[0] if known_letters else None
        # 题干：首个裸片段，且(无已知字母且以?结尾) 或 首个已知字母为 A
        stem = None
        body = pieces
        if pieces[0][0] is None:
            cand = pieces[0][1]
            if (first_known == "A") or (first_known is None and cand.endswith("?")):
                stem = cand
                body = pieces[1:]
            elif first_known is None and len(pieces) >= 5:
                stem = cand  # 题干+4个无字母选项
                body = pieces[1:]
        # 选项：已知字母直接用，未知片段按 A-D 缺位顺序回填
        opts, order = {}, []
        for letter, seg in body:
            if letter:
                if letter not in opts:
                    order.append(letter)
                opts[letter] = (opts.get(letter, "") + " " + seg).strip() if letter in opts and opts.get(letter) else seg
        missing = [c for c in "ABCD" if c not in opts]
        for (letter, seg), fill in zip([(l, s) for l, s in body if l is None], missing):
            if fill:
                opts[fill] = seg.strip()
                order.append(fill)
        out.append((b["num"], stem or "", opts))
    return out

def sentence_with_blank(joined, n):
    pat = re.compile(rf"(^|[\s(（])({n})(\s+|_+)")
    m = pat.search(joined)
    if not m:
        return None
    idx = m.start(2)
    start = max(0, joined.rfind(". ", 0, idx) + 1)
    em = re.search(r"[.!?]\s", joined[idx:])
    end = idx + (em.end() if em else 140)
    sent = joined[start:end].strip()
    return re.sub(rf"(^|[\s(（]){n}(\s+|_+)", r"\1____ ", sent)

def extract_bank(seg, table_cells):
    bank = {}
    order_fill = iter([c for c in "ABCDEFGHIJKLMNO" if c not in bank])
    # 1) 表格：优先取带字母的，字母丢失的按出现顺序补 A-O
    for cell in table_cells:
        for chunk in re.split(r"\s{2,}|\n", cell):
            chunk = chunk.strip()
            if not chunk:
                continue
            m = re.match(r"^([A-O0])[)）]\s*([a-zA-Z][\w'\-\.]*)\s*$", chunk)
            if m:
                bank.setdefault('O' if m.group(1)=='0' else m.group(1), m.group(2))
            elif re.match(r"^[a-zA-Z][\w'\-\.]*$", chunk) and len(chunk) <= 24:
                nxt = next((c for c in "ABCDEFGHIJKLMNO" if c not in bank), None)
                if nxt:
                    bank[nxt] = chunk
    # 2) 段落兜底
    if len(bank) < 15:
        for t in seg:
            for m in re.finditer(r"(?:^|\s)([A-O0])[)）]\s*([a-zA-Z][\w'\-\.]*)", t):
                bank.setdefault('O' if m.group(1)=='0' else m.group(1), m.group(2))
    return bank

def parse_paper(paras, banks, exam, ym, paper, src):
    warn = []
    paras = [norm(p) for p in paras if p and p.strip()]
    matches = []
    PART_FIX = {"in": "III", "ili": "III", "lll": "III", "il": "II", "li": "II",
                "ii": "II", "iii": "III", "iv": "IV", "i": "I", "l": "I"}
    for i, t in enumerate(paras):
        m = RE_PART.match(t.strip())
        if m:
            matches.append((i, m.group(1).upper()))
        else:
            # PDF 字体连字常把 III 提取成 in 等；仅接受整行 "Part <token>" 的短行兜底
            m2 = re.match(r"^Part\s+([\wⅠⅡⅢⅣ]{1,4})\s*$", t.strip())
            if m2 and m2.group(1).lower() in PART_FIX:
                matches.append((i, PART_FIX[m2.group(1).lower()]))
    part_idx = {}
    if len(matches) >= 4 and [x[1] for x in matches[:4]] == ["I", "II", "III", "IV"]:
        part_idx = dict(zip(["I", "II", "III", "IV"], [x[0] for x in matches[:4]]))
    else:
        seen = set()
        for i, lab in matches:
            if lab not in seen:
                part_idx[lab] = i
                seen.add(lab)
    if "II" not in part_idx:
        iis = [i for i, lab in matches if lab == "I"]
        if len(iis) >= 2:
            part_idx["II"] = iis[1]
            warn.append("fixed duplicate Part I -> II")
    if len(part_idx) < 4:
        # PDF 兜底：用独立的模块标题行定位（Writing/Listening/Reading/Translation）
        title_map = {"writing": "I", "listening comprehension": "II",
                     "reading comprehension": "III", "translation": "IV"}
        for i, t in enumerate(paras):
            ts = re.sub(r"\s*\(.*\)\s*$", "", t.strip()).strip().lower()
            if ts in title_map:
                part_idx.setdefault(title_map[ts], i)
    # 标题锚点（优先级最高）：整行形如 "[Part X] <模块名> [(NN minutes)]"
    TITLE_PAT = re.compile(
        r"^(?:Part\s*[\wⅠⅡⅢⅣ]{1,4}\s+)?(Writing|Listening Comprehension|Reading Comprehension|Translation)\s*(?:\(\d+\s*minutes?\))?\s*$", re.I)
    T2P = {"writing": "I", "listening comprehension": "II",
           "reading comprehension": "III", "translation": "IV"}
    anchors = {}
    for i, t in enumerate(paras):
        m2 = TITLE_PAT.match(t.strip())
        if m2:
            anchors.setdefault(T2P[m2.group(1).lower()], i)
    if len(anchors) == 4:
        part_idx = dict(anchors)
    else:
        for k, v in anchors.items():
            part_idx.setdefault(k, v)
    p1 = part_idx.get("I")
    p4 = part_idx.get("IV")
    p2 = part_idx.get("II")
    p3 = part_idx.get("III")
    if p1 is None and (p2 is not None or p4 is not None):
        p1 = 0  # Part I 标题缺失/损坏：卷首到下一分部之间视为写作
        warn.append("Part I header missing; writing taken from document head")
    if p1 is None or p4 is None or p1 >= p4:
        return None, [f"missing parts {[k for k in ('I','II','III','IV') if k not in part_idx]}; found {matches[:8]}"]
    partial = p2 is None or p3 is None
    if partial:
        warn.append("partial paper (writing/translation only; shared listening/reading with same-session paper)")

    # p1/p2/p3/p4 已在上方安全取得（partial 时 p2/p3 可能为 None）
    questions, passages = [], []
    lv = "cet4" if exam == "CET-4" else "cet6"

    # Part I Writing
    w_lines = [t for t in paras[p1 + 1:(p2 if p2 is not None else p4)] if not RE_PART.match(t)]
    writing_prompt = " ".join(w_lines).strip() or None

    # Part II Listening
    lis = paras[p2 + 1:(p3 if p3 is not None else p4)] if p2 is not None else []
    hdrs = [(j, RE_QHDR.match(t)) for j, t in enumerate(lis)]
    hdrs = [(j, m) for j, m in hdrs if m]
    gi = 0
    for hi, (j, m) in enumerate(hdrs):
        lo, hi_n, kw = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        gi += 1
        genre = ("短篇新闻" if "news" in kw else "长对话" if "conversation" in kw
                 else "听力篇章" if "passage" in kw else "讲座/讲话")
        end = hdrs[hi + 1][0] if hi + 1 < len(hdrs) else len(lis)
        gid = f"{lv}.l.{ym}_p{paper}.g{gi}"
        blocks = parse_question_blocks(lis[j + 1:end], range(lo, hi_n + 1))
        for num, stem, opts in blocks:
            questions.append(qrec(exam, ym, paper, "听力", num, stem, opts, f"g{gi}", gid, src))
        if len(blocks) < (hi_n - lo + 1):
            warn.append(f"listening g{gi}({genre}) got {len(blocks)}/{hi_n-lo+1}")

    # Part III Reading
    rd = paras[p3 + 1:p4] if p3 is not None else []
    sec_idx = {}
    for j, t in enumerate(rd):
        if re.match(r"^Section\s+([ABC])\s*$", t.strip()):
            sec_idx.setdefault(t.strip()[-1], j)
    if not sec_idx:
        warn.append("no reading sections")

    # Section A cloze (26-35)
    if "A" in sec_idx:
        a0 = sec_idx["A"]
        a1 = sec_idx.get("B", len(rd))
        seg = rd[a0:a1]
        bank = extract_bank(seg, banks)
        def is_bankline(t):
            t = t.strip()
            return bool(re.match(r"^([A-O][)）])?\s*[a-zA-Z][\w'\-\.]*$", t)) and len(t) < 40
        d_idx = next((j for j, t in enumerate(seg) if t.startswith("Directions")), None)
        h_idx = next((j for j, t in enumerate(seg) if RE_QHDR_P.match(t)), None)
        start0 = max(x for x in (d_idx, h_idx) if x is not None) + 1 if (d_idx is not None or h_idx is not None) else 1
        j = len(seg)
        while j > start0 and is_bankline(seg[j - 1]):
            j -= 1
        passage_lines = [t for t in seg[start0:j] if not is_bankline(t)]
        cpass = re.sub(r"\s+", " ", " ".join(passage_lines)).strip()
        ca_id = f"{lv}.r.{ym}_p{paper}.ca"
        if cpass:
            located = [n for n in range(26, 36) if re.search(rf"(?<!\d){n}(?!\d)", cpass)]
            for n in range(26, 36):
                stem = sentence_with_blank(cpass, n) if n in located else None
                questions.append(qrec(exam, ym, paper, "阅读", n, stem, bank, "ca", ca_id, src))
            passages.append({"id": ca_id, "kind": "cloze", "word_bank": bank or None,
                             "text": cpass, "question_ids": [q["id"] for q in questions if q["passage_id"] == ca_id]})
            if len(bank) < 15:
                warn.append(f"cloze bank {len(bank)}/15")
            miss = [n for n in range(26, 36) if n not in located]
            if miss:
                warn.append(f"cloze blanks unmarked: {miss}" if len(miss) < 10 else "cloze blanks all unmarked")
        else:
            warn.append("cloze passage not found")

    # Section B matching (36-45)
    if "B" in sec_idx:
        b0 = sec_idx["B"]
        b1 = sec_idx.get("C", len(rd))
        seg = rd[b0:b1]
        para_map, cur_letter, cur_txt, title = [], None, [], None
        for t in seg[1:]:
            pm = re.match(r"^([A-J])\s*[).、）]\s*(.*)$", t)
            if pm:
                if cur_letter:
                    para_map.append((cur_letter, " ".join(cur_txt).strip()))
                cur_letter, cur_txt = pm.group(1), [pm.group(2)]
            elif cur_letter is None:
                if t.startswith("Directions") or RE_QHDR_P.match(t) or RE_QNUM.match(t):
                    continue
                title = (title + " " + t).strip() if title else t
            else:
                cur_txt.append(t)
        if cur_letter:
            para_map.append((cur_letter, " ".join(cur_txt).strip()))
        cb_id = f"{lv}.r.{ym}_p{paper}.cb"
        # numbered statements first
        qsi = next((j for j, t in enumerate(seg) if re.match(r"^3[6-9][.、．]", t)), None)
        if qsi is not None:
            blocks = parse_question_blocks(seg[qsi:], range(36, 46))
        else:
            blocks = []
        if not blocks:
            # 老格式：题号丢失，取节末 10 条陈述行
            tail = [t for t in seg if TERM_PUNCT.search(t) and not re.match(r"^([A-J])\s*[).、）]", t)
                    and not t.startswith("Directions") and not RE_QNUM.match(t)
                    and "答题卡" not in t and "注意" not in t and len(t) > 15]
            if len(tail) >= 10:
                blocks = [(36 + i, t.strip(), {}) for i, t in enumerate(tail[-10:])]
                warn.append("matching statements recovered positionally")
        for num, stem, opts in blocks:
            questions.append(qrec(exam, ym, paper, "阅读", num, stem, {}, "cb", cb_id, src))
        body_end = qsi if qsi is not None else (len(seg) - 10 if len(blocks) == 10 and not para_map else len(seg))
        if para_map:
            ptext = re.sub(r"\s+", " ", (title or "") + " " + " ".join(x[1] for x in para_map)).strip()
            passages.append({"id": cb_id, "kind": "matching", "title": title,
                             "paragraphs": [{"letter": l, "text": t} for l, t in para_map],
                             "text": ptext, "question_ids": [q["id"] for q in questions if q["passage_id"] == cb_id]})
        else:
            ptext = re.sub(r"\s+", " ", " ".join(seg[1:body_end])).strip()
            if ptext:
                passages.append({"id": cb_id, "kind": "matching", "title": title, "paragraphs": None,
                                 "text": ptext, "question_ids": [q["id"] for q in questions if q["passage_id"] == cb_id]})
                warn.append("matching paragraphs unlettered (old format)")
        if len(blocks) < 10:
            warn.append(f"matching got {len(blocks)}/10")

    # Section C careful reading (46-55)
    if "C" in sec_idx:
        cseg = rd[sec_idx["C"]:]
        hdrs = [(j, RE_QHDR_P.match(t)) for j, t in enumerate(cseg)]
        hdrs = [(j, m) for j, m in hdrs if m]
        pi = 0
        for hi, (j, m) in enumerate(hdrs):
            lo, hi_n = int(m.group(1)), int(m.group(2))
            end = hdrs[hi + 1][0] if hi + 1 < len(hdrs) else len(cseg)
            pi += 1
            cid = f"{lv}.r.{ym}_p{paper}.c{pi}"
            qstart = next((k for k in range(j + 1, end)
                           if RE_QNUM.match(cseg[k].strip()) or re.match(r"^\s*([A-O])[)）]", cseg[k])), None)
            if qstart is None:
                # 老卷：题号/选项字母全丢 → 首个以问号结尾的行视为第一题题干
                qstart = next((k for k in range(j + 1, end) if cseg[k].rstrip().endswith("?")), None)
            ptext = re.sub(r"\s+", " ", " ".join(cseg[j + 1:qstart])).strip() if qstart else ""
            blocks = parse_question_blocks(cseg[qstart:end] if qstart is not None else [], range(lo, hi_n + 1))
            for num, stem, opts in blocks:
                questions.append(qrec(exam, ym, paper, "阅读", num, stem, opts, f"c{pi}", cid, src))
            if ptext:
                passages.append({"id": cid, "kind": "reading", "text": ptext,
                                 "question_ids": [q["id"] for q in questions if q["passage_id"] == cid]})
            else:
                warn.append(f"careful c{pi} passage empty")
            if len(blocks) < (hi_n - lo + 1):
                warn.append(f"careful c{pi} got {len(blocks)}/{hi_n-lo+1}")

    # Part IV Translation
    tr_lines = [t for t in paras[p4 + 1:] if not RE_PART.match(t)
                and not re.match(r"^Section\s+[ABC]$", t)
                and not re.match(r"^Directions[:：]", t)]
    tr_text = re.sub(r"\s+", " ", " ".join(tr_lines)).strip()
    translation = tr_text or None

    return {"questions": questions, "passages": passages, "writing": writing_prompt,
            "translation": translation}, warn

RE_FILE = re.compile(r"(?P<year>20\d{2})\s*[年\.\s]?\s*(?P<mon>\d{1,2})\s*月?.*?(四级|4级|六级|6级).*?(?:第?\s*(?P<pap>[\d一二三])\s*套|卷?\s*(?P<pap2>[\d一二三]))", re.I)
CN = {"一": "1", "二": "2", "三": "3"}

def file_meta(path: Path):
    m = RE_FILE.search(path.name)
    if not m:
        return None
    pap = m.group("pap") or m.group("pap2")
    if pap is None:
        return None
    pap = CN.get(pap, pap)
    exam = "CET-4" if ("四级" in path.name or "4级" in path.name) else "CET-6"
    return exam, f"{m.group('year')}-{int(m.group('mon')):02d}", int(pap)

def load_docx(path: Path):
    """按文档顺序输出段落与表格单元格（老卷的词库/文章常在表格里），并收集含选项字母的表格单元格。"""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx_source import read_docx_units
    lines,cells=[],[]
    for text,loc in read_docx_units(path):
        text=norm(text.strip())
        if text:lines.append(text)
        if loc.get('kind')=='table' and re.search(r'[A-O]\s*[)）]',text):cells.append(text)
    return lines, cells

def main():
    sources = list(STAGE.rglob("*.docx"))
    for pat in ("*真题*套*.docx", "*真题*第*套*.docx", "*级（卷*）*.docx", "*真题【*.docx", "*原题*.docx", "*级真题*.docx"):
        sources += list(SRC.rglob(pat))
    seen, papers = set(), []
    for p in sources:
        meta = file_meta(p)
        if not meta or str(p.resolve()) in seen:
            continue
        seen.add(str(p.resolve()))
        papers.append((meta, p))
    print(f"exam docx found: {len(papers)}")

    reading_out, prompts_out, trans_out, papers_out, report = [], [], [], [], {}
    best = {}
    q_ok = 0
    for (exam, ym, paper), path in sorted(papers, key=lambda x: (x[0][0], x[0][1], x[0][2])):
        try:
            paras, banks = load_docx(path)
            origin = str(path.relative_to(SRC)) if str(path).startswith(str(SRC)) else f"_staging/{path.parent.name}/{path.name}"
            res, warn = parse_paper(paras, banks, exam, ym, paper, {"origin_file": origin})
            if res:
                from fill_answers import read_source,question_blocks,normalized
                source_text,units=read_source(path)
                blocks={n:block for n,block,a,b in question_blocks(source_text)}
                for q in res['questions']:
                    opts=q.get('options',{});block=normalized(blocks.get(q['number'],''))
                    if set(opts)==set('ABCD') and all(normalized(v) and normalized(v) in block for v in opts.values()) and block:
                        q['option_parse_method']='exact_original_word_question_number_and_four_options'
                        q['source']['numbering_method']='original_word_numbering_xml_with_explicit_option_identity'
        except Exception as e:
            report[f"{exam} {ym} p{paper}"] = {"error": str(e), "file": path.name}
            continue
        if res is None:
            report[f"{exam} {ym} p{paper}"] = {"error": "part structure not found", "file": path.name, "warn": warn}
            continue
        key = (exam, ym, paper)
        score = len(res["questions"])
        if key in best and score <= best[key]["score"]:
            report[f"{exam} {ym} p{paper}"] = {"dup_skipped": path.name}
            continue
        if key in best:
            report[f"{exam} {ym} p{paper}"] = {"dup_better_replaced": path.name}
            # 从聚合列表中移除旧份
            lv0 = "cet4" if exam == "CET-4" else "cet6"
            old_ids = {q["id"] for q in best[key]["res"]["questions"]}
            reading_out = [x for x in reading_out if x["id"] not in {p["id"] for p in best[key]["res"]["passages"]}]
            prompts_out = [x for x in prompts_out if x["id"] not in {f"{lv0}.w.{ym}_p{paper}"}]
            trans_out = [x for x in trans_out if x["id"] != f"{lv0}.t.{ym}_p{paper}"]
            papers_out = [x for x in papers_out if x["id"] != f"{lv0}.{ym}_p{paper}"]
        best[key] = {"res": res, "warn": warn, "score": score, "file": path.name}
        lv = "cet4" if exam == "CET-4" else "cet6"
        # 阅读题号归一化：源卷题号越界（如 2015-12 p2 仔细阅读错标 56-60）→ 按题型顺序重编 26-55
        rqs = [q for q in res["questions"] if q["module"] == "阅读"]
        if any(not (26 <= q["number"] <= 55) for q in rqs):
            order = {"选词填空": 0, "长篇阅读": 1, "仔细阅读": 2}
            id_map = {}
            for i, q in enumerate(sorted(rqs, key=lambda x: (order.get(x["question_type"], 9), x["number"])), 26):
                old_id = q["id"]
                q["number"] = i
                q["id"] = old_id.rsplit(".q", 1)[0] + f".q{i}"
                q["text"] = re.sub(r"】\d+\.", f"】{i}.", q["text"], count=1)
                id_map[old_id] = q["id"]
            for ps_ in res["passages"]:
                ps_["question_ids"] = [id_map.get(x, x) for x in ps_["question_ids"]]
                ps_["id"] = id_map.get(ps_["id"], ps_["id"])
            warn.append("reading questions renumbered to 26-55 (source numbering out of range)")
        ofile = QDIR / lv / f"{ym}_p{paper}.jsonl"
        ofile.parent.mkdir(parents=True, exist_ok=True)
        merge_jsonl(ofile,res["questions"])
        q_ok += len(res["questions"])
        reading_out += [dict(x, exam=exam, year=ym, paper=paper,
                             source={"origin_file": origin}, review={"status": "auto_parsed"},
                             text=x["text"]) for x in res["passages"]]
        if res["writing"]:
            prompts_out.append({"id": f"{lv}.w.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                                "topic_prompt": res["writing"], "source": {"origin_file": origin},
                                "review": {"status": "auto_parsed"},
                                "text": f"【{ym.replace('-','年')}月{exam}写作真题第{paper}套】{res['writing'][:400]}"})
        if res["translation"]:
            trans_out.append({"id": f"{lv}.t.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                              "theme": None, "source_text": res["translation"], "reference": None,
                              "key_phrases": [], "notes": None, "source": {"origin_file": origin},
                              "review": {"status": "auto_parsed"},
                              "text": f"【{ym.replace('-','年')}月{exam}翻译真题第{paper}套】中文：{res['translation'][:400]}"})
        n_l = sum(1 for q in res["questions"] if q["module"] == "听力")
        n_r = sum(1 for q in res["questions"] if q["module"] == "阅读")
        papers_out.append({"id": f"{lv}.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                           "listening_qs": n_l, "reading_qs": n_r,
                           "has_writing": bool(res["writing"]), "has_translation": bool(res["translation"]),
                           "has_passages": len(res["passages"]), "warnings": warn,
                           "source_file": path.name, "parse": "docx"})
        report[f"{exam} {ym} p{paper}"] = {"listening": n_l, "reading": n_r, "passages": len(res["passages"]), "warnings": warn}

    # 听力共享标注：第2/3套听力常不在卷内（实考共享第1套），登记 listening_ref
    by_session = {}
    for p in papers_out:
        by_session.setdefault((p["exam"], p["year"]), []).append(p)
    for (exam, ym), ps in by_session.items():
        src = next((x for x in ps if x["listening_qs"] == 25), None)
        if src:
            for p in ps:
                if p["listening_qs"] == 0:
                    p["listening_ref"] = src["id"]
                    p["warnings"].append(f"listening shared from {src['id']} (not printed in this paper)")

    merge_jsonl(PDIR / "reading.jsonl",reading_out)
    merge_jsonl(KB / "writing" / "_prompts.jsonl",prompts_out)
    merge_jsonl(KB / "translation" / "_from_papers.jsonl",trans_out)
    merge_jsonl(MDIR / "papers.jsonl",papers_out)
    (MDIR / "parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    q_ok = 0
    for lv in ("cet4", "cet6"):
        for f in (QDIR / lv).glob("*.jsonl"):
            q_ok += len([x for x in f.read_text(encoding="utf-8").split("\n") if x.strip()])
    print(f"total questions: {q_ok} | papers ok: {len(papers_out)} / {len(papers)} | reading passages: {len(reading_out)}")
    full = sum(1 for x in papers_out if x["listening_qs"] == 25 and x["reading_qs"] == 30)
    print(f"papers with full 25 listening + 30 reading: {full}")
    bad = {k: v for k, v in report.items() if "error" in v or v.get("warnings")}
    print(f"papers with warnings: {len(bad)}")
    for k in list(bad)[:15]:
        v = bad[k]
        print("  !", k, v.get("error") or "; ".join(v.get("warnings", []))[:150])

if __name__ == "__main__":
    main()
