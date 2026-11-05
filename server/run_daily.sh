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
  free -m | sed -n '1,2p'
  echo "=== end ==="
} > "$TMP" 2>&1

mkdir -p logs
cp "$TMP" logs/last_run.log; rm -f "$TMP"

git add data/ docs/data/ logs/
if ! git diff --cached --quiet; then
  git -c user.name="server-bot" -c user.email="server-bot@users.noreply.github.com" \
      commit -q -m "chore: 서버 데이터 업데이트 $(date +%F)"
  git pull --rebase -q 2>/dev/null
  git push -q 2>&1 || echo "[WARN] push 실패" >> logs/last_run.log
fi
