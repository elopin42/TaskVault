from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def short_addr(value, keep: int = 4) -> str:
    """'GABC…WXYZ' for a 56-char Stellar address (untouched when short)."""
    s = str(value or "")
    if len(s) <= keep * 2 + 1:
        return s
    return f"{s[:keep]}…{s[-keep:]}"


@register.filter
def plain(value) -> str:
    """'500' / '400.5' for a Decimal(18,7) — never '500.0000000' (input max/placeholder, data-*)."""
    if value in (None, ""):
        return ""
    try:
        return f"{Decimal(str(value)).normalize():f}"
    except (InvalidOperation, ValueError):
        return str(value)


@register.filter
def usdc(value, code: str = "USDC") -> str:
    """'1,234.50 USDC' — two decimals, thousands separator; '—' when empty."""
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return f"{amount:,.2f} {code}"
