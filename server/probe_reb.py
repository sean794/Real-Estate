"""주간 가격지수 통계표의 실제 응답 구조 확인 (필터 없이 + 최근 기간)"""
import os, json, requests
KEY = os.environ["REB_API_KEY"]
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
for sid in ["T244183132827305", "T247713133046872"]:
    for extra in [{}, {"WRTTIME_IDTFR_ID": "2026"}, {"WRTTIME_IDTFR_ID": "202610"}]:
        p = {"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 5, "STATBL_ID": sid, "DTACYCLE_CD": "WK", **extra}
        try:
            r = requests.get(URL, params=p, timeout=30)
            print(f"\n## {sid} {extra} -> HTTP {r.status_code}")
            print(r.text[:1200])
        except Exception as e:
            print(f"\n## {sid} {extra} -> 오류 {e}")
