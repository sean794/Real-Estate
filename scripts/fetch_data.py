"""
서울 아파트 실거래가 & 전월세 데이터 수집 스크립트
+ 전세가율 계산 추가
"""

import os
import math
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
import json

TRADE_API_KEY = os.environ["MOLIT_TRADE_API_KEY"]
RENT_API_KEY  = os.environ["MOLIT_RENT_API_KEY"]

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


def get_ym_list(months_back=3):
    result = []
    today = datetime.today()
    for i in range(months_back):
        d = today - timedelta(days=30 * i)
        result.append(d.strftime("%Y%m"))
    return result


def fetch_trade(gu_name, gu_code, ym):
    params = {"serviceKey": TRADE_API_KEY, "LAWD_CD": gu_code, "DEAL_YMD": ym, "numOfRows": 1000}
    try:
        res = requests.get(BASE_TRADE_URL, params=params, timeout=15)
        res.raise_for_status()
        root = ET.fromstring(res.content)
        records = []
        for item in root.findall(".//item"):
            def g(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else None
            amt = g("dealAmount")
            records.append({
                "구": gu_name, "법정동": g("umdNm"), "아파트명": g("aptNm"),
                "전용면적": g("excluUseAr"), "층": g("floor"), "건축년도": g("buildYear"),
                "거래금액": amt.replace(",", "") if amt else None,
                "년": g("dealYear"), "월": g("dealMonth"), "일": g("dealDay"),
                "거래유형": g("dealingGbn"),
            })
        print(f"  [매매] {gu_name} {ym}: {len(records)}건")
        return records
    except Exception as e:
        print(f"  [매매 오류] {gu_name} {ym}: {e}")
        return []


def fetch_rent(gu_name, gu_code, ym):
    params = {"serviceKey": RENT_API_KEY, "LAWD_CD": gu_code, "DEAL_YMD": ym, "numOfRows": 1000}
    try:
        res = requests.get(BASE_RENT_URL, params=params, timeout=15)
        res.raise_for_status()
        root = ET.fromstring(res.content)
        records = []
        for item in root.findall(".//item"):
            def g(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else None
            deposit = g("deposit")
            monthly = g("monthlyRent")
            records.append({
                "구": gu_name, "법정동": g("umdNm"), "아파트명": g("aptNm"),
                "전용면적": g("excluUseAr"), "층": g("floor"), "건축년도": g("buildYear"),
                "보증금": deposit.replace(",", "") if deposit else None,
                "월세": monthly.replace(",", "") if monthly else None,
                "년": g("dealYear"), "월": g("dealMonth"), "일": g("dealDay"),
            })
        print(f"  [전월세] {gu_name} {ym}: {len(records)}건")
        return records
    except Exception as e:
        print(f"  [전월세 오류] {gu_name} {ym}: {e}")
        return []


def save_csv(records, path):
    if not records:
        return
    df = pd.DataFrame(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  저장 완료: {path} ({len(df)}행)")


def clean_nan(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nan(i) for i in obj]
    return obj


def calc_jeonse_rate(trade_dir, rent_dir):
    """구별 전세가율 계산 (최근 월 기준, 전세만 사용)"""
    trade_files = sorted(trade_dir.glob("*.csv"))
    rent_files  = sorted(rent_dir.glob("*.csv"))
    if not trade_files or not rent_files:
        return []

    # 최근 월 파일 사용
    tf = trade_files[-1]
    rf = rent_files[-1]
    ym = tf.stem

    trade_df = pd.read_csv(tf, encoding="utf-8-sig")
    rent_df  = pd.read_csv(rf, encoding="utf-8-sig")

    trade_df["거래금액"] = pd.to_numeric(trade_df["거래금액"].astype(str).str.replace(",", ""), errors="coerce")
    rent_df["보증금"]    = pd.to_numeric(rent_df["보증금"].astype(str).str.replace(",", ""),    errors="coerce")
    rent_df["월세"]      = pd.to_numeric(rent_df["월세"].astype(str).str.replace(",", ""),      errors="coerce")

    # 전세만 필터 (월세 == 0 또는 NaN)
    jeonse_df = rent_df[(rent_df["월세"].isna()) | (rent_df["월세"] == 0)].copy()

    result = []
    for gu in SEOUL_GU_CODES.keys():
        t = trade_df[trade_df["구"] == gu]["거래금액"]
        j = jeonse_df[jeonse_df["구"] == gu]["보증금"]
        if len(t) < 3 or len(j) < 3:
            continue
        avg_trade  = t.mean()
        avg_jeonse = j.mean()
        if avg_trade > 0:
            rate = round(avg_jeonse / avg_trade * 100, 1)
            result.append({
                "구": gu,
                "평균매매가": round(avg_trade, 0),
                "평균전세가": round(avg_jeonse, 0),
                "전세가율": rate,
                "신호": "매수고려" if rate >= 70 else ("주의" if rate >= 60 else "관망"),
                "ym": ym,
            })

    result.sort(key=lambda x: x["전세가율"], reverse=True)
    return result


def build_summary(trade_dir, rent_dir, out_path):
    summary = {
        "trade": [],
        "rent": [],
        "jeonse_rate": [],
        "updated": datetime.today().strftime("%Y-%m-%d"),
    }

    # 매매 요약
    for f in sorted(trade_dir.glob("*.csv")):
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["거래금액"] = pd.to_numeric(df["거래금액"].astype(str).str.replace(",", ""), errors="coerce")
        df["전용면적"] = pd.to_numeric(df["전용면적"].astype(str), errors="coerce")
        ym = f.stem
        per_gu = (
            df.groupby("구")["거래금액"]
            .agg(["mean", "median", "count"])
            .reset_index()
            .rename(columns={"mean": "평균가", "median": "중위가", "count": "거래수"})
        )
        per_gu["ym"] = ym

        # 예산 필터용: 면적대별 평균가
        size_bins = [
            ("~60㎡",  df[df["전용면적"] <= 60]),
            ("60~85㎡", df[(df["전용면적"] > 60) & (df["전용면적"] <= 85)]),
            ("85~135㎡", df[(df["전용면적"] > 85) & (df["전용면적"] <= 135)]),
            ("135㎡~",  df[df["전용면적"] > 135]),
        ]
        size_avg = []
        for label, sub in size_bins:
            if len(sub) > 0:
                size_avg.append({
                    "구간": label,
                    "평균가": round(float(sub["거래금액"].mean()), 0) if not sub["거래금액"].isna().all() else 0,
                    "거래수": len(sub),
                })

        summary["trade"].append({
            "ym": ym,
            "전체평균": round(float(df["거래금액"].mean()), 0) if not df["거래금액"].isna().all() else 0,
            "전체중위": round(float(df["거래금액"].median()), 0) if not df["거래금액"].isna().all() else 0,
            "거래수": len(df),
            "구별": per_gu.to_dict(orient="records"),
            "면적별": size_avg,
        })

    # 전월세 요약
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

    # 전세가율
    summary["jeonse_rate"] = calc_jeonse_rate(trade_dir, rent_dir)

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
