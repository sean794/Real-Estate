"""R-ONE 통계표 목록에서 주간 아파트 매매/전세 가격지수 STATBL_ID 후보를 찾아 출력"""
import os, json, requests
KEY = os.environ.get("REB_API_KEY", "")
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTbl.do"
print("key length:", len(KEY))
rows, raw = [], None
for page in range(1, 6):
    r = requests.get(URL, params={"KEY": KEY, "Type": "json", "pIndex": page, "pSize": 1000}, timeout=30)
    raw = r.text[:300]
    try:
        d = r.json()
    except Exception:
        print("JSON 아님:", raw); break
    body = d.get("SttsApiTbl")
    if not body:
        print("응답:", json.dumps(d, ensure_ascii=False)[:300]); break
    got = []
    for part in body:
        got += part.get("row", []) if isinstance(part, dict) else []
    if not got: break
    rows += got
    if len(got) < 1000: break
print("통계표 수:", len(rows))
for x in rows:
    nm = str(x.get("STATBL_NM", ""))
    cyc = str(x.get("DTACYCLE_NM", ""))
    if ("아파트" in nm) and (("매매" in nm) or ("전세" in nm)) and ("주" in cyc or "주간" in nm):
        print(x.get("STATBL_ID"), "|", nm, "|", cyc)
