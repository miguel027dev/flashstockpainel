import re
from datetime import datetime
from decimal import Decimal


def _tag(block, name):
    m = re.search(rf"<{name}>([^<\r\n]+)", block, re.I)
    return m.group(1).strip() if m else None


def parse_ofx(text):
    """Parser simples para OFX SGML/QFX comum. Não depende de API externa."""
    text = text.replace("\x00", "")
    blocks = re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|$)", text, re.I | re.S)
    result = []
    for b in blocks:
        amount = _tag(b, "TRNAMT")
        dt = _tag(b, "DTPOSTED")
        if not amount or not dt:
            continue
        try:
            tx_date = datetime.strptime(dt[:8], "%Y%m%d").date()
        except ValueError:
            continue
        result.append({
            "external_id": _tag(b, "FITID") or f"{dt}-{amount}-{len(result)}",
            "date": tx_date,
            "amount": Decimal(amount.replace(",", ".")),
            "description": _tag(b, "MEMO") or _tag(b, "NAME") or "Movimentação bancária",
        })
    return result
