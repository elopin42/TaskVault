# payments (placeholder)

Owned by the payments agent: Soroban escrow via Trustless Work (fund, release,
dispute) in USDC on testnet.

Mounted at `/pay/` in `lowbid/urls.py`. Templates go in `templates/payments/`.
Settings you can read: `STELLAR_NETWORK`, `STELLAR_NETWORK_PASSPHRASE`,
`STELLAR_HORIZON_URL`, `STELLAR_SOROBAN_RPC_URL`, `STELLAR_USDC_ISSUER`,
`STELLAR_USDC_CODE`, `TRUSTLESS_WORK_API_URL`, `TRUSTLESS_WORK_API_KEY`.

Browser side: `window.Lowbid.signTransaction(xdr)` (Freighter) returns the
signed XDR; `window.StellarSdk` (vendored `@stellar/stellar-sdk`) and
`window.LOWBID` (network passphrase, Horizon / RPC URLs, USDC asset) are
available on every page that extends `base.html`.
