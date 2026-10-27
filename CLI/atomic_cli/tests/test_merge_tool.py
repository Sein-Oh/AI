import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_merged_code_md_is_in_sync_with_sources(tmp_path):
    out = tmp_path / "merged.md"
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "merge_code.py"), "merge", str(out)], check=True)
    with open(os.path.join(ROOT, "merged_code.md"), encoding="utf-8") as f:
        committed = f.read().splitlines()[3:]   # 생성일 줄 제외
    generated = out.read_text(encoding="utf-8").splitlines()[3:]
    assert committed == generated, "merged_code.md가 소스와 다릅니다. python tools/merge_code.py merge 를 실행하세요."
