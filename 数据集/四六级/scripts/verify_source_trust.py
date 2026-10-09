# -*- coding: utf-8 -*-
"""抽取可信度验证：用题库中「已有答案」作为基准，检验解析册抽取的一致率。

只有一致率达标（>=95%）的源才允许写入主库；其余源进入隔离名单。
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cet_pdf_columns import parse_booklet  # noqa: E402
from fill_answers import pdf_text  # noqa: E402
import re  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
KEY_SETS = {'短篇新闻': 'ABCD', '长对话': 'ABCD', '听力篇章': 'ABCD', '讲座/讲话': 'ABCD',
            '选词填空': 'ABCDEFGHIJKLMNOP', '长篇阅读': 'ABCDEFGHIJKLMNOP', '仔细阅读': 'ABCD'}


def quality(path):
    try:
        t = pdf_text(path)
    except Exception:
        return 'unreadable', ''
    if len(t) < 500:
        return 'image_only', t
    cjk = len(re.findall(r'[\u4e00-\u9fff]', t))
    weird = len(re.findall(r'[\u0080-\u024f]', t))
    if cjk and weird / cjk > 0.3:
        return 'broken_font', t
    return 'good', t


def main():
    inv = json.load(open(ROOT / '数据集/四六级/manifest/answer_source_inventory.json', encoding='utf-8'))
    rows = []
    out_rows = []
    for idx0, (key, meta) in enumerate(sorted(inv.items())):
        print(f'[{idx0+1}/{len(inv)}] {key}', flush=True)
        jsonl = ROOT / meta['jsonl'].replace('\\', '/')
        if not jsonl.exists():
            continue
        kb = {}
        for line in jsonl.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            n = (r.get('extra') or {}).get('number')
            if n is not None:
                kb[n] = r
        if not kb:
            continue
        pool = []
        for s in meta.get('local_sources') or []:
            p = (ROOT / s['path'].replace('\\', '/'))
            if p.exists():
                q, t = quality(p)
                pool.append((q, len(t), p))
        pool.sort(key=lambda x: (x[0] != 'good', -x[1]))
        if not pool or pool[0][0] != 'good':
            rows.append({'paper': key, 'status': 'no_readable_source'})
            continue
        src = pool[0][2]
        try:
            secs = parse_booklet(str(src))
        except Exception as e:
            rows.append({'paper': key, 'status': f'parse_error:{e}'})
            continue
        agree = dis = usable = 0
        for n, r in kb.items():
            keys = {k for k in secs.get(n, {}).get('keys', [])
                    if k in KEY_SETS.get(r.get('question_type') or '', '')}
            if len(keys) != 1:
                continue
            s = next(iter(keys))
            known = (r.get('content') or {}).get('answer')
            if not known:
                usable += 1
            elif known == s:
                agree += 1
            else:
                dis += 1
        total = agree + dis
        rate = (agree / total) if total else None
        rows.append({'paper': key, 'source': src.name, 'checked': total,
                     'agree': agree, 'disagree': dis, 'agreement_rate': rate,
                     'new_answer_available': usable,
                     'status': 'trusted' if (rate is not None and rate >= 0.95) else
                               ('unverified' if total == 0 else 'distrusted')})
    print('DONE', flush=True)
    out = ROOT / '数据集/四六级/manifest/source_trust_report.json'
    out.write_text(json.dumps({'generated': '2026-10-07', 'threshold': 0.95, 'papers': rows},
                              ensure_ascii=False, indent=1), encoding='utf-8')
    tr = sum(1 for r in rows if r['status'] == 'trusted')
    di = sum(1 for r in rows if r['status'] == 'distrusted')
    un = sum(1 for r in rows if r['status'] == 'unverified')
    ns = sum(1 for r in rows if r['status'] == 'no_readable_source')
    print(f'套数 total={len(rows)}trusted={tr} distrusted={di} unverified={un} no_source={ns}')
    for r in rows:
        if r['status'] == 'distrusted':
            print(f"  DIS {r['paper']:24s} {r['agree']}/{r['checked']} rate={r['agreement_rate']}")


if __name__ == '__main__':
    main()
