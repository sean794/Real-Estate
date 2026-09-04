"""
서울 아파트 실거래가 & 전월세 + 한국부동산원 주간 시세 수집
v6: 전일 거래 요약 + 주간 가격동향 추가
"""

import os, math, json, requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

TRADE_API_KEY = os.environ["MOLIT_TRADE_API_KEY"]
RENT_API_KEY  = os.environ["MOLIT_RENT_API_KEY"]
REB_API_KEY   = os.environ.get("REB_API_KEY", "")

SEOUL_GU_CODES = {
    "종로구":"11110","중구":"11140","용산구":"11170","성동구":"11200",
    "광진구":"11215","동대문구":"11230","중랑구":"11260","성북구":"11290",
    "강북구":"11305","도봉구":"11320","노원구":"11350","은평구":"11380",
    "서대문구":"11410","마포구":"11440","양천구":"11470","강서구":"11500",
    "구로구":"11530","금천구":"11545","영등포구":"11560","동작구":"11590",
    "관악구":"11620","서초구":"11650","강남구":"11680","송파구":"11710",
    "강동구":"11740",
}

BASE_TRADE_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
BASE_RENT_URL  = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

# 한국부동산원 R-ONE API
REB_BASE_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"

def get_ym_list(months_back=3):
    return [(datetime.today()-timedelta(days=30*i)).strftime("%Y%m") for i in range(months_back)]

def fetch_xml(url, params):
    res = requests.get(url, params=params, timeout=15)
    res.raise_for_status()
    return ET.fromstring(res.content)

def parse_trade(root, gu_name):
    records = []
    for item in root.findall(".//item"):
        def g(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else None
        amt = g("dealAmount")
        records.append({
            "구":gu_name,"법정동":g("umdNm"),"아파트명":g("aptNm"),
            "전용면적":g("excluUseAr"),"층":g("floor"),"건축년도":g("buildYear"),
            "거래금액":amt.replace(",","") if amt else None,
            "년":g("dealYear"),"월":g("dealMonth"),"일":g("dealDay"),
            "거래유형":g("dealingGbn"),
        })
    return records

def parse_rent(root, gu_name):
    records = []
    for item in root.findall(".//item"):
        def g(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else None
        dep=g("deposit"); mon=g("monthlyRent")
        records.append({
            "구":gu_name,"법정동":g("umdNm"),"아파트명":g("aptNm"),
            "전용면적":g("excluUseAr"),"층":g("floor"),"건축년도":g("buildYear"),
            "보증금":dep.replace(",","") if dep else None,
            "월세":mon.replace(",","") if mon else None,
            "년":g("dealYear"),"월":g("dealMonth"),"일":g("dealDay"),
        })
    return records

def fetch_all(gu_name, gu_code, ym):
    trade_params = {"serviceKey":TRADE_API_KEY,"LAWD_CD":gu_code,"DEAL_YMD":ym,"numOfRows":1000}
    rent_params  = {"serviceKey":RENT_API_KEY, "LAWD_CD":gu_code,"DEAL_YMD":ym,"numOfRows":1000}
    try:
        t = parse_trade(fetch_xml(BASE_TRADE_URL, trade_params), gu_name)
        print(f"  [매매] {gu_name} {ym}: {len(t)}건")
    except Exception as e:
        print(f"  [매매 오류] {gu_name} {ym}: {e}"); t=[]
    try:
        r = parse_rent(fetch_xml(BASE_RENT_URL, rent_params), gu_name)
        print(f"  [전월세] {gu_name} {ym}: {len(r)}건")
    except Exception as e:
        print(f"  [전월세 오류] {gu_name} {ym}: {e}"); r=[]
    return t, r

def save_csv(records, path):
    if not records: return
    df = pd.DataFrame(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    # GitHub Pages용 복사
    docs_path = Path("docs") / path
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(docs_path, index=False, encoding="utf-8-sig")
    print(f"  저장: {path} ({len(df)}행)")

def clean_nan(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return 0
    if isinstance(obj, dict): return {k:clean_nan(v) for k,v in obj.items()}
    if isinstance(obj, list): return [clean_nan(i) for i in obj]
    return obj

def iqr_filter(series):
    q1,q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3-q1
    return series[(series >= q1-1.5*iqr) & (series <= q3+1.5*iqr)]

def gu_stats(prices, min_count=3):
    if len(prices) < min_count: return None
    filtered = iqr_filter(prices)
    if len(filtered) < min_count: return None
    return {"평균가":round(float(filtered.mean()),0),"중위가":round(float(filtered.median()),0),"거래수":int(len(prices)),"필터후건수":int(len(filtered))}

def fetch_weekly_price():
    """한국부동산원 주간 아파트 가격동향 수집"""
    if not REB_API_KEY:
        print("  REB_API_KEY 없음, 주간 시세 건너뜀")
        return []

    # 주간 아파트 매매가격지수 변동률 STATBL_ID
    # A_2024_00045: 주간 아파트 매매가격지수
    statbl_ids = ["A_2024_00045", "A_2024_00046", "R214", "A_2024_00900"]

    for statbl_id in statbl_ids:
        params = {
            "KEY": REB_API_KEY,
            "Type": "json",
            "pIndex": 1,
            "pSize": 10,
            "STATBL_ID": statbl_id,
            "DTACYCLE_CD": "WK",
            "WRTTIME_IDTFR_ID": "20260801",
            "WRTTIME_IDTFR_ID_END": "20260904",
        }
        try:
            res = requests.get(
                "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do",
                params=params, timeout=15
            )
            data = res.json()
            print(f"  [{statbl_id}] 응답: {str(data)[:200]}")
            stts_data = data.get("SttsApiTblData", [])
            if stts_data and len(stts_data) >= 2:
                items = stts_data[1].get("row", [])
                if items:
                    print(f"  [{statbl_id}] 데이터 발견! {len(items)}건")
                    result = []
                    for item in items:
                        result.append({
                            "지역": item.get("AREA_NM", ""),
                            "기준일": item.get("WRTTIME_IDTFR_ID", ""),
                            "지수": float(item.get("DATA_VALUE", 0) or 0),
                            "변동률": float(item.get("CMPRSN_VALUE", 0) or 0),
                        })
                    return result
        except Exception as e:
            print(f"  [{statbl_id}] 오류: {e}")

    print("  주간 시세: 모든 STATBL_ID 실패")
    return []

def make_daily_recap(trade_dir, rent_dir):
    """전일 거래 요약 생성"""
    today = datetime.today()
    ym = today.strftime("%Y%m")
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    recap = {
        "date": yesterday,
        "trade": {"건수":0,"평균가":0,"최고가":0,"최고가_단지":"","구별":[]},
        "rent":  {"건수":0,"평균보증금":0,"구별":[]},
    }

    trade_file = trade_dir / f"{ym}.csv"
    if trade_file.exists():
        df = pd.read_csv(trade_file, encoding="utf-8-sig")
        df["거래금액"] = pd.to_numeric(df["거래금액"].astype(str).str.replace(",",""), errors="coerce")
        # 전일 거래 필터 (년월일 조합)
        df["날짜"] = df["년"].astype(str)+"-"+df["월"].astype(str).str.zfill(2)+"-"+df["일"].astype(str).str.zfill(2)
        yesterday_df = df[df["날짜"] == yesterday]
        if len(yesterday_df) > 0:
            recap["trade"]["건수"] = len(yesterday_df)
            recap["trade"]["평균가"] = round(float(yesterday_df["거래금액"].mean()), 0) if not yesterday_df["거래금액"].isna().all() else 0
            max_row = yesterday_df.loc[yesterday_df["거래금액"].idxmax()] if not yesterday_df["거래금액"].isna().all() else None
            if max_row is not None:
                recap["trade"]["최고가"] = float(max_row["거래금액"])
                recap["trade"]["최고가_단지"] = f"{max_row['구']} {max_row['아파트명']}"
            # 구별 거래수
            gu_cnt = yesterday_df.groupby("구").size().reset_index(name="거래수")
            recap["trade"]["구별"] = gu_cnt.sort_values("거래수", ascending=False).to_dict(orient="records")

    rent_file = rent_dir / f"{ym}.csv"
    if rent_file.exists():
        df = pd.read_csv(rent_file, encoding="utf-8-sig")
        df["보증금"] = pd.to_numeric(df["보증금"].astype(str).str.replace(",",""), errors="coerce")
        df["날짜"] = df["년"].astype(str)+"-"+df["월"].astype(str).str.zfill(2)+"-"+df["일"].astype(str).str.zfill(2)
        yesterday_df = df[df["날짜"] == yesterday]
        if len(yesterday_df) > 0:
            recap["rent"]["건수"] = len(yesterday_df)
            recap["rent"]["평균보증금"] = round(float(yesterday_df["보증금"].mean()), 0) if not yesterday_df["보증금"].isna().all() else 0
            gu_cnt = yesterday_df.groupby("구").size().reset_index(name="거래수")
            recap["rent"]["구별"] = gu_cnt.sort_values("거래수", ascending=False).to_dict(orient="records")

    return recap

def build_summary(trade_dir, rent_dir, out_path):
    summary = {"trade":[],"rent":[],"jeonse_rate":[],"weekly_price":[],"daily_recap":{},"updated":datetime.today().strftime("%Y-%m-%d")}

    # 매매 요약
    for f in sorted(trade_dir.glob("*.csv")):
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["거래금액"] = pd.to_numeric(df["거래금액"].astype(str).str.replace(",",""), errors="coerce")
        df["전용면적"] = pd.to_numeric(df["전용면적"].astype(str), errors="coerce")
        df = df.dropna(subset=["거래금액","전용면적"])
        ym = f.stem
        per_gu = []
        for gu in SEOUL_GU_CODES.keys():
            sub = df[df["구"]==gu]["거래금액"]
            stats = gu_stats(sub)
            if stats: per_gu.append({"구":gu,"ym":ym,**stats})
        SIZE_BINS = [("소형 (~60㎡)",0,60),("중형 (60~85㎡)",60,85),("대형 (85㎡~)",85,999)]
        POPULAR_SIZES = [("59㎡",55,63),("84㎡",80,90)]
        size_gu = {}
        for label,lo,hi in SIZE_BINS:
            size_df = df[(df["전용면적"]>lo)&(df["전용면적"]<=hi)]
            gl = []
            for gu in SEOUL_GU_CODES.keys():
                stats = gu_stats(size_df[size_df["구"]==gu]["거래금액"])
                if stats: gl.append({"구":gu,**stats})
            size_gu[label] = sorted(gl, key=lambda x:x["평균가"], reverse=True)
        popular_gu = {}
        for label,lo,hi in POPULAR_SIZES:
            pop_df = df[(df["전용면적"]>=lo)&(df["전용면적"]<=hi)]
            gl = []
            for gu in SEOUL_GU_CODES.keys():
                stats = gu_stats(pop_df[pop_df["구"]==gu]["거래금액"])
                if stats: gl.append({"구":gu,**stats})
            popular_gu[label] = sorted(gl, key=lambda x:x["평균가"], reverse=True)
        all_prices = iqr_filter(df["거래금액"])
        summary["trade"].append({
            "ym":ym,
            "전체평균":round(float(all_prices.mean()),0) if len(all_prices) else 0,
            "전체중위":round(float(all_prices.median()),0) if len(all_prices) else 0,
            "거래수":len(df),
            "구별":sorted(per_gu, key=lambda x:x["평균가"], reverse=True),
            "면적별":size_gu,
            "국민평형":popular_gu,
        })

    # 전월세 요약
    for f in sorted(rent_dir.glob("*.csv")):
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["보증금"] = pd.to_numeric(df["보증금"].astype(str).str.replace(",",""), errors="coerce")
        df["월세"]   = pd.to_numeric(df["월세"].astype(str).str.replace(",",""), errors="coerce")
        df["전용면적"] = pd.to_numeric(df["전용면적"].astype(str), errors="coerce")
        ym = f.stem
        jeonse_df = df[(df["월세"].isna())|(df["월세"]==0)].dropna(subset=["보증금"])
        per_gu_rent = []
        for gu in SEOUL_GU_CODES.keys():
            stats = gu_stats(jeonse_df[jeonse_df["구"]==gu]["보증금"])
            if stats: per_gu_rent.append({"구":gu,**stats})
        POPULAR_SIZES = [("59㎡",55,63),("84㎡",80,90)]
        popular_rent = {}
        for label,lo,hi in POPULAR_SIZES:
            pop_df = jeonse_df[(jeonse_df["전용면적"]>=lo)&(jeonse_df["전용면적"]<=hi)]
            gl = []
            for gu in SEOUL_GU_CODES.keys():
                stats = gu_stats(pop_df[pop_df["구"]==gu]["보증금"])
                if stats: gl.append({"구":gu,**stats})
            popular_rent[label] = sorted(gl, key=lambda x:x["평균가"], reverse=True)
        filt_dep = iqr_filter(jeonse_df["보증금"]) if len(jeonse_df) else pd.Series([])
        filt_mon = iqr_filter(df.dropna(subset=["월세"])["월세"]) if len(df.dropna(subset=["월세"])) else pd.Series([])
        summary["rent"].append({
            "ym":ym,
            "평균보증금":round(float(filt_dep.mean()),0) if len(filt_dep) else 0,
            "평균월세":round(float(filt_mon.mean()),0) if len(filt_mon) else 0,
            "거래수":len(df),
            "구별전세":sorted(per_gu_rent, key=lambda x:x["평균가"], reverse=True),
            "국민평형전세":popular_rent,
        })

    # 전세가율
    if summary["trade"] and summary["rent"]:
        last_trade = summary["trade"][-1]
        last_rent  = summary["rent"][-1]
        ym = last_trade["ym"]
        trade_map = {d["구"]:d["중위가"] for d in last_trade["구별"]}
        rent_map  = {d["구"]:d["중위가"] for d in last_rent["구별전세"]}
        result = []
        for gu in SEOUL_GU_CODES.keys():
            t=trade_map.get(gu); r=rent_map.get(gu)
            if t and r and t>0:
                rate = round(r/t*100,1)
                result.append({"구":gu,"평균매매가":t,"평균전세가":r,"전세가율":rate,"ym":ym,
                    "신호":"매수고려" if rate>=70 else ("주의" if rate>=60 else "관망")})
        summary["jeonse_rate"] = sorted(result, key=lambda x:x["전세가율"], reverse=True)

    # 주간 시세
    summary["weekly_price"] = fetch_weekly_price()

    # 전일 거래 요약
    summary["daily_recap"] = make_daily_recap(trade_dir, rent_dir)

    summary = clean_nan(summary)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path,"w",encoding="utf-8") as fp:
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
            t,r = fetch_all(gu_name, gu_code, ym)
            trade_all.extend(t); rent_all.extend(r)
        save_csv(trade_all, trade_dir/f"{ym}.csv")
        save_csv(rent_all,  rent_dir/f"{ym}.csv")
    build_summary(trade_dir, rent_dir, Path("docs/data/summary.json"))
    print("\n✅ 수집 완료!")

if __name__ == "__main__":
    main()
