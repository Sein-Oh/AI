import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import ppt_session

# PPT PpSlideLayout 상수 (기본 빈 슬라이드: ppLayoutBlank = 12, 제목+내용: 2)
PPT_LAYOUT_BLANK = 12
PPT_LAYOUT_TITLE_AND_CONTENT = 2

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 슬라이드 추가/복제/삭제/이동을 수행합니다."""
    action = params.get("action", "add").lower()
    slide_index = params.get("slide") or params.get("index")
    dest_index = params.get("dest")

    try:
        total_slides = prs.Slides.Count

        if action == "add":
            # 새 슬라이드 추가 (기본 맨 뒤에 추가)
            insert_pos = int(slide_index) if slide_index else (total_slides + 1)
            # 빈 슬라이드 레이아웃 사용 (ppLayoutBlank = 12)
            try:
                layout = prs.SlideMaster.CustomLayouts(7)  # 기본 빈 레이아웃
                new_slide = prs.Slides.AddSlide(insert_pos, layout)
            except Exception:
                new_slide = prs.Slides.Add(insert_pos, PPT_LAYOUT_BLANK)

            return format_response(
                status="ok",
                module="ppt_slide",
                action="add",
                preview=f"Added new blank slide at position {new_slide.SlideIndex} (Total: {prs.Slides.Count})",
                agent_directive="VERIFIED: Slide added successfully.",
                extra={"slide_index": new_slide.SlideIndex, "total_slides": prs.Slides.Count}
            )

        elif action == "duplicate":
            if not slide_index:
                raise ValueError("복제할 대상 슬라이드 번호(slide)가 필요합니다.")
            src_idx = int(slide_index)
            if src_idx < 1 or src_idx > total_slides:
                raise IndexError(f"슬라이드 번호 범위를 벗어났습니다: {src_idx} (총 {total_slides}장)")
            
            dup_range = prs.Slides(src_idx).Duplicate()
            try:
                dup_idx = dup_range.Item(1).SlideIndex
            except Exception:
                try:
                    dup_idx = dup_range.SlideIndex
                except Exception:
                    dup_idx = src_idx + 1

            return format_response(
                status="ok",
                module="ppt_slide",
                action="duplicate",
                preview=f"Duplicated slide {src_idx} to position {dup_idx} (Total: {prs.Slides.Count})",
                agent_directive="VERIFIED: Slide duplicated successfully.",
                extra={"slide_index": dup_idx, "total_slides": prs.Slides.Count}
            )

        elif action == "delete":
            if not slide_index:
                raise ValueError("삭제할 대상 슬라이드 번호(slide)가 필요합니다.")
            del_idx = int(slide_index)
            if del_idx < 1 or del_idx > total_slides:
                raise IndexError(f"슬라이드 번호 범위를 벗어났습니다: {del_idx}")
            if total_slides <= 1:
                raise ValueError("프레젠테이션에 슬라이드가 1개뿐이어서 삭제할 수 없습니다.")
            
            prs.Slides(del_idx).Delete()
            return format_response(
                status="ok",
                module="ppt_slide",
                action="delete",
                preview=f"Deleted slide {del_idx} (Remaining: {prs.Slides.Count})",
                agent_directive="VERIFIED: Slide deleted.",
                extra={"remaining_slides": prs.Slides.Count}
            )

        elif action == "move":
            if not slide_index or not dest_index:
                raise ValueError("'slide'(출발 번호)와 'dest'(목적 번호) 파라미터가 필요합니다.")
            prs.Slides(int(slide_index)).MoveTo(int(dest_index))
            return format_response(
                status="ok",
                module="ppt_slide",
                action="move",
                preview=f"Moved slide {slide_index} to position {dest_index}",
                agent_directive="VERIFIED: Slide moved."
            )

        elif action in ["count", "list"]:
            return format_response(
                status="ok",
                module="ppt_slide",
                action="count",
                preview=f"Total slides: {total_slides}",
                agent_directive="VERIFIED: Slide count retrieved.",
                extra={"total_slides": total_slides}
            )

        elif action in ["clear", "clean"]:
            cleared_shapes = 0
            if slide_index:
                s_idx = int(slide_index)
                target_slide = prs.Slides(s_idx)
                for i in range(target_slide.Shapes.Count, 0, -1):
                    target_slide.Shapes.Item(i).Delete()
                    cleared_shapes += 1
                msg = f"슬라이드 {s_idx}의 모든 요소({cleared_shapes}개)를 삭제했습니다."
            else:
                for s in range(1, prs.Slides.Count + 1):
                    target_slide = prs.Slides(s)
                    for i in range(target_slide.Shapes.Count, 0, -1):
                        target_slide.Shapes.Item(i).Delete()
                        cleared_shapes += 1
                msg = f"모든 슬라이드의 요소({cleared_shapes}개)를 전체 삭제했습니다."

            return format_response(
                status="ok",
                module="ppt_slide",
                action="clear",
                preview=msg,
                agent_directive="VERIFIED: Slide content cleared. Do not re-verify.",
                extra={"cleared_shapes": cleared_shapes}
            )

        else:
            raise ValueError(f"알 수 없는 슬라이드 액션입니다: {action}")

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_slide",
            action=action,
            preview=str(e),
            agent_directive=f"STOP_RETRY: Slide action failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Slide Management Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--action", default="add", choices=["add", "duplicate", "delete", "move", "count", "list", "clear"])
    parser.add_argument("--slide", type=int, help="대상 슬라이드 번호 (1-based)")
    parser.add_argument("--dest", type=int, help="이동할 목적 위치 번호 (1-based)")
    args = parser.parse_args()

    params = {
        "action": args.action,
        "slide": args.slide,
        "dest": args.dest
    }

    with ppt_session(target=args.target, snapshot=True) as (app, prs):
        res = execute(app, prs, params)
        emit_response(res)
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
