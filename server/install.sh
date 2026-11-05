#!/usr/bin/env bash
# 서버에서 1회 실행: 클론 + 키 저장 + cron 등록(매일 KST 00:30, 서버 시간대 무관)
set -e
REPO_DIR="$HOME/Real-Estate"
command -v git >/dev/null || sudo apt-get install -y git
command -v python3 >/dev/null || sudo apt-get install -y python3
python3 -c "import pandas, requests" 2>/dev/null || sudo apt-get install -y python3-pandas python3-requests

if [ ! -d "$REPO_DIR/.git" ]; then
  read -rsp "GitHub 토큰(sean794/Real-Estate contents:write): " TOKEN; echo
  git clone "https://sean794:${TOKEN}@github.com/sean794/Real-Estate.git" "$REPO_DIR"
fi

if [ ! -f "$HOME/.realestate.env" ]; then
  read -rsp "MOLIT_TRADE_API_KEY: " A; echo
  read -rsp "MOLIT_RENT_API_KEY: " B; echo
  read -rsp "REB_API_KEY(없으면 엔터): " C; echo
  printf 'MOLIT_TRADE_API_KEY=%s\nMOLIT_RENT_API_KEY=%s\nREB_API_KEY=%s\n' "$A" "$B" "$C" > "$HOME/.realestate.env"
  chmod 600 "$HOME/.realestate.env"
fi

chmod +x "$REPO_DIR/server/run_daily.sh"
# KST 00:30 = UTC 15:30
( crontab -l 2>/dev/null | grep -v run_daily.sh; echo "CRON_TZ=Asia/Seoul"; echo "30 0 * * * $REPO_DIR/server/run_daily.sh" ) | crontab -
echo "== 첫 실행 =="; "$REPO_DIR/server/run_daily.sh"; tail -n 20 "$REPO_DIR/logs/last_run.log"
