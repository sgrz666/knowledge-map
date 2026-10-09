# -*- coding: utf-8 -*-
"""偏移发现诊断（只读）：用题库已有答案为基准，搜索解析册题号 -> 题库题号的偏移规律。

对每套 distrusted 解析册：
  - 解析册块：取「唯一答案字母」的块（多字母/空 → 不可用作校验）。
  - 题库：取有已知答案的题作基准。
  - 尝试「常数偏移」C：bk_num = db_num + C，统计一致率。
  - 尝试「按题型分段偏移」：每个 question_type 单独拟合最佳 C。
输出每套的最佳偏移与一致率，用于判断可行性。
"""
import sys, json, re
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '数据集/四六级/scripts'))
import cet_pdf_columns as cc  # noqa: E402

INV = json.load(open(ROOT / '数据集/四六级/manifest/answer_source_inventory.json', encoding='utf-8'))
TRUST = json.load(open(ROOT / '数据集/四六级/manifest/source_trust_report.json', encoding='utf-8'))
DISTRUSTED = [r['paper'] for r in TRUST['papers'] if r.get('status') == 'distrusted']

KEY_ALLOW = set('ABCDEFGHIJKLMNOP')


def single_key(seg):
    ks = set(seg.get('keys') or [])
    if len(ks) == 1:
        return next(iter(ks))
    return None


def search_constant(db, bk, drange=range(-45, 46)):
    best = None
    for C in drange:
        ag = dis = 0
        for num, (qt, ans) in db.items():
            if ans is None:
                continue
            bn = num + C
            k = bk.get(bn)
            if k is None:
                continue
            if k == ans:
                ag += 1
            else:
                dis += 1
        tot = ag + dis
        if tot >= 5:
            rate = ag / tot
            if best is None or rate > best[0] or (rate == best[0] and tot > best[2]):
                best = (rate, C, tot, ag, dis)
    return best


def search_per_qtype(db, bk):
    by_type = defaultdict(dict)
    for num, (qt, ans) in db.items():
        if ans is not None:
            by_type[qt][num] = ans
    out = {}
    for qt, sub in by_type.items():
        # 仅样本足够时拟合
        best = None
        for C in range(-45, 46):
            ag = dis = 0
            for num, ans in sub.items():
                k = bk.get(num + C)
                if k is None:
                    continue
                if k == ans:
                    ag += 1
                else:
                    dis += 1
            tot = ag + dis
            if tot >= 3:
                rate = ag / tot
                if best is None or rate > best[0]:
                    best = (rate, C, tot, ag, dis)
        out[qt] = best
    return out


def diag_paper(paper):
    meta = INV[paper]
    jsonl = ROOT / meta['jsonl']
    if not jsonl.exists():
        return {'paper': paper, 'error': 'no_jsonl'}
    rows = [json.loads(l) for l in jsonl.read_text(encoding='utf-8').splitlines() if l.strip()]
    db = {}
    for r in rows:
        n = (r.get('extra') or {}).get('number')
        if n is not None:
            db[int(n)] = (r.get('question_type'), (r.get('content') or {}).get('answer'))

    srcs = meta.get('local_sources') or []
    good = [s for s in srcs if s.get('quality') == 'good']
    if not good:
        return {'paper': paper, 'error': 'no_good_source', 'n_db': len(db)}
    pdf = ROOT / good[0]['path']
    if not pdf.exists():
        return {'paper': paper, 'error': 'pdf_missing'}
    try:
        secs = cc.parse_booklet(str(pdf))
    except Exception as e:
        return {'paper': paper, 'error': f'parse:{e}'}
    bk = {num: single_key(seg) for num, seg in secs.items()}
    # 仅保留有唯一字母的块
    bk = {n: k for n, k in bk.items() if k}

    const = search_constant(db, bk)
    perqt = search_per_qtype(db, bk)
    n_known = sum(1 for v in db.values() if v[1] is not None)
    return {
        'paper': paper,
        'n_db': len(db), 'n_known': n_known,
        'n_bk_blocks': len(secs), 'n_bk_single_key': len(bk),
        'constant_best': const,  # (rate, C, total, ag, dis)
        'per_qtype_best': perqt,
    }


def main():
    results = []
    for paper in DISTRUSTED:
        print(f"[diag] {paper}", flush=True)
        results.append(diag_paper(paper))
    out = ROOT / '数据集/四六级/manifest/offset_diagnosis.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    # 简要汇总
    for r in results:
        if 'error' in r:
            print(f"  {r['paper']:24s} ERR {r['error']}")
            continue
        cb = r['constant_best']
        cbs = f"rate={cb[0]:.2f} C={cb[1]:+d} n={cb[2]}" if cb else "none"
        print(f"  {r['paper']:24s} known={r['n_known']:>3} bk={r['n_bk_single_key']:>3} const: {cbs}")
        for qt, b in r['per_qtype_best'].items():
            if b:
                print(f"      {qt:8s} rate={b[0]:.2f} C={b[1]:+d} n={b[2]}")
    print("WROTE", out, flush=True)


if __name__ == '__main__':
    main()
