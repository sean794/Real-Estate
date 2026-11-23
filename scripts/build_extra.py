"""추가 분석 (메모리 절약: 필요한 열·기간만 읽음)
출력 (docs/data/):
  renewal.json     - 전세 갱신 인상률 (구×월 + 최근 3개월 구별 요약)
  cancel.json      - 구×월 매매 해제(취소) 비율
  price_drops.json - 같은 단지·면적의 직전 1년 중위가보다 크게 낮은 최근 거래(급매/조정 후보)
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from clean import clean_trade, clean_rent, has_new_schema_rent, has_new_schema_trade

TRADE_DIR, RENT_DIR, OUT = Path("data/apt_trade"), Path("data/apt_rent"), Path("docs/data")
TODAY = pd.Timestamp(datetime.today().date())

def num(s): return pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")

def rd(f, cols=None):
    return pd.read_csv(f, encoding="utf-8-sig", dtype=str, usecols=(lambda c: c in cols) if cols else None)

def stats(r):
    """r: ratio Series(신보증금/종전보증금). 인상률(%) 요약"""
    n = len(r)
    if n == 0: return None
    pct = (r - 1) * 100
    return {"n": int(n), "med": round(float(pct.median()), 2), "mean": round(float(pct.mean()), 2),
            "up": round(float((pct > 0.1).mean() * 100), 1), "flat": round(float((pct.abs() <= 0.1).mean() * 100), 1),
            "down": round(float((pct < -0.1).mean() * 100), 1),
            "over5": round(float((pct > 5.1).mean() * 100), 1)}      # 법정 상한(5%)을 넘겨 올린 비율

def renewal():
    files = sorted(RENT_DIR.glob("*.csv"))
    cols = {"구", "보증금", "월세", "년", "월", "일", "계약구분", "갱신권사용", "종전보증금", "종전월세", "법정동", "아파트명", "전용면적", "층"}
    per = {}   # ym -> DataFrame(구, r, use)
    for f in files:
        d = clean_rent(rd(f, cols))
        if not has_new_schema_rent(d): continue
        d = d[d["계약구분"].fillna("").str.strip() == "갱신"].copy()
        d["dep"], d["pre"] = num(d["보증금"]), num(d["종전보증금"])
        d["mon"], d["pmon"] = num(d["월세"]).fillna(0), num(d["종전월세"]).fillna(0)
        d = d[(d["mon"] == 0) & (d["pmon"] == 0) & (d["pre"] > 0) & (d["dep"] > 0)]     # 순수 전세 갱신만
        d["r"] = d["dep"] / d["pre"]
        d = d[(d["r"] >= 0.5) & (d["r"] <= 2.0)]                                         # 입력 오류성 이상치 제외
        d["use"] = d["갱신권사용"].fillna("").str.strip().eq("사용")
        per[f.stem] = d[["구", "r", "use"]]
    months = sorted(per)
    cnt = [len(per[m]) for m in months]
    fi = len(months) - 1
    while fi > 0 and cnt[fi] < 0.5 * cnt[fi - 1]: fi -= 1
    gus = sorted(set().union(*[set(per[m]["구"]) for m in months]))
    out = {"months": months, "partial_from": months[fi + 1] if fi + 1 < len(months) else "999999", "gu": {}, "recent": []}
    def ser(gu):
        rows = []
        for m in months:
            d = per[m] if gu is None else per[m][per[m]["구"] == gu]
            s = stats(d["r"]) if len(d) >= 10 else None
            if s: s["use"] = round(float(d["use"].mean() * 100), 1)
            rows.append(s)
        return rows
    out["gu"]["서울 전체"] = ser(None)
    for g in gus: out["gu"][g] = ser(g)
    full = months[: fi + 1][-3:]                       # 마지막 확정 3개월 합산
    out["recent_months"] = full
    pool = pd.concat([per[m] for m in full], ignore_index=True)
    for g in gus + [None]:
        d = pool if g is None else pool[pool["구"] == g]
        if len(d) < 30: continue
        s = stats(d["r"]); s["use"] = round(float(d["use"].mean() * 100), 1)
        # 갱신청구권 미사용(=시장 협의) 갱신의 인상률
        nu = d[~d["use"]]
        s["med_nouse"] = round(float(((nu["r"] - 1) * 100).median()), 2) if len(nu) >= 10 else None
        s["gu"] = g or "서울 전체"
        out["recent"].append(s)
    out["recent"].sort(key=lambda x: (x["gu"] != "서울 전체", -x["med"]))
    return out

def cancel():
    files = sorted(TRADE_DIR.glob("*.csv"))
    months, gus_all, per = [], set(), {}
    for f in files:
        d = rd(f, {"구", "해제여부"})
        if not has_new_schema_trade(d): continue
        c = d["해제여부"].fillna("").str.strip().eq("O")
        # 해제 1건 = 원 행 1 + 해제 표시 행 1 → 체결(원 거래) 수 = 전체 행 - 해제 표시 행
        agg = pd.DataFrame({"구": d["구"], "c": c}).groupby("구")["c"].agg(["sum", "size"])
        per[f.stem] = agg; months.append(f.stem); gus_all |= set(agg.index)
    out = {"months": months, "gu": {}}
    def ser(gu):
        rows = []
        for m in months:
            a = per[m]
            c, tot = (a["sum"].sum(), a["size"].sum()) if gu is None else ((a.loc[gu, "sum"], a.loc[gu, "size"]) if gu in a.index else (0, 0))
            deals = tot - c
            rows.append(round(float(c / deals * 100), 2) if deals >= 30 else None)
        return rows
    out["gu"]["서울 전체"] = ser(None)
    for g in sorted(gus_all): out["gu"][g] = ser(g)
    # 신고 지연으로 해제가 아직 덜 반영된 최근 2개월은 화면에서 '집계 중' 처리
    out["partial_last"] = 2
    return out

def drops():
    files = sorted(TRADE_DIR.glob("*.csv"))[-16:]
    cols = {"구", "법정동", "아파트명", "전용면적", "층", "거래금액", "년", "월", "일", "해제여부", "거래유형", "건축년도"}
    fr = []
    for f in files:
        d = clean_trade(rd(f, cols))
        if "거래유형" in d.columns: d = d[d["거래유형"] != "직거래"]
        fr.append(d)
    t = pd.concat(fr, ignore_index=True)
    t["price"], t["area"], t["floor"] = num(t["거래금액"]), num(t["전용면적"]), num(t["층"])
    t["date"] = pd.to_datetime(t["년"].astype(str) + "-" + t["월"].astype(str).str.zfill(2) + "-" + t["일"].astype(str).str.zfill(2), errors="coerce")
    t = t.dropna(subset=["price", "area", "date"])
    t["a"] = t["area"].round().astype(int)
    key = ["구", "법정동", "아파트명", "a"]
    res = []
    lo = TODAY - timedelta(days=90)
    for k, g in t.groupby(key, sort=False):
        g = g.sort_values("date")
        if g["date"].iloc[-1] < lo or len(g) < 4: continue
        for _, row in g[g["date"] >= lo].iterrows():
            prior = g[(g["date"] < row["date"]) & (g["date"] >= row["date"] - timedelta(days=365))]
            if len(prior) < 3: continue
            ref = float(prior["price"].median())
            drop = row["price"] / ref - 1
            if drop <= -0.10:
                res.append({"gu": k[0], "dong": k[1], "name": k[2], "a": int(k[3]), "date": row["date"].strftime("%Y-%m-%d"),
                            "price": int(row["price"]), "ref": int(ref), "drop": round(drop * 100, 1),
                            "floor": int(row["floor"]) if pd.notna(row["floor"]) else None,
                            "ref_n": int(len(prior)), "ref_min": int(prior["price"].min())})
    res.sort(key=lambda x: x["drop"])
    return res[:300], len(res)


def history():
    """단지 상세 차트용: 구별 파일(docs/data/cx/{구}.json). 키 '법정동|단지|전용면적(반올림)'.
    t=[[YYYYMMDD,가격,층],...] 매매(직거래 제외, 해제 제거, 36개월), j=[[YYYYMMDD,보증금],...] 신규 전세(18개월)"""
    d_out = OUT / "cx"; d_out.mkdir(parents=True, exist_ok=True)
    by = {}
    def add(gu, k, kind, row):
        by.setdefault(gu, {}).setdefault(k, {"t": [], "j": []})[kind].append(row)
    for f in sorted(TRADE_DIR.glob("*.csv")):
        d = clean_trade(rd(f, {"구", "법정동", "아파트명", "전용면적", "층", "거래금액", "년", "월", "일", "해제여부", "거래유형"}))
        if "거래유형" in d.columns: d = d[d["거래유형"] != "직거래"]
        p, a, fl = num(d["거래금액"]), num(d["전용면적"]), num(d["층"])
        ymd = num(d["년"]) * 10000 + num(d["월"]) * 100 + num(d["일"])
        ai = a.round()
        ok = p.notna() & a.notna() & ymd.notna()
        for gu, dong, nm, aa, dt, pp, ff in zip(d["구"][ok], d["법정동"][ok], d["아파트명"][ok], ai[ok], ymd[ok], p[ok], fl[ok]):
            add(gu, f"{dong}|{nm}|{int(aa)}", "t", [int(dt), int(pp), None if pd.isna(ff) else int(ff)])
    for f in sorted(RENT_DIR.glob("*.csv"))[-18:]:
        d = clean_rent(rd(f, {"구", "법정동", "아파트명", "전용면적", "보증금", "월세", "년", "월", "일", "계약구분", "층"}))
        if not has_new_schema_rent(d): continue
        d = d[d["계약구분"].fillna("").str.strip() != "갱신"]
        dep, a, mon = num(d["보증금"]), num(d["전용면적"]), num(d["월세"]).fillna(0)
        ymd = num(d["년"]) * 10000 + num(d["월"]) * 100 + num(d["일"])
        ok = dep.notna() & a.notna() & ymd.notna() & (mon == 0) & (a > 0)
        ai = a.round()
        for gu, dong, nm, aa, dt, dd in zip(d["구"][ok], d["법정동"][ok], d["아파트명"][ok], ai[ok], ymd[ok], dep[ok]):
            add(gu, f"{dong}|{nm}|{int(aa)}", "j", [int(dt), int(dd)])
    tot = 0
    for gu, m in by.items():
        for v in m.values():
            v["t"].sort(); v["j"].sort()
        (d_out / f"{gu}.json").write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tot += (d_out / f"{gu}.json").stat().st_size
    print(f"  cx/*.json: {len(by)}개 구 {tot/1024:.0f}KB")

def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {name}: {(OUT / name).stat().st_size/1024:.0f}KB")

if __name__ == "__main__":
    meta = {"updated": datetime.today().strftime("%Y-%m-%d")}
    dump("renewal.json", {**meta, **renewal()})
    dump("cancel.json", {**meta, **cancel()})
    items, total = drops()
    dump("price_drops.json", {**meta, "total": total, "items": items})
    history()
    print(f"갱신/해제/하락 완료: 하락거래 {total}건")
