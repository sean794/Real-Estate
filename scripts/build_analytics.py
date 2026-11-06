"""
단지·평형 단위 분석 + 구별 월별 추이 생성 (서버/로컬 공용, 메모리 절약형)
출력:
  docs/data/complexes.json  - 후보 단지 탭용 (단지×면적: 최근가/최고가/직전대비/12개월/전세/전세가율/갭)
  docs/data/new_highs.json  - 최근 신고가 갱신 목록
  docs/data/gu_trends.json  - 구별 월 거래량 / ㎡당 매매가 / ㎡당 전세가 / 전세가율
"""
import json, math
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from clean import clean_trade, clean_rent, new_contracts_only, has_new_schema_rent

TRADE_DIR, RENT_DIR = Path("data/apt_trade"), Path("data/apt_rent")
OUT = Path("docs/data")
TODAY = pd.Timestamp(datetime.today().date())
M2_TO_PY = 3.3058

def num(s): return pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")

def load_trade():
    frames = []
    for f in sorted(TRADE_DIR.glob("*.csv")):
        d = clean_trade(pd.read_csv(f, encoding="utf-8-sig", dtype=str))     # 해제(취소) 거래 제거
        d["ym"] = f.stem
        frames.append(d)
    if not frames: return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d["price"] = num(d["거래금액"]); d["area"] = num(d["전용면적"]); d["floor"] = num(d["층"])
    d["built"] = num(d["건축년도"])
    d["date"] = pd.to_datetime(d["년"].astype(str) + "-" + d["월"].astype(str).str.zfill(2) + "-" + d["일"].astype(str).str.zfill(2), errors="coerce")
    d = d.dropna(subset=["price", "area", "date"])
    d["a"] = d["area"].round().astype(int)
    d["ppm"] = d["price"] / d["area"]          # 만원/㎡
    return d

def build():
    OUT.mkdir(parents=True, exist_ok=True)
    t = load_trade()
    if t.empty:
        print("거래 데이터 없음"); return
    # 직거래(특수관계 가능)는 시세 판단에서 제외
    t_main = t[t.get("거래유형", "") != "직거래"].copy() if "거래유형" in t.columns else t.copy()

    key = ["구", "법정동", "아파트명", "a"]

    # ── 전월세: 월별 구 단위 집계 + 최근 4개월 단지 단위 보관 ───────────────
    rent_months = sorted(p.stem for p in RENT_DIR.glob("*.csv"))
    recent_rent_months = set(rent_months[-4:])         # 최근 4개월(갱신 제외 신규 전세)
    gu_month_rent = {}      # (ym, gu|None) -> (median ppm, n)   (신규 전세만, 최신 스키마 월만)
    recent_rent = []
    for ym in rent_months:
        d = clean_rent(pd.read_csv(RENT_DIR / f"{ym}.csv", encoding="utf-8-sig", dtype=str))
        if not has_new_schema_rent(d):
            continue                      # 계약구분(신규/갱신)을 모르는 옛 데이터는 전세 시세에 쓰지 않음(백필로 채워짐)
        d["dep"] = num(d["보증금"]); d["mon"] = num(d["월세"]).fillna(0); d["area"] = num(d["전용면적"])
        d = d.dropna(subset=["dep", "area"])
        d = new_contracts_only(d[(d["mon"] == 0) & (d["area"] > 0)])      # 전세 + 갱신계약 제외
        d["ppm"] = d["dep"] / d["area"]
        gu_month_rent[(ym, None)] = (float(d["ppm"].median()), int(len(d))) if len(d) else (0.0, 0)
        for gu, g in d.groupby("구"):
            gu_month_rent[(ym, gu)] = (float(g["ppm"].median()), int(len(g)))
        if ym in recent_rent_months:
            d["a"] = d["area"].round().astype(int)
            recent_rent.append(d[["구", "법정동", "아파트명", "a", "dep"]])
    rr = pd.concat(recent_rent, ignore_index=True) if recent_rent else pd.DataFrame(columns=["구", "법정동", "아파트명", "a", "dep"])
    jeonse = rr.groupby(key)["dep"].agg(["median", "count"]).rename(columns={"median": "j", "count": "jn"})

    # ── 단지×면적 집계 ───────────────────────────────────────────────────
    cut365 = TODAY - timedelta(days=365)
    cut90, cut180 = TODAY - timedelta(days=90), TODAY - timedelta(days=180)
    y_lo, y_hi = TODAY - timedelta(days=455), TODAY - timedelta(days=365)

    complexes, highs = [], []
    for k, g in t_main.groupby(key, sort=False):
        g = g.sort_values("date")
        if g["date"].iloc[-1] < cut365:
            continue
        last = g.iloc[-1]
        n = len(g)
        hi_idx = g["price"].idxmax()
        hi = g.loc[hi_idx]
        prev = g.iloc[-2] if n >= 2 else None
        r180 = g[g["date"] >= cut180]["price"]
        base = float(r180.median()) if len(r180) else None     # 최근 180일 거래가 없으면 전세가율·갭 계산 안 함(낡은 가격과 비교 방지)
        now90 = g[g["date"] >= cut90]["price"]
        old = g[(g["date"] >= y_lo) & (g["date"] <= y_hi)]["price"]
        ret12 = round((float(now90.median()) / float(old.median()) - 1) * 100, 1) if len(now90) and len(old) else None
        j = jeonse.loc[k] if k in jeonse.index else None
        jv = float(j["j"]) if j is not None else None
        rate = round(jv / base * 100, 1) if (jv and base) else None
        rec = {
            "gu": k[0], "dong": k[1], "name": k[2], "a": int(k[3]), "py": round(float(g["area"].mean()) / M2_TO_PY, 1),
            "built": int(g["built"].mode().iloc[0]) if g["built"].notna().any() else None,
            "n": n,
            "last": [int(last["price"]), last["date"].strftime("%Y-%m-%d"), int(last["floor"]) if pd.notna(last["floor"]) else None],
            "high": [int(hi["price"]), hi["date"].strftime("%Y-%m-%d")],
            "chg_prev": round((float(last["price"]) / float(prev["price"]) - 1) * 100, 1) if prev is not None else None,
            "ret12": ret12,
            "base": int(base) if base else None,
            "j": int(jv) if jv else None, "jn": int(j["jn"]) if j is not None else 0,
            "rate": rate, "gap": int(base - jv) if (jv and base) else None,
        }
        complexes.append(rec)
        # 신고가: 최근 30일 안에 직전까지의 최고가를 넘은 거래
        if n >= 3 and (TODAY - last["date"]).days <= 30:
            before = g.iloc[:-1]["price"].max()
            if last["price"] > before:
                highs.append({"gu": k[0], "dong": k[1], "name": k[2], "a": int(k[3]), "date": last["date"].strftime("%Y-%m-%d"),
                              "price": int(last["price"]), "prev_high": int(before),
                              "jump": round((float(last["price"]) / float(before) - 1) * 100, 1), "floor": rec["last"][2], "n": n})
    highs.sort(key=lambda x: (x["date"], x["jump"]), reverse=True)

    # ── 구별 월 추이 ────────────────────────────────────────────────────
    months = sorted(t["ym"].unique())
    gus = sorted(t["구"].unique())
    # 신고 지연으로 덜 모인 달: 직전 달 거래 수의 절반에 못 미치는 최근 달부터 '집계 중'
    cnt = [int(len(t_main[t_main["ym"] == m])) for m in months]
    fi = len(months) - 1
    while fi > 0 and cnt[fi] < 0.5 * cnt[fi - 1]:
        fi -= 1
    trends = {"months": months, "partial_from": months[fi + 1] if fi + 1 < len(months) else "999999", "gu": {}}
    def series(gu):
        vol, ppm, jp, rate = [], [], [], []
        for ym in months:
            g = t_main[(t_main["ym"] == ym) & ((t_main["구"] == gu) if gu else True)]
            vol.append(int(len(g)))
            p = float(g["ppm"].median()) if len(g) >= 3 else None
            ppm.append(round(p, 1) if p else None)
            jr = gu_month_rent.get((ym, gu if gu else None))
            jpv = jr[0] if jr and jr[1] >= 5 else None
            jp.append(round(jpv, 1) if jpv else None)
            rate.append(round(jpv / p * 100, 1) if jpv and p else None)
        return {"vol": vol, "ppm": ppm, "jppm": jp, "rate": rate}
    trends["gu"]["서울 전체"] = series(None)
    for gu in gus:
        trends["gu"][gu] = series(gu)

    def dump(name, obj):
        (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {name}: {(OUT / name).stat().st_size/1024:.0f}KB")
    meta = {"updated": datetime.today().strftime("%Y-%m-%d"), "months": months}
    # 구별 전세가율: 같은 단지·면적끼리 비교한 값(매매·전세 각 2건 이상)의 중위수
    import statistics as _st
    jg = {}
    for r in complexes:
        if r["rate"] is not None and r["jn"] >= 2 and r["n"] >= 2:
            jg.setdefault(r["gu"], []).append(r)
    jeonse_gu = []
    for gu_, rs in jg.items():
        if len(rs) < 5:
            continue
        rt = round(_st.median(x["rate"] for x in rs), 1)
        jeonse_gu.append({"구": gu_, "전세가율": rt, "단지수": len(rs),
                          "매매중위가": int(_st.median(x["base"] for x in rs)), "전세중위가": int(_st.median(x["j"] for x in rs)),
                          "신호": "매수고려" if rt >= 60 else ("주의" if rt >= 50 else "관망")})
    jeonse_gu.sort(key=lambda x: x["전세가율"], reverse=True)
    dump("jeonse_gu.json", {**meta, "items": jeonse_gu})
    dump("complexes.json", {**meta, "items": complexes})
    dump("new_highs.json", {**meta, "items": highs[:300]})
    dump("gu_trends.json", trends)
    print(f"단지×면적 {len(complexes)}건, 신고가 {len(highs)}건, 구 {len(gus)}개 × {len(months)}개월")

if __name__ == "__main__":
    build()
