# -*- coding: utf-8 -*-
"""P5 写作模板库：模板句型 docx + 模板 PDF → templates.jsonl + md/templates.md
用法: python build_templates.py --src <资料根目录> --kb <知识库根目录>
"""
import argparse, json, re, sys
from pathlib import Path
from docx import Document
import fitz

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--kb", required=True)
A = ap.parse_args()
SRC = Path(A.src).resolve()
KB = Path(A.kb).resolve()
for p in (SRC, KB):
    if "knowledge_map" not in p.parts:
        raise ValueError(f"path outside allowed root: {p}")

SLUG = [("phenomenon", ["现象", "描述图画", "描述图表", "漫画", "图画"]),
        ("quote", ["名言", "警句", "谚语"]),
        ("opening", ["破题", "开头", "开门见山", "引入话题", "引出"]),
        ("argument", ["论证", "观点", "议论", "表达观点", "看法"]),
        ("compare", ["对比", "不同观点", "正反"]),
        ("example", ["举例", "例证"]),
        ("cause", ["原因", "分析原因"]),
        ("solution", ["措施", "建议", "解决办法"]),
        ("concession", ["让步"]),
        ("transition", ["过渡", "衔接", "承上启下"]),
        ("prediction", ["预测", "展望", "趋势"]),
        ("ending", ["结尾", "总结", "收尾"]),
        ("universal", ["万能", "通用", "常用"]),
        ("other", [])]

def categorize(zh: str) -> str:
    for slug, kws in SLUG:
        if any(k in zh for k in kws):
            return slug
    return "other"

TID = {}
def tid(slug):
    TID[slug] = TID.get(slug, 0) + 1
    return f"tpl.{slug}.{TID[slug]:03d}"

def rec(slug, cat, en, cn, usage, book, fname):
    en = re.sub(r"\s+", " ", en).strip()
    return {"id": tid(slug), "category": slug, "function": cat, "en": en, "cn": cn,
            "usage": usage, "source": {"origin_file": fname, "book": book},
            "text": f"【写作模板·{cat}】{en}" + (f"（{cn}）" if cn else "")}

out, md_parts = [], ["# 四六级写作模板库（人读版）", "", "> 自动整理自原始资料；检索版见 writing/templates.jsonl", ""]

# ---------- 1. 高分模板句型 docx ----------
d = SRC / "【3】四六级作文模版/2026年6月英语六级作文模版/四六级写作高分模板句型.docx"
doc = Document(d)
cur_cat, cur_slug = None, "other"
n_doc = 0
md_parts += [f"## 一、四六级写作高分模板句型", ""]
for p in doc.paragraphs:
    line = p.text.strip()
    if not line:
        continue
    cm = re.match(r"^(\d+)[、，.]\s*(.+?)(?:\s*$)", line)
    if cm and len(cm.group(2)) < 30 and not re.search(r"[a-zA-Z]{8,}", cm.group(2)):
        cur_cat = cm.group(2).strip()
        cur_slug = categorize(cur_cat)
        md_parts += [f"### {cur_cat}", ""]
        continue
    en = line
    cn = None
    pm = re.search(r"[（(]([^()（）]{2,60})[)）]\s*$", en)
    if pm and re.search(r"[\u4e00-\u9fff]", pm.group(1)):
        cn = pm.group(1).strip()
        en = en[:pm.start()].strip()
    if re.search(r"[a-zA-Z]{6,}", en) and len(en) > 10:
        r = rec(cur_slug, cur_cat or "其他", en, cn, None, "四六级写作高分模板句型", str(d.name))
        out.append(r); n_doc += 1
        md_parts.append(f"- {en}" + (f"（{cn}）" if cn else ""))
md_parts.append("")

# ---------- 2. 模板 PDF（按功能表达/段落模板整段收录） ----------
PDFS = [("六级作文模板", SRC / "【3】四六级作文模版/2026年6月英语六级作文模版/六级作文模板.pdf"),
        ("石雷鹏六级作文模版", SRC / "【3】四六级作文模版/2026年6月英语六级作文模版/石雷鹏六级作文模版.pdf"),
        ("四级作文模板", SRC / "【3】四六级作文模版/2026年6月英语四级作文模版/四级作文模板.pdf"),
        ("刘小艳四级作文模板", SRC / "【3】四六级作文模版/2026年6月英语四级作文模版/刘小艳四级作文模板.pdf"),
        ("瑞斯拜四级作文模板", SRC / "【3】四六级作文模版/2026年6月英语四级作文模版/瑞斯拜四级作文模板.pdf")]
for book, path in PDFS:
    if not path.exists():
        print("MISSING", path.name)
        continue
    docf = fitz.open(path)
    text = "\n".join(docf[i].get_text() for i in range(len(docf)))
    docf.close()
    if len(text.strip()) < 500:
        print(f"SKIP (no text layer): {path.name}")
        continue
    md_parts += [f"## {book}", ""]
    n0 = len(out)
    # 石雷鹏式：功能表达 N：... 翻译：...
    seg = re.split(r"(?:功能表达\s*\d+[:：]|\n(?=\d+[.、]\s*[^\n]{2,20}))", text)
    cur_cat, cur_slug = "通用模板", "universal"
    for s in seg:
        s = s.strip()
        if not s or len(s) < 30:
            continue
        hm = re.match(r"^(\d+)[.、]\s*([^\n]{2,25})\n", s)
        if hm and not re.search(r"[a-zA-Z]{10,}", hm.group(2)):
            cur_cat, cur_slug = hm.group(2).strip(), categorize(hm.group(2))
            s = s[hm.end():].strip()
        en_m = re.search(r"((?:[A-Z][^\n\u4e00-\u9fff]*\n?)+)", s)
        cn_m = re.search(r"翻译[:：]\s*([^\n]+(?:\n[^\n]+){0,3})", s)
        en = re.sub(r"\s+", " ", en_m.group(1)).strip() if en_m else None
        cn = re.sub(r"\s+", " ", cn_m.group(1)).strip() if cn_m else None
        if en and len(en) > 30 and re.search(r"[a-zA-Z]{8,}", en):
            s2 = re.sub(r"\s+", " ", s).strip()
            out.append(rec(cur_slug, cur_cat, s2 if not en_m else s2, cn, None, book, str(path.name)))
            md_parts.append(f"- {s2[:200]}")
    print(f"{book}: {len(out)-n0} records")

ALLOWED = {"templates.jsonl"}
target = KB / "writing" / "templates.jsonl"
assert target.parent.resolve() == (KB / "writing").resolve()
content = "\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n"
target.write_text(content, encoding="utf-8")
(KB / "writing" / "md").mkdir(exist_ok=True)
(KB / "writing" / "md" / "templates.md").write_text("\n".join(md_parts), encoding="utf-8")
print(f"templates: {len(out)} (docx {n_doc})")
from collections import Counter
print("by category:", dict(Counter(x["category"] for x in out)))

if __name__ == "__main__":
    pass
