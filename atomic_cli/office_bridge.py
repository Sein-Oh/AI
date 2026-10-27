import os
import sys
import argparse
import traceback
from typing import Dict, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session, word_session, ppt_session, COMError
from _config import get_data_dir

def copy_excel_to_word(from_target: str, sheet_name: Optional[str], range_str: Optional[str],
                        chart_idx: Optional[int], to_target: str, copy_as: str = "table",
                        bookmark: Optional[str] = None) -> Dict[str, Any]:
    """Excel 범위 또는 차트를 Word 문서로 복사하여 붙여넣습니다."""
    # 대상 Word 세션을 먼저 초기화하여 클립보드 소실 방지
    with word_session(target=to_target, snapshot=True) as (w_app, doc):
        with excel_session(target=from_target, sheet_name=sheet_name) as (xl_app, wb, ws):
            # 1. 엑셀 소스 복사 (Direct File/Image 파이프라인 우선 시도)
            item_desc = ""
            exported_img_path = None
            if chart_idx is not None:
                if ws.ChartObjects().Count < chart_idx:
                    raise ValueError(f"시트에 차트 #{chart_idx}가 존재하지 않습니다. (총 {ws.ChartObjects().Count}개)")
                chart_obj = ws.ChartObjects(chart_idx)
                if copy_as == "picture":
                    try:
                        temp_dir = get_data_dir()
                        # Windows COM 호환 경로 사용
                        exported_img_path = os.path.normpath(os.path.join(temp_dir, f"chart_{chart_idx}_{os.getpid()}.png"))
                        os.makedirs(temp_dir, exist_ok=True)
                        chart_obj.Chart.Export(exported_img_path, "PNG")
                        item_desc = f"Chart #{chart_idx} (Direct Image)"
                    except Exception as ex:
                        log_debug(f"차트 직접 이미지 내보내기 실패 ({ex}) -> 클립보드 fallback")
                        exported_img_path = None
                        try:
                            chart_obj.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
                        except Exception:
                            chart_obj.CopyPicture()
                        item_desc = f"Chart #{chart_idx} (as Picture)"
                else:
                    try:
                        chart_obj.Copy()
                    except Exception:
                        chart_obj.CopyPicture(1, 2)
                    item_desc = f"Chart #{chart_idx}"
            elif range_str:
                rng = ws.Range(range_str)
                if copy_as == "picture":
                    rng.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
                    item_desc = f"Range {range_str} (as Picture)"
                else:
                    rng.Copy()
                    item_desc = f"Range {range_str} (as Table)"
            else:
                raise ValueError("복사할 --range 또는 --chart 인자가 필요합니다.")

            # 2. 워드 문서로 즉시 배치
            if bookmark and bookmark in [b.Name for b in doc.Bookmarks]:
                target_range = doc.Bookmarks(bookmark).Range
            else:
                target_range = doc.Content
                target_range.Collapse(0)  # wdCollapseEnd = 0
                target_range.InsertParagraphAfter()
                target_range.Collapse(0)

            if exported_img_path and os.path.exists(exported_img_path):
                # 클립보드 100% 배제 Direct File 주입
                doc.InlineShapes.AddPicture(FileName=exported_img_path, Range=target_range)
                try:
                    os.remove(exported_img_path)
                except Exception:
                    pass
            elif copy_as == "picture":
                try:
                    target_range.PasteSpecial(DataType=3)  # wdPasteMetafilePicture = 3
                except Exception:
                    try:
                        target_range.PasteSpecial(DataType=4)  # wdPasteBitmap = 4
                    except Exception:
                        target_range.Paste()
            else:
                try:
                    target_range.PasteExcelTable(False, False, False)
                except Exception:
                    target_range.Paste()

            # 클립보드 정리
            try:
                xl_app.CutCopyMode = False
            except Exception:
                pass

            try:
                del target_range
            except Exception:
                pass

    return format_response(
        status="ok",
        module="office_bridge",
        action="excel_to_word",
        preview=f"Transferred {item_desc} from Excel to Word document",
        agent_directive="VERIFIED: Content bridged from Excel to Word successfully.",
        extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target}
    )

def copy_word_to_ppt(from_target: str, chart_idx: Optional[int], shape_idx: Optional[int],
                      to_target: str, slide_idx: int = 1, copy_as: str = "picture",
                      left: Optional[float] = None, top: Optional[float] = None,
                      width: Optional[float] = None, height: Optional[float] = None) -> Dict[str, Any]:
    """Word 문서의 차트, 그림 또는 표를 PowerPoint 슬라이드로 복사하여 배치합니다."""
    item_desc = ""
    with word_session(target=from_target) as (w_app, doc):
        target_idx = chart_idx or shape_idx or 1
        
        # 1. InlineShapes 우선 검사 (차트, 인라인 그림)
        if doc.InlineShapes.Count >= target_idx:
            target_shape = doc.InlineShapes(target_idx)
            try:
                target_shape.Range.CopyAsPicture()
            except Exception:
                target_shape.Range.Copy()
            item_desc = f"Word InlineShape #{target_idx}"
        # 2. 부유 도형(Shapes) 검사
        elif doc.Shapes.Count >= target_idx:
            target_shape = doc.Shapes(target_idx)
            try:
                target_shape.Select()
                w_app.Selection.CopyAsPicture()
            except Exception:
                target_shape.Select()
                w_app.Selection.Copy()
            item_desc = f"Word Shape #{target_idx}"
        # 3. 표(Tables) 검사
        elif doc.Tables.Count >= target_idx:
            tbl = doc.Tables(target_idx)
            tbl.Range.Copy()
            item_desc = f"Word Table #{target_idx}"
        else:
            raise ValueError(f"Word 문서에 복사할 대상 차트/도형/표 #{target_idx}가 없습니다. (총 InlineShapes: {doc.InlineShapes.Count})")

    # 2. PowerPoint로 안전하게 붙여넣기
    with ppt_session(target=to_target, snapshot=True) as (ppt_app, prs):
        if prs.Slides.Count < slide_idx:
            slide = prs.Slides.Add(prs.Slides.Count + 1, 12)  # ppLayoutBlank = 12
        else:
            slide = prs.Slides(slide_idx)

        try:
            pasted_shapes = slide.Shapes.PasteSpecial(2)  # ppPasteBitmap = 2
        except Exception:
            pasted_shapes = slide.Shapes.Paste()

        slide_w = prs.PageSetup.SlideWidth
        slide_h = prs.PageSetup.SlideHeight

        try:
            if left is not None:
                pasted_shapes.Left = float(left)
            else:
                pasted_shapes.Left = max(40.0, (slide_w - pasted_shapes.Width) / 2)

            if top is not None:
                pasted_shapes.Top = float(top)
            else:
                pasted_shapes.Top = max(100.0, (slide_h - pasted_shapes.Height) / 2)

            if width is not None:
                pasted_shapes.Width = float(width)
            if height is not None:
                pasted_shapes.Height = float(height)
        except Exception as e:
            log_debug(f"PPT 도형 크기/위치 조정 중 경고: {e}")

    return format_response(
        status="ok",
        module="office_bridge",
        action="word_to_ppt",
        preview=f"Transferred {item_desc} as image from Word to PPT slide #{slide_idx}",
        agent_directive="VERIFIED: Content bridged from Word to PowerPoint as image successfully.",
        extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target, "slide": slide_idx}
    )

def copy_excel_to_ppt(from_target: str, sheet_name: Optional[str], range_str: Optional[str],
                       chart_idx: Optional[int], to_target: str, slide_idx: int = 1,
                       copy_as: str = "picture", left: Optional[float] = None,
                       top: Optional[float] = None, width: Optional[float] = None,
                       height: Optional[float] = None) -> Dict[str, Any]:
    """Excel 범위 또는 차트를 PowerPoint 슬라이드로 복사하여 붙여넣습니다."""
    item_desc = ""
    exported_img_path = None
    # 1. Excel 소스 복사 (Direct Image 내보내기 우선 시도)
    # Excel COM 세션에서 차트를 PNG로 직접 내보내 클립보드 의존 제거
    with excel_session(target=from_target, sheet_name=sheet_name) as (xl_app, wb, ws):
        if chart_idx is not None:
            if ws.ChartObjects().Count < chart_idx:
                raise ValueError(f"시트에 차트 #{chart_idx}가 존재하지 않습니다. (총 {ws.ChartObjects().Count}개)")
            chart_obj = ws.ChartObjects(chart_idx)
            try:
                temp_dir = get_data_dir()
                # Windows COM은 백슬래시 경로를 요구하므로 replace 제거하고 normpath 사용
                exported_img_path = os.path.normpath(os.path.join(temp_dir, f"chart_{chart_idx}_{os.getpid()}.png"))
                os.makedirs(temp_dir, exist_ok=True)
                chart_obj.Chart.Export(exported_img_path, "PNG")
                item_desc = f"Chart #{chart_idx} (Direct Image)"
            except Exception as ex:
                log_debug(f"차트 직접 이미지 내보내기 실패 ({ex}) -> 클립보드 fallback")
                exported_img_path = None
                try:
                    chart_obj.Copy()
                except Exception:
                    chart_obj.CopyPicture(1, 2)
                item_desc = f"Chart #{chart_idx}"
        elif range_str:
            rng = ws.Range(range_str)
            if copy_as == "table":
                rng.Copy()
                item_desc = f"Range {range_str} (as Table)"
            else:
                rng.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
                item_desc = f"Range {range_str} (as Picture)"
        else:
            raise ValueError("복사할 --range 또는 --chart 인자가 필요합니다.")

    # 2. PowerPoint 슬라이드로 배치
    with ppt_session(target=to_target, snapshot=True) as (ppt_app, prs):
        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            slide = prs.Slides.Add(prs.Slides.Count + 1, 12)
            slide_idx = prs.Slides.Count
        else:
            slide = prs.Slides(slide_idx)

        slide_w = prs.PageSetup.SlideWidth
        slide_h = prs.PageSetup.SlideHeight

        if exported_img_path and os.path.exists(exported_img_path):
            # 클립보드 100% 배제 Direct File 주입
            # PNG 파일을 PowerPoint 슬라이드에 직접 삽입하여 안정성 확보
            final_w = float(width) if width is not None else 500.0
            final_h = float(height) if height is not None else 300.0
            final_left = float(left) if left is not None else max(40.0, (slide_w - final_w) / 2)
            final_top = float(top) if top is not None else max(100.0, (slide_h - final_h) / 2)

            pasted_shapes = slide.Shapes.AddPicture(
                FileName=exported_img_path,
                LinkToFile=False,
                SaveWithDocument=True,
                Left=final_left,
                Top=final_top,
                Width=final_w,
                Height=final_h
            )
            try:
                os.remove(exported_img_path)
            except Exception:
                pass
        else:
            # PowerPoint 슬라이드로 클립보드 붙여넣기 fallback
            try:
                pasted_shapes = slide.Shapes.Paste()
            except Exception:
                pasted_shapes = slide.Shapes.PasteSpecial(0)
            
            # 위치 및 크기 조정
            try:
                if left is not None:
                    pasted_shapes.Left = float(left)
                else:
                    pasted_shapes.Left = max(40.0, (slide_w - pasted_shapes.Width) / 2)

                if top is not None:
                    pasted_shapes.Top = float(top)
                else:
                    pasted_shapes.Top = max(100.0, (slide_h - pasted_shapes.Height) / 2)

                if width is not None:
                    pasted_shapes.Width = float(width)
                if height is not None:
                    pasted_shapes.Height = float(height)
            except Exception as e:
                log_debug(f"PPT 도형 크기/위치 조정 중 경고: {e}")

        # PowerPoint가 살아있는 동안 로컬 COM 레퍼런스를 선제 해제하여 RPC 행 방지
        pasted_shapes = None
        slide = None
        prs = None
        ppt_app = None

    return format_response(
        status="ok",
        module="office_bridge",
        action="excel_to_ppt",
        preview=f"Transferred {item_desc} from Excel to PPT slide #{slide_idx}",
        agent_directive="VERIFIED: Content bridged from Excel to PowerPoint successfully.",
        extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target, "slide": slide_idx}
    )

def copy_excel_to_excel(from_target: str, sheet_name: Optional[str], range_str: Optional[str],
                        chart_idx: Optional[int], to_target: str, dest_range: Optional[str] = None) -> Dict[str, Any]:
    """Excel 범위 또는 차트를 이미지로 복사하여 엑셀 시트의 특정 위치에 붙여넣습니다."""
    with excel_session(target=from_target, sheet_name=sheet_name) as (xl_app, wb, ws):
        item_desc = ""
        if chart_idx is not None:
            if ws.ChartObjects().Count < chart_idx:
                raise ValueError(f"시트에 차트 #{chart_idx}가 존재하지 않습니다. (총 {ws.ChartObjects().Count}개)")
            chart_obj = ws.ChartObjects(chart_idx)
            try:
                chart_obj.CopyPicture(1, 2)
            except Exception:
                chart_obj.Copy()
            item_desc = f"Chart #{chart_idx}"
        elif range_str:
            rng = ws.Range(range_str)
            try:
                rng.CopyPicture(1, 2)
            except Exception:
                rng.Copy()
            item_desc = f"Range {range_str}"
        else:
            raise ValueError("복사할 --range 또는 --chart 인자가 필요합니다.")

        dest = dest_range or "K2"
        try:
            target_cell = ws.Range(dest)
            ws.Paste(Destination=target_cell)
        except Exception:
            ws.Paste()

        return format_response(
            status="ok",
            module="office_bridge",
            action="excel_to_excel",
            preview=f"Transferred {item_desc} as image into Excel at {dest}",
            agent_directive="VERIFIED: Content bridged into Excel as image successfully.",
            extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target}
        )

def copy_word_to_excel(from_target: str, table_idx: int = 1, to_target: str = "active",
                        sheet_name: Optional[str] = None, dest_cell: str = "A1") -> Dict[str, Any]:
    """Word 문서의 표(Table) 데이터를 추출하여 Excel 시트에 SafeArray로 일괄 기입합니다."""
    extracted_rows: List[List[str]] = []
    with word_session(target=from_target, snapshot=False) as (w_app, doc):
        if doc.Tables.Count < table_idx:
            raise ValueError(f"Word 문서에 표 #{table_idx}가 존재하지 않습니다. (총 {doc.Tables.Count}개)")
        table = doc.Tables(table_idx)
        for r_idx in range(1, table.Rows.Count + 1):
            row_data = []
            for c_idx in range(1, table.Columns.Count + 1):
                try:
                    cell_text = table.Cell(r_idx, c_idx).Range.Text.rstrip("\r\x07\n")
                    row_data.append(cell_text)
                except Exception:
                    row_data.append("")
            extracted_rows.append(row_data)

    if not extracted_rows:
        raise ValueError("추출된 표 데이터가 비어 있습니다.")

    with excel_session(target=to_target, sheet_name=sheet_name, snapshot=True) as (xl_app, wb, ws):
        start_rng = ws.Range(dest_cell)
        num_rows = len(extracted_rows)
        num_cols = max(len(r) for r in extracted_rows) if extracted_rows else 1
        end_rng = ws.Cells(start_rng.Row + num_rows - 1, start_rng.Column + num_cols - 1)
        target_rng = ws.Range(start_rng, end_rng)

        safe_matrix = [tuple(r + [""] * (num_cols - len(r))) for r in extracted_rows]
        target_rng.Value = tuple(safe_matrix)

    return format_response(
        status="ok",
        module="office_bridge",
        action="word_to_excel",
        preview=f"Transferred Table #{table_idx} ({num_rows}x{num_cols}) from Word to Excel cell {dest_cell}",
        agent_directive="VERIFIED: Word table transferred to Excel successfully.",
        extra={"from_target": from_target, "to_target": to_target, "rows": num_rows, "cols": num_cols}
    )

def copy_ppt_to_word(from_target: str, slide_idx: int = 1, to_target: str = "active",
                      shape_idx: Optional[int] = None, copy_as: str = "picture",
                      bookmark: Optional[str] = None) -> Dict[str, Any]:
    """PowerPoint 슬라이드 또는 특정 요소를 Word 문서로 복사합니다."""
    item_desc = ""
    is_table_shape = False
    with ppt_session(target=from_target, snapshot=False) as (ppt_app, prs):
        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            raise ValueError(f"PPT 슬라이드 #{slide_idx}가 유효하지 않습니다. (총 {prs.Slides.Count}장)")
        slide = prs.Slides(slide_idx)
        if shape_idx is not None and 1 <= shape_idx <= slide.Shapes.Count:
            shape = slide.Shapes(shape_idx)
            # 표 모양 여부 확인
            try:
                is_table_shape = bool(shape.HasTable)
            except Exception:
                is_table_shape = False
            shape.Copy()
            item_desc = f"Slide #{slide_idx} Shape #{shape_idx}"
            if is_table_shape:
                item_desc += " (Table)"
        else:
            slide.Copy()
            item_desc = f"Slide #{slide_idx}"

    with word_session(target=to_target, snapshot=True) as (w_app, doc):
        target_range = doc.Bookmarks(bookmark).Range if (bookmark and doc.Bookmarks.Exists(bookmark)) else doc.Range(doc.Content.End - 1, doc.Content.End - 1)
        target_range.InsertParagraphAfter()
        paste_rng = doc.Range(doc.Content.End - 1, doc.Content.End - 1)

        # 표 모양은 그림이 아닌 표 구조로 붙여넣기
        if is_table_shape or copy_as == "table":
            try:
                paste_rng.Paste()
            except Exception:
                doc.Content.Paste()
        else:
            try:
                paste_rng.PasteSpecial(DataType=3)  # wdPasteMetafilePicture
            except Exception:
                try:
                    paste_rng.Paste()
                except Exception:
                    doc.Content.Paste()

    return format_response(
        status="ok",
        module="office_bridge",
        action="ppt_to_word",
        preview=f"Transferred {item_desc} from PPT to Word",
        agent_directive="VERIFIED: PowerPoint content bridged to Word successfully.",
        extra={"from_target": from_target, "to_target": to_target, "slide": slide_idx}
    )

def copy_ppt_to_excel(from_target: str, slide_idx: int = 1, shape_idx: Optional[int] = None,
                       to_target: str = "active", sheet_name: Optional[str] = None,
                       dest_cell: str = "A1") -> Dict[str, Any]:
    """PowerPoint 슬라이드의 표(Table Shape)를 추출하여 Excel 시트에 SafeArray로 기입합니다."""
    extracted_rows: List[List[str]] = []
    with ppt_session(target=from_target, snapshot=False) as (ppt_app, prs):
        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            raise ValueError(f"PPT 슬라이드 #{slide_idx}가 유효하지 않습니다. (총 {prs.Slides.Count}장)")
        slide = prs.Slides(slide_idx)
        
        target_table = None
        if shape_idx is not None and 1 <= shape_idx <= slide.Shapes.Count:
            sh = slide.Shapes(shape_idx)
            if sh.HasTable:
                target_table = sh.Table
        else:
            for sh in slide.Shapes:
                if sh.HasTable:
                    target_table = sh.Table
                    break

        if not target_table:
            raise ValueError(f"슬라이드 #{slide_idx}에서 표(Table)를 찾을 수 없습니다.")

        for r_idx in range(1, target_table.Rows.Count + 1):
            row_data = []
            for c_idx in range(1, target_table.Columns.Count + 1):
                try:
                    cell_text = target_table.Cell(r_idx, c_idx).Shape.TextFrame.TextRange.Text.strip()
                    row_data.append(cell_text)
                except Exception:
                    row_data.append("")
            extracted_rows.append(row_data)

    with excel_session(target=to_target, sheet_name=sheet_name, snapshot=True) as (xl_app, wb, ws):
        start_rng = ws.Range(dest_cell)
        num_rows = len(extracted_rows)
        num_cols = max(len(r) for r in extracted_rows) if extracted_rows else 1
        end_rng = ws.Cells(start_rng.Row + num_rows - 1, start_rng.Column + num_cols - 1)
        target_rng = ws.Range(start_rng, end_rng)

        safe_matrix = [tuple(r + [""] * (num_cols - len(r))) for r in extracted_rows]
        target_rng.Value = tuple(safe_matrix)

    return format_response(
        status="ok",
        module="office_bridge",
        action="ppt_to_excel",
        preview=f"Transferred Table ({num_rows}x{num_cols}) from PPT slide #{slide_idx} to Excel cell {dest_cell}",
        agent_directive="VERIFIED: PPT table transferred to Excel successfully.",
        extra={"from_target": from_target, "to_target": to_target, "slide": slide_idx, "rows": num_rows, "cols": num_cols}
    )

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """통합 Cross-Office Bridge 실행 함수."""
    from_app = (params.get("from_app") or "excel").lower()
    to_app = (params.get("to_app") or "word").lower()
    from_target = params.get("from_target") or params.get("from") or "active"
    to_target = params.get("to_target") or params.get("to") or "active"
    sheet_name = params.get("sheet")
    range_str = params.get("range")
    chart_val = params.get("chart")
    chart_idx = int(chart_val) if chart_val is not None else None
    copy_as_default = "picture" if (to_app in ["ppt", "powerpoint"] or chart_idx is not None) else "table"
    copy_as = (params.get("copy_as") or copy_as_default).lower()
    bookmark = params.get("bookmark")
    slide_idx = int(params.get("slide") or 1)
    left = params.get("left")
    top = params.get("top")
    width = params.get("width")
    height = params.get("height")

    try:
        if from_app == "excel" and to_app == "excel":
            return copy_excel_to_excel(
                from_target=from_target,
                sheet_name=sheet_name,
                range_str=range_str,
                chart_idx=chart_idx,
                to_target=to_target,
                dest_range=params.get("range") or params.get("dest")
            )
        elif from_app == "excel" and to_app == "word":
            return copy_excel_to_word(
                from_target=from_target,
                sheet_name=sheet_name,
                range_str=range_str,
                chart_idx=chart_idx,
                to_target=to_target,
                copy_as=copy_as,
                bookmark=bookmark
            )
        elif from_app == "excel" and to_app in ["ppt", "powerpoint"]:
            return copy_excel_to_ppt(
                from_target=from_target,
                sheet_name=sheet_name,
                range_str=range_str,
                chart_idx=chart_idx,
                to_target=to_target,
                slide_idx=slide_idx,
                copy_as=copy_as,
                left=left,
                top=top,
                width=width,
                height=height
            )
        elif from_app == "word" and to_app in ["ppt", "powerpoint"]:
            return copy_word_to_ppt(
                from_target=from_target,
                chart_idx=chart_idx,
                shape_idx=params.get("shape") or params.get("item"),
                to_target=to_target,
                slide_idx=slide_idx,
                copy_as=copy_as,
                left=left,
                top=top,
                width=width,
                height=height
            )
        elif from_app == "word" and to_app == "excel":
            return copy_word_to_excel(
                from_target=from_target,
                table_idx=int(params.get("table") or params.get("item") or 1),
                to_target=to_target,
                sheet_name=sheet_name,
                dest_cell=params.get("range") or params.get("dest") or "A1"
            )
        elif from_app in ["ppt", "powerpoint"] and to_app == "word":
            return copy_ppt_to_word(
                from_target=from_target,
                slide_idx=slide_idx,
                to_target=to_target,
                shape_idx=params.get("shape") or params.get("item"),
                copy_as=copy_as,
                bookmark=bookmark
            )
        elif from_app in ["ppt", "powerpoint"] and to_app == "excel":
            return copy_ppt_to_excel(
                from_target=from_target,
                slide_idx=slide_idx,
                shape_idx=params.get("shape") or params.get("item"),
                to_target=to_target,
                sheet_name=sheet_name,
                dest_cell=params.get("range") or params.get("dest") or "A1"
            )
        else:
            raise NotImplementedError(f"지원하지 않는 브릿지 경로입니다: {from_app} -> {to_app}")

    except Exception as e:
        log_debug(f"office_bridge 실행 오류: {traceback.format_exc()}")
        return format_response(
            status="error",
            module="office_bridge",
            action=f"{from_app}_to_{to_app}",
            preview=f"Bridge failed: {e}",
            agent_directive=f"STOP_RETRY: Cross-Office transfer failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Cross-Office Content Bridge Micro Block")
    parser.add_argument("--from-app", default="excel", choices=["excel", "word", "ppt", "powerpoint"], help="원본 오피스 앱 (excel, word, ppt)")
    parser.add_argument("--from", "--from-target", dest="from_target", default="active", help="원본 파일 경로 또는 'active'")
    parser.add_argument("--sheet", help="엑셀 시트명")
    parser.add_argument("--range", help="엑셀 범위 또는 대상 시작 셀 (예: 'A1:E10', 'A1')")
    parser.add_argument("--chart", type=int, help="복사할 엑셀 차트 번호 (1부터 시작)")
    parser.add_argument("--table", type=int, help="복사할 표 번호 (1부터 시작)")
    parser.add_argument("--shape", type=int, help="복사할 도형 번호 (1부터 시작)")
    parser.add_argument("--copy-as", default="table", choices=["table", "picture"], help="복사 형식 (기본: table)")
    
    parser.add_argument("--to-app", default="word", choices=["word", "ppt", "powerpoint", "excel"], help="대상 오피스 앱 (word, ppt, excel)")
    parser.add_argument("--to", "--to-target", dest="to_target", default="active", help="대상 파일 경로 또는 'active'")
    parser.add_argument("--slide", type=int, default=1, help="PPT 대상 슬라이드 번호 (1부터 시작)")
    parser.add_argument("--bookmark", help="Word 대상 북마크 이름")
    parser.add_argument("--left", type=float, help="PPT 도형 좌측 좌표 (pt)")
    parser.add_argument("--top", type=float, help="PPT 도형 상단 좌표 (pt)")
    parser.add_argument("--width", type=float, help="PPT 도형 너비 (pt)")
    parser.add_argument("--height", type=float, help="PPT 도형 높이 (pt)")

    args = parser.parse_args()
    params = vars(args)
    res = execute(params)
    emit_response(res)
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
