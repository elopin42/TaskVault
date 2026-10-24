> 🇫🇷 La démo et l'interface sont en français. This README is in English for the judges.

# Lowbid 📉

**A client posts a need and a maximum budget, freelancers bid the price down, and the winner is paid in USDC through an on-chain escrow on Stellar.**

- **Demo video:** TODO: link
- **Pitch deck:** TODO: link
- **Hackathon:** Hack Meridian (Stellar), track **Composed**

---

## What it does

```
   CLIENT                         LOWBID (Django)                     STELLAR (testnet)
   ------                         ---------------                     -----------------
1. Connect Freighter  ----------> signMessage check     <----------- Freighter wallet
2. Post a need        ----------> need saved (open)
   budget max, delay max,         countdown starts
   3 tags, deadline
                       FREELANCERS
3.                     Connect Freighter -------------> signMessage check
4.                     Bid: price < last bid ---------> rule checked, bid saved
                       + delay, tags, message
5.                                timer ends -> need closed
6.                                score each bid, "Recommandé" badge
7. Review offers, adjust sliders
8. Choose a freelancer ---------> need awarded
9. Click "Payer"      ----------> Trustless Work API ---------------> Soroban escrow created,
                                  (proxied by Django)                 USDC locked
                       Freelancer delivers --> need delivered
10. Validate delivery ----------> release request ------------------> escrow releases USDC
                                                                      to the freelancer wallet
```

1. The client connects their **Freighter** wallet (Stellar testnet). Login is a signed message, no password.
2. The client posts a need: title, description, **maximum budget (USDC)**, **maximum delay (days)**, up to 3 skill tags, and a bidding deadline (e.g. 2 hours).
3. Freelancers connect their own Freighter wallet.
4. Each freelancer bids: price, delay in days, tags, short message. **A bid must be strictly lower than the previous bid**, or it is refused.
5. When the countdown ends, bidding closes.
6. Lowbid computes a score for every bid and puts a **"Recommandé"** badge on the best one.
7. The client can reweight price / delay / skills with three sliders.
8. **The client chooses.** The recommendation is an aid, not a rule: any bid can win.
9. The client clicks **"Payer"**: Trustless Work creates a Soroban escrow and the USDC is locked in it.
10. The freelancer delivers, the client validates, and the escrow releases the USDC to the freelancer.

## Why Stellar

- **USDC** on Stellar: the freelancer gets a dollar-stable payment, not a volatile token.
- **Speed and cost:** settlement in about 5 seconds, fees around 0.00001 XLM. A 50 USDC job is not eaten by fees.
- **Escrow on Soroban via Trustless Work:** funds are locked by a smart contract, not held by a platform for weeks. Neither side can run away with the money.
- **Freighter:** the wallet is the identity. Both login and every payment are signed by the user in their own wallet; Lowbid never holds a private key.
- **No bank in the loop:** no 10 to 20% platform cut, no wire delays.

## Scoring

For each bid, after the deadline:

```
score = 40 * (1 - price / max_budget)
      + 30 * (1 - delay / max_delay)
      + 30 * (common_tags / requested_tags)
```

Each term is clamped to `[0, 1]` before weighting. Default weights are 40 / 30 / 30; the client can move three sliders (they always sum to 100). The highest score gets the "Recommandé" badge. Worked examples are in [`docs/PRODUCT.md`](docs/PRODUCT.md).

## Run it locally

Prerequisites: **Python 3.13**, **Node 22** (only if you rebuild the CSS), the **Freighter** browser extension set to **TESTNET** with a funded account.

```bash
cp .env.example .env
make dev
# open http://localhost:8000
```

## Where Stellar lives in the code

_Paths to confirm._

| Path | What it does |
|------|--------------|
| `accounts/` | Wallet login: challenge + Freighter `signMessage` verification |
| `payments/` | Trustless Work escrow (create, fund, release) proxied by Django + Plan B direct payment |
| `static/js/lowbid-wallet.js` | Freighter connection and message signing in the browser |
| `static/js/lowbid-pay.js` | Builds and signs escrow / payment transactions with `@stellar/stellar-sdk` |
| `docs/STELLAR_NOTES.md` | Network, USDC asset, trustlines, and what is on-chain vs off-chain |

## Testnet addresses

| Role | Public key | stellar.expert |
|------|------------|----------------|
| Client | | |
| Freelance 1 | | |
| Freelance 2 | | |
| Escrow contract | | |

## Track: Composed (Freighter + USDC + Trustless Work)

Three Stellar building blocks composed into one flow: **Freighter** for identity and signing, **USDC** as the unit of payment, **Trustless Work** escrow on Soroban for trustless settlement.

**Plan B, stated honestly:** if escrow creation fails during the demo, Lowbid falls back to a direct USDC payment (`Operation.payment`) from the client to the freelancer. It still settles on Stellar in seconds, but without the escrow guarantee. The "Status" list below says which path actually works.

## Status / what works

- [ ] Wallet login (Freighter signMessage)
- [ ] Post a need
- [ ] Bid with the descending-price rule
- [ ] Scoring + "Recommandé" badge
- [ ] Client chooses any bid
- [ ] Escrow create (USDC locked)
- [ ] Escrow release (USDC to freelancer)
- [ ] Plan B: direct USDC payment

## Built during the hackathon

Everything. Product, code, design and docs were built during Hack Meridian (Sunday build, Monday 11:00 submission).

## Team

TODO: names, roles, links

## License

MIT
