# SEPA Scanner 프로젝트 규칙

## DEVLOG 자동 업데이트
- 코드를 커밋할 때 `DEVLOG.md`도 함께 업데이트할 것
- 해당 세션에서 작업한 내용을 날짜별로 정리 (기능 추가, 버그 수정, 인프라 변경 등)
- 기존 DEVLOG 형식을 따를 것

## 리포트 생성
사용자가 "주간 리포트 만들어줘" 또는 "월간 리포트 만들어줘"라고 요청하면:

1. `report_generator.py`를 실행하여 데이터 추출
   - 주간: `/Users/mac16m1-21/sepa_scanner/venv39/bin/python3 report_generator.py weekly`
   - 월간: `/Users/mac16m1-21/sepa_scanner/venv39/bin/python3 report_generator.py monthly`
   - 특정 기간: `--period 2026-04-20` (주간) 또는 `--period 2026-04` (월간)

2. 출력된 데이터를 기반으로 분석 리포트 작성:
   - **주간 리포트**: 포트폴리오 현황 + 거래현황(거래별/종목별) + 진입근거별 분석 + 시장 지표 + 분석 및 제언
   - **월간 리포트**: 위 내용 + 전월 대비 비교 + 주간별 KPI 추이 + 보유기간별 분석 + 행동 분석(잘한 점/개선점) + 다음 달 개선 방향 + 목표 KPI

3. 리포트 구조 참고: memory/project_status_20260422.md

4. 주의사항:
   - 거래별 승률과 종목별 승률을 **반드시 구분**하여 분석
   - 종목별 기준이 실제 성과를 더 정확히 반영
   - 당일매매(0일 보유) 비율과 승률의 상관관계 분석 포함
   - 진입근거별 성과 비교 포함 (HB20 vs BO 등)

## 캐시 패턴
- 모든 데이터 조회: session_state → 파일 캐시 → 계산 → 저장
- 재계산: 캐시 삭제 없이 덮어쓰기

## 코드 수정 시
- 로컬 수정 후 반드시 git commit + push (Streamlit Cloud 반영)
- Python 3.9 호환 유지 (str | None 등 3.10+ 문법 사용 금지)
- 코워크(Co-work)에서는 코드 수정 안 함 — 여기서만 코드 수정
