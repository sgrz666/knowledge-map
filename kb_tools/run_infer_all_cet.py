# -*- coding: utf-8 -*-
"""全量推进四六级缺失答案真题：基于语篇定位的候选推导与四段式结构化解析总控。"""
import sys
import subprocess
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '数据集/四六级/scripts/infer_candidate_answers.py'


def main():
    workers = "6"
    if "--workers" in sys.argv:
        workers = sys.argv[sys.argv.index("--workers") + 1]

    limit = "999999"
    if "--limit" in sys.argv:
        limit = sys.argv[sys.argv.index("--limit") + 1]

    print(f"=== 四六级无答案真题全量推导总控启动 ===", flush=True)
    print(f"工作线程: {workers} | 目标处理上限: {limit}", flush=True)

    t0 = time.time()
    res = subprocess.run([sys.executable, str(SCRIPT), "--limit", limit, "--workers", workers], cwd=str(ROOT))
    elapsed = time.time() - t0
    print(f"推导阶段完成，耗时: {elapsed:.1f} 秒，返回码: {res.returncode}", flush=True)

    if res.returncode != 0:
        print("[!] 批处理异常终止，暂停后续回归测试。", flush=True)
        sys.exit(res.returncode)

    print(f"\n==========================================", flush=True)
    print(f"[*] 触发全库质量与合规性回归检查", flush=True)
    print(f"==========================================", flush=True)
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=str(ROOT))
    subprocess.run([sys.executable, "权威资料/verify_sources.py"], cwd=str(ROOT))
    subprocess.run([sys.executable, "审查/知识库形式审查.py"], cwd=str(ROOT))

    print(f"\n[+] 四六级无答案真题全量候选推导与解析流水线执行完毕！", flush=True)


if __name__ == '__main__':
    main()
