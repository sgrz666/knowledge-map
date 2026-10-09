# -*- coding: utf-8 -*-
"""盘点每套卷本地答案/解析源文件的文本质量,输出缺口清单(哪些卷需要外部补源)。
质量三档: good=文本层可读; needs_ocr=几乎无文本(扫描件); broken_font=有字符但中文字符占比过低(字体编码损坏)。
"""
import json
import re
import sys
from pathlib import Path

import pymupdf as fitz

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
fitz.TOOLS.mupdf_display_errors(False)

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集' / '四六级'
STAGE = KB / 'scripts' / '_staging'
SRC = ROOT / '英语四六级资料合集（2026年最新）(1)'

DATE = re.compile(r'(20\d{2})[年.\s-]*([01]?\d)[月.\s-]?')
PAPER = re.compile(r'(?:第|卷)?\s*([一二三1-3])\s*套')
CN = {'一': 1, '二': 2, '三': 3}


def file_key(name):
    dm, pm = DATE.search(name), PAPER.search(name)
    if not pm:
        pm = re.search(r'卷\s*([一二三1-3])', name)
    if not dm or not pm:
        return None
    exam = 'CET-4' if re.search(r'四级|4级|CET4', name, re.I) else \
        ('CET-6' if re.search(r'六级|6级|CET6', name, re.I) else None)
    if not exam or not 1 <= int(dm[2]) <= 12:
        return None
    return exam, f'{dm[1]}-{int(dm[2]):02d}', CN.get(pm[1], int(pm[1]) if pm[1].isdigit() else 0)


def classify_pdf(path):
    """→ (status, text_chars, cjk_ratio)"""
    try:
        with fitz.open(path) as doc:
            text = ''.join(pg.get_text(sort=True) for pg in doc)
    except Exception as e:
        return f'read_error:{type(e).__name__}', 0, 0.0
    n = len(text.strip())
    if n < 80:
        return 'needs_ocr', n, 0.0
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 解析类文档中文占比通常 >15%;字体损坏时中文几乎提取不出来
    if cjk / max(n, 1) < 0.05:
        return 'broken_font', n, round(cjk / max(n, 1), 4)
    return 'good', n, round(cjk / max(n, 1), 4)


def main():
    # 1. KB 里实际存在的卷次
    papers = {}
    for lv in ('cet4', 'cet6'):
        for p in sorted((KB / 'questions' / lv).glob('*.jsonl')):
            ym, pap = p.stem.split('_p')
            key = ('CET-4' if lv == 'cet4' else 'CET-6', ym, int(pap))
            rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
            papers[key] = {
                'jsonl': str(p.relative_to(ROOT)).replace('\\', '/'),
                'n_questions': len(rows),
                'with_answer': sum(1 for r in rows if (r.get('content') or {}).get('answer')),
                'with_analysis': sum(1 for r in rows if (r.get('analysis') or {}).get('raw')),
            }

    # 2. 本地候选源文件
    sources = {}
    roots = [STAGE, SRC]
    seen = set()
    for base in roots:
        if not base.exists():
            continue
        for p in sorted(base.rglob('*')):
            if p.suffix.lower() not in ('.pdf', '.docx') or p.is_dir():
                continue
            rp = str(p.relative_to(ROOT)).replace('\\', '/')
            if rp in seen:
                continue
            seen.add(rp)
            name = p.name
            if not re.search(r'解析|答案|answer', name, re.I):
                continue
            key = file_key(name)
            if not key:
                continue
            # 含"全套/三套全"的册子覆盖 1..3,单独记为 multi
            multi = bool(re.search(r'全\s*[二三23]\s*套|三套全', name))
            if key not in sources:
                sources[key] = []
            sources[key].append({'path': rp, 'multi': multi})

    # 3. 判定质量
    for key, items in sources.items():
        for it in items:
            p = ROOT / it['path']
            if p.suffix.lower() == '.pdf':
                status, chars, ratio = classify_pdf(p)
            else:
                try:
                    from docx_source import read_docx_units  # noqa
                    status, chars, ratio = 'good(docx)', 0, 1.0
                except Exception:
                    status, chars, ratio = 'docx', 0, 1.0
            it.update({'quality': status, 'chars': chars, 'cjk_ratio': ratio})

    # 4. 汇总缺口
    report = {}
    for key in sorted(papers):
        info = dict(papers[key])
        srcs = sources.get(key, [])
        qualities = [s['quality'] for s in srcs]
        info['local_sources'] = srcs
        info['best_quality'] = 'good' if 'good' in qualities else \
            ('good(docx)' in qualities and 'good(docx)') or \
            ('broken_font' if 'broken_font' in qualities else ('needs_ocr' if 'needs_ocr' in qualities else 'none'))
        info['needs_external'] = info['best_quality'] not in ('good', 'good(docx)')
        report[f'{key[0]}|{key[1]}|第{key[2]}套'] = info

    out = KB / 'manifest' / 'answer_source_inventory.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    # 控制台摘要
    from collections import Counter
    qsum = Counter()
    print(f'{"卷次":<24}{"题数":>4}{"有答案":>5}{"有解析":>5}  本地源质量  需外部补源')
    for k, v in report.items():
        qsum[v['best_quality']] += 1
        flag = 'YES' if v['needs_external'] else ''
        src = ';'.join(f"{Path(s['path']).name}({s['quality']})" for s in v['local_sources'][:2])
        print(f'{k:<24}{v["n_questions"]:>4}{v["with_answer"]:>5}{v["with_analysis"]:>5}  '
              f'{v["best_quality"]:<10} {flag:<4} {src[:60]}')
    print('\n质量分布:', dict(qsum))
    need = [k for k, v in report.items() if v['needs_external']]
    print('需外部补源卷次数:', len(need))
    print('已写入', out.relative_to(ROOT))


if __name__ == '__main__':
    main()
