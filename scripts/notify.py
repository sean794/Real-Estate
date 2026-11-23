"""서버 이상 알림: NTFY_TOPIC 이 설정돼 있으면 ntfy.sh 로 푸시(폰 ntfy 앱에서 해당 토픽 구독). 없으면 조용히 종료."""
import os, sys, urllib.request
topic = os.environ.get("NTFY_TOPIC", "").strip()
if not topic:
    print("NTFY_TOPIC 없음 - 알림 생략"); sys.exit(0)
title, body = (sys.argv + ["", ""])[1:3]
req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                             headers={"Title": "Seoul-RE alert", "Priority": "high", "Tags": "warning"})
try:
    urllib.request.urlopen(req, timeout=15); print("알림 전송")
except Exception as e:
    print("알림 실패:", e)
