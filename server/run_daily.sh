#!/usr/bin/env bash
# 서버용 일일 수집: pull -> 수집 -> 커밋/push -> 로그 push
# 키는 ~/.realestate.env (MOLIT_TRADE_API_KEY, MOLIT_RENT_API_KEY, REB_API_KEY) 에서 읽음
set -u
REPO_DIR="${REPO_DIR:-$HOME/Real-Estate}"
cd "$REPO_DIR" || exit 1
set -a; . "$HOME/.realestate.env"; set +a

LOG=logs/last_run.log
mkdir -p logs
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="
  git pull --rebase --autostash -q || echo "[WARN] git pull 실패"
  python3 scripts/fetch_data.py 2>&1 | tail -n 200
  echo "exit: ${PIPESTATUS[0]}"
  echo "=== end ==="
} > "$LOG" 2>&1

git add data/ docs/data/ logs/
if ! git diff --cached --quiet; then
  git -c user.name="server-bot" -c user.email="server-bot@users.noreply.github.com" \
      commit -q -m "chore: 서버 데이터 업데이트 $(date +%F)"
  git pull --rebase -q; git push -q || echo "[WARN] push 실패" >> "$LOG"
fi
