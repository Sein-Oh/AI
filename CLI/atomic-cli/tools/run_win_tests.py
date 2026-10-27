"""atomic-cli Phase 1 Windows 실기 테스트 러너 (TEST_CHECKLIST.md 자동 진행)

사용법 (atomic-cli 폴더에서 실행):
    python tools/run_win_tests.py                     # 전체 진행 (눈으로 확인할 항목은 y/n 질문)
    python tools/run_win_tests.py --only A,C          # 특정 그룹만
    python tools/run_win_tests.py --self-email me@company.com   # G3 실제 발송 테스트 포함
    python tools/run_win_tests.py --auto              # 질문 없이 자동 판정 항목만
    python tools/run_win_tests.py --dir D:\\atomic_test --skip-outlook

진행 방식:
    1) 테스트 폴더(기본 C:\\atomic_test)에 A/B 테스트 파일(xlsx, docx, pptx)을 새로 만듭니다.
    2) A.xlsx, A.docx, A.pptx를 더블클릭한 것처럼 화면에 엽니다.
    3) 체크리스트 순서대로 도구를 실행하고, COM으로 결과(셀 값, 파일 수정 시각, 슬라이드 수 등)를 자동 검증합니다.
    4) 화면 깜빡임처럼 눈으로만 확인 가능한 항목은 y/n으로 묻습니다.
    5) 결과를 테스트 폴더의 report_*.txt로 저장합니다. 이 파일 내용을 공유해 주세요.

주의:
    - 실행 전에 다른 Excel/Word/PowerPoint 문서는 저장 후 모두 닫아 주세요 (활성 문서 판정이 섞이지 않도록).
    - 테스트가 진행되는 동안 마우스/키보드로 Office 창을 조작하지 마세요 (질문에 답할 때 제외).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CMD_TIMEOUT = 120

try:
    import pythoncom
    import win32com.client
except ImportError:
    print("[ERROR] pywin32가 필요합니다. (pip install pywin32)")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, args):
        self.args = args
        self.dir = os.path.abspath(args.dir)
        self.results = []
        self.auto = args.auto

    def path(self, name):
        return os.path.join(self.dir, name)


def log(msg):
    print(msg, flush=True)


def run_cli(module, *cli_args):
    """도구를 별도 프로세스로 실행하고 (JSON dict 또는 None, 종료 코드, stdout, stderr 마지막 부분)을 반환합니다."""
    cmd = [PY, os.path.join(ROOT, module)] + [str(a) for a in cli_args]
    log(f"    $ python {module} {' '.join(str(a) for a in cli_args)}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=CMD_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", "", f"{CMD_TIMEOUT}초 안에 끝나지 않음 (대화상자가 떠서 멈췄을 가능성)"
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    data = None
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except Exception:
                pass
            break
    return data, proc.returncode, out, err[-1500:]


def ask(ctx, question):
    """눈으로 확인할 항목. y=정상(PASS), n=문제(FAIL), s=건너뜀."""
    if ctx.auto:
        return None
    while True:
        ans = input(f"    [확인] {question} (y=예 / n=아니오 / s=건너뜀): ").strip().lower()
        if ans in ("y", "n", "s"):
            return {"y": True, "n": False, "s": None}[ans]


def com_retry(fn, tries=10, delay=0.5):
    """Office가 바쁠 때(RPC_E_CALL_REJECTED 등) 잠시 기다렸다가 재시도합니다."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(delay)
    raise last


def wait_for(fn, timeout=40, delay=1.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(delay)
    return None


def process_count(image):
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                             capture_output=True).stdout.decode("cp949", errors="replace")
        return sum(1 for line in out.splitlines() if line.lower().startswith(f'"{image.lower()}"'))
    except Exception:
        return -1


def describe_com_error(e):
    """pywintypes.com_error를 사람이 읽을 수 있게 풀어 씁니다 (HRESULT, Office가 준 설명 문구)."""
    args = getattr(e, "args", ())
    if len(args) >= 3 and isinstance(args[0], int):
        hr, msg, exc = args[0], args[1], args[2]
        text = f"HRESULT={hr} (0x{hr & 0xFFFFFFFF:08X}) {msg}"
        if exc and len(exc) >= 6:
            src, desc, scode = exc[1], exc[2], exc[5]
            text += f" | 원본={src} | 설명={desc}"
            if isinstance(scode, int):
                text += f" | scode=0x{scode & 0xFFFFFFFF:08X}"
        return text
    return f"{type(e).__name__}: {e}"


def step(label, fn):
    """준비 단계 하나를 실행하고, 실패하면 어느 단계에서 왜 실패했는지 출력한 뒤 종료합니다."""
    try:
        return fn()
    except Exception as e:
        log(f"[ERROR] 준비 단계 실패: {label}")
        log(f"        {describe_com_error(e)}")
        log("        위 두 줄을 그대로 알려 주세요.")
        log(traceback.format_exc())
        raise SystemExit(1)


def mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


def short(data, raw_out=""):
    if data is None:
        return (raw_out or "").strip()[-300:] or "(JSON 출력 없음)"
    s = json.dumps(data, ensure_ascii=False)
    return s if len(s) <= 400 else s[:400] + "..."


# ---------------------------------------------------------------------------
# 테스트 실행/기록
# ---------------------------------------------------------------------------
def record(ctx, tid, title, ok, detail="", data=None, code=None, raw="", err=""):
    if ok is None:
        status = "MANUAL-SKIP"
    else:
        status = "PASS" if ok else "FAIL"
    entry = {"id": tid, "title": title, "status": status, "detail": detail,
             "exit_code": code, "json": short(data, raw)}
    if status == "FAIL" and err:
        entry["stderr_tail"] = err.strip()[-600:]
    ctx.results.append(entry)
    log(f"  => [{status}] {tid} {title} {('- ' + detail) if detail else ''}")


def run_test(ctx, tid, title, fn):
    log(f"\n[{tid}] {title}")
    try:
        fn()
    except Exception as e:
        ctx.results.append({"id": tid, "title": title, "status": "ERROR",
                            "detail": f"테스트 스크립트 예외: {describe_com_error(e)}", "trace": traceback.format_exc()[-800:]})
        log(f"  => [ERROR] {tid} {e}")


# ---------------------------------------------------------------------------
# Office 객체 조회 (테스트 검증용, atomic-cli 코드와 독립)
# ---------------------------------------------------------------------------
def xl_app():
    return win32com.client.GetActiveObject("Excel.Application")


def xl_wb(name):
    return com_retry(lambda: xl_app().Workbooks(name))


def wd_doc(name):
    return com_retry(lambda: win32com.client.GetActiveObject("Word.Application").Documents(name))


def pp_prs(name):
    return com_retry(lambda: win32com.client.GetActiveObject("PowerPoint.Application").Presentations(name))


def activate_xl(name, sheet=None):
    def _do():
        wb = xl_wb(name)
        wb.Activate()
        if sheet:
            wb.Worksheets(sheet).Activate()
        return wb
    return com_retry(_do)


# ---------------------------------------------------------------------------
# 준비: 테스트 파일 생성 및 열기
# ---------------------------------------------------------------------------
FILES = ["A.xlsx", "B.xlsx", "A.docx", "B.docx", "A.pptx", "B.pptx"]


def _set_sheet_name(wb, idx, name):
    """이미 같은 이름이면 건너뛰고, 다른 시트가 그 이름을 쓰고 있으면 먼저 비켜 줍니다."""
    ws = wb.Worksheets(idx)
    if ws.Name == name:
        return
    for other in wb.Worksheets:
        if other.Name == name:
            other.Name = f"{name}_old"
    ws.Name = name


def _save_workbook(wb, path):
    try:
        wb.SaveAs(path, FileFormat=51)  # xlOpenXMLWorkbook
    except Exception as e:
        log(f"        SaveAs(FileFormat=51) 실패 -> 형식 지정 없이 재시도: {describe_com_error(e)}")
        wb.SaveAs(path)


def setup_files(ctx):
    step(f"테스트 폴더 생성/쓰기 확인 ({ctx.dir})", lambda: _check_writable(ctx.dir))
    for f in FILES:
        p = ctx.path(f)
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                log(f"[ERROR] {p} 파일이 열려 있어 다시 만들 수 없습니다. 닫고 다시 실행하세요.")
                sys.exit(1)

    log("[준비] Excel 테스트 파일 생성")
    xl = step("Excel 백그라운드 실행 (DispatchEx)", lambda: win32com.client.DispatchEx("Excel.Application"))
    try:
        step("Excel 표시/경고 설정", lambda: (setattr(xl, "Visible", False), setattr(xl, "DisplayAlerts", False)))
        for name, a1 in (("A.xlsx", "원래값"), ("B.xlsx", "B파일")):
            wb = step(f"{name}: 새 통합문서 만들기", lambda: xl.Workbooks.Add())

            def _sheets():
                while wb.Worksheets.Count < 2:
                    wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                _set_sheet_name(wb, 1, "Sheet1")
                _set_sheet_name(wb, 2, "Sheet2")
            step(f"{name}: 시트 2개 구성", _sheets)

            def _values():
                wb.Worksheets(1).Range("A1").Value = a1
                wb.Worksheets(2).Range("A1").Value = "시트2 데이터"
            step(f"{name}: 셀 값 입력", _values)
            step(f"{name}: 저장 ({ctx.path(name)})", lambda: _save_workbook(wb, ctx.path(name)))
            step(f"{name}: 닫기", lambda: wb.Close(SaveChanges=False))
    finally:
        try:
            xl.Quit()
        except Exception:
            pass

    log("[준비] Word 테스트 파일 생성")
    wd = step("Word 백그라운드 실행 (DispatchEx)", lambda: win32com.client.DispatchEx("Word.Application"))
    try:
        step("Word 표시/경고 설정", lambda: (setattr(wd, "Visible", False), setattr(wd, "DisplayAlerts", 0)))
        for name in ("A.docx", "B.docx"):
            doc = step(f"{name}: 새 문서 만들기", lambda: wd.Documents.Add())
            step(f"{name}: 본문 입력",
                 lambda: setattr(doc.Content, "Text", f"{name} 첫 문단입니다.\r두 번째 문단입니다."))
            step(f"{name}: 저장 ({ctx.path(name)})", lambda: doc.SaveAs2(ctx.path(name), FileFormat=16))
            step(f"{name}: 닫기", lambda: doc.Close(SaveChanges=0))
    finally:
        try:
            wd.Quit(SaveChanges=0)
        except Exception:
            pass

    log("[준비] PowerPoint 테스트 파일 생성")
    running = True
    try:
        win32com.client.GetActiveObject("PowerPoint.Application")
    except Exception:
        running = False
    pp = step("PowerPoint 실행/연결", lambda: win32com.client.Dispatch("PowerPoint.Application"))
    for name in ("A.pptx", "B.pptx"):
        prs = step(f"{name}: 새 프레젠테이션 만들기 (창 없이)", lambda: pp.Presentations.Add(0))

        def _slides():
            for i in range(1, 4):
                s = prs.Slides.Add(i, 12)  # ppLayoutBlank
                s.Shapes.AddTextbox(1, 50, 50, 400, 50).TextFrame.TextRange.Text = f"{name} 슬라이드 {i}"
                s.Shapes.AddTextbox(1, 50, 150, 400, 50).TextFrame.TextRange.Text = f"본문 {i}"
        step(f"{name}: 슬라이드 3장 구성", _slides)
        step(f"{name}: 저장 ({ctx.path(name)})", lambda: prs.SaveAs(ctx.path(name), 24))
        step(f"{name}: 닫기", lambda: prs.Close())
    if not running:
        try:
            if pp.Presentations.Count == 0:
                pp.Quit()
        except Exception:
            pass


def _check_writable(folder):
    os.makedirs(folder, exist_ok=True)
    probe = os.path.join(folder, "_write_test.tmp")
    with open(probe, "w", encoding="utf-8") as f:
        f.write("ok")
    os.remove(probe)


def open_user_windows(ctx):
    log("[준비] A.xlsx / A.docx / A.pptx를 화면에 엽니다 (더블클릭과 동일)")
    os.startfile(ctx.path("A.xlsx"))
    if not wait_for(lambda: xl_wb("A.xlsx")):
        log("[ERROR] A.xlsx가 열리지 않았습니다.")
        sys.exit(1)
    os.startfile(ctx.path("A.docx"))
    if not wait_for(lambda: wd_doc("A.docx")):
        log("[ERROR] A.docx가 열리지 않았습니다.")
        sys.exit(1)
    os.startfile(ctx.path("A.pptx"))
    if not wait_for(lambda: pp_prs("A.pptx")):
        log("[ERROR] A.pptx가 열리지 않았습니다.")
        sys.exit(1)
    time.sleep(2)


# ---------------------------------------------------------------------------
# A. 사용자 창 간섭
# ---------------------------------------------------------------------------
def test_A(ctx):
    def a1():
        activate_xl("A.xlsx")
        before = process_count("EXCEL.EXE")
        b_mtime = mtime(ctx.path("B.xlsx"))
        data, code, raw, err = run_cli("excel_read.py", "--target", ctx.path("B.xlsx"))
        time.sleep(2)
        after = process_count("EXCEL.EXE")
        still_open = bool(wait_for(lambda: xl_wb("A.xlsx"), timeout=5))
        visible = com_retry(lambda: bool(xl_app().Visible))
        ok = (data or {}).get("status") == "ok" and still_open and visible and after <= before \
            and mtime(ctx.path("B.xlsx")) == b_mtime
        detail = f"EXCEL.EXE {before}->{after}, A.xlsx 열림={still_open}, Visible={visible}"
        manual = ask(ctx, "실행 중 A.xlsx 창이 닫히거나 깜빡이지 않고 그대로 있었나요?")
        record(ctx, "A1", "다른 엑셀 파일 읽기 시 사용자 창 유지", ok and manual is not False, detail, data, code, raw, err)

    def a2():
        before = process_count("WINWORD.EXE")
        data, code, raw, err = run_cli("word_read.py", "--target", ctx.path("B.docx"))
        time.sleep(2)
        after = process_count("WINWORD.EXE")
        still_open = bool(wait_for(lambda: wd_doc("A.docx"), timeout=5))
        ok = (data or {}).get("status") == "ok" and still_open and after <= before
        manual = ask(ctx, "실행 중 A.docx 창이 그대로 있었나요?")
        record(ctx, "A2", "다른 워드 파일 읽기 시 사용자 창 유지", ok and manual is not False,
               f"WINWORD.EXE {before}->{after}, A.docx 열림={still_open}", data, code, raw, err)

    def a3():
        b_mtime = mtime(ctx.path("B.pptx"))
        data, code, raw, err = run_cli("ppt_inspect.py", "--target", ctx.path("B.pptx"))
        time.sleep(1)
        state = com_retry(lambda: win32com.client.GetActiveObject("PowerPoint.Application").WindowState)
        unchanged = mtime(ctx.path("B.pptx")) == b_mtime
        ok = (data or {}).get("status") == "ok" and unchanged and state != 2
        manual = ask(ctx, "PowerPoint 창이 최소화되거나 깜빡이지 않았나요?")
        record(ctx, "A3", "다른 PPT 파일 진단 시 사용자 창 유지 / 파일 미변경", ok and manual is not False,
               f"B.pptx 수정시각 불변={unchanged}, WindowState={state}", data, code, raw, err)

    def a4():
        c_path = ctx.path("C_second_instance.xlsx")
        if os.path.exists(c_path):
            os.remove(c_path)
        import shutil
        shutil.copy2(ctx.path("B.xlsx"), c_path)
        before = process_count("EXCEL.EXE")
        subprocess.Popen(["cmd", "/c", "start", "", "excel.exe", "/x", c_path])
        if not wait_for(lambda: process_count("EXCEL.EXE") > before, timeout=30):
            record(ctx, "A4", "다중 Excel 프로세스 목록", None, "두 번째 Excel 프로세스를 띄우지 못해 건너뜀")
            return
        time.sleep(5)
        data, code, raw, err = run_cli("excel_inspect.py", "--list-workbooks")
        text = json.dumps(data, ensure_ascii=False) if data else raw
        ok = "A.xlsx" in text and "C_second_instance.xlsx" in text
        record(ctx, "A4", "다중 Excel 프로세스 목록", ok, f"EXCEL.EXE 프로세스 {process_count('EXCEL.EXE')}개", data, code, raw, err)
        # 두 번째 인스턴스 정리
        try:
            sys.path.insert(0, ROOT)
            from _com_guard import find_all_native_excel_apps
            for app in find_all_native_excel_apps():
                try:
                    names = [wb.Name for wb in app.Workbooks]
                    if "C_second_instance.xlsx" in names and "A.xlsx" not in names:
                        app.Workbooks("C_second_instance.xlsx").Close(SaveChanges=False)
                        if app.Workbooks.Count == 0:
                            app.Quit()
                except Exception:
                    pass
        except Exception:
            pass
        # 남아 있으면 이후 '활성 문서' 판정이 섞이므로 반드시 닫힌 상태에서 다음 단계로 진행
        ask(ctx, "두 번째 Excel 창(C_second_instance.xlsx)이 닫혔나요? 남아 있으면 저장하지 않고 직접 닫은 뒤 y를 누르세요")

    run_test(ctx, "A1", "다른 엑셀 파일 읽기 시 사용자 창 유지", a1)
    run_test(ctx, "A2", "다른 워드 파일 읽기 시 사용자 창 유지", a2)
    run_test(ctx, "A3", "다른 PPT 파일 진단 시 사용자 창 유지", a3)
    run_test(ctx, "A4", "다중 Excel 프로세스 목록", a4)


# ---------------------------------------------------------------------------
# B. 읽기 전용 동작
# ---------------------------------------------------------------------------
def test_B(ctx):
    def b1():
        b_mtime = mtime(ctx.path("B.xlsx"))
        data, code, raw, err = run_cli("excel_read.py", "--target", ctx.path("B.xlsx"), "--sheet", "없는시트")
        time.sleep(1)
        ok = (data or {}).get("status") == "error" and "Sheet1" in (data or {}).get("preview", "") \
            and mtime(ctx.path("B.xlsx")) == b_mtime and code == 1
        record(ctx, "B1", "없는 시트 읽기 -> error, 파일 미변경", ok,
               f"B.xlsx 수정시각 불변={mtime(ctx.path('B.xlsx')) == b_mtime}", data, code, raw, err)

    def b2():
        activate_xl("A.xlsx", "Sheet1")
        data, code, raw, err = run_cli("excel_read.py", "--target", "active", "--sheet", "Sheet2")
        active = com_retry(lambda: xl_wb("A.xlsx").ActiveSheet.Name)
        got = json.dumps(data, ensure_ascii=False) if data else ""
        ok = (data or {}).get("status") == "ok" and active == "Sheet1" and "시트2 데이터" in got
        record(ctx, "B2", "활성 문서 다른 시트 읽기 시 화면 시트 유지", ok, f"읽은 뒤 활성 시트={active}", data, code, raw, err)

    def b3():
        data, code, raw, err = run_cli("excel_read.py", "--target", "active", "--sheet", "sheet2")
        got = json.dumps(data, ensure_ascii=False) if data else ""
        ok = (data or {}).get("status") == "ok" and "시트2 데이터" in got
        record(ctx, "B3", "시트명 대소문자 무시", ok, "", data, code, raw, err)

    def b4():
        missing = ctx.path("없는파일.docx")
        if os.path.exists(missing):
            os.remove(missing)
        data, code, raw, err = run_cli("word_read.py", "--target", missing)
        ok = (data or {}).get("status") == "error" and not os.path.exists(missing)
        record(ctx, "B4", "없는 워드 파일 읽기 -> error, 파일 미생성", ok,
               f"파일 생성됨={os.path.exists(missing)}", data, code, raw, err)

    run_test(ctx, "B1", "없는 시트 읽기", b1)
    run_test(ctx, "B2", "활성 시트 유지", b2)
    run_test(ctx, "B3", "시트명 대소문자 무시", b3)
    run_test(ctx, "B4", "없는 파일 읽기", b4)


# ---------------------------------------------------------------------------
# C. 되돌리기
# ---------------------------------------------------------------------------
def a1_value(book="A.xlsx", sheet="Sheet1"):
    return com_retry(lambda: xl_wb(book).Worksheets(sheet).Range("A1").Value)


def test_C(ctx):
    def c1():
        activate_xl("A.xlsx", "Sheet1")
        data, code, raw, err = run_cli("excel_fill.py", "--target", "active", "--range", "A1", "--value", "안녕")
        filled = a1_value()
        if filled != "안녕":
            record(ctx, "C1", "Excel 쓰기 후 undo", False, f"fill 후 A1={filled!r} (기대: '안녕')", data, code, raw, err)
            return
        data, code, raw, err = run_cli("clean.py", "--action", "undo", "--app", "excel")
        wait_for(lambda: xl_wb("A.xlsx"), timeout=20)
        restored = a1_value()
        ok = (data or {}).get("status") == "ok" and restored == "원래값" \
            and (data or {}).get("restored_as") == "reopened_in_office"
        record(ctx, "C1", "Excel 쓰기 후 undo", ok,
               f"undo 후 A1={restored!r}, restored_as={(data or {}).get('restored_as')}, 백업={(data or {}).get('pre_undo_backup')}",
               data, code, raw, err)

    def c2():
        activate_xl("A.xlsx", "Sheet1")
        run_cli("excel_fill.py", "--target", "active", "--range", "A1", "--value", "값1")
        activate_xl("A.xlsx", "Sheet1")
        run_cli("excel_fill.py", "--target", "active", "--range", "A1", "--value", "값2")
        d1, c1_, r1, e1 = run_cli("clean.py", "--action", "undo", "--app", "excel")
        wait_for(lambda: xl_wb("A.xlsx"), timeout=20)
        v1 = a1_value()
        d2, c2_, r2, e2 = run_cli("clean.py", "--action", "undo", "--app", "excel")
        wait_for(lambda: xl_wb("A.xlsx"), timeout=20)
        v2 = a1_value()
        ok = v1 == "값1" and v2 == "원래값"
        record(ctx, "C2", "연속 undo 두 번", ok, f"1차 undo 후 A1={v1!r}, 2차 undo 후 A1={v2!r}", d2, c2_, r2, e2)

    def c3():
        app = xl_app()
        new_wb = com_retry(lambda: app.Workbooks.Add())
        new_name = new_wb.Name
        new_wb.Activate()
        before_count = app.Workbooks.Count
        data, code, raw, err = run_cli("excel_fill.py", "--target", "active", "--range", "A1", "--value", "새문서값")
        data, code, raw, err = run_cli("clean.py", "--action", "undo", "--app", "excel")
        time.sleep(2)
        after_count = com_retry(lambda: xl_app().Workbooks.Count)
        restored_val = "?"
        try:
            restored_val = com_retry(lambda: xl_app().ActiveWorkbook.Worksheets(1).Range("A1").Value)
        except Exception:
            pass
        ok = (data or {}).get("status") == "ok" and (data or {}).get("restored_as") == "new_untitled_document" \
            and after_count == before_count + 1 and restored_val in (None, "")
        record(ctx, "C3", "저장 안 한 새 통합문서 undo -> 제목 없는 새 통합문서", ok,
               f"통합문서 수 {before_count}->{after_count}, 복원 문서 A1={restored_val!r}", data, code, raw, err)
        # 테스트로 만든 통합문서 정리 (A.xlsx 제외, 저장 안 함)
        try:
            app = xl_app()
            for i in range(app.Workbooks.Count, 0, -1):
                wb = app.Workbooks(i)
                if wb.Name != "A.xlsx" and (wb.Name == new_name or not wb.Path):
                    wb.Close(SaveChanges=False)
        except Exception:
            pass

    def c4():
        doc = wd_doc("A.docx")
        com_retry(lambda: doc.Activate())
        com_retry(lambda: doc.Range(0, 0).InsertBefore("가"))
        m_before = mtime(ctx.path("A.docx"))
        data, code, raw, err = run_cli("word_write.py", "--target", "active", "--text", "테스트 문장")
        time.sleep(1)
        doc = wd_doc("A.docx")
        text = com_retry(lambda: doc.Content.Text)
        saved_flag = com_retry(lambda: bool(doc.Saved))
        ok = (data or {}).get("status") == "ok" and "테스트 문장" in text \
            and mtime(ctx.path("A.docx")) == m_before and not saved_flag
        record(ctx, "C4", "워드 쓰기 성공 + 원본 자동 저장 안 됨", ok,
               f"수정시각 불변={mtime(ctx.path('A.docx')) == m_before}, 미저장 상태 유지={not saved_flag}",
               data, code, raw, err)

    def c5():
        data, code, raw, err = run_cli("clean.py", "--action", "undo", "--app", "word")
        wait_for(lambda: wd_doc("A.docx"), timeout=20)
        text = com_retry(lambda: wd_doc("A.docx").Content.Text)
        ok = (data or {}).get("status") == "ok" and "테스트 문장" not in text and text.startswith("가")
        record(ctx, "C5", "워드 undo -> 도구가 쓴 문장만 제거", ok,
               f"'테스트 문장' 남음={'테스트 문장' in text}, 손으로 넣은 '가' 유지={text.startswith('가')}",
               data, code, raw, err)

    def c6():
        n0 = com_retry(lambda: pp_prs("A.pptx").Slides.Count)
        data, code, raw, err = run_cli("ppt_slide.py", "--target", "active", "--action", "add")
        n1 = com_retry(lambda: pp_prs("A.pptx").Slides.Count)
        data, code, raw, err = run_cli("clean.py", "--action", "undo", "--app", "ppt")
        wait_for(lambda: pp_prs("A.pptx"), timeout=20)
        n2 = com_retry(lambda: pp_prs("A.pptx").Slides.Count)
        ok = n1 == n0 + 1 and n2 == n0 and (data or {}).get("status") == "ok"
        record(ctx, "C6", "PPT 슬라이드 추가 후 undo", ok, f"슬라이드 수 {n0}->{n1}->{n2}", data, code, raw, err)

    def c7():
        last = None
        for _ in range(4):
            last = run_cli("clean.py", "--action", "undo", "--app", "ppt")
            if (last[0] or {}).get("status") == "no_match":
                break
            wait_for(lambda: pp_prs("A.pptx"), timeout=20)
        data, code, raw, err = last
        ok = (data or {}).get("status") == "no_match" and code == 0
        record(ctx, "C7", "스냅샷 소진 시 no_match", ok, "", data, code, raw, err)

    run_test(ctx, "C1", "Excel undo", c1)
    run_test(ctx, "C2", "연속 undo", c2)
    run_test(ctx, "C3", "새 통합문서 undo", c3)
    run_test(ctx, "C4", "워드 쓰기", c4)
    run_test(ctx, "C5", "워드 undo", c5)
    run_test(ctx, "C6", "PPT undo", c6)
    run_test(ctx, "C7", "스냅샷 소진", c7)


# ---------------------------------------------------------------------------
# D. 내보내기
# ---------------------------------------------------------------------------
def test_D(ctx):
    def d1():
        doc = wd_doc("A.docx")
        com_retry(lambda: doc.Activate())
        footer_before = com_retry(lambda: doc.Sections(1).Footers(1).PageNumbers.Count)
        saved_before = com_retry(lambda: bool(doc.Saved))
        data, code, raw, err = run_cli("word_export.py", "--target", "active", "-o", "atomic_test_pagenum.pdf", "--page-number")
        doc = wd_doc("A.docx")
        footer_after = com_retry(lambda: doc.Sections(1).Footers(1).PageNumbers.Count)
        saved_after = com_retry(lambda: bool(doc.Saved))
        pdf = (data or {}).get("file_path", "")
        ok = (data or {}).get("status") == "ok" and os.path.exists(pdf) \
            and footer_before == footer_after and saved_before == saved_after
        manual = None
        if ok and not ctx.auto:
            os.startfile(pdf)
            manual = ask(ctx, "방금 열린 PDF 하단 중앙에 페이지 번호가 보이나요? (확인 후 PDF 창은 닫아 주세요)")
        record(ctx, "D1", "PDF 페이지 번호, 원본 바닥글 미변경", ok and manual is not False,
               f"원본 페이지번호 수 {footer_before}->{footer_after}, 저장상태 {saved_before}->{saved_after}, {pdf}",
               data, code, raw, err)

    def d2():
        data, code, raw, err = run_cli("word_export.py", "--target", "active", "-o", "atomic_test_x.docx", "--format", "pdf")
        fp = (data or {}).get("file_path", "")
        ok = (data or {}).get("status") == "ok" and fp.lower().endswith(".pdf") and os.path.exists(fp)
        record(ctx, "D2", "형식/확장자 불일치 보정 (.docx -> .pdf)", ok, fp, data, code, raw, err)

    def d3():
        activate_xl("A.xlsx", "Sheet1")
        before = com_retry(lambda: xl_app().Workbooks.Count)
        data, code, raw, err = run_cli("excel_export.py", "--target", "active", "--output", "atomic_test_t.xlsx")
        after = com_retry(lambda: xl_app().Workbooks.Count)
        fp = (data or {}).get("file_path", "")
        ok = (data or {}).get("status") == "ok" and os.path.exists(fp) and before == after
        record(ctx, "D3", "XLSX 내보내기 후 임시 통합문서 미잔류", ok, f"통합문서 수 {before}->{after}, {fp}", data, code, raw, err)

    run_test(ctx, "D1", "워드 PDF 페이지 번호", d1)
    run_test(ctx, "D2", "형식/확장자 보정", d2)
    run_test(ctx, "D3", "XLSX 내보내기", d3)


# ---------------------------------------------------------------------------
# E. Excel 편집
# ---------------------------------------------------------------------------
def prepare_e_sheets():
    def _do():
        app = xl_app()
        wb = app.Workbooks("A.xlsx")
        prev = app.DisplayAlerts
        app.DisplayAlerts = False
        try:
            for name in ("E_TEST", "My Sheet"):
                for s in wb.Worksheets:
                    if s.Name == name:
                        s.Delete()
                        break
                ws = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                ws.Name = name
        finally:
            app.DisplayAlerts = prev
        ws = wb.Worksheets("E_TEST")
        ws.Range("A1:B3").Value = (("가", "나"), ("다", "라"), ("마", "바"))
        ws.Range("A10").Value = "병합1"
        ws.Range("B10").Value = "병합2"
        ws.Range("A20").Value = 1
        ws.Range("B20").Value = 2
        ws.Range("C20").Formula = "=A20+B20"
        wb.Activate()
        ws.Activate()
    com_retry(_do)


def test_E(ctx):
    prepare_e_sheets()

    def e_ws():
        return xl_wb("A.xlsx").Worksheets("E_TEST")

    def e1():
        activate_xl("A.xlsx", "E_TEST")
        data, code, raw, err = run_cli("excel_range.py", "--target", "active", "--action", "move", "--range", "A1:B3", "--dest", "B2")
        vals = com_retry(lambda: e_ws().Range("B2:C4").Value)
        a1 = com_retry(lambda: e_ws().Range("A1").Value)
        ok = (data or {}).get("status") == "ok" and vals == (("가", "나"), ("다", "라"), ("마", "바")) and a1 is None
        record(ctx, "E1", "범위 이동(move) 데이터 손실 없음", ok, f"B2:C4={vals}, A1={a1!r}", data, code, raw, err)

    def e2():
        activate_xl("A.xlsx", "E_TEST")
        data, code, raw, err = run_cli("excel_range.py", "--target", "active", "--action", "merge")
        merged = com_retry(lambda: bool(e_ws().Range("A1").MergeCells))
        ok = (data or {}).get("status") == "error" and not merged
        record(ctx, "E2", "범위 없는 병합 -> error", ok, "", data, code, raw, err)

    def e3():
        activate_xl("A.xlsx", "E_TEST")
        data, code, raw, err = run_cli("excel_range.py", "--target", "active", "--action", "merge", "--range", "A10:B10")
        merged = com_retry(lambda: bool(e_ws().Range("A10").MergeCells))
        ok = (data or {}).get("status") == "ok" and merged and code != "TIMEOUT"
        record(ctx, "E3", "값이 있는 셀 병합 시 대화상자 없이 완료", ok, f"병합됨={merged}", data, code, raw, err)

    def e4():
        activate_xl("A.xlsx", "E_TEST")
        data, code, raw, err = run_cli("excel_range.py", "--target", "active", "--action", "width",
                                       "--range", "'My Sheet'!A1", "--width", "30")
        width = com_retry(lambda: xl_wb("A.xlsx").Worksheets("My Sheet").Columns(1).ColumnWidth)
        ok = (data or {}).get("status") == "ok" and abs(float(width) - 30) < 0.01
        record(ctx, "E4", "따옴표 시트명 주소 해석", ok, f"My Sheet A열 너비={width}", data, code, raw, err)

    def e5():
        activate_xl("A.xlsx", "E_TEST")
        data, code, raw, err = run_cli("excel_edit.py", "--target", "active", "--find", "3", "--replace", "9", "--bg", "yellow")
        formula = com_retry(lambda: e_ws().Range("C20").Formula)
        color = com_retry(lambda: int(e_ws().Range("C20").Interior.Color))
        ok = (data or {}).get("status") == "ok" and formula == "=A20+B20" and color == 65535
        record(ctx, "E5", "수식 셀 치환 시 수식 보존 + 서식 적용", ok, f"C20 수식={formula}, 배경색={color}", data, code, raw, err)

    run_test(ctx, "E1", "move", e1)
    run_test(ctx, "E2", "merge 범위 없음", e2)
    run_test(ctx, "E3", "merge 대화상자", e3)
    run_test(ctx, "E4", "따옴표 시트명", e4)
    run_test(ctx, "E5", "수식 보존", e5)


# ---------------------------------------------------------------------------
# F. PowerPoint
# ---------------------------------------------------------------------------
def test_F(ctx):
    def counts():
        prs = pp_prs("A.pptx")
        return [prs.Slides(i).Shapes.Count for i in range(1, prs.Slides.Count + 1)]

    def f1():
        before = com_retry(counts)
        data, code, raw, err = run_cli("ppt_slide.py", "--target", "active", "--action", "clear")
        after = com_retry(counts)
        ok = (data or {}).get("status") == "error" and before == after
        record(ctx, "F1", "슬라이드 번호 없는 clear -> error, 삭제 없음", ok, f"도형 수 {before}->{after}", data, code, raw, err)

    def f2():
        before = com_retry(counts)
        data, code, raw, err = run_cli("ppt_slide.py", "--target", "active", "--action", "clear", "--slide", "2")
        after = com_retry(counts)
        expected = list(before)
        if len(expected) >= 2:
            expected[1] = 0
        ok = (data or {}).get("status") == "ok" and after == expected
        record(ctx, "F2", "2번 슬라이드만 clear", ok, f"도형 수 {before}->{after}", data, code, raw, err)

    run_test(ctx, "F1", "clear 보호", f1)
    run_test(ctx, "F2", "clear --slide 2", f2)


# ---------------------------------------------------------------------------
# G. Outlook
# ---------------------------------------------------------------------------
def test_G(ctx):
    me = ctx.args.self_email

    def g1():
        to = me or "atomic-test@example.com"
        data, code, raw, err = run_cli("outlook_write.py", "--action", "new", "--to", to,
                                       "--subject", "[atomic-cli 테스트] 표시 전용", "--body", "본문 테스트")
        ok = (data or {}).get("status") == "ok" and (data or {}).get("sent") is False
        manual = ask(ctx, "메일 작성 창이 떴나요? (확인 후 그 창은 저장하지 않고 닫아 주세요)")
        record(ctx, "G1", "기본 동작: 작성 창만 표시, 미발송", ok and manual is not False, "", data, code, raw, err)

    def g2():
        data, code, raw, err = run_cli("outlook_write.py", "--action", "new", "--to", "zz_atomic_invalid_recipient_000",
                                       "--subject", "[atomic-cli 테스트] 잘못된 수신자", "--body", "발송되면 안 됨", "--send")
        ok = (data or {}).get("status") == "partial" and (data or {}).get("sent") is False
        ask(ctx, "작성 창이 떴다면 저장하지 않고 닫아 주세요. 닫았나요?")
        record(ctx, "G2", "잘못된 수신자 + --send -> 발송 안 됨", ok,
               f"unresolved={(data or {}).get('unresolved_recipients')}", data, code, raw, err)

    def g3():
        if not me:
            record(ctx, "G3", "명시적 --send 실제 발송", None, "--self-email 미지정으로 건너뜀")
            return
        if not ctx.auto and ask(ctx, f"{me} 주소로 실제 테스트 메일을 1통 발송합니다. 진행할까요?") is not True:
            record(ctx, "G3", "명시적 --send 실제 발송", None, "사용자가 건너뜀")
            return
        data, code, raw, err = run_cli("outlook_write.py", "--action", "new", "--to", me,
                                       "--subject", "[atomic-cli 테스트] 발송 테스트", "--body", "자동 발송 테스트 메일입니다.", "--send")
        ok = (data or {}).get("status") == "ok" and (data or {}).get("sent") is True
        record(ctx, "G3", "명시적 --send 실제 발송", ok, "", data, code, raw, err)

    run_test(ctx, "G1", "표시 전용", g1)
    run_test(ctx, "G2", "잘못된 수신자", g2)
    run_test(ctx, "G3", "실제 발송", g3)


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------
def write_report(ctx):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = ctx.path(f"report_{stamp}.txt")
    counts = {}
    for r in ctx.results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [
        f"atomic-cli Phase 1 Windows 테스트 보고서 ({stamp})",
        f"Python {sys.version.split()[0]} / 테스트 폴더 {ctx.dir}",
        "요약: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        "",
    ]
    for r in ctx.results:
        lines.append(f"[{r['status']}] {r['id']} {r['title']}")
        if r.get("detail"):
            lines.append(f"    내용: {r['detail']}")
        if r.get("exit_code") is not None:
            lines.append(f"    종료코드: {r['exit_code']}")
        if r.get("json"):
            lines.append(f"    JSON: {r['json']}")
        if r.get("stderr_tail"):
            lines.append("    stderr(끝부분): " + r["stderr_tail"].replace("\n", "\n        "))
        if r.get("trace"):
            lines.append("    trace: " + r["trace"].replace("\n", "\n        "))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path, counts


GROUPS = [("A", test_A), ("B", test_B), ("C", test_C), ("D", test_D), ("E", test_E), ("F", test_F), ("G", test_G)]


def main():
    parser = argparse.ArgumentParser(description="atomic-cli Phase 1 Windows 실기 테스트 러너")
    parser.add_argument("--dir", default=r"C:\atomic_test", help="테스트 파일을 만들 폴더 (기본 C:\\atomic_test)")
    parser.add_argument("--only", help="실행할 그룹 (예: A,C,E)")
    parser.add_argument("--self-email", help="G3 실제 발송 테스트에 쓸 본인 메일 주소 (생략 시 G3 건너뜀)")
    parser.add_argument("--skip-outlook", action="store_true", help="G 그룹(Outlook) 건너뜀")
    parser.add_argument("--auto", action="store_true", help="y/n 질문 없이 자동 판정 항목만 진행")
    args = parser.parse_args()

    pythoncom.CoInitialize()
    ctx = Ctx(args)
    selected = {g.strip().upper() for g in args.only.split(",")} if args.only else {g for g, _ in GROUPS}
    if args.skip_outlook:
        selected.discard("G")

    log("=" * 70)
    log(" atomic-cli Phase 1 Windows 테스트")
    log(f" 대상 그룹: {','.join(sorted(selected))} / 테스트 폴더: {ctx.dir}")
    log(" 실행 전 다른 Excel/Word/PowerPoint 문서는 저장 후 모두 닫아 주세요.")
    log(" 테스트 중에는 Office 창을 직접 조작하지 마세요 (질문 응답 제외).")
    log("=" * 70)
    running = {img: process_count(img) for img in ("EXCEL.EXE", "WINWORD.EXE", "POWERPNT.EXE")}
    if any(v > 0 for v in running.values()):
        log(f"[주의] 실행 중인 Office 프로세스: {running}")
    if not args.auto:
        if input("시작할까요? (y/n): ").strip().lower() != "y":
            return

    setup_files(ctx)
    open_user_windows(ctx)

    for g, fn in GROUPS:
        if g in selected:
            log(f"\n{'-' * 25} 그룹 {g} {'-' * 25}")
            try:
                fn(ctx)
            except Exception as e:
                ctx.results.append({"id": g, "title": f"그룹 {g} 준비", "status": "ERROR",
                                    "detail": str(e), "trace": traceback.format_exc()[-800:]})
                log(f"[ERROR] 그룹 {g}: {e}")

    path, counts = write_report(ctx)
    log("\n" + "=" * 70)
    log(" 결과 요약: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for r in ctx.results:
        if r["status"] not in ("PASS",):
            log(f"   [{r['status']}] {r['id']} {r['title']} {r.get('detail', '')}")
    log(f" 보고서: {path}")
    log(" 테스트용 A 파일들은 열린 채로 남아 있습니다. 저장하지 않고 닫아도 됩니다.")
    log("=" * 70)


if __name__ == "__main__":
    main()
