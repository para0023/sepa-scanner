#!/bin/bash
# SEPA Scanner 더블클릭 실행 파일

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/venv39"

cd "$SCRIPT_DIR"

# 가상환경 확인
if [ ! -f "$VENV/bin/python3" ]; then
    echo "[오류] 가상환경이 없습니다."
    echo "  cd ~/sepa_scanner"
    echo "  /usr/bin/python3 -m venv venv39"
    echo "  venv39/bin/pip install -r requirements.txt streamlit"
    read -p "엔터를 눌러 종료..."
    exit 1
fi

echo "📈 SEPA Scanner 시작 중..."
echo "   브라우저에서 http://localhost:8501 로 접속하세요"
echo "   (종료하려면 이 창을 닫거나 Ctrl+C)"
echo ""

# 브라우저 자동 오픈 (2초 후)
sleep 2 && open "http://localhost:8501" &

echo "" | "$VENV/bin/streamlit" run app.py \
    --server.headless true \
    --server.port 8501 \
    --browser.gatherUsageStats false
