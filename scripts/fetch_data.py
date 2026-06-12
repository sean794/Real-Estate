"""
서울 아파트 실거래가 & 전월세 데이터 수집 스크립트
국토교통부 실거래가 API 사용
매일 GitHub Actions에서 자동 실행
"""

import os
import math
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
import json

# ── 환경변수에서 API 키 로드 ──────────────────────────────────
TRADE_API_KEY = os.environ["MOLIT_TRADE_API_KEY"]
RENT_API_KEY  = os.environ["MOLIT_RENT_API_KEY"]

# ── 서울 25개 자치구 법정동 코드 ───────────────────────────────
SEOUL_GU_CODES = {
    "종로구": "11110", "중구":   "11140", "용산구": "11170",
    "성동구": "11200", "광진구": "11215", "동대문구": "11230",
    "중랑구": "11260", "성북구": "11290", "강북구": "11305",
    "도봉구": "11320", "노원구": "11350", "은평구": "11380",
    "서대문구": "11410", "마포구": "11440", "양천구": "11470",
    "강서구": "11500", "구로구": "11530", "금천구": "11545",
    "영등포구": "11560", "동작구": "11590", "관악구": "11620",
    "서초구": "11650", "강남구": "11680", "송파구": "11710",
    "강동구": "11740",
}

BASE_TRADE_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
BASE_RENT_URL  = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"


def get_ym_list(months_back: int = 3):
    result = []
    today = datetime.today()
    for i in range(months_back):
        d = today - timedelta(days=30 * i)
        result.append(d.strftime("%Y%m"))
    return result


def fetch_trade(gu_name, gu_code, ym):
    params = {
        "serviceKey": TRADE_API_KEY,
        "LAWD_CD": gu_code,
        "DEAL_YMD": ym,
        "numOfRows": 1000,
    }
    try:
        res = requests.get(BASE_TRADE_URL, params=params, timeout=15)
        res.raise_for_status()
        root = ET.fromstring(res.content)
        items = root.findall(".//item")
        records = []
        for item in items:
            def g(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else None
            amt = g("거래금액")
            records.append({
                "구":        gu_name,
                "법정동":    g("법정동"),
                "아파트명":  g("아파트"),
                "전용면적":  g("전용면적"),
                "층":        g("층"),
                "건축년도":  g("건축년도"),
                "거래금액":  amt.replace(",", "") if amt else None,
                "년":        g("년"),
                "월":        g("월"),
                "일":        g("일"),
                "거래유형":  g("거래유형"),
            })
        print(f"  [매매] {gu_name} {ym}: {len(records)}건")
        return records
    except Exception as e:
        print(f"  [매매 오류] {gu_name} {ym}: {e}")
        return []


def fetch_rent(gu_name, gu_code, ym):
    params = {
        "serviceKey": RENT_API_KEY,
        "LAWD_CD": gu_code,
        "DEAL_YMD": ym,
        "numOfRows": 1000,
    }
    try:
        res = requests.get(BASE_RENT_URL, params=params, timeout=15)
        res.raise_for_status()
        root = ET.fromstring(res.content)
        items = root.findall(".//item")
        records = []
        for item in items:
            def g(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else None
            deposit = g("보증금액")
            monthly = g("월세금액")
            records.append({
                "구":        gu_name,
                "법정동":    g("법정동"),
                "아파트명":  g("아파트"),
                "전용면적":  g("전용면적"),
                "층":        g("층"),
                "건축년도":  g("건축년도"),
                "보증금":    deposit.replace(",", "") if deposit else None,
                "월세":      monthly.replace(",", "") if monthly else None,
                "년":        g("년"),
                "월":        g("월"),
                "일":        g("일"),
            })
        print(f"  [전월세] {gu_name} {ym}: {len(records)}건")
        return records
    except Exception as e:
        print(f"  [전월세 오류] {gu_name} {ym}: {e}")
        return []


def save_csv(records, path):
    if not records:
        print(f"  저장 건너뜀 (데이터 없음): {path}")
        return
    df = pd.DataFrame(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  저장 완료: {path} ({len(df)}행)")


def clean_nan(obj):
    """NaN/Infinity를 0으로 변환 (JSON 직렬화 오류 방지)"""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nan(i) for i in obj]
    return obj


def build_summary(trade_dir, rent_dir, out_path):
    summary = {"trade": [], "rent": [], "updated": datetime.today().strftime("%Y-%m-%d")}

    for f in sorted(trade_dir.glob("*.csv")):
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["거래금액"] = pd.to_numeric(
            df["거래금액"].astype(str).str.replace(",", ""), errors="coerce"
        )
        ym = f.stem
        per_gu = (
            df.groupby("구")["거래금액"]
            .agg(["mean", "median", "count"])
            .reset_index()
            .rename(columns={"mean": "평균가", "median": "중위가", "count": "거래수"})
        )
        per_gu["ym"] = ym
        summary["trade"].append({
            "ym": ym,
            "전체평균": round(float(df["거래금액"].mean()), 0) if not df["거래금액"].isna().all() else 0,
            "전체중위": round(float(df["거래금액"].median()), 0) if not df["거래금액"].isna().all() else 0,
            "거래수": len(df),
            "구별": per_gu.to_dict(orient="records"),
        })

    for f in sorted(rent_dir.glob("*.csv")):
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["보증금"] = pd.to_numeric(df["보증금"].astype(str).str.replace(",", ""), errors="coerce")
        df["월세"]   = pd.to_numeric(df["월세"].astype(str).str.replace(",", ""),   errors="coerce")
        ym = f.stem
        summary["rent"].append({
            "ym": ym,
            "평균보증금": round(float(df["보증금"].mean()), 0) if not df["보증금"].isna().all() else 0,
            "평균월세":   round(float(df["월세"].mean()), 0)   if not df["월세"].isna().all() else 0,
            "거래수": len(df),
        })

    # NaN 제거 후 저장
    summary = clean_nan(summary)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
    print(f"요약 JSON 저장: {out_path}")


def main():
    ym_list = get_ym_list(months_back=3)
    print(f"수집 대상 월: {ym_list}")

    trade_dir = Path("data/apt_trade")
    rent_dir  = Path("data/apt_rent")

    for ym in ym_list:
        trade_all, rent_all = [], []
        for gu_name, gu_code in SEOUL_GU_CODES.items():
            trade_all.extend(fetch_trade(gu_name, gu_code, ym))
            rent_all.extend(fetch_rent(gu_name, gu_code, ym))

        save_csv(trade_all, trade_dir / f"{ym}.csv")
        save_csv(rent_all,  rent_dir  / f"{ym}.csv")

    build_summary(trade_dir, rent_dir, Path("docs/data/summary.json"))
    print("\n✅ 수집 완료!")


if __name__ == "__main__":
    main()
