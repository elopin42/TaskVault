# Prompt to build the TaskVault pitch deck

Paste everything below the line into a new Claude conversation, and attach the files listed in "Files to attach".

---

Build the pitch deck for my hackathon project **TaskVault** (Hack Meridian, Stellar hackathon, track "Composed").

**Format:** a Claude Slides deck (downloadable as PowerPoint and PDF). If that is not available, make a .pptx file.
**Language:** English (international jury).
**Length:** 7 slides, plus speaker notes on every slide (2 to 4 sentences, what I say out loud, in French).

**Style:**
- Dark theme (near-black / deep navy background), one accent colour: mint green, used only for money and key numbers.
- Big headlines, at most 3 to 4 short bullets per slide, lots of space.
- No stock photos of people. On-chain figures and the score formula in a monospace font.
- Use my attached screenshots as the visuals (see the mapping below). Do not invent mockups.

**Rules:**
- The attached brief (`PRESENTATION_BRIEF`) is the source of truth. Do not invent numbers, features or claims that are not in it.
- Keep the slide text close to the attached slide text (`prompt-gamma.txt`): it is already validated.
- Never claim it runs on mainnet: it is Stellar testnet.

**Slides and images:**

| # | Slide | Image |
|---|-------|-------|
| 1 | Title: TaskVault, "Fixed prices. Earned trust. Guaranteed payment." + one-line pitch | `slide1-landing.png` |
| 2 | The problem | none (big numbers: "10 to 20%", "60 days") |
| 3 | The solution | `slide3-projet.png` |
| 4 | How it works (demo, 6 steps) | `slide4a-candidats.png` + `slide4b-paiement.png` |
| 5 | Trust you can compute (score formula, 90 vs 20) | `slide5-score-90-vs-20.png` |
| 6 | Why Stellar: Freighter + USDC + Trustless Work, with a simple flow diagram: Browser + Freighter → TaskVault (Django) → Trustless Work / Horizon → Stellar | none (draw the diagram) |
| 7 | Built to be trusted + Next, ending on the one-line pitch | `slide7-mobile.png` |

When the deck is done, give me the link and a 1-line summary per slide.

---

## Files to attach

1. `TaskVault-brief.pdf`: the full brief (problem, solution, score, Stellar, Q&A). Source: `docs/PRESENTATION_BRIEF.md` in the repo.
2. `prompt-gamma.txt`: the validated text of the 7 slides.
3. The 6 images from `images-gamma.zip` (unzip first and attach the PNGs one by one):
   - `slide1-landing.png` (= `docs/screenshots/01-landing.png`)
   - `slide3-projet.png` (= `03-projet-entreprise.png`)
   - `slide4a-candidats.png` (= `04-tache-candidats.png`)
   - `slide4b-paiement.png` (= `14-paiement-tache.png`)
   - `slide5-score-90-vs-20.png` (= `08-tache-valide-recommande.png`)
   - `slide7-mobile.png` (= `mobile-tache-candidats.png`)

If the new conversation is a Claude Code session on this repo, nothing needs attaching: point it at `docs/SLIDES_PROMPT.md`, `docs/PRESENTATION_BRIEF.md`, `docs/SLIDES_TEXT.txt` (= `prompt-gamma.txt`) and `docs/screenshots/` (the original file names are in brackets above).
