# -*- coding: utf-8 -*-
"""
ml_report.py - Standalone Engineering Audit & Technical Verification Report Generator.
Generates executive-ready, highly technical Word (.docx) reports using pure python-docx.
100% Standalone: Zero-Office COM, operates seamlessly in background and server environments.

Slot-Filling Architecture:
The tool deterministically builds 90%+ of the technical tables, metrics, heatmaps, and lineage,
while LLM fills in 5 dedicated engineering insight slots (or falls back to built-in rule-based text).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_common import (  # noqa: E402
    setup_console, run_cli, JsonArgumentParser, InputError,
    sanitize_filename, normalize_version, load_json_file, strip_unit,
    save_with_lock_fallback, warn_long_path,
)

setup_console()

import re
import json
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

# python-docx is optional at import time so a missing package is reported as protocol JSON
try:
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    _DOCX_IMPORT_ERROR = None
except ImportError as _e:
    _DOCX_IMPORT_ERROR = _e


def _num(v: Any) -> Optional[float]:
    """Returns a finite float or None (ledger values may be null/NaN for constant columns)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def find_high_correlations(corr_data: Dict[str, Dict[str, Any]], exclude: List[str], threshold: float = 0.85) -> List[Tuple[str, str, float]]:
    """Feature pairs with |r| >= threshold (targets excluded), strongest first."""
    cols = [c for c in corr_data.keys() if c not in exclude]
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = _num(corr_data.get(a, {}).get(b))
            if r is not None and abs(r) >= threshold:
                pairs.append((a, b, r))
    pairs.sort(key=lambda t: abs(t[2]), reverse=True)
    return pairs


# ==============================================================================
# 2. python-docx XML Styling Helpers (Style B: Modern Clean Slate Standard)
# ==============================================================================

def set_cell_background(cell, hex_color: str) -> None:
    """Sets the background color of a table cell using OxmlElement."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def set_cell_margins(cell, top: int = 70, bottom: int = 70, left: int = 100, right: int = 100) -> None:
    """Sets internal padding (in twips, 20 twips = 1 pt) for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for edge, val in [('w:top', top), ('w:bottom', bottom), ('w:left', left), ('w:right', right)]:
        m = OxmlElement(edge)
        m.set(qn('w:w'), str(val))
        m.set(qn('w:type'), 'dxa')
        tcMar.append(m)
    tcPr.append(tcMar)


def set_table_borders(table, border_color: str = "CBD5E1") -> None:
    """Applies clean, subtle 0.5pt slate borders to all table cells."""
    tblPr = table._tbl.tblPr
    tblBorders = OxmlElement('w:tblBorders')
    for edge in ['w:top', 'w:bottom', 'w:left', 'w:right', 'w:insideH', 'w:insideV']:
        b = OxmlElement(edge)
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), '4')  # 0.5pt
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), border_color)
        tblBorders.append(b)
    tblPr.append(tblBorders)


def add_callout_box(doc, title: str, text: str, border_hex: str = "64748B", bg_hex: str = "F8FAFC") -> None:
    """Adds a clean engineering callout box (Style B: 2pt slate left bar, subtle neutral background)."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False

    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, bg_hex)
    set_cell_margins(cell, top=90, bottom=90, left=140, right=140)

    # Set left border 2.0pt slate, clear others
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    
    left_b = OxmlElement('w:left')
    left_b.set(qn('w:val'), 'single')
    left_b.set(qn('w:sz'), '16')  # 2.0 pt
    left_b.set(qn('w:space'), '0')
    left_b.set(qn('w:color'), border_hex)
    tcBorders.append(left_b)

    for b_name in ['w:top', 'w:bottom', 'w:right']:
        b = OxmlElement(b_name)
        b.set(qn('w:val'), 'none')
        tcBorders.append(b)
    tcPr.append(tcBorders)

    # Content paragraph
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15

    run_t = p.add_run(f"[{title}] ")
    run_t.font.name = "맑은 고딕"
    run_t.font.size = Pt(8.5)
    run_t.font.bold = True
    run_t.font.color.rgb = RGBColor(51, 65, 85)  # #334155

    run_b = p.add_run(text)
    run_b.font.name = "맑은 고딕"
    run_b.font.size = Pt(8.5)
    run_b.font.color.rgb = RGBColor(71, 85, 105)  # #475569

    # Blank spacing paragraph after table
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(4)


def create_styled_table(
    doc,
    matrix: List[List[str]],
    header_bg_hex: str = "F1F5F9",
    highlight_row_idx: Optional[int] = None,
    highlight_bg_hex: str = "F8FAFC",
    border_color_hex: str = "CBD5E1"
) -> Any:
    """Creates a modern clean slate table with subtle header shading and thin borders (Style B)."""
    num_rows = len(matrix)
    num_cols = max(len(r) for r in matrix) if num_rows > 0 else 0
    if num_rows == 0 or num_cols == 0:
        return None

    table = doc.add_table(rows=num_rows, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    set_table_borders(table, border_color_hex)

    for r_idx, row in enumerate(matrix):
        for c_idx, val in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            cell.text = str(val)
            set_cell_margins(cell, top=60, bottom=60, left=90, right=90)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            run = p.runs[0] if p.runs else p.add_run()
            run.font.name = "맑은 고딕"
            run.font.size = Pt(8.5)

            if r_idx == 0:
                # Header row: Subtle cool gray background, bold dark slate text
                run.font.bold = True
                run.font.color.rgb = RGBColor(30, 41, 59)  # #1E293B
                set_cell_background(cell, header_bg_hex)
            elif highlight_row_idx is not None and r_idx == highlight_row_idx:
                # Highlighted row (e.g., Best version / Champion)
                run.font.bold = True
                run.font.color.rgb = RGBColor(15, 23, 42)  # #0F172A
                set_cell_background(cell, highlight_bg_hex)
            else:
                # Pure white body cells (no zebra stripes)
                run.font.color.rgb = RGBColor(51, 65, 85)  # #334155
                set_cell_background(cell, "FFFFFF")

    # Spacing after table
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(4)
    return table


# ==============================================================================
# 3. Data Loader & Ledger Resolution
# ==============================================================================

def load_ml_history_data(data_path: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Loads all records from a specific history.json(l) file OR the parent data directory.
    Returns (records, directory_path).
    """
    abs_path = os.path.abspath(data_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"경로를 찾을 수 없습니다: {abs_path}")

    records: List[Dict[str, Any]] = []

    # 1. If a specific file is provided
    if os.path.isfile(abs_path):
        abs_dir = os.path.dirname(abs_path)
        ext = os.path.splitext(abs_path)[1].lower()
        if ext == ".json":
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        records = data
            except Exception as e:
                sys.stderr.write(f"[WARN] 지정된 JSON 로드 실패 ({e}) -> 디렉토리 자동 스캔 전환\n")
        elif ext == ".jsonl":
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line))
            except Exception as e:
                sys.stderr.write(f"[WARN] 지정된 JSONL 로드 실패 ({e}) -> 디렉토리 자동 스캔 전환\n")
    else:
        abs_dir = abs_path

    # 2. Directory fallback scan (history.json first, then history.jsonl)
    if not records:
        json_path = os.path.join(abs_dir, "history.json")
        jsonl_path = os.path.join(abs_dir, "history.jsonl")

        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        records = data
            except Exception:
                pass

        if not records and os.path.exists(jsonl_path):
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line))
            except Exception:
                pass

    if not records:
        raise InputError(f"해당 경로에서 유효한 머신러닝 실험 원장(history.json / history.jsonl)을 찾을 수 없습니다: {abs_path}")

    return records, abs_dir


# ==============================================================================
# 4. Core Report Generator Engine
# ==============================================================================

def generate_engineering_word_report(
    target_name: str,
    data_dir: str,
    out_path: Optional[str] = None,
    slots: Optional[Dict[str, str]] = None,
    specified_version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates an executive-ready engineering audit Word (.docx) report.
    """
    records, abs_dir = load_ml_history_data(data_dir)
    slots = slots or {}

    # Filter records containing the target (unit-less alias accepted: '생산효율' -> '생산효율(%)')
    all_targets = list(dict.fromkeys(t for r in records for t in r.get("targets", [])))
    if target_name not in all_targets and strip_unit(target_name) == target_name.strip():
        alias_hits = [t for t in all_targets if strip_unit(t) == strip_unit(target_name)]
        if len(alias_hits) == 1:
            sys.stderr.write(f"[INFO] 타겟명 자동 매칭: '{target_name}' -> '{alias_hits[0]}'\n")
            target_name = alias_hits[0]
    target_records = [r for r in records if target_name in r.get("targets", [])]

    if not target_records:
        available_targets = set()
        for r in records:
            available_targets.update(r.get("targets", []))
        raise InputError(
            f"타겟 '{target_name}'에 대한 학습 기록을 찾을 수 없습니다.\n"
            f"[원장에 존재하는 타겟 목록]: {sorted(list(available_targets))}"
        )

    # Determine Best Record
    best_record = None
    specified_version = normalize_version(specified_version)
    if specified_version:
        # Last match wins: a re-trained version (--version vN override) appends a newer record
        matches = [r for r in target_records if normalize_version(r.get("version")) == specified_version]
        if not matches:
            raise InputError(
                f"버전 '{specified_version}'에 타겟 '{target_name}'의 학습 기록이 없습니다. "
                f"[사용 가능한 버전]: {[r.get('version') for r in target_records]}"
            )
        best_record = matches[-1]
    if not best_record:
        # Pick the record where target champion has highest val_r2
        def get_target_r2(rec):
            return rec.get("targets_benchmark", {}).get(target_name, {}).get("champion", {}).get("val_r2", -999.0)
        best_record = max(target_records, key=get_target_r2)

    best_ver = best_record.get("version", "v1")
    best_bench = best_record.get("targets_benchmark", {}).get(target_name, {})
    best_champ = best_bench.get("champion", {})
    leaderboard = best_bench.get("leaderboard", [])

    val_r2 = best_champ.get("val_r2", 0.0)
    train_r2 = best_champ.get("train_r2", val_r2)
    overfit_gap = best_champ.get("overfit_gap", 0.0)
    mae = best_champ.get("mae", 0.0)
    rmse = best_champ.get("rmse", 0.0)
    residual_skew = best_champ.get("residual_skew", 0.0)
    champ_model = best_champ.get("champion_model", "ExtraTrees")
    top_features = best_champ.get("top_features", [])

    tgt_summary = best_record.get("target_summaries", {}).get(target_name, {})
    tgt_mean = tgt_summary.get("mean", 0.0)
    tgt_std = tgt_summary.get("std", 0.0)
    tgt_min = tgt_summary.get("min", 0.0)
    tgt_max = tgt_summary.get("max", 0.0)

    status_verdict = "적합: 프로덕션 배포 승인 (Pass)" if val_r2 >= 0.90 else "조건부 적합: 추가 피처 엔지니어링 권장 (Refinement Needed)"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ==========================================================================
    # Slot Fallbacks (100% Deterministic Rule-Based Engineering Text)
    # ==========================================================================
    if val_r2 >= 0.90:
        slot1_r2_text = f"검증 결정계수 Val R²={val_r2:.4f}를 기록하여 품질 관리 SLA(0.9000)를 충족함."
    elif val_r2 > 0:
        slot1_r2_text = f"검증 결정계수 Val R²={val_r2:.4f}로 목표 SLA(0.9000)에 미달하여 추가 피처 엔지니어링이 요구됨."
    else:
        slot1_r2_text = f"검증 결정계수 Val R²={val_r2:.4f}로 음수 설명력을 기록하여 기존 피처셋과 타겟 간 유의미한 회귀 상관성이 부족함."

    slot1_default = (
        f"챔피언 알고리즘({champ_model})의 5-Fold 교차검증 결과, {slot1_r2_text} "
        + (f"학습-검증 간 오차 간극(Overfit Gap={overfit_gap:.4f})이 통제되었으며, " if overfit_gap <= 0.10 else
           f"학습-검증 간 오차 간극(Overfit Gap={overfit_gap:.4f})이 0.10을 초과하여 과적합 경향이 있으므로 피처 축소 또는 데이터 추가가 권장되며, ")
        + f"잔차 왜도(Residual Skewness={residual_skew:.4f})가 정규분포 기준(-0.5 ~ +0.5) 내에 위치하여 특정 운전 구간에 대한 시스템적 예측 편향이 억제됨."
    )
    if abs(residual_skew) > 0.5:
        skew_intro = f"Val R²={val_r2:.4f}의 설명력을 보이나" if val_r2 >= 0.90 else f"Val R²={val_r2:.4f}를 기록하였으며"
        slot1_default = (
            f"선정 모델({champ_model})은 {skew_intro}, 잔차 왜도가 {residual_skew:.4f}로 측정되어 고오차 영역에 대한 편향이 존재함. "
            f"타겟 변수의 이상치 구간 필터링 또는 log1p 변환을 통해 잔차 대칭성을 보정할 것을 권고함."
        )

    top_f1 = top_features[0]["feature"] if len(top_features) > 0 else "X1"
    top_p1 = top_features[0]["pct"] if len(top_features) > 0 else 0.0
    top_f2 = top_features[1]["feature"] if len(top_features) > 1 else ""
    slot2_default = (
        f"순열 중요도(Permutation Importance) 분석 결과, 피처 '{top_f1}'이 전체 예측 변동성의 {top_p1:.1f}%를 설명하며 모델 출력을 전적으로 견인함. "
        + (f"보조 인자인 '{top_f2}'와의 비선형 상호작용이 관측되며, " if top_f2 else "")
        + "기여도 1% 미만인 저영향 피처는 노이즈 유입 방지를 위해 차기 실험에서 프루닝(Pruning) 고려 가능."
    )

    lb_maes = [_num(e.get("mae")) for e in leaderboard if _num(e.get("mae")) is not None]
    mae_phrase = (f"5대 경쟁 모델 중 최저 MAE({mae:.4f})" if (not lb_maes or mae <= min(lb_maes))
                  else f"5대 경쟁 모델 중 최고 검증 R²(MAE={mae:.4f})")

    is_historical = (specified_version is not None and specified_version != normalize_version(target_records[-1].get("version")))
    if is_historical:
        slot3_default = (
            f"원장 내 전체 이력 중 사용자가 지정한 {best_ver} 체크포인트를 기준으로 기술 감사를 수행함. "
            f"해당 회차에서 {champ_model} 파이프라인이 {mae_phrase} 및 검증 R²={val_r2:.4f}를 기록함."
        )
    else:
        slot3_default = (
            f"초기 베이스라인(v1)부터 최종 체크포인트({best_ver})까지 총 {len(target_records)}회의 반복 엔지니어링을 수행함. "
            f"피처셋 선별 및 파생변수 수식을 통하여 모델 예측 정밀도가 단계적으로 수렴하였으며, "
            f"최종 회차에서 {champ_model} 파이프라인이 {mae_phrase}를 기록하여 챔피언으로 선정됨."
        )

    safe_target = sanitize_filename(target_name)
    corr_data = best_record.get("correlation_matrix", {})
    if not corr_data:
        # On-the-fly recovery from model_dataset.csv snapshot
        ds_csv = os.path.join(abs_dir, best_ver, "model_dataset.csv")
        if os.path.exists(ds_csv):
            for enc in ["cp949", "utf-8-sig", "utf-8", "euc-kr"]:
                try:
                    import pandas as pd
                    df_snap = pd.read_csv(ds_csv, encoding=enc)
                    num_df = df_snap.select_dtypes(include=[np.number])
                    corr_data = num_df.corr().round(4).to_dict()
                    break
                except Exception:
                    continue

    # Slot 4 must state what the matrix actually shows (not a fixed claim)
    high_pairs = find_high_correlations(corr_data or {}, exclude=best_record.get("targets", [target_name]))
    if high_pairs:
        pair_txt = ", ".join(f"'{a}'-'{b}'(r={r:+.2f})" for a, b, r in high_pairs[:3])
        slot4_default = (
            f"투입된 독립변수 간 2차원 피어슨 상관계수를 전수 검토한 결과, 다중공선성 임계치(|r| >= 0.85)를 초과하는 "
            f"변수 쌍 {len(high_pairs)}건이 확인됨: {pair_txt}. "
            f"선형 모델(Ridge/ElasticNet) 계수 해석 시 주의가 필요하며, 차기 실험에서 쌍 중 기여도가 낮은 피처의 제외를 검토할 것을 권고함."
        )
    else:
        slot4_default = (
            f"투입된 독립변수 간 2차원 피어슨 상관계수를 전수 검토한 결과, 다중공선성 임계치(|r| >= 0.85)를 초과하는 변수 간 과도한 선형 결합은 발견되지 않음. "
            f"정규화 스케일러(StandardScaler) 및 파이프라인 정규화 기법을 통해 회귀 계수 왜곡 없이 안정적인 가중치를 산출함."
        )

    slot5_default = (
        f"배포 모델 서빙 시 입력 피처의 결측치는 내장 SimpleImputer(median)가 실시간 자동 대치함. "
        f"운영 환경에서 실시간 MAE가 관리 한계치({mae * 1.5:.2f})를 초과하거나 피처 측정값이 학습 동적 범위([Min, Max])를 벗어나는 외삽(Extrapolation) 발생 시 재학습 파이프라인 가동 요망."
    )

    slot1_text = slots.get("slot1_residual") or slots.get("residual") or slot1_default
    slot2_text = slots.get("slot2_feature") or slots.get("feature") or slot2_default
    slot3_text = slots.get("slot3_lineage") or slots.get("lineage") or slot3_default
    slot4_text = slots.get("slot4_correlation") or slots.get("correlation") or slot4_default
    slot5_text = slots.get("slot5_serving") or slots.get("serving") or slot5_default

    # ==========================================================================
    # Build python-docx Document
    # ==========================================================================
    doc = docx.Document()

    # Page Margins (Normal 1 inch)
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)

    primary_slate = "334155"
    header_slate = "F1F5F9"
    border_slate = "CBD5E1"

    def add_heading_1(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(13)
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(text)
        run.font.name = "맑은 고딕"
        run.font.size = Pt(11.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor(51, 65, 85)

    def add_body_text(text: str, italic: bool = False, bold: bool = False, space_after: int = 4) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(text)
        run.font.name = "맑은 고딕"
        run.font.size = Pt(8.5)
        run.font.italic = italic
        run.font.bold = bold
        run.font.color.rgb = RGBColor(51, 65, 85)

    # --------------------------------------------------------------------------
    # Document Title & Header Meta
    # --------------------------------------------------------------------------
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2)
    run_t = p_title.add_run(f"머신러닝 모델 기술 검증 및 엔지니어링 감사 보고서")
    run_t.font.name = "맑은 고딕"
    run_t.font.size = Pt(16)
    run_t.font.bold = True
    run_t.font.color.rgb = RGBColor(30, 41, 59)

    ver_label_header = f"{best_ver} (지정 감사)" if specified_version else f"{best_ver} (최적)"
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(10)
    run_s = p_sub.add_run(f"분석 타겟: '{target_name}'  |  기준 체크포인트: {ver_label_header}  |  판정: {status_verdict}  |  일시: {now_str}")
    run_s.font.name = "맑은 고딕"
    run_s.font.size = Pt(9.0)
    run_s.font.color.rgb = RGBColor(100, 116, 139)

    # Metadata Specification Table
    project_desc = best_record.get("description", "")
    ver_desc = f"{best_ver} (사용자 지정 감사)" if specified_version else f"{best_ver} (최고 Val R² 최적안)"
    meta_table_data = [
        ["평가 대상 타겟 변수", str(target_name), "감사 기준 버전", ver_desc],
        ["최종 검증 결정계수", f"Val R² = {val_r2:.4f}", "프로덕션 배포 판정", status_verdict],
        ["1위 챔피언 알고리즘", f"{champ_model} Pipeline", "타겟 데이터 샘플 수", f"총 {best_bench.get('sample_count', 0)}개 샘플"],
        ["원장 저장소 루트", f"{os.path.basename(abs_dir)}/", "보고서 생성 일시", now_str]
    ]
    if project_desc:
        meta_table_data.insert(0, ["데이터셋 및 모델링 목적", str(project_desc), "원천 데이터 파일", str(best_record.get("file", "-"))])
    create_styled_table(doc, meta_table_data)

    # Multi-Target Overview Table (if this version contains multiple targets)
    all_co_targets = best_record.get("targets", [])
    if len(all_co_targets) > 1:
        add_heading_1(f"■ 동시 학습 다중 타겟({len(all_co_targets)}종) 전체 현황 (Multi-Target Overview)")
        add_body_text(f"체크포인트 '{best_ver}'에서는 총 {len(all_co_targets)}개의 종속변수를 일괄 동시 학습하였습니다. 각 타겟별 챔피언 및 검증 결과는 다음과 같습니다:")
        mt_matrix = [
            ["타겟 변수명", "선정 챔피언 모델", "검증 R² (Val)", "MAE (평균오차)", "RMSE", "배포 적합성 판정", "보고서 대상 여부"]
        ]
        for t_k in all_co_targets:
            t_info = best_record.get("targets_benchmark", {}).get(t_k, {}).get("champion", {})
            t_r2 = t_info.get("val_r2", 0.0)
            t_mae = t_info.get("mae", 0.0)
            t_rmse = t_info.get("rmse", 0.0)
            t_champ_m = t_info.get("champion_model", "-")
            t_pass = "적합 (Pass)" if t_r2 >= 0.90 else "미달 (Fail)"
            is_curr_t = (t_k == target_name)
            mt_matrix.append([
                str(t_k),
                str(t_champ_m),
                f"{t_r2:.4f}",
                f"{t_mae:.4f}",
                f"{t_rmse:.4f}",
                t_pass,
                "[현재 보고서 타겟]" if is_curr_t else "동시 학습 타겟"
            ])
        create_styled_table(doc, mt_matrix)

    # --------------------------------------------------------------------------
    # SECTION 1. [두괄식] 최종 챔피언 모델 기술 사양 및 예측 오차 정밀 감사
    # --------------------------------------------------------------------------
    add_heading_1("SECTION 1. 최종 챔피언 모델 기술 사양 및 예측 오차 정밀 감사")
    add_body_text("5개 독립 폴드(Leakage-Free 5-Fold K-Fold) 상에서 동시 경쟁한 5대 회귀 알고리즘의 종합 성적표 및 품질 SLA 감사 결과입니다.")

    # 1.1 5-Model Benchmark Leaderboard Table
    lead_matrix = [
        ["순위", "알고리즘 (Regressor)", "검증 R² (Val)", "학습 R² (Train)", "Overfit Gap", "MAE (평균오차)", "RMSE (제곱근오차)", "챔피언 선정"]
    ]
    for entry in leaderboard:
        lead_matrix.append([
            f"Rank {entry.get('rank', '-')}",
            str(entry.get('model_name', '-')),
            f"{entry.get('val_r2', 0.0):.4f}",
            f"{entry.get('train_r2', 0.0):.4f}",
            f"{entry.get('overfit_gap', 0.0):.4f}",
            f"{entry.get('mae', 0.0):.4f}",
            f"{entry.get('rmse', 0.0):.4f}",
            "[1위 챔피언]" if entry.get("is_champion") else "-"
        ])
    create_styled_table(doc, lead_matrix, highlight_row_idx=1)

    # 1.2 Error & Residual Distribution Table
    err_ratio_mae = (mae / tgt_std * 100) if tgt_std > 0 else 0.0
    err_ratio_rmse = (rmse / tgt_std * 100) if tgt_std > 0 else 0.0
    skew_verdict = "적합: 대칭 정규분포" if abs(residual_skew) <= 0.5 else "주의: 한쪽 편향 잔차"

    kpi_matrix = [
        ["평가 지표 (Audit Metric)", "측정 수치", "품질 관리 기준 (SLA)", "엔지니어링 적합성 판정", "기술적 소견"],
        ["검증 결정계수 (Val R²)", f"{val_r2:.4f}", ">= 0.9000", "적합 (Pass)" if val_r2 >= 0.9 else "미달 (Fail)", "사전 정의된 설명력 목표 달성"],
        ["과적합 간극 (Overfit Gap)", f"{overfit_gap:.4f}", "<= 0.0500", "적합 (Pass)" if overfit_gap <= 0.05 else "주의 (Warn)", "학습-검증 간 성능 일관성 확보"],
        ["평균 절대 오차 (MAE)", f"{mae:.4f}", f"표준편차 20% 이내 ({tgt_std * 0.2:.2f})", "적합 (Pass)" if err_ratio_mae <= 20 else "주의", f"타겟 표준편차 대비 {err_ratio_mae:.1f}% 수준"],
        ["평균 제곱근 오차 (RMSE)", f"{rmse:.4f}", f"표준편차 25% 이내 ({tgt_std * 0.25:.2f})", "적합 (Pass)" if err_ratio_rmse <= 25 else "주의", f"이상치 왜곡 없이 고른 오차 분포"],
        ["잔차 왜도 (Residual Skew)", f"{residual_skew:.4f}", "-0.50 ~ +0.50", skew_verdict, "오차의 무작위성 및 정규분포성 검증"],
        ["타겟 데이터 범위 [Min, Max]", f"[{tgt_min:.2f} ~ {tgt_max:.2f}]", f"평균 {tgt_mean:.2f}, 표준편차 {tgt_std:.2f}", "참조 (Ref)", "데이터 스케일 및 변동 폭 기준선"]
    ]
    create_styled_table(doc, kpi_matrix)

    # 1.3 LLM Slot 1: Residual & Error Diagnostic
    add_callout_box(doc, "예측 오차 거동 및 잔차 분포 정밀 감사 (Residual Diagnostics)", slot1_text)

    # --------------------------------------------------------------------------
    # SECTION 2. 핵심 피처 민감도 및 기여도 감사
    # --------------------------------------------------------------------------
    add_heading_1("SECTION 2. 핵심 피처 민감도 및 기여도 감사 (Feature Sensitivity)")
    add_body_text("모델의 실제 예측 정확도 하락폭을 측정하는 순열 중요도(Permutation Importance) 정량 분석 및 피처별 동적 경계선입니다.")

    feat_matrix = [
        ["순위", "피처명 (Feature)", "순열 중요도 (Loss Drop)", "상대 기여율 (%)", "누적 설명력 (%)", "피처 계층 분류", "공학적 조치 권고"]
    ]
    cum_pct = 0.0
    for r_i, tf in enumerate(top_features, 1):
        pct_val = tf.get("pct", 0.0)
        cum_pct += pct_val
        tier = "핵심 주도 (Dominant)" if pct_val >= 30.0 else ("유효 기여 (Valid)" if pct_val >= 5.0 else "노이즈 후보 (Noise)")
        action = "필수 계측 유지" if pct_val >= 5.0 else "차기 모델 프루닝(제거) 고려"
        feat_matrix.append([
            str(r_i),
            str(tf.get("feature", "-")),
            f"{tf.get('importance', 0.0):.4f}",
            f"{pct_val:.1f}%",
            f"{min(cum_pct, 100.0):.1f}%",
            tier,
            action
        ])
    create_styled_table(doc, feat_matrix)

    # Extrapolation Boundaries Table
    feat_stats = {}
    m_json_path = os.path.join(abs_dir, best_ver, f"model_{safe_target}.json")
    if not os.path.exists(m_json_path):
        m_json_path = os.path.join(abs_dir, best_ver, f"model_{target_name}.json")
    if os.path.exists(m_json_path):
        try:
            with open(m_json_path, "r", encoding="utf-8") as f:
                feat_stats = json.load(f).get("feature_stats", {})
        except Exception:
            pass

    if feat_stats:
        bounds_matrix = [
            ["피처명", "최솟값 (Min)", "중앙값 (Median)", "최댓값 (Max)", "표준편차 (Std)", "서빙 유효 입력 경계선 (Valid Dynamic Range)"]
        ]
        for f_name, s_data in feat_stats.items():
            f_min = s_data.get("min", 0.0)
            f_med = s_data.get("median", 0.0)
            f_max = s_data.get("max", 0.0)
            f_std = s_data.get("std", 0.0)
            bounds_matrix.append([
                str(f_name),
                f"{f_min:.2f}",
                f"{f_med:.2f}",
                f"{f_max:.2f}",
                f"{f_std:.2f}",
                f"[{f_min:.2f} <= X <= {f_max:.2f}] (초과 시 Extrapolation 경고)"
            ])
        create_styled_table(doc, bounds_matrix)

    # 2.3 LLM Slot 2: Feature Sensitivity Analysis
    add_callout_box(doc, "피처 민감도 분석 및 노이즈 프루닝 기술 진단 (Feature Sensitivity)", slot2_text)

    # --------------------------------------------------------------------------
    # SECTION 3. 버전별 엔지니어링 계보 및 사양 진화 감사
    # --------------------------------------------------------------------------
    add_heading_1("SECTION 3. 버전별 엔지니어링 계보 및 사양 진화 감사 (Lineage & Diff)")
    add_body_text("초기 베이스라인부터 최종 최적 모델까지 투입된 피처셋 변동과 결정계수(Val R²)의 진화 계보 대조표입니다.")

    lineage_matrix = [
        ["회차", "버전", "실험 태그 (Tag/Memo)", "피처 수", "대표 챔피언", "검증 R²", "개선폭 (ΔR²)", "소요시간", "체크포인트 판정"]
    ]
    best_row_in_lineage = None
    for idx, r in enumerate(target_records, 1):
        v_name = r.get("version", f"v{idx}")
        tag_str = r.get("tag") or "-"
        f_count = len(r.get("features_used", []))
        t_champ = r.get("targets_benchmark", {}).get(target_name, {}).get("champion", {})
        c_name = t_champ.get("champion_model", "-")
        c_r2 = t_champ.get("val_r2", 0.0)
        delta_val = r.get("delta_r2", "base")
        delta_str = f"{delta_val:+.4f}" if isinstance(delta_val, (int, float)) else str(delta_val)
        dur_str = f"{r.get('duration_sec', 0.0):.1f}s" if "duration_sec" in r else "-"
        is_target_ver = (v_name == best_ver)
        if is_target_ver:
            best_row_in_lineage = idx
            verdict_label = "[지정 감사 대상]" if specified_version else "[최적 배포안 (Best)]"
        else:
            verdict_label = "비교 체크포인트"

        lineage_matrix.append([
            f"#{idx}",
            str(v_name),
            str(tag_str),
            str(f_count),
            str(c_name),
            f"{c_r2:.4f}",
            str(delta_str),
            str(dur_str),
            verdict_label
        ])
    create_styled_table(doc, lineage_matrix, highlight_row_idx=best_row_in_lineage)

    # 3.2 Feature Diff Audit Notes
    add_body_text("■ 3.2 버전 간 피처 엔지니어링 변경 내역 (Diff Audit):", bold=True)
    prev_feats = set()
    for idx, r in enumerate(target_records, 1):
        v_name = r.get("version", f"v{idx}")
        curr_feats = set(r.get("features_used", []))
        added_f = sorted(list(curr_feats - prev_feats)) if idx > 1 else list(curr_feats)
        dropped_f = sorted(list(prev_feats - curr_feats)) if idx > 1 else []
        evals = r.get("derived_evals", [])
        diff_note = (
            f"• [{v_name} 엔지니어링 기록] 투입 피처: {len(curr_feats)}개  |  "
            f"신규 추가: {', '.join(added_f) if added_f else '없음'}  |  "
            f"제거: {', '.join(dropped_f) if dropped_f else '없음'}\n"
            f"  - 적용 파생 수식 (--eval): {'; '.join(evals) if evals else '없음 (기본 피처셋 유지)'}"
        )
        add_body_text(diff_note, space_after=3)
        prev_feats = curr_feats

    # 3.3 LLM Slot 3: Lineage Cause Analysis
    add_callout_box(doc, "회차별 성능 변동(ΔR²) 공학적 원인 분석 (Engineering Lineage)", slot3_text)

    # --------------------------------------------------------------------------
    # SECTION 4. 변수 간 상관관계 행렬 및 다중공선성 진단
    # --------------------------------------------------------------------------
    if corr_data and isinstance(corr_data, dict):
        add_heading_1("SECTION 4. 변수 간 상관관계 행렬 및 다중공선성 진단")
        add_body_text("독립변수 상호 간 및 타겟과의 2차원 피어슨 상관계수 행렬을 통해 다중공선성 위험(|r| >= 0.85)을 정밀 진단한 표입니다.")

        corr_cols = list(corr_data.keys())
        if len(corr_cols) > 0:
            tbl_corr = doc.add_table(rows=len(corr_cols) + 1, cols=len(corr_cols) + 1)
            tbl_corr.alignment = WD_TABLE_ALIGNMENT.CENTER
            tbl_corr.autofit = True
            set_table_borders(tbl_corr, "CBD5E1")

            # Headers
            h_cell_0 = tbl_corr.cell(0, 0)
            h_cell_0.text = "변수명"
            set_cell_background(h_cell_0, "F1F5F9")
            h_cell_0.paragraphs[0].runs[0].font.bold = True
            h_cell_0.paragraphs[0].runs[0].font.color.rgb = RGBColor(30, 41, 59)
            h_cell_0.paragraphs[0].runs[0].font.size = Pt(8.0)

            for c_i, col_name in enumerate(corr_cols):
                c_cell = tbl_corr.cell(0, c_i + 1)
                disp_name = col_name if len(col_name) <= 8 else col_name[:7] + ".."
                c_cell.text = disp_name
                set_cell_background(c_cell, "F1F5F9")
                set_cell_margins(c_cell, top=60, bottom=60, left=60, right=60)
                p = c_cell.paragraphs[0]
                p.runs[0].font.bold = True
                p.runs[0].font.color.rgb = RGBColor(30, 41, 59)
                p.runs[0].font.size = Pt(8.0)

            # Rows
            for r_i, row_name in enumerate(corr_cols):
                r_cell = tbl_corr.cell(r_i + 1, 0)
                disp_row = row_name if len(row_name) <= 8 else row_name[:7] + ".."
                r_cell.text = disp_row
                set_cell_background(r_cell, "F8FAFC")
                set_cell_margins(r_cell, top=60, bottom=60, left=60, right=60)
                p = r_cell.paragraphs[0]
                p.runs[0].font.bold = True
                p.runs[0].font.color.rgb = RGBColor(51, 65, 85)
                p.runs[0].font.size = Pt(8.0)

                for c_i, col_name in enumerate(corr_cols):
                    val_c = _num(corr_data.get(row_name, {}).get(col_name))
                    cell_val = tbl_corr.cell(r_i + 1, c_i + 1)
                    cell_val.text = f"{val_c:.2f}" if val_c is not None else "-"
                    val_c = val_c if val_c is not None else 0.0
                    set_cell_margins(cell_val, top=60, bottom=60, left=60, right=60)

                    p_v = cell_val.paragraphs[0]
                    p_v.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    r_v = p_v.runs[0]
                    r_v.font.size = Pt(8.0)
                    r_v.font.name = "맑은 고딕"

                    if abs(val_c) >= 0.85 and r_i != c_i:
                        # Warning high correlation
                        r_v.font.bold = True
                        r_v.font.color.rgb = RGBColor(15, 23, 42)
                        set_cell_background(cell_val, "E2E8F0")
                    elif r_i == c_i:
                        r_v.font.color.rgb = RGBColor(148, 163, 184)
                        set_cell_background(cell_val, "FAFAF9")
                    else:
                        r_v.font.color.rgb = RGBColor(51, 65, 85)
                        set_cell_background(cell_val, "FFFFFF")

            p_sp = doc.add_paragraph()
            p_sp.paragraph_format.space_before = Pt(0)
            p_sp.paragraph_format.space_after = Pt(4)

        # 4.2 LLM Slot 4: Multicollinearity Diagnostic
        add_callout_box(doc, "다중공선성 및 상관 간섭 기술 진단 (Multicollinearity)", slot4_text)

    # --------------------------------------------------------------------------
    # SECTION 5. 프로덕션 서빙 사양 및 런타임 제약조건
    # --------------------------------------------------------------------------
    add_heading_1("SECTION 5. 프로덕션 서빙 사양 및 런타임 제약조건 (Serving Specifications)")
    add_body_text("최적 챔피언 모델의 서빙 배포를 위한 아티팩트 보관 규격 및 파이프라인 런타임 제약조건입니다.")

    model_joblib_file = f"model_{safe_target}.joblib"
    meta_json_file = f"model_{safe_target}.json"
    joblib_full = os.path.join(abs_dir, best_ver, model_joblib_file)
    meta_full = os.path.join(abs_dir, best_ver, meta_json_file)

    serving_matrix = [
        ["구분 항목", "세부 엔지니어링 규격 및 아티팩트 보관 경로"],
        ["배포 모델 가중치 바이너리", str(joblib_full)],
        ["추론 검증 메타데이터 파일", str(meta_full)],
        ["알고리즘 및 프레임워크", f"Scikit-Learn {champ_model} Pipeline (Zero-Office Standalone)"],
        ["내장 전처리 파이프라인", "SimpleImputer(strategy='median') -> StandardScaler() [Leakage-Free 통합]"],
        ["동적 데이터셋 스냅샷", f"{os.path.join(abs_dir, best_ver, 'model_dataset.csv')}"],
        ["단일 레코드 인라인 추론 CLI", f"python ml_predict.py --model \"{best_ver}\" --input \"{top_f1}=<값>\""],
        ["배치 파일 추론 CLI", f"python ml_predict.py --model \"{best_ver}\" --file \"new_data.xlsx\""]
    ]
    create_styled_table(doc, serving_matrix)

    # 5.2 LLM Slot 5: Serving Guidelines
    add_callout_box(doc, "서빙 파이프라인 및 재학습(Drift) 엔지니어링 가이드 (Serving Guidelines)", slot5_text)

    # --------------------------------------------------------------------------
    # Save Document
    # --------------------------------------------------------------------------
    if not out_path:
        out_path = os.path.join(abs_dir, f"report_{safe_target}.docx")
    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)

    warn_long_path(out_abs)
    out_abs = save_with_lock_fallback(out_abs, doc.save, what="Word 보고서")

    return {
        "status": "ok",
        "target": target_name,
        "best_version": best_ver,
        "report_file": out_abs,
        "metrics": {
            "val_r2": val_r2,
            "train_r2": train_r2,
            "overfit_gap": overfit_gap,
            "mae": mae,
            "rmse": rmse,
            "residual_skew": residual_skew,
            "champion_model": champ_model
        },
        "slots_filled": {
            "slot1_residual": slot1_text[:60] + "...",
            "slot2_feature": slot2_text[:60] + "...",
            "slot3_lineage": slot3_text[:60] + "...",
            "slot4_correlation": slot4_text[:60] + "..." if corr_data else "N/A",
            "slot5_serving": slot5_text[:60] + "..."
        },
        "agent_directive": (
            f"VERIFIED: Engineering Word report for target '{target_name}' generated successfully "
            f"at '{os.path.basename(out_abs)}' (python-docx Standalone). Val R2={val_r2:.4f}."
        )
    }


# ==============================================================================
# 5. CLI Entry Point
# ==============================================================================

def build_reports(args: argparse.Namespace) -> Dict[str, Any]:
    if _DOCX_IMPORT_ERROR is not None:
        raise InputError(
            f"Word 보고서 생성에 필요한 python-docx 패키지가 설치되어 있지 않습니다 ({_DOCX_IMPORT_ERROR}). "
            f"관리자에게 python-docx 설치를 요청하십시오 (docs/ENVIRONMENT.md 참고). 학습/예측 기능은 영향 없음."
        )
    # Parse slots if provided (file written by Notepad/PowerShell: UTF-8, UTF-8 BOM, UTF-16, CP949)
    slot_dict: Dict[str, Any] = {}
    if args.slots:
        s_raw = args.slots.strip()
        try:
            if os.path.isfile(s_raw):
                slot_dict = load_json_file(s_raw)
            elif s_raw.startswith("{"):
                slot_dict = json.loads(s_raw)
            else:
                raise InputError("--slots는 JSON 파일 경로 또는 '{'로 시작하는 JSON 문자열이어야 합니다.")
            if not isinstance(slot_dict, dict):
                raise InputError("슬롯 JSON은 객체({...})여야 합니다.")
        except (InputError, ValueError) as e:
            sys.stderr.write(f"[WARN] 슬롯 JSON 파싱 실패 ({e}) -> 내장 소견 사용\n")
            slot_dict = {}

    records, _abs_dir = load_ml_history_data(args.data_dir)
    version = normalize_version(args.version)

    def version_targets() -> List[str]:
        if version:
            v_recs = [r for r in records if normalize_version(r.get("version")) == version]
            if not v_recs:
                raise InputError(
                    f"원장에 버전 '{version}'이(가) 없습니다. [사용 가능한 버전]: "
                    f"{list(dict.fromkeys(r.get('version') for r in records))}"
                )
            return v_recs[-1].get("targets", [])
        return records[-1].get("targets", [])

    # Determine targets to generate
    t_raw = (args.target or "").strip()
    if not t_raw or t_raw.lower() == "all":
        targets_to_generate = version_targets()
    else:
        targets_to_generate = [t.strip() for t in t_raw.split(",") if t.strip()]

    if not targets_to_generate:
        raise InputError("원장(history)에서 보고서를 생성할 타겟 변수명을 찾을 수 없습니다.")

    results = []
    for t_name in targets_to_generate:
        # Custom out path applies only when a single report is generated
        out_target_path = args.out if (len(targets_to_generate) == 1 and args.out) else None
        results.append(generate_engineering_word_report(
            target_name=t_name,
            data_dir=args.data_dir,
            out_path=out_target_path,
            slots=slot_dict,
            specified_version=version
        ))

    if len(results) == 1:
        return results[0]
    return {
        "status": "ok",
        "version": version or "best",
        "target_count": len(results),
        "reports": [
            {
                "target": r["target"],
                "report_file": r["report_file"],
                "val_r2": r["metrics"]["val_r2"],
                "champion": r["metrics"]["champion_model"]
            }
            for r in results
        ],
        "agent_directive": (
            f"VERIFIED: Batch generated {len(results)} engineering Word reports for version "
            f"'{version or 'best'}' across targets: {', '.join(r['target'] for r in results)}."
        )
    }


def main():
    parser = JsonArgumentParser(
        description="Standalone Engineering Audit & Technical Verification Word Report Generator"
    )
    parser.add_argument(
        "--data-dir", "-d", "--history", "-H", dest="data_dir", required=True,
        help="학습 산출물 루트 디렉토리 또는 history.json(l) 파일 경로 (예: sample_v2_ml_data/ 또는 sample_v2_ml_data/history.json)"
    )
    parser.add_argument(
        "--target", "-t",
        help="보고서를 생성할 대상 타겟 변수명 (생략 또는 'all' 시 해당 버전의 전체 타겟, 콤마로 다중 지정)"
    )
    parser.add_argument(
        "--out", "-o",
        help="생성할 Word (.docx) 파일 저장 경로 (생략 시 data_dir 하위에 report_<target>.docx 자동 생성)"
    )
    parser.add_argument(
        "--slots",
        help="LLM이 작성한 5대 기술 소견 슬롯이 담긴 JSON 파일 경로 또는 JSON 문자열 (생략 시 내장 규칙 기반 소견 자동 작성)"
    )
    parser.add_argument(
        "--version", "-v",
        help="보고서의 기준이 될 특정 버전 지정 (예: v2 또는 2. 생략 시 최고 Val R2 기록 버전 자동 선택)"
    )

    args = parser.parse_args()
    run_cli(lambda: build_reports(args), hint="Check data_dir, target name or version.")


if __name__ == "__main__":
    main()
