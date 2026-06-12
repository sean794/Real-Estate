"""
서울 아파트 실거래가 & 전월세 데이터 수집 스크립트
국토교통부 실거래가 API 사용
매일 GitHub Actions에서 자동 실행
"""

import os
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
    """최근 N개월 YYYYMM 리스트 반환"""
    result = []
    today = datetime.today()
    for i in range(months_back):
        d = today - timedelta(days=30 * i)
        result.append(d.strftime("%Y%m"))
    return result


def fetch_trade(gu_name: str, gu_code: str, ym: str) -> list[dict]:
    """매매 데이터 수집"""
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
            records.append({
                "구":        gu_name,
                "법정동":    g("법정동"),
                "아파트명":  g("아파트"),
                "전용면적":  g("전용면적"),
                "층":        g("층"),
                "건축년도":  g("건축년도"),
                "거래금액":  g("거래금액").replace(",", "") if g("거래금액") else None,
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


def fetch_rent(gu_name: str, gu_code: str, ym: str) -> list[dict]:
    """전월세 데이터 수집"""
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
            records.append({
                "구":        gu_name,
                "법정동":    g("법정동"),
                "아파트명":  g("아파트"),
                "전용면적":  g("전용면적"),
                "층":        g("층"),
                "건축년도":  g("건축년도"),
                "보증금":    g("보증금액").replace(",", "") if g("보증금액") else None,
                "월세":      g("월세금액").replace(",", "") if g("월세금액") else None,
                "년":        g("년"),
                "월":        g("월"),
                "일":        g("일"),
            })
        print(f"  [전월세] {gu_name} {ym}: {len(records)}건")
        return records
    except Exception as e:
        print(f"  [전월세 오류] {gu_name} {ym}: {e}")
        return []


def save_csv(records: list[dict], path: Path):
    """데이터프레임으로 변환 후 CSV 저장"""
    if not records:
        print(f"  저장 건너뜀 (데이터 없음): {path}")
        return
    df = pd.DataFrame(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  저장 완료: {path} ({len(df)}행)")


def build_summary(trade_dir: Path, rent_dir: Path, out_path: Path):
    """월별 평균가 요약 JSON 생성 (웹 시각화용)"""
    summary = {"trade": [], "rent": [], "updated": datetime.today().strftime("%Y-%m-%d")}

    # 매매 요약
    trade_files = sorted(trade_dir.glob("*.csv"))
    for f in trade_files:
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["거래금액"] = pd.to_numeric(df["거래금액"], errors="coerce")
        df["전용면적"] = pd.to_numeric(df["전용면적"], errors="coerce")
        df["ym"] = f.stem  # 파일명 = YYYYMM
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
            "전체평균": round(df["거래금액"].mean(), 0) if not df["거래금액"].isna().all() else 0,
            "전체중위": round(df["거래금액"].median(), 0) if not df["거래금액"].isna().all() else 0,
            "거래수": len(df),
            "구별": per_gu.to_dict(orient="records"),
        })

    # 전월세 요약
    rent_files = sorted(rent_dir.glob("*.csv"))
    for f in rent_files:
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["보증금"] = pd.to_numeric(df["보증금"], errors="coerce")
        df["월세"]   = pd.to_numeric(df["월세"],   errors="coerce")
        ym = f.stem
        summary["rent"].append({
            "ym": ym,
            "평균보증금": round(df["보증금"].mean(), 0) if not df["보증금"].isna().all() else 0,
            "평균월세":   round(df["월세"].mean(), 0)   if not df["월세"].isna().all() else 0,
            "거래수": len(df),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
    print(f"요약 JSON 저장: {out_path}")


def main():
    ym_list = get_ym_list(months_back=3)  # 최근 3개월
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
