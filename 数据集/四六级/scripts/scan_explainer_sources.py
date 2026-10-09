# -*- coding: utf-8 -*-
"""全量扫描原始资料，找出所有含答案详解区、可用于提取答案的解析册。

背景：`answer_source_inventory.json` 只登记了 128 份 staging 文件（历史流程的子集），
而原始资料里有 344 份答案/解析文件。本脚本扫描全部原始 PDF，找出真正含
「答案详解 + X）【..】锚点」的册子，建立 paper -> 源 的新映射。

只读扫描，输出 manifest/explainer_source_scan.json，不改题库。
"""
import json
import os
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[3]
# 两个来源目录：原始资料合集 + 历史 staging 解析册
# staging 里的整卷解析册（如2019.06四级）文本层完整，但不在原始资料目录中，
# 只扫原始资料会漏掉它们。
CORPUS_DIRS = [
    ROOT / '英语四六级资料合集（2026年最新）(1)',
    ROOT / '数据集/四六级/scripts/_staging/answers',
]
OUT = ROOT / '数据集/四六级/manifest/explainer_source_scan.json'

EXPLAIN = re.compile(r'答案详解|答案与解析|试题解析|答案解析')
ANCHOR = re.compile(r'[（(]?([A-P])[)）]\s*【[^】]{1,12}】')
# 文件名 -> (级别, 年月, 套数)
YEAR = re.compile(r'(20\d{2})\s*[.\-年]?\s*(\d{1,2})')
LEVEL = [('四级', 'CET-4'), ('4级', 'CET-4'), ('六级', 'CET-6'), ('6级', 'CET-6')]
PAPER = [('第1套', 1), ('第2套', 2), ('第3套', 3),
         ('卷一', 1), ('卷二', 2), ('卷三', 3), ('卷1', 1), ('卷2', 2), ('卷3', 3)]


def classify(name):
    """从文件名解析 paper key。识别不了返回 None。"""
    ym = YEAR.search(name)
    if not ym:
        return None
    year, mon = int(ym.group(1)), int(ym.group(2))
    if mon == 7:
        mon = 6
    if not (1 <= mon <= 12):
        return None
    lv = None
    for k, v in LEVEL:
        if k in name:
            lv = v
            break
    if not lv:
        return None
    p = None
    for k, v in PAPER:
        if k in name:
            p = v
            break
    if not p:
        return None
    return f'{lv}|{year}-{mon:02d}|第{p}套'


def main():
    pdfs = []
    for d in CORPUS_DIRS:
        if d.exists():
            pdfs += sorted(d.rglob('*.pdf'))
    print(f'扫描 {len(pdfs)} 份 PDF（{len(CORPUS_DIRS)} 个目录）...', flush=True)
    found = []
    for i, p in enumerate(pdfs):
        if i % 50 == 0:
            print(f'  [{i}/{len(pdfs)}]', flush=True)
        try:
            d = fitz.open(p)
            t = ''.join(d[k].get_text() for k in range(d.page_count))
            d.close()
        except Exception:
            continue
        if not EXPLAIN.search(t):
            continue
        anchors = ANCHOR.findall(t)
        if len(anchors) < 5:
            continue
        key = classify(p.name)
        if not key:
            continue
        found.append({
            'paper': key,
            'path': p.relative_to(ROOT).as_posix(),
            'name': p.name,
            'chars': len(t),
            'anchors': len(anchors),
            'has_explainer_mark': bool(EXPLAIN.search(t)),
        })

    by_paper = {}
    for r in found:
        cur = by_paper.get(r['paper'])
        if cur is None or r['anchors'] > cur['anchors']:
            by_paper[r['paper']] = r

    out = {
        'generated': '2026-10-08',
        'scanned_pdfs': len(pdfs),
        'explainer_pdfs': len(found),
        'papers_covered': len(by_paper),
        'best_per_paper': by_paper,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\n含答案详解区的PDF: {len(found)}份')
    print(f'可映射到试卷: {len(by_paper)} 套')
    for k in sorted(by_paper)[:20]:
        r = by_paper[k]
        print(f"  {k:24s} 锚点{r['anchors']:4d}  {r['name'][:48]}")


if __name__ == '__main__':
    main()
