# SEPA Scanner 개발 로그

---

## 2026-03-19

### 인프라
- launchd 등록 (`~/Library/LaunchAgents/com.sepa.scanner.plist`)
  - 로그인 시 자동 시작, 크래시 시 자동 재시작 (KeepAlive)
  - 로그 저장 위치: `~/sepa_scanner/logs/scanner.log`
- 다크모드 고정: `.streamlit/config.toml`에 `base = "dark"` 추가

### 현재 상태
- Streamlit 서버 포트 8501에서 운영 중
- Tailscale로 핸드폰 원격 접속 가능 (어느정도 완성 단계)

### 기능 추가
- **차트 타이틀에 당일 가격 + 등락률 표시** (`relative_strength.py`)
  - 상승: 빨간색, 하락: 파란색
- **포트폴리오 성과 분석 강화** (`portfolio.py`, `app.py`)
  - 거래별/종목별 테이블에 `목표손절률(%)` 컬럼 추가
  - 패배 시 평균손실률 아래 "목표보다 X%p 절약✓ / 초과" delta 표시
  - 목표손절 위반 횟수 / 위반율 KPI 추가 (거래별, 종목별)

### 버그 수정
- **NASDAQ/NYSE VCP 0개 버그** (`market_ranking.py`)
  - 1차 원인: 재부팅 후 랭킹 데이터 미준비 상태에서 VCP 자동 계산 → 0개짜리 캐시 저장
    - 수정: 처리 성공 종목이 입력의 10% 미만이면 캐시 저장 안 함
  - 2차 원인 (근본 원인): FinanceDataReader가 미국 주식 최신 날짜를 중복 행으로 반환, 첫 번째 행 Close=NaN → hl_pct 전체 NaN → range_ok=False → 아무것도 안 잡힘
    - 수정: fdr.DataReader 호출 직후 `stock[~stock.index.duplicated(keep='last')]` 추가 (4곳: apply_vcp_filter, apply_stage2_filter, refresh_52w_high, _detect_vcp_single)
  - 코스피/코스닥은 중복 행 현상 없어서 정상 동작했음

---

## 2026-03-22

### 기능 추가

**그룹 분석 고도화**
- 그룹 RS 랭킹 테이블 (전체 그룹 RS Score 비교, 페이지 최상단 배치)
  - 일별 캐시 + 그룹 구성 변경 시 자동 무효화 (fingerprint 방식)
  - 행 클릭 → 해당 그룹 차트로 이동
- 그룹 차트 종목별 RS 테이블 복구 (행 클릭 → 종목 차트 이동)
- 미국 패턴 스캐너 테이블에 티커 컬럼 추가 (종목명 다음)

**차트 신호 바 추가 — 진입신호 + 확장신호 이중 구조**
- 개별 종목 차트: 5패널 구조로 변경
  - Row1 진입신호 (기존): 가격·거래량 수축 → 녹색=수축/진입적합, 빨간=확장
  - Row2 확장신호 (신규): 고저폭 + 거래량 + 종가위치 계수
    - 고저폭: 5% 기준, 5%면 만점(1.0)
    - 거래량: 0.7배 시작, 1.5배면 만점
    - 종가위치 계수: 50~70% 선형 감소, 70% 이상이면 신호 완전 제거 (강세 캔들 필터)
  - Row3 캔들+MA, Row4 거래량, Row5 RS Line
- 그룹 차트: 4패널 구조로 변경
  - Row1 수축신호, Row2 확장신호(가격만, 거래량 없음), Row3 그룹지수, Row4 RS Line
- 신호 바 레이블 가로 텍스트(annotation)로 변경

### 버그 수정
- 그룹 차트 아래 종목별 RS 테이블 누락 복구

---

## 개발 이력 요약 (launchd 설정 이전)

### 주요 구현 기능
- IBD 스타일 RS Score / RS Line 계산 (한국 + 미국 주식)
- KOSPI / KOSDAQ 전체 종목 RS 랭킹 (병렬처리 + 날짜 캐시)
- VCP 필터 (거래량 수축 + 좁은 가격 범위)
- 2단계 시작 필터 (스탠 와인스타인 기준, MA60 돌파 1~2개월 이내)
- 포트폴리오 관리 (매수/매도/피라미딩/손절가 이력/RR/실현손익/진입근거별 통계)
- Streamlit 기반 웹 UI

### 파일 구조
- `app.py` — 메인 UI
- `relative_strength.py` — RS 계산 + 차트
- `market_ranking.py` — 시장 랭킹
- `portfolio.py` — 포트폴리오 관리
