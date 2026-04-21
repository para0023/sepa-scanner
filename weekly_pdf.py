"""
SEPA Scanner 주간 리포트 PDF 생성
"""
import io
from datetime import datetime
from pathlib import Path
from fpdf import FPDF


FONT_PATH = str(Path(__file__).parent / "fonts" / "NotoSansCJKkr-Regular.otf")


class WeeklyReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("korean", "", FONT_PATH)
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("korean", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, "SEPA Scanner Weekly Report", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("korean", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def section_title(self, title):
        self.set_font("korean", "", 14)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def sub_title(self, title):
        self.set_font("korean", "", 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def kv_row(self, key, value):
        self.set_font("korean", "", 9)
        self.set_text_color(100, 100, 100)
        self.cell(45, 6, key, new_x="END")
        self.set_text_color(30, 30, 30)
        self.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")

    def body_text(self, text):
        self.set_font("korean", "", 9)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5, text)
        self.ln(1)


def generate_weekly_pdf(weekly_data: dict, chart_images: dict = None, market_data: list = None, currency: str = "원") -> bytes:
    """
    주간 리포트 PDF 생성.

    weekly_data: get_weekly_review() 반환값
    chart_images: {ticker: bytes} — 차트 PNG 이미지
    market_data: [{지표, 시작, 종료, 변동률(%)}] — 시장 지표
    currency: "원" or "$"
    """
    pdf = WeeklyReportPDF()
    pdf.add_page()

    is_kr = currency == "원"
    fmt_price = lambda v: f"{int(v):,}원" if is_kr else f"${v:,.2f}"
    fmt_pct = lambda v: f"{v:+.2f}%"

    # ── 표지 ──
    pdf.set_font("korean", "", 20)
    pdf.set_text_color(30, 30, 30)
    pdf.ln(20)
    pdf.cell(0, 15, "SEPA Scanner", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("korean", "", 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, "Weekly Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("korean", "", 12)
    pdf.set_text_color(60, 60, 60)
    ws = weekly_data.get("week_start", "")
    we = weekly_data.get("week_end", "")
    pdf.cell(0, 10, f"{ws} ~ {we}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("korean", "", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C", new_x="LMARGIN", new_y="NEXT")

    # ── 1. 포트폴리오 현황 요약 ──
    pdf.add_page()
    pdf.section_title("1. 포트폴리오 현황 요약")

    ws_val = weekly_data.get("week_start_val", 0)
    we_val = weekly_data.get("week_end_val", 0)
    w_ret = weekly_data.get("weekly_return_pct", 0)

    pdf.kv_row("주초 평가", fmt_price(ws_val))
    pdf.kv_row("주말 평가", fmt_price(we_val))
    pdf.kv_row("주간 변동", fmt_price(we_val - ws_val))
    pdf.kv_row("주간 수익률", fmt_pct(w_ret))
    pdf.ln(5)

    # ── 2. 거래현황 ──
    pdf.section_title("2. 거래현황")

    summary = weekly_data.get("summary")
    if summary:
        pdf.sub_title("요약")
        pdf.kv_row("총 거래수", f"{summary['총거래수']}건")
        pdf.kv_row("승/패", f"{summary['승']}승 {summary['패']}패")
        pdf.kv_row("승률", f"{summary['승률(%)']:.1f}%")
        pdf.kv_row("승리 평균수익률", fmt_pct(summary["승리평균수익률(%)"]))
        pdf.kv_row("패배 평균손실률", fmt_pct(summary["패배평균손실률(%)"]))
        _w_capital = weekly_data.get("capital", 0)
        _w_realized_ret = round(summary["주간실현수익"] / _w_capital * 100, 2) if _w_capital > 0 else 0
        pdf.kv_row("주간 실현수익", f"{fmt_price(summary['주간실현수익'])} ({fmt_pct(_w_realized_ret)})")
        pdf.ln(3)
    else:
        pdf.body_text("해당 주 청산 거래 없음")

    # 진입/청산/진입+청산 공통 렌더
    def _render_trades(title, trades, show_buys=True, show_sells=True):
        pdf.sub_title(f"{title} ({len(trades)}건)")
        if not trades:
            pdf.body_text("없음")
            return
        for t in trades:
            # 종목 제목 + 거래 정보 + 차트가 같은 페이지에 나오도록
            # 차트 높이 약 100mm + 거래 정보 약 30mm = 130mm 필요
            _remaining = pdf.h - pdf.get_y() - pdf.b_margin
            if _remaining < 140:
                pdf.add_page()

            pdf.set_font("korean", "", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(0, 7, f"{t['종목명']} ({t['종목코드']})", new_x="LMARGIN", new_y="NEXT")

            if show_buys and t.get("매수"):
                for b in t["매수"]:
                    price_str = fmt_price(b["가격"])
                    pdf.set_font("korean", "", 9)
                    pdf.set_text_color(70, 70, 70)
                    pdf.cell(0, 5, f"  매수 {b['날짜']} | {price_str} × {b['수량']}주 | 근거: {b.get('진입근거', '-') or '-'}", new_x="LMARGIN", new_y="NEXT")

            if show_sells and t.get("매도"):
                for s in t["매도"]:
                    price_str = fmt_price(s["가격"])
                    pdf.set_font("korean", "", 9)
                    pdf.set_text_color(70, 70, 70)
                    pdf.cell(0, 5, f"  매도 {s['날짜']} | {price_str} × {s['수량']}주 | 사유: {s.get('사유', '-') or '-'}", new_x="LMARGIN", new_y="NEXT")

            # 차트 이미지
            ticker = t["종목코드"]
            if chart_images and ticker in chart_images and chart_images[ticker]:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(chart_images[ticker])
                    tmp_path = tmp.name
                pdf.ln(2)
                try:
                    pdf.image(tmp_path, x=10, w=190)
                except:
                    pass
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
                pdf.ln(3)
            else:
                pdf.ln(3)

    _render_trades("진입", weekly_data.get("entries", []), show_buys=True, show_sells=False)
    _render_trades("청산", weekly_data.get("exits", []), show_buys=False, show_sells=True)
    _render_trades("진입+청산", weekly_data.get("both", []), show_buys=True, show_sells=True)

    # ── 3. 시장 지표 요약 ──
    pdf.add_page()
    pdf.section_title("3. 시장 지표 요약")

    if market_data:
        # 테이블 헤더
        pdf.set_font("korean", "", 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(40, 7, "지표", border=1, fill=True, align="C")
        pdf.cell(40, 7, "시작", border=1, fill=True, align="C")
        pdf.cell(40, 7, "종료", border=1, fill=True, align="C")
        pdf.cell(40, 7, "변동률(%)", border=1, fill=True, align="C")
        pdf.ln()

        for row in market_data:
            pdf.set_text_color(30, 30, 30)
            pdf.cell(40, 6, str(row.get("지표", "")), border=1, align="C")
            pdf.cell(40, 6, str(row.get("시작", "")), border=1, align="R")
            pdf.cell(40, 6, str(row.get("종료", "")), border=1, align="R")
            chg = row.get("변동률(%)", 0)
            if chg >= 0:
                pdf.set_text_color(217, 43, 43)
            else:
                pdf.set_text_color(26, 94, 204)
            pdf.cell(40, 6, f"{chg:+.2f}%", border=1, align="R")
            pdf.set_text_color(30, 30, 30)
            pdf.ln()
    else:
        pdf.body_text("시장 데이터 없음")

    return bytes(pdf.output())
