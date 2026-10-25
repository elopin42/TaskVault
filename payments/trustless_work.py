"""Thin client for the Trustless Work v1 REST API (Soroban escrow on Stellar testnet).

Spec: docs/STELLAR_NOTES.md §1 (checked against `@trustless-work/escrow@3.0.5` and the
vendor's REST reference). Base URL `settings.TRUSTLESS_WORK_API_URL`
(default https://dev.api.trustlesswork.com), header `x-api-key`.

Every write endpoint answers ``{"status": "SUCCESS", "unsignedTransaction": "<XDR>"}``.
The wallet named in the body signs that XDR in the browser (Freighter, with the
testnet passphrase + the same address) and the signed XDR comes back to Django,
which calls :func:`send_transaction`. Nothing here signs or holds keys.

Lifecycle of one TaskVault TASK (one single-release escrow per task, one milestone)::

    step      endpoint                                            signs (Freighter)
    deploy    POST /deployer/single-release                       company   -> send-transaction returns contractId  (persist it)
    fund      POST /escrow/single-release/fund-escrow             company   (needs the asset + trustline)
    deliver   POST /escrow/single-release/change-milestone-status freelance (serviceProvider; delivery link = evidence)
    approve   POST /escrow/single-release/approve-milestone       company   (approver)
    release   POST /escrow/single-release/release-funds           company   (releaseSigner) -> receiver gets amount - fees
    read      GET  /escrow/single-release/get-escrow              nobody    (platformFee / flags / balance)

Role mapping: company = signer / approver / releaseSigner; the chosen freelance =
serviceProvider / receiver (needs the asset trustline BEFORE release — Trustless Work fixes the
receiver AT DEPLOY, which is why an escrow exists per task and only once a freelance is chosen);
``settings.LOWBID_PLATFORM_ADDRESS`` = disputeResolver / platformAddress.

Every function returns the same envelope and never raises on HTTP or transport
errors::

    {"ok": bool, "status": int, "data": dict, "error": str | None}

``data`` is the parsed JSON body (``data["unsignedTransaction"]`` for builds,
``data["contractId"]`` after a deploy is sent). ``status`` is 0 when the request
never reached the API (transport error, missing key).

Testnet smoke test (Django shell, run once before wiring the UI — notes §6)::

    from decimal import Decimal
    from payments import trustless_work as tw
    C, F, P = "G<COMPANY>", "G<FREELANCE>", "G<PLATFORM>"
    r = tw.deploy_single_release(signer=C, engagement_id="smoke-1", title="smoke", description="smoke",
            amount=Decimal("1"), approver=C, service_provider=F, receiver=F, release_signer=C,
            dispute_resolver=P, platform_address=P, platform_fee=Decimal("1"), milestone_description="m")
    print(r["ok"], r["error"]); xdr = r["data"]["unsignedTransaction"]
    # sign `xdr` with the COMPANY wallet (https://lab.stellar.org -> Sign transaction -> Freighter, Testnet)
    s = tw.send_transaction(signed_xdr="<signed XDR>")
    print(s["data"].get("contractId"))      # persist this
    print(tw.get_escrow(contract_id=s["data"]["contractId"], signer=C)["data"])  # read platformFee back
"""

import logging
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings

from payments import stellar

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://dev.api.trustlesswork.com"
DEFAULT_TIMEOUT = 15.0

# Endpoint paths (v1). Kept in one place so the tests and the docs can point at them.
PATH_DEPLOY = "/deployer/single-release"
PATH_FUND = "/escrow/single-release/fund-escrow"
PATH_CHANGE_MILESTONE = "/escrow/single-release/change-milestone-status"
PATH_APPROVE_MILESTONE = "/escrow/single-release/approve-milestone"
PATH_RELEASE = "/escrow/single-release/release-funds"
PATH_GET_ESCROW = "/escrow/single-release/get-escrow"
PATH_SEND = "/helper/send-transaction"
PATH_SET_TRUSTLINE = "/helper/set-trustline"

ERR_NOT_CONFIGURED = "The escrow service is not configured (Trustless Work API key missing)."
ERR_UNREACHABLE = "The escrow service is unreachable, try again in a moment."
ERR_UNEXPECTED = "Unexpected response from the escrow service."

Envelope = dict[str, Any]


# --- plumbing -----------------------------------------------------------------


def _base_url() -> str:
    return (getattr(settings, "TRUSTLESS_WORK_API_URL", "") or DEFAULT_API_URL).rstrip("/")


def _api_key() -> str:
    return (getattr(settings, "TRUSTLESS_WORK_API_KEY", "") or "").strip()


def is_configured() -> bool:
    """True when an API key is present (the escrow path can be offered at all)."""
    return bool(_api_key())


def _headers() -> dict[str, str]:
    return {"x-api-key": _api_key(), "Content-Type": "application/json", "Accept": "application/json"}


def _number(value: Decimal | int | float | str) -> int | float:
    """JSON number in asset units (`25`, `12.5`) — never a string, never stroops."""
    d = Decimal(str(value))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def _trustline() -> dict[str, str]:
    """v1 expects the ISSUER G address + symbol (the API resolves the SAC). Native XLM is not expressible here."""
    return {"address": stellar.asset_issuer(), "symbol": stellar.asset_code()}


def _envelope(ok: bool, status: int, data: dict | None = None, error: str | None = None) -> Envelope:
    return {"ok": ok, "status": status, "data": data or {}, "error": error}


def _message(data: dict, status: int) -> str:
    msg = data.get("message") or data.get("error")
    if isinstance(msg, list):
        msg = "; ".join(str(m) for m in msg)
    return str(msg) if msg else f"HTTP {status}"


def _finish(resp: requests.Response, path: str) -> Envelope:
    status = int(resp.status_code)
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {"raw": (resp.text or "")[:500]}
    if not isinstance(data, dict):
        data = {"result": data}
    ok = 200 <= status < 300 and str(data.get("status", "")).upper() != "FAILED"
    if ok:
        return _envelope(True, status, data)
    error = _message(data, status)
    logger.warning("trustless_work: path=%s status=%s error=%s", path, status, error)
    return _envelope(False, status, data, error)


def _post(path: str, payload: dict, timeout: float = DEFAULT_TIMEOUT) -> Envelope:
    if not is_configured():
        logger.warning("trustless_work: path=%s skipped, no API key", path)
        return _envelope(False, 0, error=ERR_NOT_CONFIGURED)
    url = f"{_base_url()}{path}"
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("trustless_work: transport error path=%s err=%s", path, exc.__class__.__name__)
        return _envelope(False, 0, error=ERR_UNREACHABLE)
    except Exception:
        logger.exception("trustless_work: unexpected error path=%s", path)
        return _envelope(False, 0, error=ERR_UNEXPECTED)
    return _finish(resp, path)


def _get(path: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> Envelope:
    if not is_configured():
        logger.warning("trustless_work: path=%s skipped, no API key", path)
        return _envelope(False, 0, error=ERR_NOT_CONFIGURED)
    url = f"{_base_url()}{path}"
    try:
        resp = requests.get(url, params=params or {}, headers=_headers(), timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("trustless_work: transport error path=%s err=%s", path, exc.__class__.__name__)
        return _envelope(False, 0, error=ERR_UNREACHABLE)
    except Exception:
        logger.exception("trustless_work: unexpected error path=%s", path)
        return _envelope(False, 0, error=ERR_UNEXPECTED)
    return _finish(resp, path)


# --- escrow lifecycle (single-release, one milestone) ------------------------------


def deploy_single_release(
    *,
    signer: str,
    engagement_id: str,
    title: str,
    description: str,
    amount: Decimal,
    approver: str,
    service_provider: str,
    receiver: str,
    release_signer: str,
    dispute_resolver: str,
    platform_address: str,
    platform_fee: Decimal | int,
    milestone_description: str,
) -> Envelope:
    """Build the deploy tx. Signs: `signer` (company). Send it, then persist `data["contractId"]`."""
    payload = {
        "signer": signer,
        "engagementId": engagement_id,
        "title": (title or "")[:100],
        "description": (description or "")[:500],
        "roles": {
            "approver": approver,
            "serviceProvider": service_provider,
            "receiver": receiver,
            "releaseSigner": release_signer,
            "disputeResolver": dispute_resolver,
            "platformAddress": platform_address,
        },
        "amount": _number(amount),
        "platformFee": _number(platform_fee),
        # Only `description` per milestone: extra keys (status/approved) make v1 answer 400.
        "milestones": [{"description": milestone_description}],
        "trustline": _trustline(),
    }
    return _post(PATH_DEPLOY, payload, timeout=20.0)


def fund_escrow(*, contract_id: str, signer: str, amount: Decimal) -> Envelope:
    """Build the fund tx. Signs: `signer` (company; must hold `amount` of the asset + the trustline)."""
    return _post(PATH_FUND, {"contractId": contract_id, "signer": signer, "amount": _number(amount)})


def change_milestone_status(
    *,
    contract_id: str,
    milestone_index: str = "0",
    new_status: str = "completed",
    evidence: str = "",
    service_provider: str,
) -> Envelope:
    """Mark the milestone done. Signs: `service_provider` (freelance). `evidence` may be ""."""
    return _post(
        PATH_CHANGE_MILESTONE,
        {
            "contractId": contract_id,
            "milestoneIndex": str(milestone_index),
            "newStatus": new_status,
            "newEvidence": evidence or "",
            "serviceProvider": service_provider,
        },
    )


def approve_milestone(*, contract_id: str, milestone_index: str = "0", approver: str) -> Envelope:
    """Approve the milestone. Signs: `approver` (company). 400 if status still empty / already approved."""
    return _post(
        PATH_APPROVE_MILESTONE,
        {"contractId": contract_id, "milestoneIndex": str(milestone_index), "approver": approver},
    )


def release_funds(*, contract_id: str, release_signer: str) -> Envelope:
    """Release to `receiver`. Signs: `release_signer`. Needs every milestone approved + balance >= amount."""
    return _post(PATH_RELEASE, {"contractId": contract_id, "releaseSigner": release_signer})


def send_transaction(*, signed_xdr: str) -> Envelope:
    """Submit a Freighter-signed XDR. After a deploy, `data` also carries `contractId` + `escrow`."""
    return _post(PATH_SEND, {"signedXdr": signed_xdr}, timeout=30.0)


def set_trustline(*, address: str) -> Envelope:
    """Optional helper: TW builds the asset changeTrust for `address` (alternative to stellar.build_change_trust_xdr)."""
    return _post(PATH_SET_TRUSTLINE, {"address": address, "assetAddress": stellar.asset_issuer()})


def get_escrow(*, contract_id: str, signer: str | None = None, validate_on_chain: bool = False) -> Envelope:
    """Read the escrow back (`amount`, `balance`, `platformFee`, `flags{...}`, `milestones[]`, `roles`).

    Pass `validate_on_chain=True` before release/dispute decisions (bypasses the indexer cache).
    The v1 `platformFee` unit is unverified — read it here after the first deploy.
    """
    params: dict[str, str] = {"contractId": contract_id}
    if signer:
        params["signer"] = signer
    if validate_on_chain:
        params["validateOnChain"] = "true"
    return _get(PATH_GET_ESCROW, params)
