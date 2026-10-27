import sys
import os
import json
import argparse
from typing import Dict, Any, List, Optional
from collections import Counter

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, parse_color_to_bgr, bgr_to_hex
from _config import get_data_dir
from _com_guard import (
    excel_session, word_session, ppt_session,
    get_all_running_excel_workbooks, get_all_running_word_documents, get_all_running_ppt_presentations,
    COMError
)

# --- 비즈니스 표준 컬러 테마 프리셋 모음 ---
THEME_PRESETS = {
    "navy": {
        "name": "Corporate Navy",
        "description": "신뢰감 있는 클래식 비즈니스 네이비 테마",
        "primary": "#1B365D",
        "secondary": "#4A777A",
        "accent": "#D9381E",
        "header": {
            "bg": "#1B365D",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F4F7FB"
        },
        "summary": {
            "bg": "#E8EEF5",
            "color": "#1B365D",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#D0D7DE",
            "outer_color": "#1B365D"
        },
        "number_format": "#,##0"
    },
    "slate": {
        "name": "Modern Slate",
        "description": "미니멀하고 세련된 차콜/슬레이트 테마",
        "primary": "#2B2D42",
        "secondary": "#8D99AE",
        "accent": "#EF233C",
        "header": {
            "bg": "#2B2D42",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F8F9FA"
        },
        "summary": {
            "bg": "#EDF2F4",
            "color": "#2B2D42",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#E5E7EB",
            "outer_color": "#2B2D42"
        },
        "number_format": "#,##0"
    },
    "teal": {
        "name": "Clean Teal",
        "description": "전략/재무 보고서에 최적화된 다크 틸 & 민트 테마",
        "primary": "#004D40",
        "secondary": "#00897B",
        "accent": "#FF6F00",
        "header": {
            "bg": "#004D40",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F0FDF4"
        },
        "summary": {
            "bg": "#E0F2F1",
            "color": "#004D40",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#CCFBF1",
            "outer_color": "#004D40"
        },
        "number_format": "#,##0"
    },
    "emerald": {
        "name": "Forest Emerald",
        "description": "안정적이고 차분한 에메랄드 그린 테마",
        "primary": "#1E4620",
        "secondary": "#3E7B43",
        "accent": "#E65100",
        "header": {
            "bg": "#1E4620",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F2F8F2"
        },
        "summary": {
            "bg": "#E5EFE5",
            "color": "#1E4620",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#D1E7DD",
            "outer_color": "#1E4620"
        },
        "number_format": "#,##0"
    }
}

def resolve_theme(theme_arg: Optional[str] = None) -> Dict[str, Any]:
    r"""프리셋 이름 또는 테마 JSON 파일 경로를 받아 완성된 테마 딕셔너리를 반환합니다.
    생략되거나 'auto'인 경우 C:\cli_data\data\current_theme.json을 자동 상속받습니다.
    """
    if not theme_arg or theme_arg.strip().lower() in ["auto", "default", "none"]:
        current_theme_file = os.path.join(get_data_dir(), "current_theme.json")
        if os.path.exists(current_theme_file):
            try:
                with open(current_theme_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return THEME_PRESETS["navy"]

    t_clean = theme_arg.strip().lower()
    if t_clean in THEME_PRESETS:
        return THEME_PRESETS[t_clean]

    # 로컬 파일 경로 탐색
    cand_paths = [
        theme_arg,
        os.path.join(get_data_dir(), theme_arg),
        os.path.join(get_data_dir(), f"{theme_arg}.json")
    ]
    for p in cand_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)

    return THEME_PRESETS.get(t_clean, THEME_PRESETS["navy"])

# --- Excel 정밀 스타일 분석기 ---
def extract_excel_style_dna(ws) -> Dict[str, Any]:
    """Excel Worksheet의 UsedRange를 스캔하여 스타일 DNA를 정밀 추출합니다."""
    used_range = ws.UsedRange
    row_count = used_range.Rows.Count
    col_count = used_range.Columns.Count
    start_row = used_range.Row
    start_col = used_range.Column

    dna: Dict[str, Any] = {
        "app": "excel",
        "sheet_name": ws.Name,
        "grid_lines": getattr(ws.Parent.Windows(1), "DisplayGridlines", True),
        "header": {},
        "zebra": {"enabled": False},
        "summary": {},
        "number_format": "#,##0",
        "font_family": "맑은 고딕",
        "palette": []
    }

    if row_count == 0 or col_count == 0:
        return dna

    # 1. 헤더 행 분석 (1행 샘플링)
    header_cell = ws.Cells(start_row, start_col)
    try:
        dna["font_family"] = str(header_cell.Font.Name)
        h_bg_int = header_cell.Interior.Color
        h_color_int = header_cell.Font.Color
        
        # 기본 흰색/투명 제외 유의미한 배경색 추출
        h_bg_hex = bgr_to_hex(h_bg_int)
        h_color_hex = bgr_to_hex(h_color_int)

        dna["header"] = {
            "bg": h_bg_hex if h_bg_hex not in ["#FFFFFF", None] else "#1B365D",
            "color": h_color_hex if h_color_hex is not None else "#FFFFFF",
            "bold": bool(header_cell.Font.Bold),
            "font_size": float(header_cell.Font.Size),
            "align": "center" if header_cell.HorizontalAlignment == -4108 else "left",
            "row_height": float(ws.Rows(start_row).RowHeight)
        }
    except Exception as e:
        log_debug(f"헤더 분석 예외: {e}")

    # 2. 데이터 행 및 Zebra 패턴 분석
    bg_colors = []
    num_formats = []
    
    # 상위 10행 샘플링
    sample_rows = min(row_count - 1, 10)
    for r in range(1, sample_rows + 1):
        curr_row = start_row + r
        try:
            cell = ws.Cells(curr_row, start_col)
            bg = bgr_to_hex(cell.Interior.Color)
            if bg:
                bg_colors.append(bg)
        except Exception:
            pass

    # 숫자 열 포맷 샘플링
    for c in range(col_count):
        curr_col = start_col + c
        try:
            for r in range(1, min(row_count, 5)):
                val = ws.Cells(start_row + r, curr_col).Value
                fmt = ws.Cells(start_row + r, curr_col).NumberFormat
                if isinstance(val, (int, float)) and fmt and fmt != "General":
                    num_formats.append(str(fmt))
                    break
        except Exception:
            pass

    if num_formats:
        most_common_fmt = Counter(num_formats).most_common(1)[0][0]
        dna["number_format"] = most_common_fmt

    # Zebra 교차 배경색 탐지
    if len(bg_colors) >= 2:
        distinct_bgs = list(dict.fromkeys(bg_colors))
        if len(distinct_bgs) >= 2 and distinct_bgs[0] != distinct_bgs[1]:
            dna["zebra"] = {
                "enabled": True,
                "odd": distinct_bgs[0],
                "even": distinct_bgs[1]
            }

    # 3. 합계/요약 행 분석 (마지막 행)
    if row_count >= 3:
        last_row = start_row + row_count - 1
        last_cell = ws.Cells(last_row, start_col)
        last_val = str(last_cell.Value or "")
        
        is_summary = any(k in last_val for k in ["합계", "총계", "Total", "소계", "평균"])
        try:
            # 이중 밑줄 확인 (xlDouble = -4119, xlEdgeBottom = 9)
            has_double_border = (last_cell.Borders(9).LineStyle == -4119)
        except Exception:
            has_double_border = False

        if is_summary or has_double_border or bool(last_cell.Font.Bold):
            dna["summary"] = {
                "detected": True,
                "row_index": last_row,
                "bold": bool(last_cell.Font.Bold),
                "bg": bgr_to_hex(last_cell.Interior.Color),
                "border_bottom": "double" if has_double_border else "single"
            }

    # 4. 전체 팔레트 추출 (상위 사용 색상)
    color_counter = Counter([dna["header"].get("bg"), dna["zebra"].get("even"), dna["summary"].get("bg")])
    dna["palette"] = [c for c, _ in color_counter.most_common() if c and c != "#FFFFFF"]

    return dna

# --- PowerPoint 정밀 스타일 분석기 ---
def extract_ppt_style_dna(prs) -> Dict[str, Any]:
    """PowerPoint 프레젠테이션을 스캔하여 타이포그래피 및 지배적 컬러 팔레트를 추출합니다."""
    dna: Dict[str, Any] = {
        "app": "ppt",
        "title_font": "맑은 고딕",
        "title_size": 28,
        "title_color": "#1B365D",
        "body_font": "맑은 고딕",
        "body_size": 14,
        "body_color": "#333333",
        "palette": [],
        "card_styles": []
    }

    fill_colors = []
    font_colors = []
    fonts = []

    for slide in prs.Slides:
        for shape in slide.Shapes:
            # 도형/카드 채우기 색상
            try:
                if shape.Fill.Visible and shape.Fill.ForeColor.RGB:
                    hex_color = bgr_to_hex(shape.Fill.ForeColor.RGB)
                    if hex_color and hex_color not in ["#FFFFFF", "#000000"]:
                        fill_colors.append(hex_color)
            except Exception:
                pass

            # 텍스트 속성
            try:
                if shape.HasTextFrame and shape.TextFrame.HasText:
                    tr = shape.TextFrame.TextRange
                    if tr.Font.Name:
                        fonts.append(str(tr.Font.Name))
                    if tr.Font.Color.RGB:
                        fc = bgr_to_hex(tr.Font.Color.RGB)
                        if fc:
                            font_colors.append(fc)

                    # 제목 텍스트 상자 추정 (20pt 이상)
                    if tr.Font.Size >= 20:
                        dna["title_font"] = str(tr.Font.Name)
                        dna["title_size"] = float(tr.Font.Size)
                        if fc:
                            dna["title_color"] = fc
                    elif tr.Font.Size <= 16:
                        dna["body_font"] = str(tr.Font.Name)
                        dna["body_size"] = float(tr.Font.Size)
                        if fc:
                            dna["body_color"] = fc
            except Exception:
                pass

    # 주요 팔레트 계산
    all_colors = fill_colors + font_colors
    if all_colors:
        top_colors = [c for c, _ in Counter(all_colors).most_common(5)]
        dna["palette"] = top_colors

    return dna

# --- Word 정밀 스타일 분석기 ---
def extract_word_style_dna(doc) -> Dict[str, Any]:
    """Word 문서를 스캔하여 표준 본문/제목 글꼴 및 표 서식을 추출합니다."""
    dna: Dict[str, Any] = {
        "app": "word",
        "font_family": "맑은 고딕",
        "body_size": 10.5,
        "body_color": "#000000",
        "heading_font": "맑은 고딕",
        "heading_size": 14,
        "heading_color": "#1B365D",
        "table_header_bg": "#1B365D",
        "palette": []
    }

    try:
        # 본문(Normal) 기본 글꼴 추출
        norm_style = doc.Styles("Normal")
        dna["font_family"] = str(norm_style.Font.Name)
        dna["body_size"] = float(norm_style.Font.Size)
    except Exception:
        pass

    try:
        # Heading 1 글꼴 추출
        h1_style = doc.Styles("Heading 1")
        dna["heading_font"] = str(h1_style.Font.Name)
        dna["heading_size"] = float(h1_style.Font.Size)
        h_color = bgr_to_hex(h1_style.Font.Color)
        if h_color:
            dna["heading_color"] = h_color
    except Exception:
        pass

    # 표 헤더 색상 검사
    try:
        if doc.Tables.Count > 0:
            first_tbl = doc.Tables(1)
            cell = first_tbl.Cell(1, 1)
            bg = bgr_to_hex(cell.Range.Shading.BackgroundPatternColor)
            if bg and bg != "#FFFFFF":
                dna["table_header_bg"] = bg
                dna["palette"].append(bg)
    except Exception:
        pass

    return dna

# --- 통합 실행 인터페이스 ---
def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 스타일 테마 추출/목록 조회를 실행합니다."""
    action = (params.get("action") or "extract").lower()
    target = params.get("target") or "active"
    app_hint = (params.get("app") or "").lower()
    export_path = params.get("export") or params.get("export_theme")

    # 1. 내장 프리셋 목록 조회
    if action in ["list", "list-presets", "presets"]:
        presets_summary = {k: {"name": v["name"], "description": v["description"], "primary": v["primary"]} for k, v in THEME_PRESETS.items()}
        return format_response(
            status="ok",
            module="office_theme",
            action="list_presets",
            preview=f"총 {len(THEME_PRESETS)}개 내장 비즈니스 테마 프리셋 제공: [{', '.join(THEME_PRESETS.keys())}]",
            agent_directive="VERIFIED: Theme presets listed.",
            extra={"presets": presets_summary}
        )

    # 1-B. 활성 글로벌 테마 설정 (Set/Apply)
    if action in ["set", "apply", "activate"]:
        theme_name = params.get("theme") or params.get("name") or "navy"
        resolved = resolve_theme(theme_name)
        curr_theme_path = os.path.join(get_data_dir(), "current_theme.json")
        with open(curr_theme_path, "w", encoding="utf-8") as f:
            json.dump(resolved, f, ensure_ascii=False, indent=2)
        return format_response(
            status="ok",
            module="office_theme",
            action="set_theme",
            preview=f"글로벌 활성 테마 설정 완료: '{theme_name}' (이후 모든 Office 도구에 자동 상속)",
            agent_directive="VERIFIED: Global theme activated.",
            extra={"theme": theme_name, "path": curr_theme_path}
        )

    # 2. 스타일 DNA 추출 실행
    # 앱 종류 판별
    if not app_hint:
        t_lower = target.lower()
        if t_lower.endswith((".xlsx", ".xls", ".xlsm")):
            app_hint = "excel"
        elif t_lower.endswith((".docx", ".doc")):
            app_hint = "word"
        elif t_lower.endswith((".pptx", ".ppt")):
            app_hint = "ppt"
        else:
            # 활성 창 기반 자동 감지
            excel_wbs = get_all_running_excel_workbooks()
            if excel_wbs:
                app_hint = "excel"
            elif get_all_running_word_documents():
                app_hint = "word"
            elif get_all_running_ppt_presentations():
                app_hint = "ppt"
            else:
                app_hint = "excel"

    dna_result = {}
    if app_hint == "excel":
        with excel_session(target=target, snapshot=False) as (app, wb, ws):
            dna_result = extract_excel_style_dna(ws)
    elif app_hint == "word":
        with word_session(target=target, snapshot=False) as (app, doc):
            dna_result = extract_word_style_dna(doc)
    elif app_hint == "ppt":
        with ppt_session(target=target, snapshot=False) as (app, prs):
            dna_result = extract_ppt_style_dna(prs)
    else:
        raise ValueError(f"지원하지 않는 애플리케이션: {app_hint}")

    # 글로벌 활성 테마 버스 자동 동기화 (이후 생성 도구에 자동 상속)
    try:
        curr_theme_path = os.path.join(get_data_dir(), "current_theme.json")
        with open(curr_theme_path, "w", encoding="utf-8") as f:
            json.dump(dna_result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 테마 JSON 저장 처리
    saved_file = None
    if export_path:
        if not os.path.isabs(export_path):
            export_path = os.path.join(get_data_dir(), export_path)
        if not export_path.endswith(".json"):
            export_path += ".json"
        
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(dna_result, f, ensure_ascii=False, indent=2)
        saved_file = export_path
        log_debug(f"스타일 DNA 프로필 저장 완료: {export_path}")

    preview_msg = (
        f"[{app_hint.upper()}] 스타일 DNA 추출 완료 | "
        f"폰트: {dna_result.get('font_family') or dna_result.get('title_font', '기본')} | "
        f"주요색상: {dna_result.get('palette', ['없음'])}"
    )
    if saved_file:
        preview_msg += f" | 파일 저장: {os.path.basename(saved_file)}"

    return format_response(
        status="ok",
        module="office_theme",
        action="extract_theme",
        preview=preview_msg,
        agent_directive="VERIFIED: Style theme extracted.",
        extra={
            "app": app_hint,
            "theme_path": saved_file,
            "theme": dna_result
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Office Style & Theme DNA Extraction Micro Block")
    parser.add_argument("--action", "-a", default="extract", choices=["extract", "list-presets", "list", "set", "apply"], help="수행할 작업")
    parser.add_argument("--target", "-t", default="active", help="대상 (active 또는 파일 경로)")
    parser.add_argument("--theme", help="설정할 테마 이름 또는 JSON 경로 (set/apply 시)")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="애플리케이션 명시")
    parser.add_argument("--export", "--export-theme", "-o", type=str, help="추출된 테마 JSON 저장 파일명/경로")
    args = parser.parse_args()

    params = {
        "action": args.action,
        "target": args.target,
        "theme": args.theme,
        "app": args.app,
        "export": args.export
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
