from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def short_addr(value, keep=4) -> str:
    """'GABC…WXYZ' for a 56-char Stellar address (untouched when short). `keep` tolerates ''/None."""
    s = str(value or "")
    try:
        keep = int(keep) if keep not in (None, "") else 4
    except (TypeError, ValueError):
        keep = 4
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


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Current query string with some keys replaced: `{% qs page=2 %}` → `?tab=open&page=2`.

    A value of None / '' drops the key. Keeps every other GET parameter (tab, tag, q, sort…).
    """
    request = context.get("request")
    params = request.GET.copy() if request is not None else {}
    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)
    encoded = params.urlencode() if hasattr(params, "urlencode") else ""
    return f"?{encoded}" if encoded else "?"


@register.filter
def pct(value, total) -> int:
    """Integer percentage of value over total (0 when total is 0): `{{ done|pct:total }}`."""
    try:
        total = float(total)
        return int(round(100 * float(value) / total)) if total else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def hue(address) -> str:
    """Same two hues as Lowbid.identicon() in lowbid-ui.js, as 'a b' — for SSR identicons without JS."""
    s = str(address or "")
    h1, h2 = 7, 13
    for ch in s:
        c = ord(ch)
        h1 = (h1 * 31 + c) & 0xFFFFFFFF
        h2 = (h2 * 17 + c * 7) & 0xFFFFFFFF
    return f"{h1 % 360} {(h2 % 360 + 120) % 360}"
