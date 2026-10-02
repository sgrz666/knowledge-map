# -*- coding: utf-8 -*-
"""P4 写作/翻译库：真题合集 PDF + 范文合集 PDF + 真题册拆出的 prompts/translation 三源合并。
用法: python build_writing_translation.py --src <资料根目录> --kb <知识库根目录>
产出: writing/model_essays.jsonl  translation/items.jsonl
"""
import argparse, json, re, sys
from pathlib import Path
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

RE_HDR = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*大学?英语?\s*(四级|六级)\s*(写作|翻译)\s*(真题|范文|参考译文|答案)?\s*第\s*([一二三\d])\s*套", re.I)
CN = {"一": 1, "二": 2, "三": 3}
NOISE = re.compile(r"淘宝店|叮当助考|微信号|公众号|第\s*\d+\s*页|版权|侵权|https?://\S+")

def split_by_header(text):
    """按条目标题切分 → {(exam,ym,paper): body}"""
    out = {}
    hdrs = list(RE_HDR.finditer(text))
    for i, m in enumerate(hdrs):
        lv = "cet4" if "四级" in m.group(3) else "cet6"
        paper = int(CN.get(m.group(6), m.group(6)))
        ym = f"{m.group(1)}-{int(m.group(2)):02d}"
        start = m.end()
        end = hdrs[i + 1].start() if i + 1 < len(hdrs) else len(text)
        body = NOISE.sub("", text[start:end]).strip()
        out[(lv, ym, paper)] = body
    return out

def pdf_text_all(path: Path) -> str:
    doc = fitz.open(path)
    t = "\n".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()
    return t

def clean_pdf_en(s: str) -> str:
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)   # 行尾连字
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)      # Y ou → 分词修复由下方词典处理
    s = s.replace("Y ou", "You").replace("W hat", "What").replace("T he ", "The ")
    s = re.sub(r"[ \t]*\n[ \t]*", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()

def main():
    S = SRC / "【2】四六级专项题汇总（听力、阅读、翻译、作文）"
    writing_src = {
        ("cet6", "prompt"): S / "六级专项题/【4】六级写作真题专项（2015-2025.12）/六级写作真题（2015-2025年6月）.pdf",
        ("cet6", "essay"): S / "六级专项题/【4】六级写作真题专项（2015-2025.12）/六级写作范文（2015-2025年6月）.pdf",
        ("cet4", "prompt"): S / "四级专项题/【4】四级写作真题专项（2015-2025.12）/四级写作真题（2015-2025年6月）.pdf",
        ("cet4", "essay"): S / "四级专项题/【4】四级写作真题专项（2015-2025.12）/四级写作范文（2015-2025年6月） .pdf",
    }
    trans_src = {
        ("cet6", "zh"): S / "六级专项题/【3】六级翻译真题专项（2015-2025.12）/六级翻译真题（2015-2025年6月）.pdf",
        ("cet6", "en"): S / "六级专项题/【3】六级翻译真题专项（2015-2025.12）/六级翻译范文（2015-2025年6月）.pdf",
        ("cet4", "zh"): S / "四级专项题/【3】四级翻译真题专项（2015-2025.12）/四级翻译真题（2015-2025年6月）.pdf",
        ("cet4", "en"): S / "四级专项题/【3】四级翻译真题专项（2015-2025.12）/四级翻译译文（2015-2025年6月）.pdf",
    }
    # 额外文件（2025.12/2026.6 带答案的合集）
    for extra in SRC.rglob("*.pdf"):
        n = extra.name
        if "专项" in str(extra):
            if re.search(r"作文真题及答案", n):
                lv = "cet4" if "四级" in n else "cet6"
                writing_src[(lv, "prompt+essay")] = extra
            if re.search(r"翻译真题及答案", n):
                lv = "cet4" if "四级" in n else "cet6"
                trans_src[(lv, "zh+en")] = extra

    # ---- 写作 ----
    wprompts, lessays = {}, {}
    for key, path in writing_src.items():
        if not Path(path).exists():
            print("MISSING", path)
            continue
        segs = split_by_header(pdf_text_all(path))
        for (lv, ym, paper), body in segs.items():
            if "prompt" in key[1]:
                wprompts[(lv, ym, paper)] = (clean_pdf_en(body), path.name)
            if "essay" in key[1]:
                lessays[(lv, ym, paper)] = (clean_pdf_en(body), path.name)
    # 真题册 prompts（docx/pdf 拆题产物）
    prompts_papers = {}
    pf = KB / "writing" / "_prompts.jsonl"
    if pf.exists():
        for l in pf.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                lv = "cet4" if r["exam"] == "CET-4" else "cet6"
                prompts_papers[(lv, r["year"], r["paper"])] = (r["topic_prompt"], r["source"]["origin_file"])

    w_out = []
    for lv in ("cet4", "cet6"):
        keys = sorted(set(list(wprompts) + list(lessays) + [k for k in prompts_papers if k[0] == lv]),
                      key=lambda k: (k[1], k[2]))
        for k in keys:
            lv2, ym, paper = k
            prompt, essay = None, None
            srcfiles = []
            if k in wprompts:
                prompt, sf = wprompts[k]; srcfiles.append(sf)
            if k in prompts_papers and not prompt:
                prompt, sf = prompts_papers[k]; srcfiles.append(sf)
            elif k in prompts_papers:
                srcfiles.append(prompts_papers[k][1])
            if k in lessays:
                essay, sf = lessays[k]; srcfiles.append(sf)
            if not prompt and not essay:
                continue
            exam = "CET-4" if lv2 == "cet4" else "CET-6"
            wc = len(essay.split()) if essay else None
            text = f"【{ym.replace('-','年')}月{exam}写作真题·第{paper}套】题目：{prompt or ''}\n范文：{essay or '（本库暂未收录范文）'}"
            w_out.append({"id": f"{lv2}.w.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                          "task_type": None, "topic_prompt": prompt, "model_essay": essay,
                          "outline": None, "good_expressions": [], "word_count": wc,
                          "source": {"origin_file": "; ".join(dict.fromkeys(srcfiles))},
                          "review": {"status": "auto_parsed"}, "text": text})

    # ---- 翻译 ----
    tzh, ten = {}, {}
    for key, path in trans_src.items():
        if not Path(path).exists():
            print("MISSING", path)
            continue
        segs = split_by_header(pdf_text_all(path))
        for (lv, ym, paper), body in segs.items():
            if "zh" in key[1]:
                tzh[(lv, ym, paper)] = (re.sub(r"\s+", " ", body).strip(), path.name)
            if "en" in key[1]:
                ten[(lv, ym, paper)] = (clean_pdf_en(body), path.name)
    papers_trans = {}
    tf = KB / "translation" / "_from_papers.jsonl"
    if tf.exists():
        for l in tf.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                lv = "cet4" if r["exam"] == "CET-4" else "cet6"
                papers_trans[(lv, r["year"], r["paper"])] = (r["source_text"], r["source"]["origin_file"])

    t_out = []
    for lv in ("cet4", "cet6"):
        keys = sorted(set(list(tzh) + list(ten) + [k for k in papers_trans if k[0] == lv]),
                      key=lambda k: (k[1], k[2]))
        for k in keys:
            lv2, ym, paper = k
            zh, en = None, None
            srcfiles = []
            if k in tzh:
                zh, sf = tzh[k]; srcfiles.append(sf)
            if k in papers_trans and not zh:
                zh, sf = papers_trans[k]; srcfiles.append(sf)
            elif k in papers_trans:
                srcfiles.append(papers_trans[k][1])
            if k in ten:
                en, sf = ten[k]; srcfiles.append(sf)
            if not zh and not en:
                continue
            exam = "CET-4" if lv2 == "cet4" else "CET-6"
            text = f"【{ym.replace('-','年')}月{exam}翻译真题·第{paper}套】中文：{zh or ''}\n参考译文：{en or '（本库暂未收录译文）'}"
            t_out.append({"id": f"{lv2}.t.{ym}_p{paper}", "exam": exam, "year": ym, "paper": paper,
                          "theme": None, "source_text": zh, "reference": en, "key_phrases": [],
                          "notes": None, "source": {"origin_file": "; ".join(dict.fromkeys(srcfiles))},
                          "review": {"status": "auto_parsed"}, "text": text})

    (KB / "writing" / "model_essays.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in w_out) + "\n", encoding="utf-8")
    (KB / "translation" / "items.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in t_out) + "\n", encoding="utf-8")
    print(f"model_essays: {len(w_out)} (with essay: {sum(1 for x in w_out if x['model_essay'])})")
    print(f"translation items: {len(t_out)} (with reference: {sum(1 for x in t_out if x['reference'])})")

if __name__ == "__main__":
    main()
