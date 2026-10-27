"""atomic_cli 루트의 *.py 소스를 반출용 단일 마크다운(merged_code.md)으로 병합하거나, 역으로 분리합니다.

사용법:
    python tools/merge_code.py merge            # *.py -> merged_code.md
    python tools/merge_code.py split [md_path]  # merged_code.md -> *.py
"""
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MD = os.path.join(ROOT, "merged_code.md")
FILE_BLOCK_RE = re.compile(
    r"^=== FILE: (.+?) ===\s*\n+```python\n(.*?)```\s*\n+=== END FILE: \1 ===", re.S | re.M
)


def merge(md_path: str = DEFAULT_MD) -> int:
    files = sorted(f for f in os.listdir(ROOT) if f.endswith(".py"))
    parts = [
        "# atomic_cli 소스 코드 (루트 폴더만, 하위 폴더 제외)\n\n",
        f"생성일: {date.today().isoformat()}\n",
        f"총 파일 수: {len(files)}\n\n---\n\n",
    ]
    for name in files:
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
            code = f.read()
        if not code.endswith("\n"):
            code += "\n"
        parts.append(f"=== FILE: {name} ===\n\n```python\n{code}```\n\n=== END FILE: {name} ===\n\n---\n\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(parts))
    return len(files)


def split(md_path: str = DEFAULT_MD) -> int:
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()
    count = 0
    for m in FILE_BLOCK_RE.finditer(text):
        name = os.path.basename(m.group(1).strip())
        with open(os.path.join(ROOT, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(m.group(2))
        count += 1
    return count


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "merge"
    path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MD
    if cmd == "split":
        print(f"[INFO] {split(path)}개 파일 분리 완료")
    else:
        print(f"[INFO] {merge(path)}개 파일 병합 완료: {path}")
