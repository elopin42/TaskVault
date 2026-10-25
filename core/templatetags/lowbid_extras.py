from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def underline_last(value) -> str:
    """Wrap the LAST word of a title in <span class="ui-underline"> (the short amber underline of the
    coutrio look): `{{ "Mes projets"|underline_last }}` → `Mes <span class="ui-underline">projets</span>`.
    The input is escaped first; an empty value stays empty."""
    s = escape(str(value or "").strip())
    if not s:
        return ""
    head, sep, last = s.rpartition(" ")
    # One outer span: inside a flex h1 (title + status badge) the words must stay ONE flex item.
    return mark_safe(f'<span class="ui-title">{head}{sep}<span class="ui-underline">{last}</span></span>')


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
def usdc(value, code: str | None = None) -> str:
    """'1,234.50 USDC' — two decimals, thousands separator; '—' when empty. The unit defaults to the
    configured payment asset (payments.stellar.asset_code()); pass "" for the bare number."""
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if code is None:
        from payments.stellar import asset_code  # lazy: keep the tag library import-light

        code = asset_code()
    return f"{amount:,.2f} {code}"


@register.filter
def usdc_parts(value) -> str:
    """'1,234<span class="ui-dec">.50</span>' — the |usdc number (no unit) with faint decimals; '—' when empty."""
    text = usdc(value, "")
    head, dot, tail = text.strip().partition(".")
    if not dot:
        return text
    return mark_safe(f'{escape(head)}<span class="ui-dec">.{escape(tail)}</span>')


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
    """Same two hues as Lowbid.identicon() in lowbid-ui.js, as an inline style string
    (`--id-a:38;--id-b:200`) so identicons render server-side, before JS runs: `style="{{ addr|hue }}"`."""
    s = str(address or "")
    h1, h2 = 7, 13
    for ch in s:
        c = ord(ch)
        h1 = (h1 * 31 + c) & 0xFFFFFFFF
        h2 = (h2 * 17 + c * 7) & 0xFFFFFFFF
    return f"--id-a:{h1 % 360};--id-b:{(h2 % 360 + 120) % 360}"
