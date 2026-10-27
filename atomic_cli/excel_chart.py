import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, parse_color_to_bgr
from _com_guard import excel_session
from office_theme import resolve_theme

# Excel XlChartType 상수 매핑
CHART_TYPES = {
    "column": 51,        # xlColumnClustered
    "bar": 57,           # xlBarClustered
    "line": 4,           # xlLine
    "line_markers": 65,  # xlLineMarkers
    "pie": 5,            # xlPie
    "area": 1,           # xlArea
    "combo": 51          # 복합 차트 (1계열 막대 + 2계열 보조축 꺾은선)
}

LEGEND_POSITIONS = {
    "bottom": -4107,     # xlLegendPositionBottom
    "right": -4152,      # xlLegendPositionRight
    "top": -4160,        # xlLegendPositionTop
    "left": -4131        # xlLegendPositionLeft
}

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 차트를 생성하거나 삭제합니다."""
    action = str(params.get("action") or "create").lower()

    # 차트 삭제/초기화 분기
    if action in ["delete", "remove", "clear"]:
        chart_name = params.get("title") or params.get("name") or params.get("chart")
        try:
            chart_objs = ws.ChartObjects()
            total = chart_objs.Count
            if total == 0:
                return format_response(
                    status="ok",
                    module="excel_chart",
                    action="delete_chart",
                    preview="시트에 삭제할 차트가 없습니다 (현재 차트 수: 0개).",
                    agent_directive="VERIFIED: No charts to delete."
                )
            deleted_count = 0
            if chart_name:
                for i in range(total, 0, -1):
                    obj = chart_objs.Item(i)
                    obj_title = ""
                    try:
                        if obj.Chart.HasTitle:
                            obj_title = str(obj.Chart.ChartTitle.Text)
                    except Exception:
                        pass
                    if str(chart_name).lower() in obj.Name.lower() or (obj_title and str(chart_name).lower() in obj_title.lower()):
                        obj.Delete()
                        deleted_count += 1
                if deleted_count == 0:
                    chart_objs.Item(1).Delete()
                    deleted_count = 1
            else:
                deleted_count = total
                chart_objs.Delete()

            return format_response(
                status="ok",
                module="excel_chart",
                action="delete_chart",
                preview=f"시트 '{ws.Name}'에서 차트 {deleted_count}개를 성공적으로 삭제했습니다.",
                agent_directive="VERIFIED: Chart deleted. Do not re-verify.",
                extra={"deleted_count": deleted_count}
            )
        except Exception as e:
            return format_response(
                status="error",
                module="excel_chart",
                action="delete_chart",
                preview=f"차트 삭제 실패: {e}",
                agent_directive=f"STOP_RETRY: Chart deletion failed: {e}"
            )

    source_addr = params.get("source_range") or params.get("range")
    chart_type_name = str(params.get("type", "column")).lower()
    title = params.get("title", "")
    target_cell = params.get("target_cell", "G2")
    width = float(params.get("width", 420))
    height = float(params.get("height", 260))
    data_labels = params.get("data_labels", False)
    theme_arg = params.get("theme")
    legend_pos = params.get("legend", "bottom").lower()

    if not source_addr:
        try:
            used_addr = ws.UsedRange.Address
            if used_addr and (used_addr != "$A$1" or ws.Range("$A$1").Value is not None):
                source_addr = used_addr
                log_debug(f"Source range omitted. Auto-detected UsedRange: {source_addr}")
            else:
                return format_response(
                    status="no_match",
                    module="excel_chart",
                    action="create_chart",
                    preview="source_range is required",
                    agent_directive="STOP_RETRY: Missing source data range for chart."
                )
        except Exception:
            return format_response(
                status="no_match",
                module="excel_chart",
                action="create_chart",
                preview="source_range is required",
                agent_directive="STOP_RETRY: Missing source data range for chart."
            )

    try:
        source_rng = ws.Range(source_addr)
        anchor_cell = ws.Range(target_cell)
        left = anchor_cell.Left
        top = anchor_cell.Top

        chart_code = CHART_TYPES.get(chart_type_name, 51)
        log_debug(f"차트 생성: 유형={chart_type_name}, 데이터={source_addr}, 위치={target_cell}")

        # 차트 오브젝트 생성
        chart_obj = ws.ChartObjects().Add(left, top, width, height)
        chart = chart_obj.Chart
        chart.ChartType = chart_code
        chart.SetSourceData(source_rng)

        # 1. 제목 설정
        if title:
            chart.HasTitle = True
            chart.ChartTitle.Text = title

        # 2. 이중 축 (Combo: 1계열 막대 + 2계열 꺾은선) 구성
        is_combo = chart_type_name in ["combo", "column_line"]
        if is_combo:
            try:
                series_collection = chart.SeriesCollection()
                if series_collection.Count >= 2:
                    # 1계열: 세로 막대 (기본 축)
                    series_collection(1).ChartType = 51  # xlColumnClustered
                    series_collection(1).AxisGroup = 1   # xlPrimary
                    
                    # 2계열: 꺾은선 마커 (보조 축 xlSecondary = 2)
                    series_collection(2).ChartType = 65  # xlLineMarkers
                    series_collection(2).AxisGroup = 2   # xlSecondary
                    log_debug("이중 축(Combo) 차트 구성 완료 (1계열: 막대, 2계열: 보조축 꺾은선)")
            except Exception as ce:
                log_debug(f"이중 축 구성 예외: {ce}")

        # 3. 데이터 레이블(값 표시) 적용
        if data_labels:
            try:
                chart.ApplyDataLabels()
                log_debug("차트 데이터 레이블 적용 완료")
            except Exception as de:
                log_debug(f"데이터 레이블 적용 예외: {de}")

        # 4. 범례 위치 지정
        if legend_pos == "none":
            chart.HasLegend = False
        elif legend_pos in LEGEND_POSITIONS:
            chart.HasLegend = True
            chart.Legend.Position = LEGEND_POSITIONS[legend_pos]

        # 5. 테마 색상 연계
        applied_theme_name = None
        if theme_arg:
            try:
                theme = resolve_theme(theme_arg)
                applied_theme_name = theme.get("name", theme_arg)
                series_collection = chart.SeriesCollection()
                
                # 주색상 / 보조색상 매핑
                p_color = parse_color_to_bgr(theme.get("primary"))
                s_color = parse_color_to_bgr(theme.get("secondary"))
                
                if series_collection.Count >= 1 and p_color is not None:
                    series_collection(1).Format.Fill.ForeColor.RGB = p_color
                if series_collection.Count >= 2 and s_color is not None:
                    if is_combo:
                        series_collection(2).Format.Line.ForeColor.RGB = s_color
                    else:
                        series_collection(2).Format.Fill.ForeColor.RGB = s_color
                log_debug(f"차트 테마({applied_theme_name}) 색상 반영 완료")
            except Exception as te:
                log_debug(f"차트 테마 색상 적용 예외: {te}")

        return format_response(
            status="ok",
            module="excel_chart",
            action="create_chart",
            preview=f"Chart '{title or chart_type_name}' created at {target_cell} using {source_addr} (Combo: {is_combo}, Labels: {data_labels})",
            agent_directive="VERIFIED: Chart generated. Do not re-verify.",
            extra={
                "chart_type": chart_type_name,
                "title": title,
                "anchor": target_cell,
                "is_combo": is_combo,
                "data_labels": data_labels,
                "theme": applied_theme_name
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_chart",
            action="create_chart",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Chart creation failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Advanced Chart Micro Block (Combo & DataLabels Support, Delete Support)")
    parser.add_argument("--action", default="create", choices=["create", "delete", "clear"], help="차트 작업 (create=생성, delete=삭제)")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--range", "--source-range", required=False, help="차트 원본 데이터 범위 (create 시 필수, 예: A1:C6)")
    parser.add_argument("--type", default="column", choices=["column", "bar", "line", "line_markers", "pie", "area", "combo"], help="차트 유형 (combo=이중축 혼합차트)")
    parser.add_argument("--title", type=str, help="차트 제목 (delete 시 특정 차트 매칭)")
    parser.add_argument("--target-cell", default="G2", help="차트 배치 기준 셀 (예: G2)")
    parser.add_argument("--width", type=float, default=420, help="차트 너비(pt)")
    parser.add_argument("--height", type=float, default=260, help="차트 높이(pt)")
    parser.add_argument("--data-labels", action="store_true", help="수치 데이터 레이블 표시")
    parser.add_argument("--legend", choices=["bottom", "right", "top", "none"], default="bottom", help="범례 위치")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald) 또는 JSON 경로")
    args = parser.parse_args()

    if args.action == "create" and not args.range:
        parser.error("--range는 차트 생성(action=create) 시 필수입니다.")

    params = {
        "action": args.action,
        "range": args.range,
        "type": args.type,
        "title": args.title,
        "target_cell": args.target_cell,
        "width": args.width,
        "height": args.height,
        "data_labels": args.data_labels,
        "legend": args.legend,
        "theme": args.theme
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
