#!/usr/bin/env bash
# 원본 XML 필드 점검 (조회 전용, API 4회 호출)
python3 - <<'PY'
import os, requests, collections
import xml.etree.ElementTree as ET
T=os.environ["MOLIT_TRADE_API_KEY"]; R=os.environ["MOLIT_RENT_API_KEY"]
def get(url,key,code,ym):
    items=[];page=1
    while True:
        r=requests.get(url,params={"serviceKey":key,"LAWD_CD":code,"DEAL_YMD":ym,"pageNo":page,"numOfRows":1000},timeout=30)
        root=ET.fromstring(r.content)
        its=[{c.tag:(c.text or "").strip() for c in i} for i in root.findall(".//item")]
        items+=its; tot=int(root.findtext(".//totalCount") or 0)
        if not its or len(items)>=tot: break
        page+=1
    return items,tot
tu="http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
ru="http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
for name,url,key,code,ym in (("매매 강동 202506",tu,T,"11740","202506"),("매매 강동 202610",tu,T,"11740","202610"),("전월세 강동 202610",ru,R,"11740","202610"),("전월세 광진 202606",ru,R,"11215","202606")):
    it,tot=get(url,key,code,ym)
    print("==",name,"rows",len(it),"totalCount",tot)
    if not it: continue
    print("fields:",list(it[0].keys()))
    for f in ("cdealType","cdealDay","dealingGbn","contractType","useRRRight","aptDong","buyerGbn","slerGbn"):
        if f in it[0]: print(f, collections.Counter(x.get(f,"") for x in it).most_common(6))
    key_all=lambda x:tuple(sorted(x.items()))
    c=collections.Counter(key_all(x) for x in it)
    print("완전동일(모든 필드) 중복 행:",sum(v-1 for v in c.values() if v>1))
    base=("aptNm","excluUseAr","floor","dealAmount","deposit","monthlyRent","dealYear","dealMonth","dealDay","umdNm")
    c2=collections.Counter(tuple(x.get(f) for f in base) for x in it)
    print("핵심필드 동일 중복 행:",sum(v-1 for v in c2.values() if v>1))
    shown=0
    for k,v in c2.items():
        if v>1 and shown<2:
            print(" 예시:",[ {f:x.get(f) for f in ("aptNm","aptDong","excluUseAr","floor","dealAmount","dealDay","cdealType","cdealDay","dealingGbn","rgstDate","jibun","contractType") if f in x} for x in it if tuple(x.get(f) for f in base)==k]); shown+=1
PY
