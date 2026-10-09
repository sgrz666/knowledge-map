"""运行只读回归和全库验收，保存真实退出码及输出，不把待补退出1改成通过。"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "审查"
COMMANDS = [
    ["-m", "unittest", "discover", "-s", "tests", "-v"],
    ["-m", "unittest", "discover", "-s", "权威资料", "-p", "test_source_index.py", "-v"],
    ["权威资料/verify_sources.py"],
    ["审查/知识库形式审查.py"],
    ["审查/validate_kb.py"],
]


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs = OUT / "验证日志" / stamp
    logs.mkdir(parents=True, exist_ok=True)
    record_path = OUT / "验证运行记录.json"
    record = {
        "started_at": now(), "python": sys.executable, "cwd": str(ROOT),
        "note": "单元测试和结构检查通过不代表内容完整；全量验收的实际退出码原样保存。",
        "runs": [],
    }
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for index, arguments in enumerate(COMMANDS, 1):
        started_at = now()
        run = subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = logs / f"{index:02d}.log"
        log.write_bytes(run.stdout)
        output = run.stdout.decode("utf-8", errors="replace")
        count = re.search(r"Ran (\d+) tests? in", output)
        item = {"command": "python " + " ".join(arguments), "started_at": started_at,
                "finished_at": now(), "exit_code": run.returncode,
                "log": log.relative_to(ROOT).as_posix(),
                "log_sha256": hashlib.sha256(run.stdout).hexdigest()}
        if count:
            item["test_count"] = int(count.group(1))
        record["runs"].append(item)
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(item, ensure_ascii=False), flush=True)
    record["finished_at"] = now()
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    # 报告读取以上记录；它自身成功只代表报告生成成功。
    summary = subprocess.run([sys.executable, "审查/build_repair_summary.py"], cwd=ROOT, env=env)
    failures = [r for r in record["runs"] if r["exit_code"] != 0]
    return 1 if failures or summary.returncode else 0


if __name__ == "__main__":
    raise SystemExit(main())
