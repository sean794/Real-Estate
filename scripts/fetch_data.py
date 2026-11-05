"""
서울 아파트 실거래가 & 전월세 + 한국부동산원 주간 시세 수집
v6: 전일 거래 요약 + 주간 가격동향 추가
"""

import os, math, json, time, requests
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

class QuotaExceeded(Exception):
    pass

def fetch_xml(url, params, retries=3):
    """XML 응답 1회 호출 (재시도 + 일일 호출한도 감지)"""
    last = None
    for i in range(retries):
        try:
            res = requests.get(url, params=params, timeout=30)
            res.raise_for_status()
            root = ET.fromstring(res.content)
            if root.tag == "OpenAPI_ServiceResponse":      # 게이트웨이 오류 형식
                reason = (root.findtext(".//returnReasonCode") or "").strip()
                msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or ""
                if reason == "22" or "LIMITED" in msg.upper():
                    raise QuotaExceeded(msg)
                raise RuntimeError(f"gateway {reason} {msg}")
            code = (root.findtext(".//resultCode") or "").strip()
            if code not in ("", "00", "000"):
                msg = root.findtext(".//resultMsg") or ""
                if code == "22" or "LIMIT" in msg.upper():
                    raise QuotaExceeded(msg)
                raise RuntimeError(f"resultCode {code} {msg}")
            return root
        except QuotaExceeded:
            raise
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last

def fetch_paged(url, base_params, parser, gu_name):
    """totalCount 기준으로 모든 페이지 수집 (1000건 초과 구 대응)"""
    records, page = [], 1
    while True:
        root = fetch_xml(url, {**base_params, "pageNo": page, "numOfRows": 1000})
        recs = parser(root, gu_name)
        records.extend(recs)
        total = int(root.findtext(".//totalCount") or 0)
        if not recs or len(records) >= total or page >= 20:
            break
        page += 1
    return records

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
    """(매매, 전월세, 성공여부). 호출한도 초과는 QuotaExceeded 로 그대로 올림"""
    ok = True
    t, r = [], []
    try:
        t = fetch_paged(BASE_TRADE_URL, {"serviceKey":TRADE_API_KEY,"LAWD_CD":gu_code,"DEAL_YMD":ym}, parse_trade, gu_name)
        print(f"  [매매] {gu_name} {ym}: {len(t)}건")
    except QuotaExceeded:
        raise
    except Exception as e:
        ok = False; print(f"  [매매 오류] {gu_name} {ym}: {e}")
    try:
        r = fetch_paged(BASE_RENT_URL, {"serviceKey":RENT_API_KEY,"LAWD_CD":gu_code,"DEAL_YMD":ym}, parse_rent, gu_name)
        print(f"  [전월세] {gu_name} {ym}: {len(r)}건")
    except QuotaExceeded:
        raise
    except Exception as e:
        ok = False; print(f"  [전월세 오류] {gu_name} {ym}: {e}")
    return t, r, ok

DOCS_MONTHS = 12   # 브라우저(거래내역 탭)용 복사본은 최근 12개월만

def save_csv(records, path):
    if not records: return
    df = pd.DataFrame(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    cutoff = (datetime.today() - timedelta(days=31 * DOCS_MONTHS)).strftime("%Y%m")
    if path.stem >= cutoff:
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

REB_WEEKLY_TABLES = {"매매": "T244183132827305", "전세": "T247713133046872"}  # (주) 매매/전세가격지수

def _iso_week_ids(n=10):
    """최근 n주의 R-ONE 주차 ID (YYYY + ISO 주차 2자리, 예: 202610 = 2026-03-02 주)"""
    out, d = [], datetime.today()
    for i in range(n):
        y, w, _ = (d - timedelta(weeks=i)).isocalendar()
        out.append(f"{y}{w:02d}")
    return out[::-1]

def fetch_weekly_price():
    """R-ONE 주간 서울 매매/전세 가격지수(+전주 대비 변동률) 및 25개 구별 최근 변동률.
    반환: (서울 시계열 list, 구별 list)"""
    if not REB_API_KEY:
        print("  REB_API_KEY 없음, 주간 시세 건너뜀")
        return [], []

    result, gu_vals = [], {}
    for kind, statbl_id in REB_WEEKLY_TABLES.items():
        series = []
        gu_week = {}   # 기준일 -> {구: 지수}
        for wid in _iso_week_ids(10):
            try:
                res = requests.get(REB_BASE_URL, params={
                    "KEY": REB_API_KEY, "Type": "json", "pIndex": 1, "pSize": 1000,
                    "STATBL_ID": statbl_id, "DTACYCLE_CD": "WK", "WRTTIME_IDTFR_ID": wid,
                }, timeout=30)
                body = res.json().get("SttsApiTblData", [])
            except Exception as e:
                print(f"  [{kind} {wid}] 오류: {e}")
                continue
            rows = body[1].get("row", []) if len(body) >= 2 else []
            for r in rows:
                full, v = r.get("CLS_FULLNM") or "", r.get("DTA_VAL")
                if v is None: continue
                day = (r.get("WRTTIME_DESC") or "").replace("-", "")
                if full == "서울":
                    series.append((r.get("WRTTIME_DESC", ""), float(v)))
                parts = full.split(">")
                if len(parts) == 4 and parts[0] == "서울" and parts[3].endswith("구"):
                    gu_week.setdefault(day, {})[parts[3]] = float(v)
        series.sort()
        print(f"  주간 {kind}지수 서울: {len(series)}주 수집")
        for i, (day, val) in enumerate(series):
            prev = series[i-1][1] if i > 0 else None
            result.append({
                "구분": kind, "지역": "서울", "기준일": day.replace("-", ""),
                "지수": round(val, 3),
                "변동률": round((val/prev - 1) * 100, 3) if prev else 0.0,
            })
        days = sorted(gu_week)
        if len(days) >= 2:
            cur, prv = gu_week[days[-1]], gu_week[days[-2]]
            gu_vals[kind] = (days[-1], {g: round((v/prv[g]-1)*100, 3) for g, v in cur.items() if g in prv and prv[g]})

    gu_rows = []
    for gu in SEOUL_GU_CODES:
        row = {"구": gu}
        for kind in ("매매", "전세"):
            if kind in gu_vals:
                row["기준일"] = gu_vals[kind][0]
                row[f"{kind}변동률"] = gu_vals[kind][1].get(gu)
        if "매매변동률" in row or "전세변동률" in row:
            gu_rows.append(row)
    print(f"  구별 주간 변동률: {len(gu_rows)}개 구")
    return result, gu_rows

def make_daily_recap(trade_dir, rent_dir, days=7):
    """최근 N일(전일까지) 계약 거래 요약. 신고 지연 때문에 하루 단위는 건수가 너무 적어 7일 창으로 집계."""
    today = datetime.today()
    end = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    yms = sorted({(today - timedelta(days=i)).strftime("%Y%m") for i in range(days + 1)})
    label = f"{start} ~ {end} (최근 {days}일)"

    recap = {
        "date": label,
        "trade": {"건수":0,"평균가":0,"최고가":0,"최고가_단지":"","구별":[]},
        "rent":  {"건수":0,"평균보증금":0,"구별":[]},
    }

    def load(dir_, col):
        frames = []
        for ym in yms:
            f = dir_ / f"{ym}.csv"
            if f.exists():
                frames.append(pd.read_csv(f, encoding="utf-8-sig"))
        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True)
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",",""), errors="coerce")
        df["날짜"] = df["년"].astype(str)+"-"+df["월"].astype(str).str.zfill(2)+"-"+df["일"].astype(str).str.zfill(2)
        return df[(df["날짜"] >= start) & (df["날짜"] <= end)]

    t = load(trade_dir, "거래금액")
    if t is not None and len(t) > 0 and not t["거래금액"].isna().all():
        recap["trade"]["건수"] = len(t)
        recap["trade"]["평균가"] = round(float(t["거래금액"].mean()), 0)
        m = t.loc[t["거래금액"].idxmax()]
        recap["trade"]["최고가"] = float(m["거래금액"])
        recap["trade"]["최고가_단지"] = f"{m['구']} {m['아파트명']}"
        g = t.groupby("구").size().reset_index(name="거래수")
        recap["trade"]["구별"] = g.sort_values("거래수", ascending=False).to_dict(orient="records")

    r = load(rent_dir, "보증금")
    if r is not None and len(r) > 0:
        recap["rent"]["건수"] = len(r)
        recap["rent"]["평균보증금"] = round(float(r["보증금"].mean()), 0) if not r["보증금"].isna().all() else 0
        g = r.groupby("구").size().reset_index(name="거래수")
        recap["rent"]["구별"] = g.sort_values("거래수", ascending=False).to_dict(orient="records")

    return recap

def build_summary(trade_dir, rent_dir, out_path):
    summary = {"trade":[],"rent":[],"jeonse_rate":[],"weekly_price":[],"weekly_gu":[],"daily_recap":{},"updated":datetime.today().strftime("%Y-%m-%d")}

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
    summary["weekly_price"], summary["weekly_gu"] = fetch_weekly_price()

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
        trade_all, rent_all, month_ok = [], [], True
        try:
            for gu_name, gu_code in SEOUL_GU_CODES.items():
                t, r, ok = fetch_all(gu_name, gu_code, ym)
                trade_all.extend(t); rent_all.extend(r); month_ok &= ok
        except QuotaExceeded as e:
            print(f"  ⚠ 일일 호출한도 초과({e}) — {ym} 이후 수집 중단, 기존 파일 유지")
            break
        if not month_ok and (trade_dir/f"{ym}.csv").exists():
            print(f"  ⚠ {ym}: 일부 구 수집 실패 — 기존 CSV 유지(덮어쓰지 않음)")
            continue
        save_csv(trade_all, trade_dir/f"{ym}.csv")
        save_csv(rent_all,  rent_dir/f"{ym}.csv")
    build_summary(trade_dir, rent_dir, Path("docs/data/summary.json"))
    print("\n✅ 수집 완료!")

if __name__ == "__main__":
    main()
