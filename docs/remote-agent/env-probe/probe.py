"""원격 에이전트 스킬 실행 환경 진단 (표준 라이브러리만 사용, 파일을 바꾸거나 네트워크에 접속하지 않음)

사용: python probe.py [확인할 파일 경로 ...]
출력: stdout에 JSON 1줄
"""
import importlib
import json
import os
import platform
import sys
import tempfile

PACKAGES = {
    "pandas": "pandas", "numpy": "numpy", "scikit-learn": "sklearn", "scipy": "scipy", "joblib": "joblib",
    "openpyxl": "openpyxl", "python-docx": "docx", "python-pptx": "pptx", "pymupdf": "pymupdf",
    "olefile": "olefile", "matplotlib": "matplotlib", "pywin32": "win32com.client",
}


def package_versions():
    out = {}
    for dist, mod in PACKAGES.items():
        try:
            m = importlib.import_module(mod)
            out[dist] = str(getattr(m, "__version__", "") or getattr(m, "VersionBind", "") or "설치됨")
        except Exception as e:
            out[dist] = f"없음 ({type(e).__name__})"
    return out


def file_checks(paths):
    out = []
    for p in paths:
        item = {"path": p, "exists": os.path.exists(p)}
        if item["exists"] and os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    head = f.read(16)
                item.update(size=os.path.getsize(p), readable=True, head_hex=head.hex(" "))
            except Exception as e:
                item.update(readable=False, error=f"{type(e).__name__}: {e}")
        elif item["exists"]:
            try:
                item["dir_entries"] = sorted(os.listdir(p))[:20]
            except Exception as e:
                item["error"] = f"{type(e).__name__}: {e}"
        out.append(item)
    return out


def main():
    cwd = os.getcwd()
    try:
        with tempfile.NamedTemporaryFile(dir=cwd, delete=True):
            cwd_writable = True
    except Exception:
        cwd_writable = False
    result = {
        "status": "ok",
        "os": platform.platform(),
        "is_windows": os.name == "nt",
        "python": sys.version.split()[0],
        "python_exe": sys.executable,
        "cwd": cwd,
        "cwd_writable": cwd_writable,
        "script_dir": os.path.dirname(os.path.abspath(__file__)),
        "script_dir_files": sorted(os.listdir(os.path.dirname(os.path.abspath(__file__))))[:30],
        "home": os.path.expanduser("~"),
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "temp_dir": tempfile.gettempdir(),
        "c_cli_exists": os.path.isdir(r"C:\CLI"),
        "packages": package_versions(),
        "files": file_checks(sys.argv[1:]),
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
