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

**차트 엔진 ECharts 전환** (`relative_strength.py`, `app.py`)
- Plotly → LWC(Lightweight Charts) 시도 → x축 정렬 불가 → **Apache ECharts로 최종 전환**
- 단일 차트 인스턴스 + 5개 grid → x축 완벽 정렬 해결
- 5패널 구성: 진입신호 / 분배신호 / 주가+MA / 거래량 / RS Line
- 다크모드 배경(`#1a1a2e`) + 축/라벨/제목 색상 다크 테마 적용
- 차트 내부 헤더 (graphic rich text): 종목명, 코드, 종가, 등락률, RS Score, 수익률, MA 범례
- 패널별 독립 tooltip (진입/분배 신호는 호버로 수치 확인)
- 매수/매도 마커: 라벨 제거, 호버로 단가+진입근거/매도사유 표시
- 매수평균가선: "매수평균가 xx,xxx원" 형식
- 하단 슬라이더/기간 버튼 제거 (inside zoom만 유지)
- 구버전(Plotly) 코드 유지하되 UI에서 숨김 (복원 가능)

**용어 변경: 분배신호 → 분배신호**
- 전체 코드베이스 일괄 변경 (`relative_strength.py`, `watchlist.py`)
- "분배(distribution)"가 세력 물량 분배의 의미를 더 정확히 전달

**신호 백테스트** (`backtest.py`, `app.py`)
- 진입+분배 동시 적색 이벤트 감지 → N거래일 후 수익률/최대상승/최대낙폭 측정
- 추세 필터: MA20 위 + 최근 10일 중 7일 이상 MA20 위 (BO 제외)
- 백테스트 Tab 1 UI: 시장/기간/관찰일/적색기준 필터, KPI 6개, 수익률 분포 히스토그램, 상세 테이블
- 결론: 신호는 기계적 백테스트보다 차트 위 시각적 보조 도구로서 가치 있음

**사전 계산 자동화** (`precalc.py`)
- RS 랭킹 + VCP + Stage2 필터를 매일 자동 사전 계산
- launchd 스케줄: 한국 시장 16:30, 미국 시장 07:00
- `com.sepa.precalc.kr.plist`, `com.sepa.precalc.us.plist` 등록

**인프라**
- Git 초기화: `.gitignore` 설정, 초기 커밋 완료

**차트 신호 바 추가 — 진입신호 + 분배신호 이중 구조**
- 개별 종목 차트: 5패널 구조로 변경
  - Row1 진입신호 (기존): 가격·거래량 수축 → 녹색=수축/진입적합, 빨간=확장
  - Row2 분배신호 (신규): 고저폭 + 거래량 + 종가위치 계수
    - 고저폭: 5% 기준, 5%면 만점(1.0)
    - 거래량: 0.7배 시작, 1.5배면 만점
    - 종가위치 계수: 50~70% 선형 감소, 70% 이상이면 신호 완전 제거 (강세 캔들 필터)
  - Row3 캔들+MA, Row4 거래량, Row5 RS Line
- 그룹 차트: 4패널 구조로 변경
  - Row1 수축신호, Row2 분배신호(가격만, 거래량 없음), Row3 그룹지수, Row4 RS Line
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
