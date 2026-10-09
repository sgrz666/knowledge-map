# -*- coding: utf-8 -*-
"""只读扫描:对 128 份解析册做三分类 (good / broken_font / image_only)。
规则(来自 task 指令):
  - 文本层 < 500 字符  -> image_only
  - 中文字符数少 且 非 ASCII 字符占比 > 30%  -> broken_font
  - 其余 -> good
输出 JSON 到 manifest/_scan_classify.json
"""
import json
import re
from collections import defaultdict
from pathlib import Path

import pymupdf as fitz

HERE = Path(__file__).resolve().parent  # scripts
REPO = HERE.parents[2]  # knowledge_map
STAGE = REPO / '数据集' / '四六级' / 'scripts' / '_staging' / 'answers'
OUT = REPO / '数据集' / '四六级' / 'manifest' / '_scan_classify.json'

CJK = re.compile(r'[\u4e00-\u9fff]')
MOJIBAKE = re.compile(r'[\u0900-\u0dff\u0e00-\u0fff\uf900-\ufaff\ue000-\uf8ff\ufffd]')


def classify(path):
    try:
        with fitz.open(path) as doc:
            pages = doc.page_count
            text = ''.join(pg.get_text(sort=True) for pg in doc)
    except Exception as e:
        return {'status': 'error', 'error': str(e)[:200], 'pages': 0,
                'total_len': 0, 'cjk': 0, 'non_ascii_ratio': 0, 'mojibake': 0}
    total = len(text)
    cjk = len(CJK.findall(text))
    moji = len(MOJIBAKE.findall(text))
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = total - ascii_count
    non_ascii_ratio = (non_ascii / total) if total else 0.0
    moji_ratio = (moji / (cjk + moji + 1))
    if total < 500:
        cls = 'image_only'
    elif moji_ratio > 0.10:
        cls = 'broken_font'
    else:
        cls = 'good'
    return {'status': 'ok', 'pages': pages, 'total_len': total, 'cjk': cjk,
            'non_ascii_ratio': round(non_ascii_ratio, 3), 'mojibake': moji,
            'moji_ratio': round(moji_ratio, 3), 'class': cls}


def main():
    results = []
    pdfs = sorted(STAGE.rglob('*.pdf'))
    by_class = defaultdict(list)
    for p in pdfs:
        rel = str(p.relative_to(REPO)).replace('\\', '/')
        info = classify(p)
        info['path'] = rel
        info['exam'] = 'cet6' if '/cet6/' in rel else ('cet4' if '/cet4/' in rel else 'unknown')
        info['name'] = p.name
        results.append(info)
        if info['status'] == 'ok':
            by_class[info['class']].append(rel)
    summary = {c: len(v) for c, v in by_class.items()}
    summary['total'] = len(results)
    summary['errors'] = sum(1 for r in results if r['status'] == 'error')
    out = {'summary': summary,
           'image_only': by_class.get('image_only', []),
           'broken_font': by_class.get('broken_font', []),
           'good': by_class.get('good', []),
           'details': results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    print('details ->', OUT.relative_to(REPO))


if __name__ == '__main__':
    main()
