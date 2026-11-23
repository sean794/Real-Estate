#!/usr/bin/env bash
# 추가 분석 + 검증 1회 실행(서버 메모리 피크 측정 포함)
cd ~/Real-Estate
python3 - <<'PY'
import resource, runpy, sys
sys.argv = ["scripts/build_extra.py"]; sys.path.insert(0, "scripts")
runpy.run_path("scripts/build_extra.py", run_name="__main__")
print("피크 메모리 MB:", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024))
PY
python3 scripts/validate_data.py | tail -12
free -m | sed -n 1,3p
