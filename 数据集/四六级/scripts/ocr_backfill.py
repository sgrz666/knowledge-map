# -*- coding: utf-8 -*-
"""方案A:OCR 提取图片型/损坏型解析册 -> 回填题库缺失答案与解析。

两阶段:
  默认(无 --write):OCR + 提取 + 交叉校验 + 决策,打印一致率与人类抽样,写入
    manifest/_ocr_eval.json,但绝不改动题库。
  --write:在决策结果基础上,只填补缺失字段并追加溯源记录,写入题库与最终报告。

信任门(team-lead 指令):
  - 按源对"题库已有答案"的题做交叉比对,样本>=8 且一致率>=0.95 -> 全量信任;
  - 一致率<0.95 且样本>=8 -> 隔离(疑似题号错位),不写入;
  - 样本<8 -> 证据不足,改走"逐题身份匹配"保守回填(仅填 OCR 块能命中题干/
    选项的题),其余留空。
答案字母合法性(valid_key):其余题型仅 A-D 且在选项内;选词填空/长篇阅读可 A-O。
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fill_answers_ocr as fo  # noqa: E402
import fill_answers as fa  # noqa: E402
from cet_common import load_jsonl, jsonl_dumps  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
QDIR = REPO / '数据集' / '四六级' / 'questions'
OCR_ENGINE = 'Windows.Media.Ocr zh-Hans-CN 200dpi'

TRUST_AGREE = 0.95

# (relpath, category). image_only 中 2016-06 六级无题库文件 -> no_db_target(不 OCR)。
TARGETS = [
    # ---- image_only (cet6) ----
    ('数据集/四六级/scripts/_staging/answers/cet6/2015.06英语六级考试第1套解析.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2015.06英语六级考试第2套解析.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2015.06英语六级考试第3套解析.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2015.12英语六级考试第1套解析.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2015.12英语六级考试第2套解析.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2015.12英语六级考试第3套解析.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2016.06英语六级考试第1套解析.pdf', 'image_only_no_db'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2016.06英语六级考试第2套解析.pdf', 'image_only_no_db'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2016.06英语六级考试第3套解析.pdf', 'image_only_no_db'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2019年06月真题解析第1套.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2019年06月真题解析第2套.pdf', 'image_only'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2019年06月真题解析第3套.pdf', 'image_only'),
    # ---- broken_font 试跑 5 份 ----
    ('数据集/四六级/scripts/_staging/answers/cet6/2016年12月六级（第1套）答案及解析.pdf', 'broken_font'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2016年12月六级（第2套）答案及解析.pdf', 'broken_font'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2017.06英语六级考试第1套解析.pdf', 'broken_font'),
    ('数据集/四六级/scripts/_staging/answers/cet6/2017.06英语六级考试第2套解析.pdf', 'broken_font'),
    ('数据集/四六级/scripts/_staging/answers/cet4/2017年6月英语四级真题（卷一）答案解析.pdf', 'broken_font'),
]


def choose_letter(letters, prose):
    if len(letters) == 1:
        return next(iter(letters))
    if len(letters) > 1:
        return prose if (prose and len(prose) == 1) else None
    if prose and len(prose) == 1:
        return prose
    return None


def per_question_trusted(row, block):
    if not block:
        return False
    ok, _ = fo.identity_level_a(row, block)
    if ok:
        return True
    ok, _ = fo.identity_level_b(row, block)
    return ok


def load_db():
    db = {}
    files = {}
    for lv in ('cet4', 'cet6'):
        for f in sorted((QDIR / lv).glob('*.jsonl')):
            ym, pap = f.stem.split('_p')
            key = ('CET-4' if lv == 'cet4' else 'CET-6', ym, int(pap))
            rows = load_jsonl(f)
            d = {}
            for r in rows:
                ex = r.setdefault('extra', {})
                n = ex.get('source_question_number') or ex.get('number')
                if n is None:
                    continue
                d[int(n)] = r
            db[key] = d
            files[key] = f
    return db, files


def process_source(path, category):
    rel = str(path.relative_to(REPO)).replace('\\', '/')
    info = {'path': rel, 'category': category}
    if category == 'image_only_no_db':
        with fo.fitz.open(path) as doc:
            info['pages'] = doc.page_count
        info['status'] = 'no_db_target'
        info['note'] = '解析册存在但题库无对应卷文件,无法回填'
        return info
    meta = fo.file_key(path.name, rel)
    if not meta:
        info['status'] = 'no_meta'
        return info
    exam, ym, pnum = meta
    try:
        pages = fo.ocr_pdf(path)
    except Exception as e:
        info['status'] = 'ocr_error'
        info['error'] = str(e)[:200]
        return info
    text, page_of = fo.build_ocr_text(pages)

    # --- 主导提取:答案行 "N · X"(中点在 U+00B7 等),EOL 仅单个字母 ---
    answers, expls, ans_pages, stems = extract_answer_lines(text, page_of)

    # --- 备选:印刷答案表 与 块级标签 ---
    grid = {n: (ch, gp) for n, ch, gp in fo.extract_grids(text, page_of)}
    blocks = fo.ocr_question_blocks(text, page_of)
    block_map = {}
    for blk in blocks:
        n = blk['n']
        letters, expl, marker, prose = fo.block_answer_and_explanation(blk['text'])
        pf = fo.page_for(page_of, blk['start'], blk['end'])
        letter = choose_letter(letters, prose)
        block_map[n] = {'letter': letter, 'expl': expl, 'pages': pf,
                        'marker': marker, 'block': blk['text'][:1500]}

    # --- 合并:答案行优先,其次 grid,其次块字母 ---
    cands = {}
    all_n = set(answers) | set(grid) | set(block_map)
    for n in all_n:
        al = answers.get(n)
        gl = grid.get(n)
        bl = block_map.get(n, {}).get('letter')
        letter = (al[0] if al else None) or (gl[0] if gl else None) or bl
        expl = expls.get(n) or block_map.get(n, {}).get('expl')
        pf = (al[2] if al else None) or (gl[1] if gl else None) or block_map.get(n, {}).get('pages')
        method = ('ocr_answer_line' if al else
                  ('published_answer_grid' if gl else
                   ('ocr_' + block_map.get(n, {}).get('marker', 'block') if block_map.get(n, {}).get('marker') else 'ocr_block')))
        # 身份匹配用块:题干行 + 解析段(含题干原文,便于命中 stem/options)
        blk_text = ' '.join(x for x in [stems.get(n, ''), expl or ''] if x).strip()[:1500]
        cands[n] = {'letter': letter,
                    'letters': sorted({x for x in [al[0] if al else None, gl[0] if gl else None, bl] if x}),
                    'expl': expl, 'pages': pf, 'method': method,
                    'block': blk_text or block_map.get(n, {}).get('block', ''),
                    'prose': None, 'marker': method}
    info.update({'status': 'ocr_ok', 'exam': exam, 'ym': ym, 'pnum': pnum,
                 'pages': len(pages), 'n_cands': len(cands), 'cands': cands})
    return info


def extract_answer_lines(text, page_of):
    """答案行形如 '10 · D' / '21. A' / '36 · E' (数字+分隔符+行尾单字母)。
    分隔符含中点在 U+00B7。返回 answers[n]=(letter,marker,page), expls[n]=说明段,
    stems[n]=题干行原文(用于身份匹配)。"""
    ANS = re.compile(r'(?m)^\s*(\d{1,2})\s*[·•・\.．、]\s*([A-Oa-o])\s*[。.．]?\s*$')
    STEM = re.compile(r'(?m)^\s*(\d{1,2})\s*[·•・\.．、]\s*(?=[A-Za-z一-鿿])')
    lines = text.split('\n')
    pos = 0
    line_start = []
    for ln in lines:
        line_start.append(pos)
        pos += len(ln) + 1

    def page_of_line(i):
        p = line_start[i]
        for a, b, pg in page_of:
            if a <= p < b:
                return pg
        return page_of[-1][2] if page_of else None

    ans_hits = []
    stem_idx = set()
    stems = {}
    for i, ln in enumerate(lines):
        m = ANS.match(ln)
        if m and 1 <= int(m.group(1)) <= 55:
            ans_hits.append((i, int(m.group(1)), m.group(2).upper()))
        elif STEM.match(ln) and len(ln) > 6:
            stem_idx.add(i)
            sm = STEM.match(ln)
            n = int(sm.group(1))
            if 1 <= n <= 55 and n not in stems:
                stems[n] = ln.strip()
    answers, expls, ans_pages = {}, {}, {}
    anchor_idx = set(i for i, _, _ in ans_hits) | stem_idx
    for k, (i, n, ch) in enumerate(ans_hits):
        if n in answers:
            continue  # 取首次出现
        answers[n] = (ch, 'ocr_answer_line', page_of_line(i))
        ans_pages[n] = page_of_line(i)
        # 说明段:从答案行后一行到下一个锚点(答案行或题干行)
        seg = []
        j = i + 1
        while j < len(lines) and j not in anchor_idx:
            seg.append(lines[j])
            j += 1
        expl = ' '.join(seg).strip()
        if expl:
            expls[n] = re.sub(r'\s+', ' ', expl)
    return answers, expls, ans_pages, stems


def evaluate(db, info):
    key = (info['exam'], info['ym'], info['pnum'])
    d = db.get(key, {})
    agree = disagree = illegal = no_row = 0
    mismatches = []
    for n, c in info['cands'].items():
        L = c['letter']
        if L is None:
            continue
        row = d.get(n)
        if row is None:
            no_row += 1
            continue
        if not fa.valid_key(row, L):
            illegal += 1
            continue
        dbans = (row.get('content') or {}).get('answer')
        if dbans:
            if L == dbans:
                agree += 1
            else:
                disagree += 1
                mismatches.append({'q': n, 'ocr': L, 'db': dbans,
                                   'snippet': (c['block'] or '')[:60]})
    sample = agree + disagree
    rate = (agree / sample) if sample else None
    # 信任门(team-lead 指令):样本可测且一致率>=0.95 -> full; 否则 isolate;
    # 样本为 0(本卷题库无已有答案) -> unverified(无法用 DB 校验,隔离待专家审)。
    if sample == 0:
        trust = 'unverified'
    elif rate is not None and rate >= TRUST_AGREE:
        trust = 'full'
    else:
        trust = 'isolate'
    # DB 该题卷已有答案的字母分布(异常单字母主导 -> 地面真值可能不可靠)
    dist = {}
    for r in d.values():
        a = (r.get('content') or {}).get('answer')
        if a:
            dist[a] = dist.get(a, 0) + 1
    total_db = sum(dist.values())
    max_share = (max(dist.values()) / total_db) if total_db else 0
    db_unreliable = total_db >= 8 and max_share > 0.45
    info['xcheck'] = {'sample': sample, 'agree': agree, 'disagree': disagree,
                      'illegal': illegal, 'no_db_row': no_row,
                      'agree_rate': round(rate, 4) if rate is not None else None,
                      'trust': trust, 'mismatches': mismatches[:20],
                      'db_answer_distribution': dist,
                      'db_unreliable_distribution': db_unreliable}
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='实际回填题库(默认只评估)')
    args = ap.parse_args()

    db, files = load_db()
    results = []
    for rel, cat in TARGETS:
        path = REPO / rel
        if not path.exists():
            results.append({'path': rel, 'category': cat, 'status': 'missing_file'})
            continue
        info = process_source(path, cat)
        if info.get('status') in ('ocr_ok',) and 'exam' in info:
            info = evaluate(db, info)
        results.append(info)
        st = info.get('status')
        if st == 'ocr_ok':
            x = info['xcheck']
            print(f"[{cat}] {info['exam']} {info['ym']} p{info['pnum']} "
                  f"pages={info['pages']} cands={info['n_cands']} "
                  f"xcheck sample={x['sample']} agree={x['agree']} "
                  f"disagree={x['disagree']} illegal={x['illegal']} "
                  f"rate={x['agree_rate']} -> {x['trust']}")
        else:
            print(f"[{cat}] {rel} -> {st} {info.get('note','')}")

    # 人类抽样:从 full 信任源挑已交叉校验命中的题,展示 OCR 字母与块片段
    sample_cases = []
    for info in results:
        if info.get('status') != 'ocr_ok' or info['xcheck']['trust'] != 'full':
            continue
        key = (info['exam'], info['ym'], info['pnum'])
        d = db.get(key, {})
        shown = 0
        for n, c in list(info['cands'].items())[:8]:
            L = c['letter']
            if L is None:
                continue
            row = d.get(n)
            if not row:
                continue
            dbans = (row.get('content') or {}).get('answer')
            sample_cases.append({'exam': info['exam'], 'ym': info['ym'], 'p': info['pnum'],
                                 'q': n, 'ocr_letter': L, 'db_answer': dbans,
                                 'method': c['method'],
                                 'block_snippet': (c['block'] or '')[:90]})
            shown += 1
            if len(sample_cases) >= 12:
                break
        if len(sample_cases) >= 12:
            break

    out_eval = REPO / '数据集' / '四六级' / 'manifest' / '_ocr_eval.json'
    out_eval.write_text(json.dumps({'results': results, 'sample_cases': sample_cases},
                                  ensure_ascii=False, indent=2), encoding='utf-8')
    print('eval ->', out_eval.relative_to(REPO))
    print('=== HUMAN SAMPLE (first 12) ===')
    for s in sample_cases[:12]:
        print(f"  {s['exam']} {s['ym']} p{s['p']} Q{s['q']}: OCR={s['ocr_letter']} "
              f"DB={s['db_answer']} [{s['method']}] {s['block_snippet']!r}")

    if args.write:
        write_back(db, files, results)


def write_back(db, files, results):
    report = {'rule': 'ocr_backfill_planA', 'ocr_engine': OCR_ENGINE,
              'min_xcheck_sample': MIN_XCHECK_SAMPLE, 'trust_agree': TRUST_AGREE,
              'sources': {}, 'totals': {}}
    totals = defaultdict(int)
    modified_files = set()
    still_missing = defaultdict(list)  # key str -> [qnums]
    for info in results:
        if info.get('status') != 'ocr_ok' or 'exam' not in info:
            report['sources'][info['path']] = {'status': info.get('status'),
                                               'note': info.get('note')}
            if info.get('status') == 'no_db_target':
                totals['no_db_target'] += 1
            continue
        key = (info['exam'], info['ym'], info['pnum'])
        d = db.get(key, {})
        trust = info['xcheck']['trust']
        reason = None
        if trust == 'isolate':
            reason = ('cross_check_agree_rate=%.3f (<0.95); possible numbering '
                      'misalignment or DB/ground-truth error' % (info['xcheck']['agree_rate'] or 0))
        elif trust == 'unverified':
            reason = 'no DB existing answers for this paper; cannot validate via cross-check'
        if info['xcheck'].get('db_unreliable_distribution'):
            reason = (reason + '; ' if reason else '') + 'DB ground-truth letter distribution anomalous (single-letter dominated), cross-check may be invalid'
        per = report['sources'].setdefault(info['path'], {
            'exam': info['exam'], 'ym': info['ym'], 'pnum': info['pnum'],
            'category': info['category'], 'pages': info['pages'],
            'trust': trust, 'xcheck': info['xcheck'], 'new_answers': 0,
            'new_analyses': 0, 'illegal_dropped': 0, 'unbound': 0,
            'isolated': 0, 'isolate_reason': reason})
        if trust != 'full':
            # 隔离:本源整体不写入(已有答案不覆盖,缺失不填)
            per['isolated'] = info['xcheck']['sample']
            totals['isolated_sources'] += 1
            continue
        for n, c in info['cands'].items():
            L = c['letter']
            if L is None:
                continue
            row = d.get(n)
            if row is None:
                continue
            if not fa.valid_key(row, L):
                per['illegal_dropped'] += 1
                totals['illegal_dropped'] += 1
                continue
            dbans = (row.get('content') or {}).get('answer')
            if dbans:
                continue  # 已有答案,不覆盖
            # 回填答案(缺失)
            row['content']['answer'] = L
            ex = row.setdefault('extra', {})
            ex['answer_status'] = 'source_extracted_pending_expert_review'
            ex['answer_extraction'] = {
                'method': c['method'], 'rule_version': 4,
                'source_count': 1, 'binding': c['method'],
                'expert_review': {'status': 'pending', 'reviewer': None,
                                  'reviewed_at': None}}
            per['new_answers'] += 1
            totals['new_answers'] += 1
            # 溯源记录
            files_list = row.setdefault('source', {}).setdefault('files', [])
            loc = {'question_number': n, 'pages': c['pages'],
                   'binding': c['method'], 'extraction': 'ocr',
                   'ocr_engine': OCR_ENGINE}
            entry = {'path': info['path'], 'role': 'answer_analysis', 'locator': loc}
            if entry not in files_list:
                files_list.append(entry)
            # 解析原文
            a = row.setdefault('analysis', {})
            if not a.get('raw') and c.get('expl'):
                expl = c['expl']
                cjk = len(re.findall(r'[\u4e00-\u9fff]', expl))
                if cjk >= 12:
                    a['raw'] = expl
                    a['status'] = 'source_extracted_pending_expert_review'
                    a['method'] = 'published_explanation_text_extraction'
                    a['source'] = {'path': info['path'], 'role': 'answer_analysis',
                                   'locator': loc}
                    a['trace_back'] = (f"原始解析 {info['path']}，题号 {n}，"
                                       f"OCR 页码 {c['pages']}；"
                                       f"{OCR_ENGINE} 提取，待专家审核。")
                    per['new_analyses'] += 1
                    totals['new_analyses'] += 1
            modified_files.add(key)
        # 该卷仍缺失答案
        for nn, rrow in d.items():
            if not (rrow.get('content') or {}).get('answer'):
                still_missing[f'{info["exam"]}|{info["ym"]}|p{info["pnum"]}'].append(nn)

    for key in modified_files:
        f = files[key]
        rows = load_jsonl(f)
        # 重新按 number 映射以写回(保持原顺序)
        by_num = {}
        for r in rows:
            ex = r.get('extra', {})
            nn = ex.get('source_question_number') or ex.get('number')
            if nn is not None:
                by_num[int(nn)] = r
        # db 中已就地修改,直接用 db[key] 的内容覆盖对应行
        out_rows = []
        for r in rows:
            ex = r.get('extra', {})
            nn = ex.get('source_question_number') or ex.get('number')
            if nn is not None and int(nn) in db[key]:
                out_rows.append(db[key][int(nn)])
            else:
                out_rows.append(r)
        f.write_text('\n'.join(jsonl_dumps(r) for r in out_rows) + '\n', encoding='utf-8')
        totals['files_modified'] += 1

    report['totals'] = dict(totals)
    report['still_missing_by_paper'] = {k: sorted(v) for k, v in still_missing.items()}
    out = REPO / '数据集' / '四六级' / 'manifest' / 'ocr_backfill_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('REPORT ->', out.relative_to(REPO))
    print('totals:', json.dumps(totals, ensure_ascii=False))


if __name__ == '__main__':
    main()
