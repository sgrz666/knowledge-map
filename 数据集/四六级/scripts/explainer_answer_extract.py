# -*- coding: utf-8 -*-
"""从讲解型解析册中提取答案字母（可行性验证版）。

版式解剖结论（以 cet4/2019.06解析册 为例）：

    答案详解
    2. What did the father do to encourage his son?
    A）【精析】事实细节题。新闻中提到,这位父亲说他...

    规则：
      1. 题号行以 `N. <英文题干>` 开头
      2. 紧随其后的 `X）【精析】` 中X 即为答案字母
      3. `X）` 单独成行（双栏换行导致），但紧跟在题号行之后

    干扰项与排除：
      - 原文区里也有 `(3)`, `(4)` 标记，那是填空序号，不是题号-答案对
      - 选项区里 `A) xxx` 是选项文本，不是答案
      - 因此只在「答案详解」标记之后、且题号行必须是英文问句时才采信

验证策略：用题库已有答案作基准，逐卷算一致率，>=95% 才算可行。
本脚本只读+ 输出报告，不写题库。
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'

# 题号行：N. 后面紧跟英文问句（以 ? 或 ? 前缀的疑问词）
QLINE = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*([A-Z][^\n]{6,200}?\?)\s*$')
# 答案行：单独成行的 X） 紧跟【精析】类标签
ALINE = re.compile(r'(?m)^\s*[（(]?([A-P])[)）]\s*【[^】]{1,12}】')
# 兜底：题号行后紧跟 X） 且下一行是【
ALINE2 = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、][^\n]{0,200}\n\s*[（(]?([A-P])[)）]\s*【')

EXAM_START = re.compile(r'(?:答案详解|答案解析|试题解析|参考答案|答案与解析)')


def extract_from_text(text):
    """返回 {题号: 答案字母}。只在答案详解区作业。

    需覆盖两类版式（实测归纳）：

    A类 听力/仔细阅读 —— 题号+英文问句+ 答案字母 + 【精析】
        2. What did the father do to encourage his son?
        A）【精析】事实细节题。新闻中提到...

    B 类 选词填空/长篇阅读 —— 题号 + 【考点】标签 + 答案字母 + 【语法判断】
        26 . 【考点】动词辨析题。
        H）【语法判断】通过分析句子结构可知...

    区分要点：答案字母永远紧跟一个【...】样式标签，而非紧跟英文问句。
    """
    m = EXAM_START.search(text)
    if not m:
        return {}
    region = text[m.start():]
    out = {}

    # ---- A 类：题号行(英文问句) → 其后第一个 X）【..】 ----
    for qm in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*([A-Z][^\n]{4,240}?\?)\s*$', region):
        n = int(qm.group(1))
        if n in out:
            continue
        tail = region[qm.end():qm.end() + 500]
        am = ALINE.search(tail)
        if am:
            out[n] = am.group(1)

    # ---- B 类：题号 + 【标签】行 → 其后第一个 X）【..】 ----
    for qm in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*【[^】]{1,14}】[^\n]{0,80}$', region):
        n = int(qm.group(1))
        if n in out:
            continue
        tail = region[qm.end():qm.end() + 600]
        am = ALINE.search(tail)
        if am:
            out[n] = am.group(1)

    # ---- 双锚点互验：解析正文里的「故…答案为X）」「正确答案为X）」 ----
    # 实测（cet4/2019.06）：长篇阅读区两种锚点 10/12 吻合，吻合者可安全采信。
    # 只保留「两法一致」的题，避免解析册内部版式噪声导致错配。
    concl = {}
    for qm in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]', region):
        n = int(qm.group(1))
        if n in concl:
            continue
        tail = region[qm.end():qm.end() + 900]
        cm = re.search(r'(?:故(?:本题)?(?:正确答案)?为|正确答案为|答案为)\s*([A-P])[)）]', tail)
        if cm:
            concl[n] = cm.group(1)
    for n, v in concl.items():
        if n in out and out[n] != v:
            out[n] = None# 两法冲突 → 标记为不可信，稍后剔除
    for n in [k for k, v in out.items() if v is None]:
        del out[n]
    return out


def extract_loose(text):
    """宽松提取：没有「答案详解」标记时，直接扫「题号+英文问句 → X）」模式。

    适用于部分解析册把答案直接放在每段解析开头、无区块标记的版式。
    同样做双锚点互验，冲突则剔除。
    """
    out = {}
    for qm in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*([A-Z][^\n]{4,240}?\?)\s*$', text):
        n = int(qm.group(1))
        if n in out:
            continue
        tail = text[qm.end():qm.end() + 500]
        am = ALINE.search(tail)
        if am:
            out[n] = am.group(1)
    if not out:
        return {}
    # 双锚点互验
    concl = {}
    for qm in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]', text):
        n = int(qm.group(1))
        if n in concl:
            continue
        tail = text[qm.end():qm.end() + 900]
        cm = re.search(r'(?:故(?:本题)?(?:正确答案)?为|正确答案为|答案为)\s*([A-P])[)）]', tail)
        if cm:
            concl[n] = cm.group(1)
    for n, v in concl.items():
        if n in out and out[n] != v:
            out[n] = None
    return {k: v for k, v in out.items() if v}


def main():
    inv = json.load(open(KB / 'manifest' / 'answer_source_inventory.json', encoding='utf-8'))

    def read_rows(p):
        rows = []
        for line in Path(p).open(encoding='utf-8'):
            if line.strip():
                x = json.loads(line)
                rows.extend(x if isinstance(x, list) else [x])
        return rows

    # 题库索引：paper key -> jsonl
    kb_index = {}
    for lvl in ('cet4', 'cet6'):
        for f in (KB / f'questions/{lvl}').glob('*.jsonl'):
            m = re.match(r'([0-9]{4})-([0-9]{2})_p(\d)', f.stem)
            if m:
                key = f'CET-{4 if lvl=="cet4" else 6}|{m.group(1)}-{m.group(2)}|第{m.group(3)}套'
                kb_index[key] = f

    report = {'threshold': 0.95, 'papers': [], 'summary': {}}
    tot_check = tot_agree = tot_fill = 0
    trusted_fills = 0
    for key, meta in sorted(inv.items()):
        if key not in kb_index:
            continue
        rows = read_rows(kb_index[key])
        bynum = {(r.get('extra') or {}).get('number'): r for r in rows}
        best = None
        # 遍历该套的**所有**本地源，取提取题数最多的那个。
        # 原因：首选源常是「听力原文册」，答案详解可能只在分题型解析册里。
        for s in meta.get('local_sources') or []:
            p = ROOT / s['path'].replace('\\', '/')
            if not p.exists():
                continue
            try:
                if p.suffix.lower() == '.pdf':
                    import fitz
                    d = fitz.open(p)
                    t = '\n'.join(d[i].get_text() for i in range(d.page_count))
                    d.close()
                else:
                    t = p.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            got = extract_from_text(t)
            if got and (best is None or len(got) > len(best[1])):
                best = (p, got)
        if not best:
            # 兜底：首选源里没有答案详解区，但可能有「N. 英文问句 + X）」
            for s in meta.get('local_sources') or []:
                p = ROOT / s['path'].replace('\\', '/')
                if not p.exists():
                    continue
                try:
                    if p.suffix.lower() == '.pdf':
                        import fitz
                        d = fitz.open(p)
                        t = '\n'.join(d[i].get_text() for i in range(d.page_count))
                        d.close()
                    else:
                        t = p.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue
                got = extract_loose(t)
                if got and (best is None or len(got) > len(best[1])):
                    best = (p, got)
        if not best:
            report['papers'].append({'paper': key, 'status': 'no_answer_explainer_found'})
            continue
        src, got = best
        agree = dis = fill = 0
        dis_detail = []
        for n, r in bynum.items():
            if n is None or n not in got:
                continue
            g = got[n]
            known = (r.get('content') or {}).get('answer')
            if known:
                if known == g:
                    agree += 1
                else:
                    dis += 1
                    dis_detail.append({'q': n, 'kb': known, 'got': g})
            else:
                fill += 1
        checked = agree + dis
        rate = (agree / checked) if checked else None
        rec = {'paper': key, 'source': src.name, 'extracted': len(got),
               'checked': checked, 'agree': agree, 'disagree': dis,
               'agreement_rate': rate, 'new_answer_available': fill,
               'disagree_detail': dis_detail[:8],
               'status': ('trusted' if rate is not None and rate >= 0.95 else
                          'unverified' if checked == 0 else 'distrusted')}
        report['papers'].append(rec)
        if rec['status'] == 'trusted':
            tot_check += checked
            tot_agree += agree
            trusted_fills += fill

    tr = [p for p in report['papers'] if p['status'] == 'trusted']
    report['summary'] = {
        'papers_scanned': len(report['papers']),
        'trusted': len(tr),
        'distrusted': sum(1 for p in report['papers'] if p['status'] == 'distrusted'),
        'unverified': sum(1 for p in report['papers'] if p['status'] == 'unverified'),
        'no_explainer': sum(1 for p in report['papers'] if p['status'] == 'no_answer_explainer_found'),
        'trusted_checked': tot_check, 'trusted_agree': tot_agree,
        'trusted_overall_rate': (tot_agree / tot_check) if tot_check else None,
        'recoverable_answers': trusted_fills,
    }
    out = KB / 'manifest' / 'explainer_answer_feasibility.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    s = report['summary']
    print('=== 讲解型解析册答案提取可行性 ===')
    print(f"扫描 {s['papers_scanned']} 套")
    print(f"  可信(trusted)     {s['trusted']}")
    print(f"  不可信(distrusted) {s['distrusted']}")
    print(f"  无校验样本         {s['unverified']}")
    print(f"  未找到答案详解区   {s['no_explainer']}")
    print()
    if s['trusted_overall_rate'] is not None:
        print(f"可信套一致率: {s['trusted_agree']}/{s['trusted_checked']} = {s['trusted_overall_rate']:.3f}")
    print(f"可恢复答案: {s['recoverable_answers']} 题")
    print()
    print('可信套明细（按可恢复数排序）:')
    for p in sorted(tr, key=lambda x: -x['new_answer_available'])[:20]:
        print(f"  {p['paper']:24s} 提取{p['extracted']:3d} 校验{p['checked']:3d} "
              f"一致率{p['agreement_rate']:.3f} 可补{p['new_answer_available']:3d}")
    print()
    print('不一致样本（用于诊断规则缺陷）:')
    for p in [x for x in report['papers'] if x['status'] == 'distrusted'][:5]:
        print(f"  {p['paper']}  {p['agree']}/{p['checked']}  {p['disagree_detail'][:4]}")


if __name__ == '__main__':
    main()
