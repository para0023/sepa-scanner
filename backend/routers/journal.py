"""
/api/journal/* — 매매일지 CRUD
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/journal", tags=["journal"])


class JournalEntry(BaseModel):
    date: str
    entries: List[dict]
    extra_notes: str = ""


@router.get("/dates")
def get_dates():
    from trading_journal import get_journal_dates
    return {"dates": get_journal_dates()}


@router.get("/{date}")
def get_journal(date: str):
    from trading_journal import get_journal as _get
    data = _get(date)
    return data if data else {"date": date, "entries": [], "extra_notes": ""}


@router.post("/{date}")
def save_journal(date: str, req: JournalEntry):
    from trading_journal import save_journal as _save
    _save(date, req.entries, req.extra_notes)
    return {"status": "ok"}


@router.delete("/{date}")
def delete_journal(date: str):
    from trading_journal import delete_journal as _del
    _del(date)
    return {"status": "ok"}
