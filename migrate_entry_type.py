"""
portfolio.json / portfolio_us.json 의 기존 매수 거래에 entry_type 필드를 소급 추가한다.

판정 규칙:
  각 position의 trades 중 type=="buy"만 날짜순(동일 날짜면 배열 순서)으로 정렬.
  첫 buy 거래를 initial, 나머지 buy 거래를 add_on으로 분류.
  sell 거래는 손대지 않음.
  trade_log(있으면)도 매수 레코드에 한해 동일 필드 채움.

안전:
  실행 전 원본을 타임스탬프 백업 (.bak.<epoch>).
  이미 entry_type이 있는 거래는 건드리지 않음(재실행 안전).

사용:
  python3 migrate_entry_type.py           # 실제 적용
  python3 migrate_entry_type.py --dry-run # 변경 카운트만 출력
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

FILES = [
    Path(__file__).parent / "portfolio.json",
    Path(__file__).parent / "portfolio_us.json",
]


def sort_key(t: dict, idx: int):
    return (t.get("date") or "", idx)


def migrate_positions(data: dict) -> tuple[int, int, int]:
    """Return (initial_set, add_on_set, skipped)."""
    initial_cnt = 0
    add_on_cnt = 0
    skipped = 0

    for pos in data.get("positions", []):
        trades = pos.get("trades", [])
        # 원 배열 순서 보존을 위해 (trade, original_index)를 정렬 키에 사용
        indexed_buys = [
            (i, t) for i, t in enumerate(trades) if t.get("type") == "buy"
        ]
        indexed_buys.sort(key=lambda pair: sort_key(pair[1], pair[0]))

        for rank, (_, t) in enumerate(indexed_buys):
            if "entry_type" in t and t["entry_type"] in ("initial", "add_on"):
                skipped += 1
                continue
            if rank == 0:
                t["entry_type"] = "initial"
                initial_cnt += 1
            else:
                t["entry_type"] = "add_on"
                add_on_cnt += 1

    # trade_log도 동기화 (포지션의 매수 레코드에 대응)
    # position_id + trade_id 매칭으로 찾음
    position_trades_index: dict[str, dict] = {}
    for pos in data.get("positions", []):
        for t in pos.get("trades", []):
            tid = t.get("id")
            if tid:
                position_trades_index[tid] = t

    for log in data.get("trade_log", []):
        if log.get("type") != "매수":
            continue
        if "entry_type" in log and log["entry_type"] in ("initial", "add_on"):
            continue
        tid = log.get("trade_id")
        matched = position_trades_index.get(tid)
        if matched and "entry_type" in matched:
            log["entry_type"] = matched["entry_type"]

    return initial_cnt, add_on_cnt, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="변경사항 출력만, 저장 안 함")
    args = ap.parse_args()

    total_initial = total_add_on = total_skip = 0

    for path in FILES:
        if not path.exists():
            print(f"[skip] {path} 없음")
            continue

        with path.open() as f:
            data = json.load(f)

        initial, add_on, skipped = migrate_positions(data)
        total_initial += initial
        total_add_on += add_on
        total_skip += skipped

        print(
            f"[{path.name}] initial={initial}  add_on={add_on}  already={skipped}"
        )

        if args.dry_run:
            continue

        # 백업
        backup = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
        shutil.copy2(path, backup)
        print(f"  backup → {backup.name}")

        # 저장 (원본 포맷 최대한 유지)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  saved  → {path.name}")

    print(
        f"\n전체: initial={total_initial}  add_on={total_add_on}  already={total_skip}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
