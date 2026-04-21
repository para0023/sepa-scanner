"""
SEPA Scanner 매매 일지 관리
- 날짜별 보유종목 리뷰 + 행동 계획 기록
- trading_journal.json에 저장
"""

import json
from datetime import datetime
from pathlib import Path

_JOURNAL_FILE = Path(__file__).parent / "trading_journal.json"


def _load() -> list:
    """일지 데이터 로드"""
    try:
        if _JOURNAL_FILE.exists():
            with open(_JOURNAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return []


def _save(data: list):
    """일지 데이터 저장"""
    with open(_JOURNAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_journal_dates() -> list:
    """일지가 있는 날짜 목록 반환 (내림차순)"""
    data = _load()
    dates = sorted(set(entry["date"] for entry in data), reverse=True)
    return dates


def get_journal(date: str) -> dict:
    """특정 날짜의 일지 반환"""
    data = _load()
    for entry in data:
        if entry["date"] == date:
            return entry
    return {}


def save_journal(date: str, entries: list, extra_notes: str = ""):
    """
    일지 저장.
    date: "2026-04-22"
    entries: [{"종목코드": "...", "종목명": "...", "메모": "..."}]
    extra_notes: 추가 메모 (보유 외 관심종목 등)
    """
    data = _load()

    # 기존 날짜 덮어쓰기
    data = [e for e in data if e["date"] != date]

    data.append({
        "date": date,
        "saved_at": datetime.now().isoformat(),
        "entries": entries,
        "extra_notes": extra_notes,
    })

    # 날짜 순 정렬
    data.sort(key=lambda x: x["date"], reverse=True)
    _save(data)


def delete_journal(date: str):
    """특정 날짜 일지 삭제"""
    data = _load()
    data = [e for e in data if e["date"] != date]
    _save(data)
