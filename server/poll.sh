#!/usr/bin/env bash
# 5분마다 cron 으로 실행: 저장소의 server/request.txt 를 보고 요청된 작업을 실행한 뒤 결과 로그를 push
#   request.txt 형식:  1행 = 요청 ID(바뀌면 실행),  2행 = 작업 이름
#   작업: daily | backfill | analytics | 그 외는 server/jobs/<이름>.sh
set -u
REPO_DIR="${REPO_DIR:-$HOME/Real-Estate}"
cd "$REPO_DIR" || exit 1
git pull --rebase --autostash -q 2>/dev/null || exit 0
REQ=server/request.txt
[ -f "$REQ" ] || exit 0
ID=$(sed -n 1p "$REQ" | tr -d '\r '); JOB=$(sed -n 2p "$REQ" | tr -d '\r ')
[ -n "$ID" ] && [ -n "$JOB" ] || exit 0
STATE="${STATE_FILE:-$HOME/.last_job_id}"
[ "$ID" = "$(cat "$STATE" 2>/dev/null)" ] && exit 0
echo "$ID" > "$STATE"

[ -f "$HOME/.realestate.env" ] && { set -a; . "$HOME/.realestate.env"; set +a; }
mkdir -p logs
{
  echo "=== job '$JOB' (id $ID) start $(date '+%F %T %Z') ==="
  case "$JOB" in
    daily)     bash server/run_daily.sh ;;
    backfill)  python3 scripts/backfill.py --months 36 --max-calls 1200 ;;
    analytics) python3 scripts/build_analytics.py ;;
    *)
      if [[ "$JOB" =~ ^[A-Za-z0-9_-]+$ ]] && [ -f "server/jobs/$JOB.sh" ]; then bash "server/jobs/$JOB.sh"
      else echo "알 수 없는 작업: $JOB"; fi ;;
  esac
  echo "=== end $(date '+%F %T %Z') ==="
} 2>&1 | tail -n 400 > logs/job_result.log

for d in logs data docs/data; do [ -d "$d" ] && git add "$d"; done
if ! git diff --cached --quiet; then
  git -c user.name="server-bot" -c user.email="server-bot@users.noreply.github.com" commit -q -m "chore: 서버 작업 결과 ($JOB / $ID)"
  git pull --rebase -q 2>/dev/null; git push -q 2>&1 || echo "[WARN] push 실패" >> logs/job_result.log
fi
