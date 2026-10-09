"""Reproducible CET build. Existing evidence/review/extensions survive reruns."""
import argparse, subprocess, sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--extract',action='store_true',help='reparse vocabulary/papers/writing/templates before repair')
    ap.add_argument('--src',type=Path)
    ap.add_argument('--kb',type=Path,default=Path(__file__).resolve().parents[1])
    args=ap.parse_args();kb=args.kb.resolve();root=kb.parents[1];scripts=kb/'scripts'
    src=args.src.resolve() if args.src else root/'英语四六级资料合集（2026年最新）(1)'
    def run(name,*params):
        subprocess.run([sys.executable,str(scripts/name),*map(str,params)],check=True,cwd=root)
    if args.extract:
        run('build_ontology_v2.py')
        run('build_vocab.py','--src',src,'--out',kb/'vocabulary')
        run('build_questions.py','--src',src,'--stage',scripts/'_staging','--kb',kb)
        run('build_questions_pdf.py','--src',src,'--kb',kb)
        run('build_writing_translation.py','--src',src,'--kb',kb)
        run('build_templates.py','--src',src,'--kb',kb)
    run('migrate_v2_schema.py')
    run('restore_original_stems.py')
    run('recover_reading_resources.py')
    run('recover_listening.py','--src',src,'--kb',kb)
    run('fill_answers.py','--src',src,'--stage',scripts/'_staging/answers','--kb',kb)
    run('repair_kb.py')
    # Second pass: fill_answers/repair rewrite extra.answer_status, so rebind appendix A.1 contract fields last.
    run('migrate_v2_schema.py')
    run('build_graph.py')
    run('build_stats.py','--kb',kb)

if __name__=='__main__': main()
