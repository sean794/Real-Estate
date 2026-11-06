"""원천 CSV 정제 (수집 스크립트와 분석 스크립트가 공유).

 - 매매: 'O'(해제) 거래 제거. 해제 건은 API에 '원 거래 행 + 해제 표시 행' 2개로 나오므로,
         해제 1건당 같은 거래(단지·면적·층·금액·계약일) 원 행 1개를 함께 제거한다.
         (옛 CSV는 해제여부 열이 없어서, 같은 행이 짝수 개면 원본+해제 쌍으로 보고 홀짝(parity)으로 추정)
 - 전월세: 같은 계약의 중복 행 제거. 갱신계약(옛 보증금 그대로)은 시세 지표에서 제외할 수 있게 계약구분 유지.
"""
import pandas as pd

TRADE_KEY = ["구", "법정동", "아파트명", "전용면적", "층", "거래금액", "년", "월", "일"]
RENT_KEY = ["구", "법정동", "아파트명", "전용면적", "층", "보증금", "월세", "년", "월", "일"]

def _k(df, cols):
    return df[cols].astype(str).agg("|".join, axis=1)

def clean_trade(df):
    """원본 DataFrame(문자열) -> 해제 거래 제거된 DataFrame. 반환 열은 원본과 동일."""
    if df.empty:
        return df
    df = df.copy()
    df["_k"] = _k(df, TRADE_KEY)
    if "해제여부" in df.columns:
        canc = df["해제여부"].fillna("").astype(str).str.strip().eq("O")
        n_cancel = df[canc].groupby("_k").size()
        keep = df[~canc].copy()
        keep["_n"] = keep.groupby("_k").cumcount()
        keep["_c"] = keep["_k"].map(n_cancel).fillna(0)
        keep = keep[keep["_n"] >= keep["_c"]]
        return keep.drop(columns=["_k", "_n", "_c"])
    # 구 스키마: 동일 행이 2~4개면 원본+해제 쌍으로 보고 홀수면 1개, 짝수면 0개가 유효.
    # 5개 이상 똑같은 행은 한 단지의 같은 층 여러 호실 일괄 거래(시행사 물량 등)라 전부 유효로 둠.
    df["_n"] = df.groupby("_k").cumcount()
    df["_size"] = df.groupby("_k")["_k"].transform("size")
    keep = df[(df["_size"] >= 5) | (df["_n"] < (df["_size"] % 2))]
    return keep.drop(columns=["_k", "_n", "_size"])

def has_new_schema_trade(df):
    return "해제여부" in df.columns

def clean_rent(df):
    """전월세 중복 제거. 같은 계약이 계약구분 공란/표기 두 줄로 오는 경우 표기 있는 쪽을 남김."""
    if df.empty:
        return df
    df = df.copy()
    if "계약구분" in df.columns:
        df["_blank"] = df["계약구분"].fillna("").astype(str).str.strip().eq("")
        df = df.sort_values("_blank", kind="stable")
        df = df.drop_duplicates(subset=RENT_KEY, keep="first").drop(columns="_blank")
    else:
        df = df.drop_duplicates(subset=RENT_KEY, keep="first")
    return df

def has_new_schema_rent(df):
    return "계약구분" in df.columns

def new_contracts_only(df):
    """전세 시세용: 갱신계약 제외(신규 + 구분 없음). 구 스키마면 그대로(구분 불명)."""
    if "계약구분" not in df.columns:
        return df
    return df[df["계약구분"].fillna("").astype(str).str.strip() != "갱신"]
