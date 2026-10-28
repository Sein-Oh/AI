import subprocess, sys, os, json
PY = r"C:\WPy64-313130\python\python.exe"
env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
r = subprocess.run([PY] + sys.argv[1:], capture_output=True, env=env)
out = r.stdout.decode("utf-8", "replace").strip().splitlines()
err = r.stderr.decode("utf-8", "replace")[-800:]
print(out[-1] if out else json.dumps({"status": "error", "message": "출력 없음", "stderr": err}, ensure_ascii=False))
sys.exit(r.returncode)
