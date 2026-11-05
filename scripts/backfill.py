"""
과거 실거래 백필 (최근 N개월). 일일 호출한도에 걸리면 조용히 멈추고 다음 실행에서 이어서 수집.
 - 구/종류별 중간 결과는 data/_partial/ 에 캐시 (git 제외)
 - 한 달치(25개 구 × 매매·전월세)가 다 모이면 data/apt_trade|apt_rent/YYYYMM.csv 로 저장
사용: python3 scripts/backfill.py [--months 36] [--max-calls 800]
"""
import argparse, sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import fetch_data as fd

PARTIAL = Path("data/_partial")

def month_list(n):
    t = datetime.today()
    y, m = t.year, t.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0: y, m = y - 1, 12
    return out  # 최신 -> 과거

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=36)
    ap.add_argument("--max-calls", type=int, default=800, help="이번 실행에서 쓸 최대 호출 수(일일 쿼터 보호)")
    args = ap.parse_args()

    trade_dir, rent_dir = Path("data/apt_trade"), Path("data/apt_rent")
    todo = [ym for ym in month_list(args.months)[3:]            # 최근 3개월은 일일 수집이 담당
            if not ((trade_dir/f"{ym}.csv").exists() and (rent_dir/f"{ym}.csv").exists())]
    if not todo:
        print("백필: 모두 완료"); return
    print(f"백필 대기 {len(todo)}개월: {todo[0]} ~ {todo[-1]}")

    calls, done = 0, 0
    kinds = {
        "trade": (fd.BASE_TRADE_URL, fd.TRADE_API_KEY, fd.parse_trade, trade_dir),
        "rent":  (fd.BASE_RENT_URL,  fd.RENT_API_KEY,  fd.parse_rent,  rent_dir),
    }
    try:
        for ym in todo:
            month_ok = True
            for gu_name, gu_code in fd.SEOUL_GU_CODES.items():
                for kind, (url, key, parser, _) in kinds.items():
                    cache = PARTIAL / kind / f"{ym}_{gu_code}.csv"
                    if cache.exists():
                        continue
                    if calls >= args.max_calls:
                        raise fd.QuotaExceeded("자체 호출 상한")
                    try:
                        recs = fd.fetch_paged(url, {"serviceKey": key, "LAWD_CD": gu_code, "DEAL_YMD": ym}, parser, gu_name)
                        calls += 1
                    except fd.QuotaExceeded:
                        raise
                    except Exception as e:
                        month_ok = False
                        print(f"  [{kind} 오류] {gu_name} {ym}: {e}")
                        continue
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    if recs: pd.DataFrame(recs).to_csv(cache, index=False, encoding="utf-8-sig")
                    else: cache.write_text("")
            if not month_ok:
                continue
            for kind, (_, _, _, out_dir) in kinds.items():
                frames = []
                for gu_code in fd.SEOUL_GU_CODES.values():
                    c = PARTIAL / kind / f"{ym}_{gu_code}.csv"
                    if c.exists() and c.stat().st_size > 0:
                        frames.append(pd.read_csv(c, encoding="utf-8-sig", dtype=str))
                if frames:
                    df = pd.concat(frames, ignore_index=True)
                    fd.save_csv(df.to_dict("records"), out_dir / f"{ym}.csv")
                for gu_code in fd.SEOUL_GU_CODES.values():
                    (PARTIAL / kind / f"{ym}_{gu_code}.csv").unlink(missing_ok=True)
            done += 1
            print(f"  ✔ {ym} 백필 완료 (누적 호출 {calls})")
    except fd.QuotaExceeded as e:
        print(f"  ⏸ 호출 한도 도달({e}) — 오늘은 여기까지, 다음 실행에서 이어서 진행")
    print(f"백필 이번 실행: {done}개월 완료, 호출 {calls}회, 남은 {len(todo)-done}개월")

if __name__ == "__main__":
    main()
