#!/usr/bin/env bash
# 서버에서 1회 실행: 5분 폴링 + 일일 수집 cron 을 겹침 방지(flock)와 함께 등록
set -e
R="$HOME/Real-Estate"
chmod +x "$R"/server/*.sh "$R"/server/jobs/*.sh
# 이미 처리된 요청은 다시 실행하지 않도록 현재 요청 ID 를 기록
[ -f "$R/server/request.txt" ] && sed -n 1p "$R/server/request.txt" | tr -d '\r ' > "$HOME/.last_job_id" || true
( crontab -l 2>/dev/null | grep -v -e run_daily.sh -e "server/poll.sh" -e "^CRON_TZ"
  echo "CRON_TZ=Asia/Seoul"
  echo "30 0 * * * flock -n /tmp/realestate.lock $R/server/run_daily.sh"
  echo "*/5 * * * * flock -n /tmp/realestate.lock $R/server/poll.sh"
) | crontab -
crontab -l
