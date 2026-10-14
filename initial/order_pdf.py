"""Render a completed order as a PDF receipt."""

from pathlib import Path
from typing import Literal

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from catalog import money
from orders import Order

ORDERS_DIR = Path(__file__).resolve().parent / "orders"


def write_order_pdf(order: Order, directory: Path = ORDERS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{order.order_id}.pdf"

    pdf = FPDF()
    pdf.add_page()

    def line(text: str = "", size: int = 11, style: Literal["", "B", "I"] = "") -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    line("Yanez Mart - Order Confirmation", 18, "B")
    line("Demo only: no real payment was taken and nothing will be delivered.", 9, "I")
    line()
    line(f"Order: {order.order_id}", style="B")
    line(f"Placed: {order.created_at:%Y-%m-%d %H:%M}")
    line(f"Status: {order.status.replace('_', ' ')}")
    line()

    widths = (90, 20, 35, 35)
    pdf.set_font("Helvetica", "B", 11)
    for width, heading, align in zip(widths, ("Item", "Qty", "Unit price", "Total"), "LRRR"):
        pdf.cell(width, 8, heading, border="B", align=align)
    pdf.ln()
    pdf.set_font("Helvetica", "", 11)
    for item in order.lines:
        cells = (item.name, str(item.quantity), money(item.unit_price_cents), money(item.total_cents))
        for width, text, align in zip(widths, cells, "LRRR"):
            pdf.cell(width, 8, text, align=align)
        pdf.ln()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(sum(widths[:3]), 9, "Order total", border="T")
    pdf.cell(widths[3], 9, money(order.total_cents), border="T", align="R")
    pdf.ln()
    line()

    line("Payment", 13, "B")
    line(f"Payment ID: {order.payment_id}")
    if order.paid_at:
        line(f"Paid: {order.paid_at:%Y-%m-%d %H:%M}")
    line()

    line("Delivery", 13, "B")
    line(f"Ship to: {order.customer}")
    line(order.address)
    if order.delivery_date:
        line(f"Date: {order.delivery_date:%A, %B %d, %Y}, {order.delivery_window}")
    line(f"Tracking number: {order.tracking_number}")

    pdf.output(str(path))
    return path
