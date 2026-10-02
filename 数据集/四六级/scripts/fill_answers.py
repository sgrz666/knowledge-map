# -*- coding: utf-8 -*-
"""P3a-2 答案填充：从解析册 PDF/docx 提取客观题答案，回填 questions/*.jsonl。
用法: python fill_answers.py --stage <staging/answers目录> --src <资料根目录> --kb <知识库根目录>
"""
import argparse, json, re, sys
from pathlib import Path
import fitz
from docx import Document

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--stage", required=True)
ap.add_argument("--src", required=True)
ap.add_argument("--kb", required=True)
A = ap.parse_args()
STAGE = Path(A.stage).resolve()
SRC = Path(A.src).resolve()
KB = Path(A.kb).resolve()
for p in (STAGE, SRC, KB):
    if "knowledge_map" not in p.parts:
        raise ValueError(f"path outside allowed root: {p}")

RE_FILE = re.compile(r"(?P<year>20\d{2})\s*[年\.\s]?\s*(?P<mon>\d{1,2})\s*月?.*?(四级|4级|六级|6级).*?(?:第?\s*(?P<pap>[\d一二三])\s*套|卷?\s*(?P<pap2>[\d一二三])|第?\s*(?P<pap3>[\d一二三])\s*套)", re.I)
CN = {"一": "1", "二": "2", "三": "3"}

def file_meta(path: Path):
    m = RE_FILE.search(path.name)
    if not m:
        return None
    pap = m.group("pap") or m.group("pap2") or m.group("pap3")
    if pap is None:
        return None
    pap = CN.get(pap, pap)
    exam = "CET-4" if ("四级" in path.name or "4级" in path.name) else "CET-6"
    return exam, f"{m.group('year')}-{int(m.group('mon')):02d}", int(pap)

def pdf_text(path: Path) -> str:
    doc = fitz.open(path)
    t = "\n".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()
    return t

def docx_text(path: Path) -> str:
    d = Document(path)
    return "\n".join(p.text for p in d.paragraphs)

ANS_IN_WINDOW = re.compile(r"【?答案】?\s*[:：]?\s*为?\s*([A-O])\s*[项）)]?")

def extract_answers(text: str):
    """题号锚点扫描：首行裸字母（"9. D"）或窗口内"【答案】/答案为/答案：X"（2017/2022 版式）。"""
    votes = {}
    for m in re.finditer(r"(?m)^\s*(\d{1,2})\s*[.、．]\s*", text):
        n = int(m.group(1))
        if not (1 <= n <= 55):
            continue
        line_end = text.find("\n", m.end())
        first_line = text[m.end():line_end if line_end != -1 else m.end() + 60].strip()
        lm = re.match(r"^([A-O])\s*(?:$|[^\wA-Za-z)])", first_line)
        if lm:
            votes.setdefault(n, {})
            votes[n][lm.group(1)] = votes[n].get(lm.group(1), 0) + 1
            continue
        window = text[m.end():m.end() + 300]
        am = ANS_IN_WINDOW.search(window)
        if am:
            votes.setdefault(n, {})
            votes[n][am.group(1)] = votes[n].get(am.group(1), 0) + 1
    out, conflicts = {}, []
    for n in sorted(votes):
        v = votes[n]
        best_letter, best_cnt = max(v.items(), key=lambda x: x[1])
        out[n] = best_letter
        if len(v) > 1:
            conflicts.append((n, dict(v)))
    return out, conflicts

def main():
    # 1) 收集解析源
    sources = {}
    for p in STAGE.rglob("*.pdf"):
        meta = file_meta(p)
        if meta:
            sources.setdefault(meta, []).append(p)
    for p in SRC.rglob("*.pdf"):
        meta = file_meta(p)
        if meta and ("解析" in p.name or "答案" in p.name) and "专项" not in str(p):
            sources.setdefault(meta, []).append(p)
    for p in SRC.rglob("*.docx"):
        meta = file_meta(p)
        if meta and "解析" in p.name:
            sources.setdefault(meta, []).append(p)
    # 阅读专项解析（"全3套/全2套"文件：按内部"第X套"切分后挂到各套）
    RE_PAPSEG = re.compile(r"第\s*([一二三1-3])\s*套")
    for p in SRC.rglob("*.pdf"):
        n = p.name
        if "解析" not in n or "专项" not in str(p):
            continue
        mm = re.search(r"(?P<year>20\d{2})[.\s年]\s*(?P<mon>\d{1,2})", n)
        if not mm:
            continue
        ym = f"{mm.group('year')}-{int(mm.group('mon')):02d}"
        exam = "CET-4" if ("四级" in n or "4级" in n) else "CET-6"
        try:
            t = pdf_text(p)
        except Exception:
            continue
        parts = RE_PAPSEG.split(t)
        segs = {}
        for i in range(1, len(parts) - 1, 2):
            pap = int(CN.get(parts[i], parts[i]))
            segs.setdefault(pap, parts[i + 1])
        for pap, seg in segs.items():
            sources.setdefault((exam, ym, pap), []).append(("__text__", seg))
    print(f"answer sources mapped: {len(sources)}")

    # 2) 逐卷填充
    filled_report = {}
    for lv in ("cet4", "cet6"):
        for qf in (KB / "questions" / lv).glob("*.jsonl"):
            m = re.match(r"(\d{4}-\d{2})_p(\d)", qf.stem)
            ym, paper = m.group(1), int(m.group(2))
            exam = "CET-4" if lv == "cet4" else "CET-6"
            recs = [json.loads(l) for l in qf.read_text(encoding="utf-8").splitlines() if l.strip()]
            need = [r for r in recs if r.get("answer") is None]
            if not need:
                continue
            answers = {}
            conflicts = []
            for spath in sources.get((exam, ym, paper), []):
                if isinstance(spath, tuple):
                    t = spath[1]
                else:
                    t = docx_text(spath) if spath.suffix == ".docx" else pdf_text(spath)
                a, c = extract_answers(t)
                for k, v in a.items():
                    answers.setdefault(k, v)
                conflicts += c
            if not answers:
                filled_report[f"{lv}/{qf.name}"] = {"need": len(need), "filled": 0, "note": "no answer source"}
                continue
            n_filled = 0
            for r in recs:
                if r.get("answer") is None and r["number"] in answers:
                    r["answer"] = answers[r["number"]]
                    r["analysis_status"] = "answer_from_key"
                    n_filled += 1
            qf.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
            filled_report[f"{lv}/{qf.name}"] = {"need": len(need), "filled": n_filled, "conflicts": conflicts[:5]}

    (KB / "manifest" / "answers_fill_report.json").write_text(json.dumps(filled_report, ensure_ascii=False, indent=1), encoding="utf-8")
    total_need = sum(v["need"] for v in filled_report.values())
    total_fill = sum(v["filled"] for v in filled_report.values())
    no_src = [k for k, v in filled_report.items() if v.get("note")]
    print(f"answer fill: {total_fill}/{total_need} | papers without source: {len(no_src)}")
    for k in no_src[:8]:
        print("  -", k)

if __name__ == "__main__":
    main()
