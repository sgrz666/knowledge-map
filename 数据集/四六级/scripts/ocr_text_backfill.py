# -*- coding: utf-8 -*-
"""从 ocr_cache 的 OCR 文本提取答案与解析，补全缺解析/缺答案的题。

背景（重要）：
  此前误判「OCR 文本不含解析」，原因是 OCR 输出在字符间插入空格
  （原文 `10．C` 变成 `1 0 ． C`），用常规关键词搜索无法命中。
  去空格归一化后实测：397 份内容 OCR 中 306 份（77%）含「解析」、219 份（55%）含「答案为」。

OCR 版式的答案格式：
    10．C
    〖解题思路〗四项均为不定式短语……
    〖解析〗题目问的是……

流程：
  1. 归一化（去行内空格，保留换行结构）
  2. 提取「题号 + 答案字母」
  3. 提取「〖解析〗/〖解题思路〗」段落作为解析正文
  4. **交叉验证**：用题库已有答案做基准，逐套算一致率
  5. 一致率 >= 阈值才写库；只填缺失，不覆盖

默认只验证不写盘；加 --apply 执行。
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'
OCR_DIR = KB / 'scripts/_staging/ocr_cache'

# 归一化：去掉所有行内空白（OCR 会在字符间插空格），但保留换行
def normalize(t):
    t = t.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for line in t.split('\n'):
        out.append(re.sub(r'[ \t\u3000]+', '', line))
    return '\n'.join(out)


# 答案行：题号 + 分隔符 + 单个字母，且该行只含这些内容
ANS_LINE = re.compile(r'(?m)^(\d{1,2})\s*[.．、,，·。]?\s*[（(]?([A-P])[)）]?\s*$')
# 解析段落起始标记
EXP_MARK = re.compile(r'〖(?:解析|解题思路|精析|考点|定位)〗')
# 题号行（用于切分题目范围）：题号 + 答案 或 题号 + 题干
QNUM_LINE = re.compile(r'(?m)^(\d{1,2})\s*[.．、]')

KEY_SETS = {'短篇新闻': 'ABCD', '长对话': 'ABCD', '听力篇章': 'ABCD', '讲座/讲话': 'ABCD',
            '选词填空': 'ABCDEFGHIJKLMNOP', '长篇阅读': 'ABCDEFGHIJKLMNOP', '仔细阅读': 'ABCD'}

# OCR 文件名 -> 试卷 key
LEVEL = [('四级', 4), ('4级', 4), ('六级', 6), ('6级', 6)]
PAPER = [('第1套', 1), ('第2套', 2), ('第3套', 3),
         ('第一套', 1), ('第二套', 2), ('第三套', 3),
         ('卷1', 1), ('卷2', 2), ('卷3', 3),
         ('卷一', 1), ('卷二', 2), ('卷三', 3)]


def classify(name):
    m = re.match(r'([0-9]{4})\s*[.\-年]?\s*0?(\d{1,2})', name)
    if not m:
        return None
    year, mon = int(m.group(1)), int(m.group(2))
    if mon == 7:
        mon = 6
    if not (1 <= mon <= 12):
        return None
    lvl = None
    for k, v in LEVEL:
        if k in name:
            lvl = v
            break
    if lvl is None:
        return None
    pn = None
    for k, v in PAPER:
        if k in name:
            pn = v
            break
    if pn is None:
        # 「三套全」「全1套」这类，无法定位单套
        return None
    return f'CET-{lvl}|{year}-{mon:02d}|第{pn}套'


def extract_from_ocr(text):
    """返回 {题号: {'answer': 字母, 'raw': 解析正文}}"""
    n = normalize(text)
    qnums = [(m.start(), int(m.group(1))) for m in QNUM_LINE.finditer(n)]
    out = {}
    for i, (pos, num) in enumerate(qnums):
        end = qnums[i + 1][0] if i + 1 < len(qnums) else len(n)
        block = n[pos:end]
        # 答案：块首若是「题号 + 字母」单独一行
        head = block.split('\n')[0]
        am = re.match(r'^(\d{1,2})\s*[.．、,，·。]?\s*[（(]?([A-P])[)）]?\s*$', head)
        ans = am.group(2) if am else None
        # 解析正文：取标记之后的文字
        mm = EXP_MARK.search(block)
        raw = None
        if mm:
            raw = block[mm.start():].strip()
            raw = re.sub(r'\n{2,}', '\n', raw)
            if len(raw) < 20:
                raw = None
        if ans or raw:
            if num not in out or (raw and not out[num].get('raw')):
                out[num] = {'answer': ans, 'raw': raw}
    return out


def read_rows(p):
    rows = []
    for line in Path(p).open(encoding='utf-8'):
        if line.strip():
            x = json.loads(line)
            rows.extend(x if isinstance(x, list) else [x])
    return rows


def write_rows(p, rows):
    p.write_text(''.join(json.dumps(r, ensure_ascii=False).replace('\x85', '\\u0085').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029') + '\n' for r in rows),
                 encoding='utf-8')


def build_kb_index():
    idx = {}
    for lvl in ('cet4', 'cet6'):
        for f in (KB / f'questions/{lvl}').glob('*.jsonl'):
            m = re.match(r'([0-9]{4})-([0-9]{2})_p(\d)', f.stem)
            if m:
                key = f'CET-{4 if lvl == "cet4" else 6}|{m.group(1)}-{m.group(2)}|第{m.group(3)}套'
                idx[key] = f
    return idx


def main():
    apply_mode = '--apply' in sys.argv
    kb_index = build_kb_index()

    ocr_files = [f for f in sorted(os.listdir(OCR_DIR))
                 if f.endswith('.txt') and not f.startswith('_list_')]

    report = {'generated': '2026-10-08',
              'method': 'extract answers+analysis from ocr_cache (space-normalized)',
              'ocr_files_scanned': len(ocr_files),
              'validation': {}, 'per_paper': [], 'filled_answers': 0,
              'filled_analyses': 0, 'skipped': []}

    # ---------- 阶段1：交叉验证 ----------
    v_agree = v_dis = 0
    dis_detail = []
    best_for_paper = {}
    for f in ocr_files:
        key = classify(f)
        if not key or key not in kb_index:
            continue
        text = (OCR_DIR / f).read_text(encoding='utf-8', errors='ignore')
        got = extract_from_ocr(text)
        if not got:
            continue
        prev = best_for_paper.get(key)
        if prev is None or len(got) > len(prev[1]):
            best_for_paper[key] = (f, got)

    for key, (f, got) in sorted(best_for_paper.items()):
        rows = read_rows(kb_index[key])
        bynum = {(r.get('extra') or {}).get('number'): r for r in rows}
        for num, info in got.items():
            r = bynum.get(num)
            if not r or not info.get('answer'):
                continue
            known = (r.get('content') or {}).get('answer')
            if not known:
                continue
            if known == info['answer']:
                v_agree += 1
            else:
                v_dis += 1
                if len(dis_detail) < 12:
                    dis_detail.append({'paper': key, 'q': num, 'kb': known,
                                       'ocr': info['answer']})

    checked = v_agree + v_dis
    rate = v_agree / checked if checked else None
    report['validation'] = {'checked': checked, 'agree': v_agree, 'disagree': v_dis,
                            'rate': rate, 'disagree_detail': dis_detail}
    print('=== OCR 提取交叉验证（用题库已有答案做基准）===')
    print(f'可校验 {checked} 题   一致 {v_agree}   分歧 {v_dis}   '
          f'一致率 {rate:.4f}' if rate else '无样本')
    for d in dis_detail[:8]:
        print(f"  {d['paper']} Q{d['q']} 库={d['kb']} OCR={d['ocr']}")

    THRESHOLD = 0.90
    if rate is None or rate < THRESHOLD:
        print(f'\n一致率未达 {THRESHOLD}，不执行写入。')
        return
    if not apply_mode:
        print('\n(验证模式。加 --apply 执行)')
        return

    # ---------- 阶段2：写入 ----------
    for key, (f, got) in sorted(best_for_paper.items()):
        path = kb_index[key]
        rows = read_rows(path)
        bynum = {(r.get('extra') or {}).get('number'): r for r in rows}
        fa = fana = 0
        for num, info in got.items():
            r = bynum.get(num)
            if not r:
                continue
            qt = r.get('question_type') or ''
            allowed = KEY_SETS.get(qt, 'ABCD')
            changed = False
            if info.get('answer') and info['answer'] in allowed:
                if not (r.get('content') or {}).get('answer') and (r.get('extra') or {}).get('answer_status') != 'source_conflict':
                    r['content']['answer'] = info['answer']
                    r.setdefault('extra', {})['answer_extraction'] = {
                        'method': 'ocr_text_extraction',
                        'source': f,
                        'review_status': 'ocr_extracted_pending_expert_review'}
                    fa += 1
                    changed = True
            if info.get('raw') and not (r.get('analysis') or {}).get('raw'):
                r.setdefault('analysis', {})['raw'] = info['raw']
                r['analysis']['status'] = 'ocr_extracted_pending_expert_review'
                r['analysis']['method'] = 'ocr_text_extraction'
                r['analysis']['source'] = {'path': f'数据集/四六级/scripts/_staging/ocr_cache/{f}',
                                           'role': 'answer_analysis'}
                fana += 1
                changed = True
        if fa or fana:
            write_rows(path, rows)
            report['per_paper'].append({'paper': key, 'ocr_file': f,
                                        'filled_answers': fa, 'filled_analyses': fana})
            report['filled_answers'] += fa
            report['filled_analyses'] += fana

    print(f"\n=== 写入结果 ===")
    print(f'新填答案 {report["filled_answers"]}   新填解析 {report["filled_analyses"]}')
    (KB / 'manifest' / 'ocr_extract_backfill.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('已写 manifest/ocr_extract_backfill.json')


if __name__ == '__main__':
    main()
