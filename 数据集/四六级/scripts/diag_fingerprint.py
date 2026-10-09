# -*- coding: utf-8 -*-
"""内容指纹对齐诊断（只读）：不依赖题号，直接用题干/选项文本指纹把
   解析册块与题库题做 1:1 匹配，再用题库已知答案验证一致率。

这是 team-lead 建议的主判据（题号指纹对齐），区别于纯偏移搜索。
若此法仍无法达到 >=0.95，则可判定「题号对齐」路径不可行。
"""
import sys, json, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '数据集/四六级/scripts'))
import cet_pdf_columns as cc  # noqa: E402

INV = json.load(open(ROOT / '数据集/四六级/manifest/answer_source_inventory.json', encoding='utf-8'))
TRUST = json.load(open(ROOT / '数据集/四六级/manifest/source_trust_report.json', encoding='utf-8'))
DISTRUSTED = [r['paper'] for r in TRUST['papers'] if r.get('status') == 'distrusted']

STOP = set('''what which when where who whom whose why how that this these those
the a an and or but if then than as at by for from in of on to with into onto
he she it they we you his her its their our your our has have had was were is are
been being be do does did done will would can could should may might must not no
his him her them us me my your our their there here whats whichs said says say
about over under more most some such only also each other another one two three'''.split())

WORD = re.compile(r'[A-Za-z][A-Za-z]{3,}')


def tokens(s):
    if not s:
        return set()
    return {w.lower() for w in WORD.findall(str(s))} - STOP


def single_key(seg):
    ks = set(seg.get('keys') or [])
    return next(iter(ks)) if len(ks) == 1 else None


def db_query(obj):
    c = obj.get('content') or {}
    qt = tokens(c.get('stem')) | tokens((obj.get('extra') or {}).get('text'))
    for v in (c.get('options') or {}).values():
        qt |= tokens(v)
    return qt


def main():
    out = []
    for paper in DISTRUSTED:
        meta = INV[paper]
        jsonl = ROOT / meta['jsonl']
        if not jsonl.exists():
            out.append({'paper': paper, 'error': 'no_jsonl'}); continue
        rows = [json.loads(l) for l in jsonl.read_text(encoding='utf-8').splitlines() if l.strip()]
        db = {}
        for r in rows:
            n = (r.get('extra') or {}).get('number')
            if n is not None:
                db[int(n)] = r
        srcs = [s for s in (meta.get('local_sources') or []) if s.get('quality') == 'good']
        if not srcs:
            out.append({'paper': paper, 'error': 'no_good_source'}); continue
        pdf = ROOT / srcs[0]['path']
        if not pdf.exists():
            out.append({'paper': paper, 'error': 'pdf_missing'}); continue
        try:
            secs = cc.parse_booklet(str(pdf))
        except Exception as e:
            out.append({'paper': paper, 'error': f'parse:{e}'}); continue
        bk = {num: seg for num, seg in secs.items() if single_key(seg)}
        bk_tokens = {num: tokens(seg.get('raw')) for num, seg in bk.items()}

        # 构造候选对 (db_num, bk_num, score)
        pairs = []
        for dn, obj in db.items():
            dq = db_query(obj)
            if not dq:
                continue
            for bn, seg in bk.items():
                sc = len(dq & bk_tokens[bn])
                if sc >= 3:
                    pairs.append((sc, dn, bn))
        pairs.sort(reverse=True)
        used_d, used_b = set(), set()
        match = {}  # db_num -> bk_num
        for sc, dn, bn in pairs:
            if dn in used_d or bn in used_b:
                continue
            used_d.add(dn); used_b.add(bn); match[dn] = bn

        ag = dis = checked = 0
        details = []
        for dn, obj in db.items():
            if dn not in match:
                continue
            ans = (obj.get('content') or {}).get('answer')
            k = single_key(bk[match[dn]])
            if ans is None or k is None:
                continue
            checked += 1
            if k == ans:
                ag += 1
            else:
                dis += 1
            details.append((dn, match[dn], ans, k, obj.get('question_type')))
        rate = (ag / checked) if checked else None
        out.append({
            'paper': paper,
            'n_db': len(db), 'n_bk_single': len(bk),
            'n_matched': len(match), 'checked': checked,
            'agree': ag, 'disagree': dis, 'rate': rate,
            'mismatches': [(d, b, a, k, t) for (d, b, a, k, t) in details if a != k][:15],
        })
        print(f"{paper:24s} matched={len(match):>3} checked={checked:>3} "
              f"agree={ag} disagree={dis} rate={rate}", flush=True)

    Path(ROOT / '数据集/四六级/manifest/fingerprint_diagnosis.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print("WROTE fingerprint_diagnosis.json", flush=True)


if __name__ == '__main__':
    main()
