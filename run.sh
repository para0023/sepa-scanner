#!/bin/bash
# SEPA Scanner 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/venv39"

cd "$SCRIPT_DIR"

# 가상환경 확인
if [ ! -f "$VENV/bin/python3" ]; then
    echo "[오류] 가상환경이 없습니다. 먼저 설치를 실행해주세요."
    echo "  /usr/bin/python3 -m venv venv39"
    echo "  venv39/bin/pip install -r requirements.txt streamlit"
    exit 1
fi

echo "📈 SEPA Scanner 시작 중..."
echo "   브라우저에서 http://localhost:8501 로 접속하세요"
echo ""
echo "" | "$VENV/bin/streamlit" run app.py \
    --server.headless false \
    --server.port 8501 \
    --browser.gatherUsageStats false
