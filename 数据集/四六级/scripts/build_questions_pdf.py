# -*- coding: utf-8 -*-
"""P3b PDF 真题拆题：仅处理无 docx 版本、且有文本层的场次（2024-12 / 2025-06 / 2025-12）。
用法: python build_questions_pdf.py --src <资料根目录> --kb <知识库根目录>
"""
import argparse, json, re, sys
from pathlib import Path
import fitz

sys.stdout.reconfigure(encoding="utf-8")
sys.argv_backup = sys.argv[:]
sys.argv = ["x", "--src", "a", "--stage", "a", "--kb", "a"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_questions as BQ

sys.argv = sys.argv_backup
ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--kb", required=True)
A = ap.parse_args()
SRC = Path(A.src).resolve()
KB = Path(A.kb).resolve()
for p in (SRC, KB):
    if "knowledge_map" not in p.parts:
        raise ValueError(f"path outside allowed root: {p}")

JUNK = re.compile(r"^(第\s*\d+\s*页|共\s*\d+\s*页|\d+\s*/\s*\d+|\d+)$|淘宝店|叮当助考|微信号|公众号|赢在|www\.|\.com|扫描|内部资料|仅供学习")
RE_PDF_FILE = re.compile(r"(?P<year>20\d{2})[.\s年]\s*(?P<mon>\d{1,2})[.\s月]?.*?(四级|六级).*?(?:第?\s*(?P<pap>[\d一二三])\s*套)", re.I)

def pdf_lines(path: Path):
    doc = fitz.open(path)
    lines = []
    for i in range(len(doc)):
        for ln in doc[i].get_text().splitlines():
            t = BQ.norm(ln.strip())
            if not t or JUNK.search(t):
                continue
            lines.append(t)
    doc.close()
    return lines

def main():
    cands = []
    for p in SRC.rglob("*.pdf"):
        name = p.name
        if "真题" not in name or "解析" in name or "专项" in str(p):
            continue
        if re.search(r"20(26|26年)?\.?6?月?.*2026|2026", name[:12]):
            continue  # 2026 扫描件跳过
        if not re.search(r"20(24\.12|24年12|25\.06|25\.6|25年6|25年06|25\.12|25年12)", name[:14]):
            continue
        m = RE_PDF_FILE.search(name)
        if not m:
            continue
        pap = str(int({"一": 1, "二": 2, "三": 3}.get(m.group("pap"), m.group("pap"))))
        exam = "CET-4" if ("四级" in name or "4级" in name) else "CET-6"
        ym = f"{m.group('year')}-{int(m.group('mon')):02d}"
        cands.append(((exam, ym, int(pap)), p))
    # 去重（同名散装与合集内重复）
    seen, papers = set(), []
    for meta, p in sorted(cands, key=lambda x: x[0]):
        if meta in seen:
            continue
        seen.add(meta)
        papers.append((meta, p))
    print(f"PDF exam papers: {len(papers)}")

    q_ok, report = 0, {}
    for (exam, ym, paper), path in papers:
        lv = "cet4" if exam == "CET-4" else "cet6"
        try:
            lines = pdf_lines(path)
            res, warn = BQ.parse_paper(lines, [], exam, ym, paper,
                                       {"origin_file": str(path.relative_to(SRC))})
        except Exception as e:
            report[f"{exam} {ym} p{paper}"] = {"error": str(e)}
            continue
        if res is None:
            report[f"{exam} {ym} p{paper}"] = {"error": "part structure not found"}
            continue
        ofile = KB / "questions" / lv / f"{ym}_p{paper}.jsonl"
        ofile.parent.mkdir(parents=True, exist_ok=True)
        ofile.write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in res["questions"]) + "\n", encoding="utf-8")
        q_ok += len(res["questions"])
        n_l = sum(1 for q in res["questions"] if q["module"] == "听力")
        n_r = sum(1 for q in res["questions"] if q["module"] == "阅读")
        # passages 追加
        pfile = KB / "passages" / "reading.jsonl"
        old = [l for l in pfile.read_text(encoding="utf-8").splitlines() if l.strip()] if pfile.exists() else []
        old = [l for l in old if json.loads(l).get("id") not in {x["id"] for x in res["passages"]}]
        new = [dict(x, exam=exam, year=ym, paper=paper,
                    source={"origin_file": str(path.relative_to(SRC))},
                    review={"status": "auto_parsed"}, text=x["text"]) for x in res["passages"]]
        pfile.write_text("\n".join(old + [json.dumps(x, ensure_ascii=False) for x in new]) + "\n", encoding="utf-8")
        # writing / translation
        if res["writing"]:
            with_w = KB / "writing" / "_prompts.jsonl"
            wlines = [l for l in with_w.read_text(encoding="utf-8").splitlines() if l.strip()] if with_w.exists() else []
            wlines = [l for l in wlines if json.loads(l)["id"] != f"{lv}.w.{ym}_p{paper}"]
            wlines.append(json.dumps({"id": f"{lv}.w.{ym}_p{paper}", "exam": exam, "year": ym,
                                      "paper": paper, "topic_prompt": res["writing"],
                                      "source": {"origin_file": str(path.relative_to(SRC))},
                                      "review": {"status": "auto_parsed"},
                                      "text": f"【{ym.replace('-','年')}月{exam}写作真题第{paper}套】{res['writing'][:400]}"}, ensure_ascii=False))
            with_w.write_text("\n".join(wlines) + "\n", encoding="utf-8")
        if res["translation"]:
            tf = KB / "translation" / "_from_papers.jsonl"
            tl = [l for l in tf.read_text(encoding="utf-8").splitlines() if l.strip()] if tf.exists() else []
            tl = [l for l in tl if json.loads(l)["id"] != f"{lv}.t.{ym}_p{paper}"]
            tl.append(json.dumps({"id": f"{lv}.t.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                                  "theme": None, "source_text": res["translation"], "reference": None,
                                  "key_phrases": [], "notes": None,
                                  "source": {"origin_file": str(path.relative_to(SRC))},
                                  "review": {"status": "auto_parsed"},
                                  "text": f"【{ym.replace('-','年')}月{exam}翻译真题第{paper}套】中文：{res['translation'][:400]}"}, ensure_ascii=False))
            tf.write_text("\n".join(tl) + "\n", encoding="utf-8")
        report[f"{exam} {ym} p{paper}"] = {"listening": n_l, "reading": n_r, "passages": len(res["passages"]), "warnings": warn}
        # 更新 papers.jsonl
        pf = KB / "manifest" / "papers.jsonl"
        plist = [json.loads(l) for l in pf.read_text(encoding="utf-8").splitlines() if l.strip()] if pf.exists() else []
        plist = [x for x in plist if x["id"] != f"{lv}.{ym}_p{paper}"]
        plist.append({"id": f"{lv}.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                      "listening_qs": n_l, "reading_qs": n_r,
                      "has_writing": bool(res["writing"]), "has_translation": bool(res["translation"]),
                      "has_passages": len(res["passages"]), "warnings": warn,
                      "source_file": path.name, "parse": "pdf"})
        pf.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in plist) + "\n", encoding="utf-8")
    print(f"PDF questions: {q_ok}")
    for k, v in report.items():
        print(" ", k, v.get("error") or f"L{v['listening']}/R{v['reading']} " + "; ".join(v.get("warnings", []))[:110])

if __name__ == "__main__":
    main()
