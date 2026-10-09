# -*- coding: utf-8 -*-
"""一键全量推进四六级与教资结构化解析升级总控脚本。

支持断点续跑，每30题增量写盘，自动防重复，执行完毕后触发全库一致性验证。
"""
import sys
import os
import subprocess
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
CET_SCRIPT = ROOT / '数据集/四六级/scripts/batch_upgrade_analysis.py'
NTCE_SCRIPT = ROOT / 'kb_tools/batch_upgrade_ntce_analysis.py'


def run_step(desc, cmd):
    print(f"\n==========================================", flush=True)
    print(f"[*] 开始阶段: {desc}", flush=True)
    print(f"执行命令: {' '.join(cmd)}", flush=True)
    print(f"==========================================", flush=True)
    t0 = time.time()
    res = subprocess.run(cmd, cwd=str(ROOT))
    elapsed = time.time() - t0
    print(f"阶段完成 [{desc}]，耗时: {elapsed:.1f} 秒，返回码: {res.returncode}", flush=True)
    return res.returncode == 0


def main():
    workers = "6"
    if "--workers" in sys.argv:
        workers = sys.argv[sys.argv.index("--workers") + 1]

    cet_limit = "999999"
    if "--cet-limit" in sys.argv:
        cet_limit = sys.argv[sys.argv.index("--cet-limit") + 1]

    ntce_limit = "999999"
    if "--ntce-limit" in sys.argv:
        ntce_limit = sys.argv[sys.argv.index("--ntce-limit") + 1]

    run_cet = "--ntce-only" not in sys.argv
    run_ntce = "--cet-only" not in sys.argv

    print(f"=== 知识库解析全量升级调度器 ===", flush=True)
    print(f"工作线程: {workers} | CET目标上限: {cet_limit} | NTCE目标上限: {ntce_limit}", flush=True)

    if run_cet:
        ok = run_step(
            "四六级（CET）深度三段式解析升级",
            [sys.executable, str(CET_SCRIPT), "--limit", cet_limit, "--workers", workers]
        )
        if not ok:
            print("[!] 四六级批处理异常终止，暂停后续流程。", flush=True)
            sys.exit(1)

    if run_ntce:
        ok = run_step(
            "教师资格证（NTCE）客观题四段式解析升级",
            [sys.executable, str(NTCE_SCRIPT), "--limit", ntce_limit, "--workers", workers]
        )
        if not ok:
            print("[!] 教资批处理异常终止，暂停后续流程。", flush=True)
            sys.exit(1)

    # 运行回归测试
    print(f"\n==========================================", flush=True)
    print(f"[*] 触发全库质量与合规性回归检查", flush=True)
    print(f"==========================================", flush=True)
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=str(ROOT))
    subprocess.run([sys.executable, "权威资料/verify_sources.py"], cwd=str(ROOT))
    subprocess.run([sys.executable, "审查/知识库形式审查.py"], cwd=str(ROOT))

    print(f"\n[+] 全量解析升级流水线全部执行完毕！", flush=True)


if __name__ == '__main__':
    main()
