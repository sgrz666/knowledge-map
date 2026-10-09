# -*- coding: utf-8 -*-
"""快速验证:对单份 image_only PDF 渲染前 N 页并 OCR,打印识别结果。
用于确认 Windows.Media.Ocr 路线在本题集上可行、质量可接受。
"""
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PDF = REPO / '数据集' / '四六级' / 'scripts' / '_staging' / 'answers' / 'cet6' / '2015.06英语六级考试第1套解析.pdf'
OCR_CACHE = REPO / '数据集' / '四六级' / 'scripts' / '_staging' / 'ocr_cache'
DPI = 200
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def main():
    with fitz.open(PDF) as doc:
        print(f'PDF pages={doc.page_count}')
        tmp = OCR_CACHE / '_test_png'
        tmp.mkdir(parents=True, exist_ok=True)
        imgs = []
        for i in range(min(N, doc.page_count)):
            out = tmp / f'test_p{i+1:03d}.png'
            doc[i].get_pixmap(dpi=DPI).save(str(out))
            imgs.append(str(out))
    listfile = tmp / 'list.txt'
    listfile.write_text('\n'.join(imgs), encoding='utf-8')
    ps = HERE / 'ocr_batch.ps1'
    proc = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(ps), '-ListFile', str(listfile)],
                          capture_output=True, timeout=600)
    print('rc=', proc.returncode)
    if proc.stderr:
        print('STDERR:', proc.stderr.decode('utf-8', errors='replace')[:500])
    text = proc.stdout.decode('utf-8', errors='replace')
    print('=== OCR OUTPUT ===')
    print(text[:4000])


if __name__ == '__main__':
    main()
