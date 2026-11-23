#!/usr/bin/env bash
# 서버용 일일 수집: pull -> 수집 -> 커밋/push (로그는 임시파일에 쓰고 마지막에 저장소로 복사)
set -u
REPO_DIR="${REPO_DIR:-$HOME/Real-Estate}"
cd "$REPO_DIR" || exit 1
set -a; . "$HOME/.realestate.env"; set +a

TMP=$(mktemp)
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="
  git pull --rebase --autostash -q 2>&1 || echo "[WARN] git pull 실패"
  python3 scripts/fetch_data.py 2>&1 | tail -n 200
  echo "exit: ${PIPESTATUS[0]}"
  echo "--- 백필 ---"
  python3 scripts/backfill.py --months 36 --max-calls 1200 2>&1 | tail -n 15
  echo "--- 분석 ---"
  python3 scripts/build_analytics.py 2>&1 | tail -n 10
  echo "analytics exit: ${PIPESTATUS[0]}"
  echo "--- 추가 분석 ---"
  python3 scripts/build_extra.py 2>&1 | tail -n 8
  echo "extra exit: ${PIPESTATUS[0]}"
  echo "--- 검증 ---"
  python3 scripts/validate_data.py 2>&1 | tail -n 30
  free -m | sed -n '1,2p'
  echo "=== end ==="
} 2>&1 | tee "$HOME/run_daily.live.log" > "$TMP"

mkdir -p logs
cp "$TMP" logs/last_run.log; rm -f "$TMP"

# 이상 징후가 있으면 알림(NTFY_TOPIC 설정 시) — 화면 상단 배지에도 표시됨(docs/data/status.json)
if ! grep -q "^=== end ===" logs/last_run.log || grep -qE "^\[FAIL\]|Traceback|Killed|(analytics|extra) exit: [1-9]|^exit: [1-9]" logs/last_run.log; then
  python3 scripts/notify.py "서울집 데이터 수집 이상" "$(grep -E '^\[FAIL\]|Traceback|Killed|exit: [1-9]' logs/last_run.log | head -5)"
fi

git add data/ docs/data/ logs/
if ! git diff --cached --quiet; then
  git -c user.name="server-bot" -c user.email="server-bot@users.noreply.github.com" \
      commit -q -m "chore: 서버 데이터 업데이트 $(date +%F)"
  git pull --rebase -q 2>/dev/null
  git push -q 2>&1 || echo "[WARN] push 실패" >> logs/last_run.log
fi
