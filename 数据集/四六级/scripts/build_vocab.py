# -*- coding: utf-8 -*-
"""P2 词汇库构建：大纲词(xls) + 核心词1500(PDF) + 高频词组/高频词 + 翻译热点词
用法: python build_vocab.py --src <资料根目录> --out <知识库vocabulary目录>
幂等可复跑：覆盖产出 5 个 JSONL。"""
import argparse, json, re, sys
from pathlib import Path
import pandas as pd
import fitz
from docx import Document
from cet_common import merge_jsonl, dedupe_resources

sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--out", required=True)
args = ap.parse_args()
SRC = Path(args.src).resolve()
OUT = Path(args.out).resolve()
if "knowledge_map" not in SRC.parts or "knowledge_map" not in OUT.parts:
    raise ValueError(f"path outside allowed root: {SRC} / {OUT}")
OUT.mkdir(parents=True, exist_ok=True)

ALLOWED_OUTPUTS = {"words_cet4.jsonl", "words_cet6.jsonl", "core_words.jsonl",
                   "phrases_highfreq.jsonl", "translation_topic_words.jsonl"}

def dump(recs, name):
    assert name in ALLOWED_OUTPUTS, f"unexpected output name: {name}"
    target = (OUT / name).resolve()
    if OUT not in target.parents:
        raise ValueError(f"output escape: {target}")
    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n"
    merged = merge_jsonl(target, recs)
    target.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in dedupe_resources(merged))+"\n",encoding="utf-8")
    print(f"{name}: {len(recs)} records")

def rec(**kw):
    kw.setdefault("review", {"status": "auto_parsed"})
    return kw

# ---------- 1. 大纲词 xls ----------
XLS = {
    "CET-4": SRC / "【4】四六级大纲词及核心词/四六级大纲词/2026年英语四级大纲词汇/【1】英语四级大纲词汇—正序版/01.大学英语四级词汇完整带音标-可打印-可编辑-正序版.xls",
    "CET-6": SRC / "【4】四六级大纲词及核心词/四六级大纲词/2026年英语六级大纲词汇/六级大纲词汇—正序版/大学英语六级词汇完整带音标-可打印-可编辑-正序版.xls",
}
words = {}
for level, path in XLS.items():
    df = pd.read_excel(path, header=0)
    df.columns = ["no", "word", "phonetic", "meaning"]
    ws = []
    for _, r in df.iterrows():
        w = str(r["word"]).strip()
        if not w or w == "nan":
            continue
        ws.append({"w": w, "phon": str(r["phonetic"]).strip(), "mean": str(r["meaning"]).strip()})
    words[level] = {x["w"].lower(): x for x in ws}
    print(f"{level} outline words: {len(ws)}")

shared46 = set(words["CET-4"]) & set(words["CET-6"])
print(f"shared CET-4/6 words: {len(shared46)}")

out4 = []
for w, x in words["CET-4"].items():
    lvl = "CET-4/6" if w in shared46 else "CET-4"
    out4.append(rec(id=f"cet4.w.{w}", word=x["w"], phonetic=x["phon"], level=lvl, tier="outline",
                    pos_meaning=x["mean"], cse_level=None,
                    source={"origin_file": XLS["CET-4"].relative_to(SRC).as_posix()},
                    text=f"{x['w']} {x['phon']} 【{lvl}大纲词汇】{x['mean']}"))
out6 = []
for w, x in words["CET-6"].items():
    lvl = "CET-4/6" if w in shared46 else "CET-6"
    cse = 4 if w in shared46 else 5
    out6.append(rec(id=f"cet6.w.{w}", word=x["w"], phonetic=x["phon"], level=lvl, tier="outline",
                    pos_meaning=x["mean"], cse_level=None,
                    source={"origin_file": XLS["CET-6"].relative_to(SRC).as_posix()},
                    text=f"{x['w']} {x['phon']} 【{lvl}大纲词汇】{x['mean']}"))
dump(out4, "words_cet4.jsonl")
dump(out6, "words_cet6.jsonl")

# ---------- 2. 核心词 1500 PDF（顶层 2026.6 版） ----------
CORE = {
    "CET-4": SRC / "2026年6月英语四级1500核心词.pdf",
    "CET-6": SRC / "2026年6月英语六级1500核心词.pdf",
}
LINE = re.compile(r"^\s*(\d{1,4})[.、．]\s*([a-zA-Z][a-zA-Z'\-\. ]{1,30}?)\s+([\[\(／/][^\n]+)$")
core = {"CET-4": [], "CET-6": []}
for level, path in CORE.items():
    doc = fitz.open(path)
    t = "\n".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()
    for line in t.splitlines():
        m = LINE.match(line.strip())
        if not m:
            continue
        w = m.group(2).strip()
        rest = m.group(3).strip()
        phon_m = re.match(r"[\[\(／/]([^\]\)／]+)[\]\)／]?\s*(.*)", rest)
        phon = "/" + phon_m.group(1).strip().strip("/") + "/" if phon_m else None
        mean = phon_m.group(2).strip() if phon_m and phon_m.group(2) else rest
        core[level].append({"w": w, "phon": phon, "mean": mean})
seen = {"CET-4": set(), "CET-6": set()}
core_out = []
for level in ("CET-4", "CET-6"):
    slug = "cet4" if level == "CET-4" else "cet6"
    for x in core[level]:
        k = x["w"].lower()
        if k in seen[level]:
            continue
        seen[level].add(k)
        phon = x["phon"] or ""
        core_out.append(rec(id=f"{slug}.core.{k}", word=x["w"], phonetic=phon, level=level, tier="core",
                            pos_meaning=x["mean"], cse_level=None,
                            source={"origin_file": CORE[level].name},
                            text=f"{x['w']} {phon} 【{level}核心1500词】{x['mean']}"))
dump(core_out, "core_words.jsonl")

# ---------- 3. 高频词组 / 高频词 ----------
phr_out = []
CJK = re.compile(r"[\u4e00-\u9fff]")
doc = fitz.open(SRC / "四六级单词/英语六级高频词组.pdf")
t = "\n".join(doc[i].get_text() for i in range(len(doc)))
doc.close()
t = t.replace("欢迎下载", "").replace("淘宝店：叮当助考", "")
n = 0
seen_phr = set()
for line in t.splitlines():
    line = line.strip()
    m = re.match(r"^(\d{1,3})[.、．]\s*(.+)$", line)
    if not m:
        continue
    body = m.group(2).strip()
    cm = CJK.search(body)
    en_part = (body[:cm.start()] if cm else body).strip()
    mean = (body[cm.start():] if cm else "").strip().rstrip("。.").strip()
    en_part = en_part.rstrip("….").strip()
    nm = re.match(r"^(.*?)\s*[\(（]([^()（）]{2,90})[\)）]\s*$", en_part)
    if nm:
        phrase, note = nm.group(1).strip(), nm.group(2).strip()
    else:
        phrase, note = en_part, None
    phrase = phrase.strip().rstrip("….").strip()
    if len(phrase) < 2 or len(mean) < 2 or phrase.lower() in seen_phr:
        continue
    seen_phr.add(phrase.lower())
    n += 1
    phr_out.append(rec(id=f"cet6.phr.{n:03d}", phrase=phrase, variant=note, meaning=mean,
                       level="CET-6", tier="phrase",
                       source={"origin_file": "四六级单词/英语六级高频词组.pdf"},
                       text=f"{phrase} {('('+note+')') if note else ''} 【六级高频词组】{mean}"))
d = Document(SRC / "四六级单词/词汇  四六级高频700词.docx")
n = 0
for p in d.paragraphs:
    line = p.text.strip()
    m = re.match(r"^(\d{1,3})[.、．]\s*([a-zA-Z][a-zA-Z'\-]*)\s+(.+)$", line)
    if not m:
        continue
    n += 1
    w = m.group(2).strip()
    phr_out.append(rec(id=f"mix.hf700.{w.lower()}", word=w, pos_meaning=m.group(3).strip(),
                       level="CET-4/6", tier="highfreq700",
                       source={"origin_file": "四六级单词/词汇  四六级高频700词.docx"},
                       text=f"{w} 【四六级高频700词】{m.group(3).strip()}"))
d = Document(SRC / "四六级单词/四六级必背200个高频词（附带近年出现频数）.docx")
n = 0
for p in d.paragraphs:
    line = p.text.strip()
    m = re.match(r"^([a-zA-Z][\w'\-]{1,25})\s*[\(（](\d{1,4})\s*次[\)）]\s*(.+)$", line)
    if not m:
        continue
    n += 1
    phr_out.append(rec(id=f"mix.top200.{m.group(1).lower()}", word=m.group(1), freq=int(m.group(2)),
                       pos_meaning=m.group(3).strip(), level="CET-4/6", tier="top200",
                       source={"origin_file": "四六级单词/四六级必背200个高频词（附带近年出现频数）.docx"},
                       text=f"{m.group(1)} 【四六级必背高频词·近年出现{m.group(2)}次】{m.group(3).strip()}"))
dump(phr_out, "phrases_highfreq.jsonl")

# ---------- 4. 翻译热点词 docx ----------
d = Document(SRC / "四六级单词/英语四六级翻译热点词汇.docx")
topics, cur = [], None
for p in d.paragraphs:
    line = p.text.strip()
    if not line:
        continue
    tm = re.match(r"^(.+?类|.+?篇|其他)$", line)
    pair = re.match(r"^([^:：]{1,24})\s*[:：]\s*(.{1,80})$", line)
    if tm and not pair:
        cur = {"theme": line, "terms": []}
        topics.append(cur)
        continue
    if pair and cur is not None:
        cur["terms"].append({"cn": pair.group(1).strip(), "en": pair.group(2).strip()})
topic_out = []
for i, tp in enumerate(topics, 1):
    if not tp["terms"]:
        continue
    listing = "；".join(f"{x['cn']} {x['en']}" for x in tp["terms"])
    topic_out.append(rec(id=f"mix.trans_topic.{i:02d}", theme=tp["theme"], terms=tp["terms"],
                         level="CET-4/6", tier="translation_topic",
                         source={"origin_file": "四六级单词/英语四六级翻译热点词汇.docx"},
                         text=f"【四六级翻译热点词汇·{tp['theme']}】{listing}"))
dump(topic_out, "translation_topic_words.jsonl")

print("\nDONE vocabulary build")
