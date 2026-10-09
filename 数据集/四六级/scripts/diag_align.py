# -*- coding: utf-8 -*-
"""诊断脚本（只读）：摸清楚「解析册题号 -> 题库题号」的真实对应关系。

方法：题干指纹对齐。
  - 题库侧：用 content.stem / extra.text / content.options 规范化后做字符 n-gram 指纹。
  - 解析册侧：用 parse_booklet 输出的每块 raw 文本规范化后做指纹。
  - 对每道 DB 题，在解析册所有块中找指纹最相似的块，建立 (db_num -> booklet_num) 映射。
  - 据此推断偏移规律：常数偏移 / 分段偏移 / 一一对应。
"""
import sys, json, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '数据集/四六级/scripts'))
import cet_pdf_columns as cc  # noqa: E402

PY = 'C:/Users/sg/AppData/Local/Programs/Python/Python313/python.exe'


def norm(s):
    if not s:
        return ''
    s = re.sub(r'[^a-z0-9]', '', str(s).lower())
    return s


def cjk(s):
    return re.sub(r'[\s]', '', re.sub(r'[^\u4e00-\u9fff]', '', str(s or '')))


def db_fingerprint(obj):
    """返回该题最稳定的英文指纹字符串（用于与解析册比对）。"""
    c = obj.get('content') or {}
    stem = norm(c.get('stem') or '')
    options = ''.join(norm(v) for v in (c.get('options') or {}).values())
    etext = norm((obj.get('extra') or {}).get('text') or '')
    # 优先 stem，其次 options，再次 extra.text
    return max([stem, options[:120], etext[:120]], key=len)


def db_cjk_fingerprint(obj):
    c = obj.get('content') or {}
    return cjk(c.get('stem')) + cjk((obj.get('extra') or {}).get('text') or '')


def ngrams(s, n=4):
    s = s[:200]
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / (len(a | b))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--paper', required=True)  # e.g. CET-4|2019-06|第1套
    ap.add_argument('--pdf', required=True)
    args = ap.parse_args()

    paper = args.paper
    pdf = Path(args.pdf)
    # 找到对应 jsonl
    inv = json.load(open(ROOT / '数据集/四六级/manifest/answer_source_inventory.json', encoding='utf-8'))
    meta = inv[paper]
    jsonl = ROOT / meta['jsonl']
    rows = [json.loads(l) for l in jsonl.read_text(encoding='utf-8').splitlines() if l.strip()]
    db = {}
    for r in rows:
        n = (r.get('extra') or {}).get('number')
        if n is not None:
            db[int(n)] = r

    # 解析册
    secs = cc.parse_booklet(str(pdf))
    # 为每块构造英文/中文指纹
    bk_fp = {}
    bk_cjk = {}
    for num, seg in secs.items():
        raw = seg.get('raw') or ''
        bk_fp[num] = ngrams(norm(raw))
        bk_cjk[num] = cjk(raw)

    print(f"\n===== {paper} =====")
    print(f"DB 题数={len(db)}  解析册块数={len(secs)}")
    print(f"解析册题号集合: {sorted(secs)[:60]}")

    # 对每道 DB 题寻找最佳匹配 booklet 块
    mapping = {}  # db_num -> (best_bk_num, score, db_answer, bk_keys)
    for n in sorted(db):
        obj = db[n]
        d_fp = ngrams(db_fingerprint(obj))
        d_cj = db_cjk_fingerprint(obj)
        best, best_score = None, 0.0
        for m in secs:
            s = 0.0
            if d_fp and bk_fp[m]:
                s = max(s, jaccard(d_fp, bk_fp[m]))
            if d_cj and bk_cjk[m]:
                # 中文指纹也做 jaccard（用更长 gram）
                sc = jaccard(ngrams(d_cj, 5), ngrams(bk_cjk[m], 5))
                s = max(s, sc * 0.9)
            if s > best_score:
                best, best_score = m, s
        qtype = obj.get('question_type')
        ans = (obj.get('content') or {}).get('answer')
        bk_keys = secs[best]['keys'] if best is not None else []
        mapping[n] = (best, round(best_score, 2), ans, bk_keys, qtype)

    # 输出映射表，用于肉眼判断偏移规律
    print(f"{'db#':>4} {'bk#':>4} {'score':>5} {'db_ans':>5} {'bk_keys':>10} {'type':>8}")
    for n in sorted(mapping):
        bk, sc, ans, keys, qt = mapping[n]
        print(f"{n:>4} {str(bk):>4} {sc:>5} {str(ans):>5} {str(keys):>10} {str(qt):>8}")

    # 推断偏移
    offsets = defaultdict(int)
    for n in sorted(mapping):
        bk = mapping[n][0]
        if bk is not None and mapping[n][1] >= 0.15:
            offsets[n - bk] += 1
    print("\n偏移分布 (db_num - bk_num):", dict(sorted(offsets.items())))

    # 按题型分组看偏移
    print("\n按题型看 db#->bk#：")
    cur = None
    for n in sorted(mapping):
        bk, sc, ans, keys, qt = mapping[n]
        if qt != cur:
            cur = qt
            print(f"  [{qt}]")
        print(f"    db{n} -> bk{bk} (score={sc}, db_ans={ans}, bk_keys={keys})")


if __name__ == '__main__':
    main()
