# -*- coding: utf-8 -*-
import sys, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '数据集/四六级/scripts'))
import cet_pdf_columns as cc

pdf = sys.argv[1]
nums = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else None
secs = cc.parse_booklet(pdf)
keys = sorted(secs) if nums is None else nums
for k in keys:
    seg = secs.get(k)
    if not seg:
        continue
    print(f"\n===== booklet #{k} =====")
    print("  keys:", seg['keys'], "labels:", seg['labels'])
    print("  raw:", repr(seg['raw'][:300]))
