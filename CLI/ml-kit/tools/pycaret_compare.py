"""pycaret_compare.py - 같은 데이터로 PyCaret 회귀 결과를 내고 ml-kit과 비교할 명령을 알려 주는 사람용 스크립트

ml-kit 도구가 아닙니다 (stdout 1줄 JSON 계약 대상 아님). PyCaret이 설치된 Python으로 실행합니다.

데이터 형식 (기본): 1행 컬럼명, 2행 단위, 3행부터 데이터. 엑셀은 첫 시트, CSV는 인코딩 자동 판별.

사용 예 (PowerShell):
    <PyCaret용 python.exe> pycaret_compare.py -f "C:\\data\\공정.xlsx" -x "반응온도,압축압력,촉매비율" -y "SPEED"
    <PyCaret용 python.exe> pycaret_compare.py -f "C:\\data\\공정.xlsx" -x "..." -y "SPEED" --transformation --normalize --tune
    <PyCaret용 python.exe> pycaret_compare.py -f "C:\\data\\공정.xlsx" --check          (PyCaret 없이 컬럼만 확인)

결과는 화면과 데이터 파일 옆의 <이름>_pycaret_<시각>.txt에 저장합니다.

비교 기준 (같은 기준끼리만 비교하세요):
    [A] ml-kit과 같은 기준: 전체 데이터 5겹 교차검증(셔플, seed 42)의 OOF R2 -> ml-kit 결과의 mean_val_score / val_r2와 비교
    [B] PyCaret 교차검증 평균: 학습용(기본 70%)의 5겹 교차검증 평균 R2 (compare_models 표)
    [C] PyCaret 홀드아웃: 학습에 쓰지 않은 나머지(기본 30%)의 R2
    학습에 쓴 데이터를 다시 예측한 R2(finalize_model 뒤 같은 데이터로 predict_model)는 부풀려지므로 비교에 쓰지 않습니다.
"""
import argparse
import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd

SEED = 42
FOLDS = 5


# ------------------------------------------------------------------ 데이터 읽기

def read_table(path: str, header_row: int, unit_row: int) -> pd.DataFrame:
    """header_row(컬럼명), unit_row(단위, 0이면 없음)를 빼고 그 아래를 데이터로 읽습니다. 행 번호는 1부터."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        raw = pd.read_excel(path, header=None, sheet_name=0, dtype=object)
    else:
        raw = None
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                raw = pd.read_csv(path, header=None, dtype=object, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            sys.exit(f"[ERROR] CSV 인코딩을 알 수 없습니다: {path}")
    names = [str(v).strip() if pd.notna(v) else f"col{i + 1}" for i, v in enumerate(raw.iloc[header_row - 1])]
    units = ([str(v).strip() if pd.notna(v) else "" for v in raw.iloc[unit_row - 1]] if unit_row else [""] * len(names))
    first = max(header_row, unit_row or 0)
    df = raw.iloc[first:].reset_index(drop=True)
    df.columns = names
    df.attrs["units"] = dict(zip(names, units))
    return df.dropna(how="all")


def pick(df: pd.DataFrame, wanted: str, kind: str) -> list:
    """쉼표로 준 이름을 컬럼으로 찾습니다 (대소문자·공백 무시, '이름(단위)'로 줘도 됨)."""
    def key(s):
        return re.sub(r"\s+", "", str(s)).lower()
    by_key = {key(c): c for c in df.columns}
    units = df.attrs.get("units", {})
    by_key.update({key(f"{c}({u})"): c for c, u in units.items() if u})
    out, missing = [], []
    for name in [w.strip() for w in wanted.split(",") if w.strip()]:
        col = by_key.get(key(name))
        (out if col else missing).append(col or name)
    if missing:
        sys.exit(f"[ERROR] {kind} 컬럼을 찾을 수 없습니다: {missing}\n사용 가능한 컬럼: {list(df.columns)}")
    return out


def to_numeric_frame(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """숫자로 바꿀 수 있는 컬럼은 숫자로 (쉼표 1,200 포함). 글자 컬럼은 그대로 두어 PyCaret이 범주형으로 처리."""
    out = df[cols].copy()
    for c in cols:
        num = pd.to_numeric(out[c].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
        if num.notna().sum() >= 0.9 * out[c].notna().sum():
            out[c] = num
    return out


# ------------------------------------------------------------------ PyCaret

def run_pycaret(data: pd.DataFrame, target: str, args, lines: list) -> None:
    try:
        from pycaret.regression import compare_models, finalize_model, predict_model, pull, setup, tune_model
    except ImportError as e:
        sys.exit(f"[ERROR] PyCaret을 불러올 수 없습니다 ({e}). PyCaret을 설치한 Python으로 실행하세요.")

    def say(text=""):
        print(text)
        lines.append(text)

    setup(data=data, target=target, train_size=args.train_size, session_id=SEED, fold=FOLDS, fold_shuffle=True,
          data_split_shuffle=True, normalize=args.normalize, transformation=args.transformation, verbose=False, html=False)
    tops = compare_models(n_select=args.top, sort="R2", verbose=False)
    tops = tops if isinstance(tops, list) else [tops]
    board = pull()
    say(f"[B] PyCaret 교차검증 평균 (학습용 {args.train_size:.0%}, {FOLDS}겹) - 상위 10개")
    say(board.head(10).to_string())
    say()

    models = tops
    if args.tune:
        tuned = []
        for m in tops:
            try:
                tuned.append(tune_model(m, optimize="R2", n_iter=args.n_iter, verbose=False))
                say(f"튜닝: {type(m).__name__} -> 교차검증 R2 {pull().loc['Mean', 'R2']:.4f}")
            except Exception as e:
                say(f"튜닝 실패 {type(m).__name__}: {e}")
                tuned.append(m)
        models = tuned
        say()

    say(f"[C] 홀드아웃 R2 (학습에 쓰지 않은 {1 - args.train_size:.0%})")
    for m in models:
        predict_model(m, verbose=False)
        say(f"  {type(m).__name__:<32} R2 {pull().loc[0, 'R2']:.4f}")
    say()

    # [A] ml-kit과 같은 기준: 전체 데이터 5겹 OOF R2 (전처리까지 포함한 파이프라인을 겹마다 새로 학습)
    from sklearn.base import clone
    from sklearn.metrics import r2_score
    from sklearn.model_selection import KFold, cross_val_predict
    say(f"[A] ml-kit과 같은 기준: 전체 {len(data)}행, {FOLDS}겹 교차검증 OOF R2 (ml-kit의 val_r2와 비교)")
    X, y = data.drop(columns=[target]), data[target].astype(float).values
    for m in models:
        try:
            pipe = finalize_model(m)
            oof = cross_val_predict(clone(pipe), X, y, cv=KFold(FOLDS, shuffle=True, random_state=SEED))
            say(f"  {type(m).__name__:<32} R2 {r2_score(y, oof):.4f}")
        except Exception as e:
            say(f"  {type(m).__name__:<32} 계산 실패: {type(e).__name__}: {e}")


# ------------------------------------------------------------------ 진입점

def main() -> None:
    ap = argparse.ArgumentParser(description="같은 데이터로 PyCaret 회귀 결과를 내고 ml-kit 비교 명령을 알려 줍니다.")
    ap.add_argument("-f", "--file", required=True, help="데이터 파일 (.xlsx/.csv)")
    ap.add_argument("-x", "--features", help="입력 컬럼, 쉼표로 (예: \"반응온도,압축압력\")")
    ap.add_argument("-y", "--target", help="타겟 컬럼 하나")
    ap.add_argument("--header-row", type=int, default=1, help="컬럼명 행 (기본 1)")
    ap.add_argument("--unit-row", type=int, default=2, help="단위 행 (기본 2, 없으면 0)")
    ap.add_argument("--train-size", type=float, default=0.7, help="PyCaret 학습용 비율 (기본 0.7, 나머지는 홀드아웃)")
    ap.add_argument("--normalize", action="store_true", help="PyCaret normalize=True")
    ap.add_argument("--transformation", action="store_true", help="PyCaret transformation=True")
    ap.add_argument("--tune", action="store_true", help="상위 모델 하이퍼파라미터 튜닝 (tune_model)")
    ap.add_argument("--n-iter", type=int, default=20, help="튜닝 시도 횟수 (기본 20)")
    ap.add_argument("--top", type=int, default=3, help="자세히 볼 상위 모델 수 (기본 3)")
    ap.add_argument("--check", action="store_true", help="PyCaret 없이 컬럼과 행 수만 확인")
    args = ap.parse_args()

    path = os.path.abspath(args.file)
    df = read_table(path, args.header_row, args.unit_row)
    units = df.attrs.get("units", {})
    print(f"[INFO] {os.path.basename(path)}: 데이터 {len(df)}행, 컬럼 {len(df.columns)}개")
    print("[INFO] 컬럼(단위): " + ", ".join(f"{c}({units[c]})" if units.get(c) else c for c in df.columns))
    if args.check:
        return
    if not args.features or not args.target:
        sys.exit("[ERROR] -x(입력 컬럼)와 -y(타겟 컬럼)를 지정하세요. 컬럼 이름은 --check로 볼 수 있습니다.")
    xs = pick(df, args.features, "입력(-x)")
    y = pick(df, args.target, "타겟(-y)")[0]
    data = to_numeric_frame(df, xs + [y])
    data[y] = pd.to_numeric(data[y], errors="coerce")
    dropped = int(data[y].isna().sum())
    data = data[data[y].notna()].reset_index(drop=True)

    lines = [f"PyCaret 비교 {datetime.now():%Y-%m-%d %H:%M}", f"파일: {path}", f"입력: {xs}", f"타겟: {y}",
             f"행: {len(data)} (타겟이 빈 행 {dropped}개 제외)",
             f"옵션: normalize={args.normalize}, transformation={args.transformation}, tune={args.tune}, "
             f"train_size={args.train_size}", ""]
    print("\n".join(lines))
    run_pycaret(data, y, args, lines)

    mlkit = (f'python "C:\\CLI\\ml-kit\\ml_train.py" -f "{path}" -x "{",".join(xs)}" -y "{y}" '
             f'--header-row {args.header_row}' + (f" --unit-row {args.unit_row}" if args.unit_row else ""))
    tail = ["", "ml-kit 비교 명령 (WinPython 기본 python으로, 결과의 mean_val_score와 위 [A]를 비교):", mlkit]
    print("\n".join(tail))
    lines += tail
    out = os.path.splitext(path)[0] + f"_pycaret_{datetime.now():%Y%m%d_%H%M%S}.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[INFO] 결과 저장: {out}")


if __name__ == "__main__":
    main()
