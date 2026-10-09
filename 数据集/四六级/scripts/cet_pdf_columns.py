# -*- coding: utf-8 -*-
"""基于 PDF 字符坐标的解析册结构化提取（解决双栏串扰）。

思路：
  PyMuPDF 的 get_text() 按视觉行拼接左右栏，导致题号与答案字母错位。
  本模块改用 get_text('dict') 拿到每个字符块的 bbox：
    1) 按 y 坐标聚类成「视觉行」；
    2) 在每个视觉行内按 x 坐标切分「栏」（以页面中缝为界）；
    3) 逐栏自上而下拼接，得到左栏、右栏各自的纯净文本流；
    4) 在纯净流上做「题号 + X）【标签】」配对，天然消除串栏。
"""
import re
from collections import defaultdict

import fitz


def _char_items(page):
    """收集 span 级字符及其 bbox。

    PyMuPDF 的 dict 模式通常不返回 chars 数组，但 span 自带 bbox，
    逐字符按等宽比例展开即可满足栏判定所需的 x 区间。
    """
    out = []
    d = page.get_text('dict')
    for blk in d.get('blocks', []):
        for line in blk.get('lines', []):
            for span in line.get('spans', []):
                text = span.get('text') or ''
                if not text:
                    continue
                x0, y0, x1, y1 = span['bbox']
                n = len(text)
                if n == 0:
                    continue
                w = (x1 - x0) / n
                for i, c in enumerate(text):
                    out.append((y0, x0 + i * w, c, y1, x0 + (i + 1) * w))
    return out


def column_texts(pdf_path, col_gap_ratio=0.06):
    """返回 (左栏文本, 右栏文本, 中缝x)。单栏页面右栏为空。"""
    doc = fitz.open(pdf_path)
    left, right = [], []
    for pno in range(doc.page_count):
        items = _char_items(doc[pno])
        if not items:
            continue
        width = doc[pno].rect.width
        mid = width / 2
        # y 聚类（容差 3pt）
        rows = defaultdict(list)
        for y0, x0, c, y1, x1 in items:
            key = round((y0 + y1) / 2 / 3)
            rows[key].append((x0, c))
        for key in sorted(rows):
            cells = sorted(rows[key])
            # 判断该视觉行是否真的跨栏：中缝附近有空白间隙
            has_gap = False
            prev_x = None
            for x0, c in cells:
                if prev_x is not None and (x0 - prev_x) > width * col_gap_ratio:
                    has_gap = True
                    break
                prev_x = x0
            if has_gap:
                lbuf = [c for x0, c in cells if x0 < mid]
                rbuf = [c for x0, c in cells if x0 >= mid]
                left.append(''.join(lbuf))
                right.append(''.join(rbuf))
            else:
                whole = ''.join(c for _, c in cells)
                # 整行偏左或偏右时归入对应栏
                avg = sum(x0 for x0, _ in cells) / max(1, len(cells))
                if avg < mid - width * 0.12:
                    left.append(whole)
                elif avg > mid + width * 0.12:
                    right.append(whole)
                else:
                    left.append(whole)
    doc.close()
    return '\n'.join(left), '\n'.join(right)


NUM_PAT = re.compile(r'^\s*(?:[(（]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、])\s*')
KEY_PAT = re.compile(r'[（(]?([A-O])[)）]\s*【([^】]{1,14})】\s*')
ANY_KEY = re.compile(r'^\s*([A-O])[)）]\s*$')
# 「6. A」式：题号后紧跟裸答案字母（无括号），常见于 2015 前后解析册
BARE_KEY_PAT = re.compile(r'^[\s　]*([A-O])(?:[\s　]*$|[.．、:：]|[\s　]*【)')


def _truncate_at_next_question(raw):
    """截断到下一题起点，避免把后续题的残片并入本题解析。"""
    if not raw:
        return raw
    # 下一题的英文题干（What/Which/Why/How ... ?）或新的题号+字母锚点
    cut = re.search(r'\s*(?:\d{1,2}\s*[.．、]\s*(?:What|Which|Why|How|Where|When|Who)'
                    r'|What\s+(?:did|does|is|are|was|were|will|can|do)\b'
                    r'|Section\s+[A-C]\b|Questions?\s+\d+|[A-O]\s*[)）]\s*【)', raw)
    return raw[:cut.start()].strip() if cut else raw


def parse_column(text):
    """在单栏纯净流上解析：题号 -> (答案字母, 标签, 解析正文)。"""
    out = {}
    cur = None
    for raw_line in text.split('\n'):
        ln = raw_line.rstrip()
        if not ln.strip():
            continue
        m = NUM_PAT.match(ln)
        if m:
            n = int(m.group(1) or m.group(2))
            if 1 <= n <= 60:
                cur = n
                out.setdefault(cur, {'keys': [], 'raw': '', 'labels': []})
                rest = ln[m.end():]
                # 形式一：6. A
                mb = BARE_KEY_PAT.match(rest)
                if mb and not KEY_PAT.match(rest):
                    out[cur]['keys'].append(mb.group(1))
                    rest = rest[mb.end():]
                # 形式二：1. xxx  A）【精析】...
                mk = KEY_PAT.search(rest)
                if mk:
                    out[cur]['keys'].append(mk.group(1))
                    out[cur]['labels'].append(mk.group(2))
                    rest = rest[mk.end():]
                # 形式三：【解析】/【做题提示】开头（答案字母在上一行）
                out[cur]['raw'] = (out[cur]['raw'] + ' ' + rest.strip()).strip()
                continue
        if cur is None:
            continue
        mk = KEY_PAT.search(ln)
        if mk:
            out[cur]['keys'].append(mk.group(1))
            out[cur]['labels'].append(mk.group(2))
            out[cur]['raw'] = (out[cur]['raw'] + ' ' + ln[mk.end():]).strip()
            continue
        # 「答案为 B 项。」句式：答案出现在解析正文里
        ma = re.match(r'[\s　]*(?:故(?:选|答案为)|答案(?:为|是)|正确选项为)\s*([A-O])\s*(?:项|。|，|,)?', ln)
        if ma:
            k = ma.group(1)
            if k not in out[cur]['keys']:
                out[cur]['keys'].append(k)
            out[cur]['raw'] = (out[cur]['raw'] + ' ' + ln[ma.end():].strip()).strip()
            continue
        if out[cur]['raw'] or out[cur]['keys']:
            out[cur]['raw'] = (out[cur]['raw'] + ' ' + ln.strip()).strip()
    for seg in out.values():
        seg['raw'] = re.sub(r'\s{2,}', ' ', _truncate_at_next_question(seg['raw'])).strip()
    return out


def parse_booklet(pdf_path):
    """双栏解析册 -> {题号: {...}}，左右栏结果合并。"""
    left, right = column_texts(pdf_path)
    merged = {}
    for txt in (left, right):
        if not txt:
            continue
        for num, seg in parse_column(txt).items():
            if num not in merged:
                merged[num] = {'keys': [], 'raw': '', 'labels': []}
            if not merged[num]['keys'] and seg['keys']:
                merged[num]['keys'] = seg['keys']
                merged[num]['labels'] = seg['labels']
            if len(seg['raw']) > len(merged[num]['raw']):
                merged[num]['raw'] = seg['raw']
    return merged


if __name__ == '__main__':
    import sys, json
    m = parse_booklet(sys.argv[1])
    ok = [k for k, v in m.items() if len(set(v['keys'])) == 1]
    print(json.dumps({'total': len(m), 'unique_key': len(ok)}, ensure_ascii=False))
    for k in sorted(m)[:8]:
        print(k, m[k]['keys'], repr(m[k]['raw'][:100]))
