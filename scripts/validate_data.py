"""데이터 검증 — 매 수집 직후 자동 실행. 결과는 logs/validation.txt (FAIL이 있으면 종료코드 1)

원천 CSV, summary.json, 분석 JSON을 서로 교차 확인한다. '화면이 그려지는지'가 아니라 '숫자가 맞는지'를 본다.
"""
import json, sys, statistics as st
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from clean import clean_trade, clean_rent

GU = ["종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구","은평구","서대문구","마포구","양천구","강서구","구로구","금천구","영등포구","동작구","관악구","서초구","강남구","송파구","강동구"]
res = []
def check(name, ok, detail="", warn=False):
    res.append(("OK" if ok else ("WARN" if warn else "FAIL"), name, detail))

T, R = sorted(Path("data/apt_trade").glob("*.csv")), sorted(Path("data/apt_rent").glob("*.csv"))
check("매매·전월세 월 파일 수 일치", len(T) == len(R) and len(T) >= 36, f"매매 {len(T)} / 전월세 {len(R)}")

counts = {}
for kind, files, col in (("매매", T, "해제여부"), ("전월세", R, "계약구분")):
    stale, miss_gu = [], []
    for f in files:
        d = pd.read_csv(f, encoding="utf-8-sig", dtype=str, usecols=lambda c: c in ("구", col))
        if col not in d.columns: stale.append(f.stem)
        g = set(d["구"].unique())
        if f.stem != files[-1].stem and len(g) < 25: miss_gu.append(f"{f.stem}:{25-len(g)}개 구 없음")
        counts[(kind, f.stem)] = len(d)
    check(f"{kind}: 최신 스키마({col})", not stale, f"옛 형식 {stale[:6]}")
    check(f"{kind}: 모든 월에 25개 구", not miss_gu, ", ".join(miss_gu[:6]))

# 월별 건수 급변(30일 신고 지연 때문에 최근 3개월은 제외)
for kind in ("매매", "전월세"):
    ms = sorted(m for (k, m) in counts if k == kind)[:-3]
    bad = [m for a, m in zip(ms, ms[1:]) if counts[(kind, m)] < 0.3 * counts[(kind, a)] or counts[(kind, m)] > 3.5 * counts[(kind, a)]]
    check(f"{kind}: 월별 건수 급변 없음", not bad, f"{bad}", warn=True)

# 매매 정제: 해제 반영 여부, 단일 구 쏠림
last = T[-2]
raw = pd.read_csv(last, encoding="utf-8-sig", dtype=str)
cl = clean_trade(raw)
canc = (raw.get("해제여부", pd.Series(dtype=str)).fillna("") == "O").sum()
check("매매: 해제 건 제거됨", len(raw) - len(cl) >= canc, f"{last.stem} 원본 {len(raw)} -> 정제 {len(cl)} (해제 {canc})")
main = cl[cl["거래유형"] != "직거래"]
top = main.groupby(["구", "아파트명", "전용면적", "층", "거래금액", "일"]).size().max()
check("매매: 중개거래에 동일 행 대량 반복 없음", top < 5, f"최대 반복 {top}건", warn=True)

# summary 교차검증
S = json.load(open("docs/data/summary.json"))
check("summary: 매매 36개월 / 전월세 갱신제외 적용", len(S["trade"]) >= 36 and all(x.get("갱신제외") for x in S["rent"]), f"{len(S['trade'])}개월")
check("summary: 주간 지수 수집", len(S.get("weekly_price", [])) >= 10 and len(S.get("weekly_gu", [])) == 25, f"{len(S.get('weekly_price', []))}행 / 구 {len(S.get('weekly_gu', []))}")
rc = S["daily_recap"]
check("summary: 최근 7일 요약 값 존재", rc["trade"]["건수"] > 0 and rc["rent"]["건수"] > 0, rc["date"], warn=True)

# 구별 중위가: summary vs 원본 재계산(마지막 확정 월)
ref = S["trade"][-2]; ym = ref["ym"]
d = clean_trade(pd.read_csv(f"data/apt_trade/{ym}.csv", encoding="utf-8-sig", dtype=str))
d = d[d["거래유형"] != "직거래"]; d["p"] = pd.to_numeric(d["거래금액"].str.replace(",", ""), errors="coerce")
diffs = []
for g in ref["구별"]:
    sub = d[d["구"] == g["구"]]["p"].dropna()
    if len(sub) >= 3:
        q1, q3 = sub.quantile(.25), sub.quantile(.75); f = sub[(sub >= q1 - 1.5 * (q3 - q1)) & (sub <= q3 + 1.5 * (q3 - q1))]
        if abs(f.median() / g["중위가"] - 1) > 0.02: diffs.append(g["구"])
check(f"구별 중위가가 원본 재계산과 일치({ym})", not diffs, f"불일치 {diffs}")
check("거래수 = 정제 후 중개거래 건수", ref["거래수"] == len(d), f"summary {ref['거래수']} / 재계산 {len(d)}")

# 전세가율 범위·일관성
J = json.load(open("docs/data/jeonse_gu.json"))["items"]
rates = [x["전세가율"] for x in J]
check("전세가율 25개 구 산출", len(J) == 25, f"{len(J)}개")
check("전세가율 현실 범위(25~90%)", all(25 <= r <= 90 for r in rates), f"최소 {min(rates)} 최대 {max(rates)}")
Tn = json.load(open("docs/data/gu_trends.json"))
sr = [x for x in Tn["gu"]["서울 전체"]["rate"] if x][-1]
check("추이 탭과 전세가율 탭 일치(±8%p)", abs(sr - st.mean(rates)) <= 8, f"추이 {sr} / 탭 평균 {st.mean(rates):.1f}")

# 단지 분석 무결성
C = json.load(open("docs/data/complexes.json"))["items"]
check("단지: 최고가 >= 최근가", all(x["high"][0] >= x["last"][0] for x in C))
check("단지: 전세가율 있는 단지는 180일 내 거래 있음", all(x["base"] for x in C if x["rate"]))
H = json.load(open("docs/data/new_highs.json"))["items"]
check("신고가: 모두 직전 최고가 초과", all(x["price"] > x["prev_high"] for x in H))


# ── 추가 분석(갱신 인상률 / 해제 비율 / 하락 거래 / 단지 이력) ──
import csv, random, datetime
RN = json.load(open("docs/data/renewal.json"))
rm = RN["recent_months"][-1]; gi = RN["months"].index(rm)
v = []
seen = set()
for r in csv.DictReader(open(f"data/apt_rent/{rm}.csv", encoding="utf-8-sig")):
    if r["구"] != "강남구" or r["계약구분"] != "갱신": continue
    k = tuple(r[c] for c in ("법정동", "아파트명", "전용면적", "층", "보증금", "월세", "일"))
    if k in seen: continue
    seen.add(k)
    try:
        d_, p_ = float(r["보증금"].replace(",", "")), float(r["종전보증금"].replace(",", "")); m_, pm_ = float(r["월세"] or 0), float(r["종전월세"] or 0)
    except ValueError: continue
    if m_ == 0 and pm_ == 0 and p_ > 0 and 0.5 <= d_ / p_ <= 2: v.append((d_ / p_ - 1) * 100)
s_ = RN["gu"]["강남구"][gi]
check(f"갱신 인상률: 원본 독립 재계산 일치(강남구 {rm})", s_ and s_["n"] == len(v) and abs(s_["mean"] - st.mean(v)) < 0.02 and abs(s_["med"] - st.median(v)) < 0.02,
      f"JSON n={s_ and s_['n']} 평균={s_ and s_['mean']} / 재계산 n={len(v)} 평균={st.mean(v):.2f}")
allr = [x for x in RN["gu"]["서울 전체"] if x]
check("갱신 인상률: 서울 평균이 현실 범위(-5~20%)", all(-5 <= x["mean"] <= 20 for x in allr), f"{min(x['mean'] for x in allr)}~{max(x['mean'] for x in allr)}")

CN = json.load(open("docs/data/cancel.json"))
cm = CN["months"][-4]; ci = CN["months"].index(cm)
tot = c_ = 0
for r in csv.DictReader(open(f"data/apt_trade/{cm}.csv", encoding="utf-8-sig")):
    tot += 1; c_ += (r.get("해제여부") or "").strip() == "O"
check(f"해제 비율: 원본 재계산 일치({cm})", abs(CN["gu"]["서울 전체"][ci] - c_ / (tot - c_) * 100) < 0.02, f"JSON {CN['gu']['서울 전체'][ci]} / 재계산 {c_/(tot-c_)*100:.2f}")
allc = [x for x in CN["gu"]["서울 전체"] if x is not None]
check("해제 비율: 0~30% 범위", all(0 <= x <= 30 for x in allc), f"최대 {max(allc)}", warn=True)

random.seed(7)
C = json.load(open("docs/data/complexes.json"))["items"]
cache, bad = {}, []
for x in random.sample(C, 300):
    m = cache.setdefault(x["gu"], json.load(open(f"docs/data/cx/{x['gu']}.json")))
    h = m.get(f"{x['dong']}|{x['name']}|{x['a']}")
    if not h or len(h["t"]) != x["n"] or h["t"][-1][0] // 100 != int(x["last"][1][:7].replace("-", "")): bad.append(x["name"])
check("단지 상세 이력: complexes.json과 거래 건수·최근 거래월 일치(300개 표본)", not bad, f"불일치 {bad[:5]}")

PD = json.load(open("docs/data/price_drops.json"))["items"]
bad = []
for x in random.sample(PD, min(25, len(PD))):
    h = cache.setdefault(x["gu"], json.load(open(f"docs/data/cx/{x['gu']}.json")))[f"{x['dong']}|{x['name']}|{x['a']}"]
    dt = int(x["date"].replace("-", ""))
    lo = int((datetime.date.fromisoformat(x["date"]) - datetime.timedelta(days=365)).strftime("%Y%m%d"))
    pr = [t[1] for t in h["t"] if lo <= t[0] < dt]
    if len(pr) != x["ref_n"] or abs(st.median(pr) - x["ref"]) > 1 or abs((x["price"] / x["ref"] - 1) * 100 - x["drop"]) > 0.06: bad.append(x["name"])
check("하락 거래: 직전 1년 중위가·하락률 독립 재계산 일치", not bad, f"불일치 {bad[:5]}")
check("하락 거래: 모두 10% 이상 하락·표본 3건 이상", all(x["drop"] <= -10 and x["ref_n"] >= 3 for x in PD))

# 데이터 신선도
upd = datetime.date.fromisoformat(S["updated"]); age = (datetime.date.today() - upd).days
check("summary 갱신일 3일 이내", age <= 3, f"{S['updated']} ({age}일 전)", warn=True)

# NaN/무한대
txt = open("docs/data/summary.json", encoding="utf-8").read()
check("summary에 NaN/Infinity 없음", "NaN" not in txt and "Infinity" not in txt)

fails_ = [r for r in res if r[0] == "FAIL"]
Path("docs/data/status.json").write_text(json.dumps({"checked": datetime.date.today().isoformat(), "total": len(res), "fail": len(fails_),
    "warn": sum(r[0] == "WARN" for r in res), "failed": [r[1] for r in fails_][:8], "updated": S["updated"]}, ensure_ascii=False), encoding="utf-8")
out = "\n".join(f"[{s}] {n}  {d}" for s, n, d in res)
Path("logs").mkdir(exist_ok=True); Path("logs/validation.txt").write_text(out + "\n", encoding="utf-8")
print(out); fails = [r for r in res if r[0] == "FAIL"]
print(f"\n검증 {len(res)}개 중 FAIL {len(fails)} / WARN {sum(r[0]=='WARN' for r in res)}")
sys.exit(1 if fails else 0)
