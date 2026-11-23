#!/usr/bin/env bash
echo "--- uptime / reboot"; uptime; last reboot -n 5 2>/dev/null | head -6
echo "--- crontab"; crontab -l
echo "--- cron 실행 기록(최근)"; (grep -h "CRON" /var/log/syslog /var/log/syslog.1 2>/dev/null | grep -i "run_daily\|poll" | grep -v "poll.sh" | tail -25)
echo "--- 디스크/메모리"; df -h / | tail -1; free -m | sed -n 2p
echo "--- 저장소 상태"; cd ~/Real-Estate && git status -sb | head -5; git log -3 --format='%h %ad %s' --date=format:'%m-%d %H:%M'
echo "--- 최근 live 로그 끝"; tail -5 ~/run_daily.live.log
echo "--- 에러 흔적"; grep -ci "error\|fail\|traceback" ~/run_daily.live.log
