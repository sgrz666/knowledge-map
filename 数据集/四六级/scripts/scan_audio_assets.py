"""扫描听力音频资产（120个MP3），建立套卷映射表，并为听力题目和听力稿对齐音频切片。"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / "数据集" / "四六级"
AUDIO_DIR = ROOT / "英语四六级资料合集（2026年最新）(1)"
sys.path.insert(0, str(KB / "scripts"))
from cet_common import jsonl_dumps, load_jsonl


def scan_audio_files():
    found = {}
    for p in AUDIO_DIR.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".mp3":
            rel = p.relative_to(ROOT).as_posix()
            found[rel] = p
            
    catalog = []
    for rel, p in sorted(found.items()):
        fname = p.name
        size = p.stat().st_size
        exam = "CET-4" if any(k in rel for k in ["四级", "CET4", "cet4"]) else ("CET-6" if any(k in rel for k in ["六级", "CET6", "cet6"]) else None)
        
        m_yr = re.search(r"(20\d\d)\s*年?\s*(0[1-9]|1[0-2]|[1-9])\s*月?", fname)
        if not m_yr:
            m_yr = re.search(r"(20\d\d)(0[1-9]|1[0-2])", fname)
        if not m_yr:
            m_yr = re.search(r"(20\d\d)\.(0[1-9]|1[0-2])", fname)
        if not m_yr:
            m_yr = re.search(r"(20\d\d)\s*年?\s*(0[1-9]|1[0-2]|[1-9])\s*月?", str(p.parent))
        
        year = f"{m_yr.group(1)}-{int(m_yr.group(2)):02d}" if m_yr else None
        
        m_p = re.search(r"[第\(（【]([1-3一二三])[套卷\)】）]", fname)
        if not m_p:
            m_p = re.search(r"p([1-3])", fname, re.I)
        
        is_shared = False
        if "全1套" in fname or "3套相同" in fname or "全1套" in rel:
            is_shared = True
            paper = "all"
        elif m_p:
            v = m_p.group(1)
            paper = {"一": 1, "二": 2, "三": 3, "1": 1, "2": 2, "3": 3}.get(v, 1)
        else:
            paper = 1
            
        catalog.append({
            "audio_id": f"audio.{fname}",
            "relative_path": rel,
            "filename": fname,
            "size_bytes": size,
            "exam": exam,
            "year": year,
            "paper": paper,
            "is_shared": is_shared
        })
    return catalog


def build_audio_mapping(catalog):
    mapping = {}
    for item in catalog:
        exam = item["exam"]
        year = item["year"]
        paper = item["paper"]
        if not exam or not year:
            continue
        if paper == "all":
            for pi in [1, 2, 3]:
                key = (exam, year, pi)
                if key not in mapping or "真题及答案" in item["relative_path"]:
                    mapping[key] = item
        else:
            key = (exam, year, int(paper))
            if key not in mapping or "真题及答案" in item["relative_path"]:
                mapping[key] = item
    return mapping


def calculate_slices(exam, number):
    """计算四六级听力题目的标准化切片起始与结束时间（秒）。"""
    if exam == "CET-4":
        if 1 <= number <= 2:
            base_s, base_e = 0.0, 140.0
            idx, total = number - 1, 2
        elif 3 <= number <= 4:
            base_s, base_e = 140.0, 280.0
            idx, total = number - 3, 2
        elif 5 <= number <= 7:
            base_s, base_e = 280.0, 420.0
            idx, total = number - 5, 3
        elif 8 <= number <= 11:
            base_s, base_e = 420.0, 660.0
            idx, total = number - 8, 4
        elif 12 <= number <= 15:
            base_s, base_e = 660.0, 900.0
            idx, total = number - 12, 4
        elif 16 <= number <= 18:
            base_s, base_e = 900.0, 1100.0
            idx, total = number - 16, 3
        elif 19 <= number <= 21:
            base_s, base_e = 1100.0, 1300.0
            idx, total = number - 19, 3
        elif 22 <= number <= 25:
            base_s, base_e = 1300.0, 1500.0
            idx, total = number - 22, 4
        else:
            base_s, base_e = 1500.0, 1560.0
            idx, total = 0, 1
    else:  # CET-6
        if 1 <= number <= 4:
            base_s, base_e = 0.0, 240.0
            idx, total = number - 1, 4
        elif 5 <= number <= 8:
            base_s, base_e = 240.0, 480.0
            idx, total = number - 5, 4
        elif 9 <= number <= 11:
            base_s, base_e = 480.0, 720.0
            idx, total = number - 9, 3
        elif 12 <= number <= 15:
            base_s, base_e = 720.0, 960.0
            idx, total = number - 12, 4
        elif 16 <= number <= 18:
            base_s, base_e = 900.0, 1170.0
            idx, total = number - 16, 3
        elif 19 <= number <= 21:
            base_s, base_e = 1170.0, 1380.0
            idx, total = number - 19, 3
        elif 22 <= number <= 25:
            base_s, base_e = 1380.0, 1600.0
            idx, total = number - 22, 4
        else:
            base_s, base_e = 1600.0, 1660.0
            idx, total = 0, 1
            
    step = (base_e - base_s) / total
    q_start = round(base_s + idx * step, 1)
    q_end = round(base_s + (idx + 1) * step, 1)
    return q_start, q_end, base_s, base_e


def apply_audio_bindings():
    catalog = scan_audio_files()
    mapping = build_audio_mapping(catalog)
    
    # 1. 保存套卷与音频元数据清单
    out_catalog = KB / "manifest" / "audio_catalog.json"
    out_catalog.parent.mkdir(parents=True, exist_ok=True)
    out_catalog.write_text(json.dumps({
        "total_audio_files": len(catalog),
        "mapped_paper_slots": len(mapping),
        "files": catalog
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 2. 更新听力题目
    q_updated = 0
    q_bound = 0
    for level in ["cet4", "cet6"]:
        q_dir = KB / "questions" / level
        for q_file in sorted(q_dir.glob("*_p*.jsonl")):
            records = load_jsonl(q_file)
            file_modified = False
            for row in records:
                if row.get("module") == "听力理解":
                    q_updated += 1
                    exam = row.get("exam")
                    extra = row.setdefault("extra", {})
                    
                    m_id = re.match(r"(cet[46])-(\d{4}-\d{2})-p(\d)-listening-(\d+)", row.get("question_id", ""))
                    if m_id:
                        year = m_id.group(2)
                        paper = int(m_id.group(3))
                        num = int(m_id.group(4))
                    else:
                        parts = q_file.stem.split("_p")
                        year = parts[0]
                        paper = int(parts[1]) if len(parts) > 1 else 1
                        num = extra.get("number", 1)
                        
                    extra["year"] = year
                    extra["paper"] = paper
                    
                    q_start, q_end, _, _ = calculate_slices(exam, num)
                    audio_entry = extra.setdefault("audio", {})
                    audio_entry["start_seconds"] = q_start
                    audio_entry["end_seconds"] = q_end
                    
                    audio_match = mapping.get((exam, year, paper))
                    if audio_match:
                        q_bound += 1
                        audio_path = audio_match["relative_path"]
                        audio_entry["file_path"] = audio_path
                        audio_entry["files"] = [{"path": audio_path, "role": "listening_audio"}]
                        audio_entry["status"] = "audio_bound"
                        file_modified = True
                    else:
                        audio_entry["status"] = "audio_spec_defined"
                        file_modified = True
                
            if file_modified:
                q_file.write_text("\n".join(jsonl_dumps(r) for r in records) + "\n", encoding="utf-8")
                
    # 3. 更新听力稿实体
    t_file = KB / "listening" / "transcripts.jsonl"
    t_updated = 0
    t_bound = 0
    if t_file.exists():
        records = load_jsonl(t_file)
        new_trans = []
        for rec in records:
            t_updated += 1
            exam = rec.get("exam")
            extra = rec.setdefault("extra", {})
            year = extra.get("year")
            paper = extra.get("paper")
            q_nums = extra.get("question_numbers", [])
            
            first_num = q_nums[0] if q_nums else 1
            last_num = q_nums[-1] if q_nums else first_num
            s_start, _, g_s, _ = calculate_slices(exam, first_num)
            _, s_end, _, g_e = calculate_slices(exam, last_num)
            
            group_start = min(s_start, g_s)
            group_end = max(s_end, g_e)
            
            audio_match = mapping.get((exam, year, paper))
            audio_info = {
                "start_seconds": group_start,
                "end_seconds": group_end,
                "status": "audio_bound" if audio_match else "audio_spec_defined"
            }
            if audio_match:
                t_bound += 1
                audio_info["file_path"] = audio_match["relative_path"]
                audio_info["filename"] = audio_match["filename"]
                
            extra["audio"] = audio_info
            rec["audio_ref"] = audio_info
            if audio_match:
                extra["audio_path"] = audio_match["relative_path"]
                
            new_trans.append(rec)
            
        t_file.write_text("\n".join(jsonl_dumps(r) for r in new_trans) + "\n", encoding="utf-8")
        
    print(f"音频扫描完成：发现 {len(catalog)} 个MP3文件，匹配 {len(mapping)} 套试卷槽位。")
    print(f"听力题目更新：共 {q_updated} 题全部具备标准化切片，其中 {q_bound} 题完成真实音频挂载。")
    print(f"听力稿更新：共 {t_updated} 篇听力稿，其中 {t_bound} 篇完成真实音频挂载。")


if __name__ == "__main__":
    apply_audio_bindings()
