#!/usr/bin/env bash
# 청약홈 분양정보 API 활성화 여부 확인 (키 값은 출력하지 않음)
for K in MOLIT_TRADE_API_KEY MOLIT_RENT_API_KEY REB_API_KEY; do
  KEY="${!K:-}"; [ -z "$KEY" ] && continue
  echo "--- $K 로 호출"
  curl -s -m 25 -G "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail" \
    --data-urlencode "page=1" --data-urlencode "perPage=2" --data-urlencode "serviceKey=$KEY" \
    --data-urlencode "cond[SUBSCRPT_AREA_CODE_NM::EQ]=서울" | head -c 900; echo
done
