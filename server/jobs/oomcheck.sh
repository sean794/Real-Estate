#!/usr/bin/env bash
echo "--- OOM 흔적"; (sudo -n dmesg -T 2>/dev/null || dmesg -T 2>/dev/null || journalctl -k --no-pager 2>/dev/null) | grep -i "out of memory\|killed process" | tail -12
echo "--- swap"; swapon --show; free -m | sed -n 2,3p
echo "--- 로컬 미푸시 커밋"; cd ~/Real-Estate && git fetch -q && git log origin/main..HEAD --format='%h %ad %s' --date=format:'%m-%d %H:%M' | head
echo "--- 일일 실행 소요/피크"; grep -h "^=== .*start\|^=== end" ~/run_daily.live.log | tail -2
