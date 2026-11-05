#!/usr/bin/env bash
# 서버 상태 점검 (조회 전용)
date; echo; free -m; echo; df -h / | tail -n 2; echo
echo "--- cron ---"; crontab -l 2>/dev/null; echo
echo "--- 실행 중 ---"; ps aux | grep -E "fetch_data|backfill|build_analytics|run_daily" | grep -v grep | awk '{print $11,$12,$13,$14}'; echo
echo "--- 데이터 ---"
echo "매매 월 파일: $(ls data/apt_trade 2>/dev/null | wc -l)개 ($(ls data/apt_trade | head -1) ~ $(ls data/apt_trade | tail -1))"
echo "전월세 월 파일: $(ls data/apt_rent 2>/dev/null | wc -l)개"
echo "백필 임시파일: $(ls data/_partial/*/ 2>/dev/null | grep -c csv)"
echo; echo "--- 마지막 수집 로그 끝 ---"; tail -n 12 logs/last_run.log 2>/dev/null
