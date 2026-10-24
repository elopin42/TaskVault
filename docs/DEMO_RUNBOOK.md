# Lowbid 📉 — Runbook démo live

> Vidéo lundi matin, **soumission avant 11:00**. Script parlé : [`PITCH.md`](PITCH.md) §A.
> Libellés copiés de l'UI réelle (commit `21149cc`). Un bouton en **gras** = un clic.

---

## 0. TL;DR — la démo en 10 lignes

1. 3 profils Chrome = 3 wallets Freighter **Test Net** : Client (Claire), Freelance 1 (Yanis), Freelance 2 (Nora).
2. Chaque compte : XLM (friendbot) + trustline USDC + USDC du faucet Circle, regroupés sur le Client.
3. **Montants ≤ 10 USDC** (faucet = 10 USDC / 24 h) : budget **10**, Yanis **9**, Nora tente **9,20** (refusé), puis **7,50**.
4. Claire : **Connecter mon wallet Freighter** → **Poster un besoin** → **Publier le besoin**.
5. Yanis puis Nora : **Envoyer mon offre** (le refus à 9,20 s'affiche en rouge sous « Mon prix »).
6. Claire : **Clôturer les enchères maintenant** → curseur **Prix** vers 90 (le badge « Recommandé » passe sur Nora) → **Choisir** Yanis.
7. Claire : **Créer l'escrow** ✍️ → **Bloquer les fonds** ✍️ → onglet stellar.expert.
8. Yanis : **Déclarer la livraison** ✍️.
9. Claire : **Valider la livraison** ✍️ → **Libérer les fonds** ✍️ → la ligne « Solde USDC du freelance » monte.
10. Trustless Work en panne ? `LOWBID_PAYMENT_MODE=direct`, redémarrer (10 s), un seul bouton **Valider et payer** ✍️.

✍️ = une popup Freighter à signer.

---

## 1. Ce soir (J-1) — préparation Stellar

> ⏱️ Compter 1 h 30 à 2 h. Faire dans l'ordre. Garder un fichier `notes-demo.txt` ouvert pour coller les adresses.

### 1.1 Trois profils Chrome

- [ ] Chrome → icône profil (en haut à droite) → **Ajouter** → nom `Client`, couleur bleue.
- [ ] Pareil : `Freelance 1` (vert), `Freelance 2` (orange).
- [ ] Dans **chaque** profil : installer Freighter (https://www.freighter.app).
- [ ] Dans chaque Freighter : **Create new wallet** → mot de passe → noter les 12 mots dans `notes-demo.txt` (testnet, pas grave).
- [ ] Dans chaque Freighter : ⚙️ **Settings** → **Network** → **Test Net**.
- [ ] *(Recommandé)* Compte **Plateforme** : dans le Freighter du profil Client → menu du compte → **Add a new address / Create**.
  - Il sert d'arbitre + reçoit le `platformFee`.
  - Sans lui, Lowbid met le client à sa place : risque de refus du contrat.
  - Repasser ensuite sur le compte **Client** comme compte actif.
- [ ] Copier les 4 adresses `G…` dans `notes-demo.txt`.

### 1.2 XLM (friendbot) — 4 fois

- [ ] Ouvrir `https://friendbot.stellar.org/?addr=G…CLIENT` → réponse JSON avec un `hash` = OK.
- [ ] Pareil pour `G…FREELANCE1`, `G…FREELANCE2`, `G…PLATEFORME`.
- [ ] (Alternative : bouton **Fund with Friendbot** dans Freighter, sur un compte neuf.)
- [ ] Vérifier dans chaque Freighter : ~10 000 XLM.

### 1.3 Trustline USDC — sur les 4 comptes

> Sans trustline : le faucet ne livre pas, et le freelance ne peut pas être payé.

**Voie A — Freighter (marche pour les 4) :**

- [ ] Freighter → **Manage assets** → **Add an asset**.
- [ ] Chercher `USDC` → vérifier l'émetteur `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`.
- [ ] Pas trouvé ? **Add manually** → Code `USDC` → Issuer = l'adresse complète ci-dessus.
- [ ] **Add** → signer → la ligne `USDC 0` apparaît.

**Voie B — le bouton Lowbid (après §1.7, Client et Freelance 1 seulement) :**

- [ ] Ouvrir le besoin seedé **« Refonte du logo et de la charte »** (attribué).
- [ ] Dans le panneau **Paiement en escrow** → **Ajouter la trustline USDC** → signer.
- [ ] Déjà présente ? Toast « Trustline USDC déjà présente. » = OK.

### 1.4 USDC de test (faucet Circle)

> 🚨 **ALERTE MONTANTS** 🚨
> Le faucet donne **10 USDC par adresse et par 24 h**.
> Donc **tous les montants de la démo restent ≤ 10 USDC** : budget **10**, offres **9 → 9,20 refusé → 7,50**, paiement **9 USDC** (Yanis).
> Pour avoir de la marge : faucet sur les **4** adresses, puis tout renvoyer au Client.

- [ ] https://faucet.circle.com → **USDC** → réseau **Stellar Testnet** → coller `G…CLIENT` → **Send**.
- [ ] Recommencer pour `G…FREELANCE1`, `G…FREELANCE2`, `G…PLATEFORME`.
- [ ] Dans Freighter de Freelance 1, Freelance 2, Plateforme : **Send** → asset **USDC** → 10 → `G…CLIENT`.
- [ ] Résultat attendu : Client ≈ **40 USDC**, Freelance 1 = **0 USDC** (beau « avant / après » dans la vidéo).

### 1.5 Clé API Trustless Work (testnet)

- [ ] Ouvrir https://dapp.trustlesswork.com → connecter le Freighter **Client** → signer.
- [ ] Cliquer sur l'adresse (en bas à gauche) → **Settings** → **API Keys**.
- [ ] Compléter le profil (le champ **use case** est obligatoire, sinon pas de clé).
- [ ] Réseau **Testnet** → **Generate API Key**.
- [ ] ⚠️ **Copier tout de suite** : elle n'est affichée **qu'une fois**. La coller dans `notes-demo.txt`.

### 1.6 Remplir `.env`

- [ ] `cd ~/Lowbid && cp -n .env.example .env`
- [ ] Ouvrir `.env`, régler / ajouter **exactement** ces lignes :

```dotenv
DJANGO_DEBUG=1
STELLAR_NETWORK=testnet
TRUSTLESS_WORK_API_URL=https://dev.api.trustlesswork.com
TRUSTLESS_WORK_API_KEY=<la clé copiée en 1.5>
LOWBID_PAYMENT_MODE=
LOWBID_PLATFORM_ADDRESS=G…PLATEFORME
LOWBID_PLATFORM_FEE=1
LOWBID_DEMO_CLIENT=G…CLIENT
LOWBID_DEMO_FREELANCE1=G…FREELANCE1
LOWBID_DEMO_FREELANCE2=G…FREELANCE2
```

- `LOWBID_PAYMENT_MODE=` vide = auto → **escrow** dès que la clé est là.
- Les 3 lignes `LOWBID_DEMO_*` ne sont **pas** dans `.env.example` : les ajouter à la main.
- `LOWBID_PLATFORM_FEE=1` : ne pas monter (unité non vérifiée, 1 est sans risque).

### 1.7 Lancer + données de démo

- [ ] Terminal 1 : `make dev` → attendre `Starting development server at http://0.0.0.0:8000/`.
- [ ] Navigateur : http://localhost:8000 → la landing s'affiche, badge `testnet` dans la barre.
- [ ] Terminal 2 : `cd ~/Lowbid && .venv/bin/python manage.py seed_demo --flush`
- [ ] Noter la dernière ligne : `needs: open=#… #…  closed=#…  awarded=#…` (les numéros **ne repartent pas de 1** après un `--flush`).

Ce que crée `seed_demo` :

- 3 wallets = **tes vrais comptes Freighter** (grâce aux `LOWBID_DEMO_*`) + 1 freelance aléatoire.
- 2 besoins **ouverts** avec offres (décor de la liste « Besoins »).
- 1 besoin **clôturé** avec 3 offres (800 USDC — pour montrer les curseurs, pas pour payer).
- 1 besoin **attribué** à Freelance 1 (120 USDC) → sert pour la trustline (voie B), **pas** pour payer : trop cher pour le faucet.
- ⚠️ Le paiement de la vidéo se fait sur un **besoin neuf** créé en live (10 USDC).

> ⚠️ `.env` modifié ? **Redémarrer** : `Ctrl+C` dans le terminal 1, puis `make run` (≈ 10 s). Le serveur ne relit pas `.env` tout seul.

### 1.8 Smoke test Trustless Work (STELLAR_NOTES §6, montant 1)

> ⏱️ **Lancer un minuteur de 30 min maintenant.**

- [ ] Terminal 2 : `.venv/bin/python manage.py shell`
- [ ] Coller (remplacer les 3 adresses) :

```python
from decimal import Decimal
from payments import trustless_work as tw
C, F, P = "G…CLIENT", "G…FREELANCE1", "G…PLATEFORME"
r = tw.deploy_single_release(signer=C, engagement_id="smoke-1", title="smoke", description="smoke",
        amount=Decimal("1"), approver=C, service_provider=F, receiver=F, release_signer=C,
        dispute_resolver=P, platform_address=P, platform_fee=Decimal("1"), milestone_description="m")
print(r["ok"], r["error"]); print(r["data"].get("unsignedTransaction"))
```

- [ ] `True None` + un long XDR `AAAA…` = OK. Copier le XDR.
- [ ] https://lab.stellar.org → réseau **Testnet** → **Transactions** → **Sign** → coller → signer avec **Freighter** (compte **Client**) → copier le XDR signé.
- [ ] Dans le shell :

```python
s = tw.send_transaction(signed_xdr="<XDR signé>")
print(s["ok"], s["error"], s["data"].get("contractId"))
print(tw.get_escrow(contract_id=s["data"]["contractId"], signer=C)["data"])
```

- [ ] Un `contractId` `C…` = 🎉. Le coller dans `notes-demo.txt` + **capture d'écran** (preuve de secours).
- [ ] Lire `platformFee` dans la dernière sortie et le noter.

### 1.9 Répétition complète dans l'app (= vidéo de secours)

- [ ] **Lancer l'enregistreur d'écran** : cette répétition devient le clip de secours (§4, plan C).
- [ ] Dérouler §3 en entier avec de **petits montants** : budget **2**, Yanis **1,50**, Nora **1**.
- [ ] Vérifier : 4 signatures Client + 1 Freelance, tous les liens stellar.expert s'ouvrent.
- [ ] Après : Freighter Freelance 1 → **Send** → tout son USDC → `G…CLIENT` (Freelance 1 revient à 0).

### 1.10 🛑 Point de décision (fin du minuteur 30 min)

- [ ] Smoke test **et** répétition OK → mode **escrow**. Dormir.
- [ ] Toujours en échec après 30 min → passer en **Plan B** :
  1. `.env` : `LOWBID_PAYMENT_MODE=direct`
  2. `Ctrl+C` → `make run`
  3. Le panneau doit afficher **Paiement direct USDC** + badge **Plan B**.
  4. Refaire la répétition 1.9 (1 seule signature Client).
  5. Dans la vidéo, dire **« paiement direct »**, jamais « escrow ».
  6. Utiliser les lignes « Variante paiement direct » de `PITCH.md` §A.

### 1.11 Si ça casse

| Symptôme (ce que tu vois) | Cause | Correctif |
|---|---|---|
| « Le destinataire n'a pas de trustline USDC. » | trustline manquante | §1.3 sur le compte qui reçoit |
| Faucet Circle : rien n'arrive | trustline créée **après** la demande | trustline, puis redemander (ou autre adresse) |
| « Solde USDC insuffisant. » | Client sous le montant | Send depuis un autre compte (§1.4) ou baisser les montants |
| « Le compte destinataire n'existe pas encore… » | compte jamais financé | friendbot (§1.2) |
| Toast « Freighter est sur « PUBLIC » ; passez sur TESTNET. » | mauvais réseau | Freighter ⚙️ → Network → **Test Net** |
| « Transaction signée par une autre adresse que le compte source. » | mauvais compte actif dans Freighter | choisir le bon compte, puis **Déconnexion** / **Connecter** |
| « Le service d'escrow n'est pas configuré (clé API…) » | `TRUSTLESS_WORK_API_KEY` vide | remplir `.env`, redémarrer |
| Erreur 401 / « Unauthorized » / « HTTP 401 » | clé fausse, ou clé **mainnet** | régénérer une clé **Testnet** (§1.5) |
| « HTTP 429 » | 50 requêtes / 60 s dépassées | attendre 1 min |
| `platformFee` lu = 1 mais le freelance reçoit bizarrement moins | unité bps / % non vérifiée | ne pas toucher (1 = 0,01 % ou 1 %) ; dire « moins les frais » |
| Erreur au déploiement qui cite `disputeResolver` | `LOWBID_PLATFORM_ADDRESS` vide (client = arbitre) | remplir l'adresse Plateforme, redémarrer |
| « Horizon n'a pas confirmé à temps… » / « Transaction envoyée, confirmation en attente… » | Horizon 504, tx peut-être passée | **ne pas re-signer** ; ouvrir le lien explorateur, recharger dans 30 s |
| Tout a disparu le matin (comptes vides) | reset du testnet | refaire §1.2 → §1.4 (≈ 20 min) |

---

## 2. Setup navigateur pour la vidéo

### 2.1 Comptes : 3 profils (recommandé)

- 1 profil Chrome = 1 Freighter = 1 session Lowbid. Zéro déconnexion pendant la vidéo.
- Le nom du profil (Client / Freelance 1 / Freelance 2) s'affiche en haut à droite : le spectateur sait qui agit.
- Changer de fenêtre : `Alt+Tab` (Windows/Linux) ou `Cmd+\`` (Mac).

**Plan B : 1 seul profil** (la danse logout / connect, ≈ 20 s à chaque changement, à couper au montage) :

1. Freighter → sélecteur de compte → choisir le nouveau compte.
2. Lowbid affiche « Freighter utilise maintenant G… — déconnectez-vous pour changer de compte. »
3. Cliquer la pastille d'adresse (en haut à droite) → **Déconnexion**.
4. **Connecter le wallet** → popup Freighter → **Sign** (message de connexion).
5. Retour sur la landing → **Besoins** → rouvrir le besoin.

### 2.2 Onglets à ouvrir avant d'enregistrer

**Fenêtre Client** (déconnecté au départ, pour filmer la connexion) :

1. Le deck (slide 1).
2. http://localhost:8000/ (landing).
3. https://stellar.expert/explorer/testnet/account/G…FREELANCE1 (solde avant).

**Fenêtre Freelance 1 — Yanis** (déjà connecté) :

1. http://localhost:8000/besoins/ (le besoin neuf apparaîtra en haut).

**Fenêtre Freelance 2 — Nora** (déjà connectée) :

1. http://localhost:8000/besoins/

### 2.3 Réglages d'affichage (dans chaque profil)

- [ ] Fenêtre **plein écran** 1920 × 1080 (2 colonnes sur la page besoin).
- [ ] Zoom **110 %** : `Ctrl/Cmd` + `+` depuis 100 %.
- [ ] Thème sombre : bouton lune/soleil **Changer de thème** dans la barre Lowbid.
- [ ] Barre de favoris masquée : `Ctrl/Cmd+Shift+B`.
- [ ] Épingler l'icône Freighter dans la barre d'extensions.
- [ ] Freighter **déverrouillé** dans les 3 profils (sinon il redemande le mot de passe en pleine prise).

### 2.4 Enregistreur

- [ ] Capturer **l'écran entier**, pas la fenêtre : les popups Freighter sont des fenêtres à part.
- [ ] OBS : *Display Capture*, 1920 × 1080, 30 fps, sortie MP4. (Mac : `Cmd+Shift+5` → *Enregistrer tout l'écran*.)
- [ ] Micro testé : 10 s d'essai, réécouter.
- [ ] Ne pas déranger / notifications coupées, veille désactivée, Slack et mails fermés.
- [ ] Partage de connexion du téléphone prêt (testé une fois) si le wifi tombe.

---

## 3. Le déroulé minute par minute

> Enregistrer **un clip par bloc** (0:00, 0:30, 1:30, 2:00, 2:30) : plus facile à refaire.
> Couper au montage les attentes de popup.

### T-10 min — vérifications

- [ ] Terminal 1 : serveur lancé, pas d'erreur rouge.
- [ ] Freighter Client ≥ **10 USDC**. Freelance 1 : noter son solde (idéalement 0).
- [ ] Les 3 Freighter déverrouillés, réseau **Test Net**.
- [ ] Besoin de secours prêt (§4.0).

### 0:00 → 0:30 — Le problème

| | |
|---|---|
| Fenêtre | Client, onglet **deck** (slide 1) |
| Action | aucune |
| Dire | « Quand on est freelance, on se fait payer en retard. Parfois jamais… » (PITCH §A) |

### 0:30 → 1:30 — Poster, enchérir, choisir

**Claire se connecte (fenêtre Client)**

1. Onglet landing → **Connecter mon wallet Freighter**.
2. Popup Freighter (connexion du site, 1re fois seulement) → **Connect**.
3. Popup Freighter « Sign message » → **Sign**.
4. Écran : toast « Connecté en tant que G… ».
5. Dire : « Je connecte mon wallet Freighter : une signature, pas de mot de passe. »

**Claire poste le besoin**

1. Barre du haut → **Poster un besoin**.
2. **Titre** : `Landing page pour ma PME`
3. **Description** : `Une page de présentation, un formulaire de contact, un bouton de paiement USDC.`
4. **Budget max** : `10` (USDC).
5. **Délai max** : `10` (jours).
6. **Compétences** : `django, stellar, ui`
7. **Durée des enchères** : laisser **2 h**.
8. **Publier le besoin**.
9. Écran : « Besoin publié. Les freelances peuvent enchérir. », compte à rebours, « Aucune offre ».
10. Dire : « Budget maximum 10 dollars — on est sur testnet —, 10 jours, trois compétences. Les enchères ferment dans deux heures ; pour la démo, je clôturerai à la main. »

**Yanis enchérit (fenêtre Freelance 1)**

1. Recharger **Besoins** → cliquer **Landing page pour ma PME**.
2. **Mon prix** : `9` · **Délai** : `5`.
3. **Mes compétences** : cliquer les 3 pastilles `django` `stellar` `ui`.
4. **Message** : `Django + Tailwind, intégration Freighter incluse.`
5. **Envoyer mon offre** → toast « Votre offre est enregistrée. »
6. Dire : « Yanis propose 9 dollars en 5 jours. »

**Nora se fait refuser, puis passe dessous (fenêtre Freelance 2)**

1. Ouvrir le même besoin, puis `F5` : la tuile **Meilleure offre** affiche `9.00 USDC`.
2. **Mon prix** : `9.20`.
3. Écran : en rouge sous le champ, « Doit être strictement inférieur à 9.00 USDC. »
4. Dire : « Nora tente 9,20 : refusé, il faut passer sous la meilleure offre. »
5. Corriger **Mon prix** : `7.50` · **Délai** : `9` · **Mes compétences** : `stellar`.
6. **Envoyer mon offre**.
7. Dire : « Elle descend à 7,50, en 9 jours. »

**Claire clôture et choisit (fenêtre Client)**

1. La page s'est mise à jour seule (2 offres). Sinon `F5`.
2. **Clôturer les enchères maintenant** → boîte de confirmation → **OK**.
3. Écran : toast « Enchères clôturées. À vous de choisir. », titre « Offres classées », badge ⭐ **Recommandé** sur Yanis (≈ 49 / 100 contre ≈ 23).
4. Dire : « Lowbid note chaque offre sur le prix, le délai et les compétences. Yanis est recommandé. »
5. Panneau **Vos priorités** : glisser le curseur **Prix** vers **90** (les deux autres tombent à 5).
   - Le basculement se fait vers 80 ; à 90 l'écart est net (≈ 25 contre 17).
6. Écran : Nora remonte en 1re, le badge **Recommandé** passe sur elle.
7. Dire : « Si le prix compte plus pour moi, c'est Nora qui passe devant. Mais c'est moi qui décide. »
8. *(Optionnel)* bouton ↺ (Revenir à 40 / 30 / 30).
9. Sur la ligne de Yanis → **Choisir** → confirmation « Retenir l'offre G… · 9.00 USDC ? » → **OK**.
10. Écran : panneau **Offre retenue** (9.00 USDC) + panneau **Paiement en escrow** dessous.
11. Dire : « Je choisis Yanis : plus rapide, toutes les compétences. »

### 1:30 → 2:00 — L'escrow (fenêtre Client)

> Le panneau est dans la **colonne de droite**, sous « Offre retenue ».
> Titre **Paiement en escrow**, étapes : Escrow créé · Fonds bloqués · Livré · Fonds libérés.

1. **Créer l'escrow** → toast « Signature demandée » → popup Freighter → **Sign**.
2. Écran : « Envoi sur le réseau Stellar… » puis « Escrow créé sur Stellar. » → la page se recharge.
3. Dire : « Je crée l'escrow : Trustless Work déploie un contrat sur Stellar. »
4. **Bloquer les fonds** → popup Freighter → **Sign**.
5. Écran : « Fonds bloqués dans l'escrow. », badge **Fonds bloqués**.
6. Dire : « Je bloque les fonds : mes 9 USDC partent dans le contrat. Ni chez le freelance, ni chez nous. »
7. Bas du panneau : lien **Contrat escrow** `C…` → s'ouvre sur stellar.expert.
8. Dire : « Voilà le contrat, public, sur stellar.expert. Yanis sait que l'argent existe avant de commencer. »

### 2:00 → 2:30 — Livraison et libération

**Yanis livre (fenêtre Freelance 1)**

1. `F5` sur le besoin (relance aussi le suivi du solde, actif **2 min** après chaque chargement).
2. Panneau : **Note de livraison** → `https://figma.com/… maquette + code livrés`.
3. **Déclarer la livraison** → popup Freighter → **Sign**.
4. Écran : « Livraison déclarée. Le client peut valider. »
5. Dire : « Yanis livre, et signe de son côté. »

**Claire valide et libère (fenêtre Client)**

1. `F5` → **Valider la livraison** → popup Freighter → **Sign**.
2. Écran : « Livraison validée. Vous pouvez libérer les fonds. »
3. Dire : « Je vérifie, je valide. »
4. **Libérer les fonds** → popup Freighter → **Sign**.
5. Écran : « Fonds libérés vers le freelance. » puis encadré vert « Fonds libérés vers le freelance. Merci ! »

**💰 Le plan qui compte**

- Où : panneau **Paiement en escrow** → 3e ligne **Solde USDC du freelance** (sous « Montant » et « Freelance »).
- Elle passe de `0.00 USDC` à ≈ `8.9x USDC` (montant moins les frais).
- Effet « en direct » : basculer sur la fenêtre **Freelance 1** (rechargée il y a < 2 min) → la ligne change toute seule dans les 5 s.
- Bas du panneau : lien **Libération des fonds** → stellar.expert montre le virement vers Yanis.
- Bonus : ouvrir Freighter de Freelance 1 → la ligne USDC.
- Dire : « Regardez son solde : il vient de monter, en cinq secondes. Pas de virement, pas trente jours d'attente. »

### 2:30 → 3:00 — Pourquoi Stellar

| | |
|---|---|
| Fenêtre | Client, onglet **deck** (slide 4) |
| Dire | « Pourquoi Stellar ? … Lowbid : les freelances se battent sur le prix, et ils sont sûrs d'être payés. » |

### Qui signe quoi

**Mode escrow** (par défaut) — 5 signatures de transaction :

| # | Fenêtre | Bouton | Ce que fait la signature |
|---|---|---|---|
| 1 | Client | **Créer l'escrow** | déploie le contrat Trustless Work |
| 2 | Client | **Bloquer les fonds** | envoie 9 USDC dans le contrat |
| 3 | Freelance 1 | **Déclarer la livraison** | marque le jalon « livré » |
| 4 | Client | **Valider la livraison** | approuve le jalon |
| 5 | Client | **Libérer les fonds** | le contrat paie Yanis |

→ Client : **4**. Freelance : **1**. (+ 1 « Sign message » par connexion.)

**Mode direct** (`LOWBID_PAYMENT_MODE=direct`) — 1 signature de transaction :

| # | Fenêtre | Bouton | Signature ? |
|---|---|---|---|
| 1 | Freelance 1 | **Déclarer la livraison** | non (simple déclaration, « Envoi… ») |
| 2 | Client | **Valider et payer** | **oui** : un paiement USDC Client → Yanis |

- Le panneau s'appelle **Paiement direct USDC** + badge **Plan B**. Étapes : Livré · Payé.
- Lien du bas : **Paiement USDC**.
- Avant la livraison, le bouton client s'appelle **Payer le freelance** : attendre la livraison pour filmer **Valider et payer**.

### Popup Freighter lente ou absente

1. Attendre **10 s** (le toast « Signature demandée » est affiché).
2. Pas de popup ? Cliquer l'icône **Freighter** dans la barre : la demande en attente s'y trouve.
3. Freighter demande le mot de passe ? Le taper, la demande continue.
4. Toujours rien ? `F5` puis recliquer le bouton. Rien n'a été envoyé, rien n'est perdu.
5. Popup refusée par erreur ? Toast « Signature refusée dans Freighter — rien n'a été envoyé. » → recliquer.

---

## 4. Plan B / Plan C pendant l'enregistrement

### 4.0 Besoin de secours (à préparer le matin, 5 min, hors caméra)

- [ ] Créer un 2e besoin identique (budget 10, offres Yanis 9 / Nora 7,50).
- [ ] **Clôturer les enchères maintenant** → **Choisir** Yanis. **Ne pas cliquer plus loin.**
- [ ] Noter son URL `/besoins/<n>/` : il attend en état « attribué », sans escrow, prêt pour les deux modes.

### 4.1 Une signature échoue

- Message en rouge sous le bouton + toast. **Le même bouton redevient cliquable** : c'est le bouton « réessayer ».
- Recliquer **une** fois.
- Message « confirmation en attente » ? **Ne pas re-signer** : lien explorateur, puis `F5` dans 30 s.

### 4.2 Trustless Work tombe en pleine démo

1. `.env` : `LOWBID_PAYMENT_MODE=direct`
2. Terminal 1 : `Ctrl+C` → `make run` → **≈ 10 secondes**.
3. Escrow **pas encore créé** (étape « Escrow créé » non cochée) ? Le même besoin passe en direct : `F5`.
4. Escrow **déjà créé** ? Ce besoin reste en escrow. Ouvrir le **besoin de secours** (§4.0).
5. **Ré-enregistrer à partir de 1:30 seulement**, avec les lignes « Variante paiement direct » (PITCH §A).

### 4.3 Tout est en panne (réseau, testnet, Horizon)

- [ ] Monter la **répétition enregistrée hier soir** (§1.9) à la place des blocs 0:30 → 2:30.
- [ ] Ajouter la capture du `contractId` du smoke test.
- [ ] Le dire honnêtement dans la vidéo : « enregistré hier soir sur testnet ».
- [ ] Wifi seul en cause ? Partage de connexion du téléphone, puis on reprend.

---

## 5. Après la vidéo (9 h → 11 h)

> ⏰ Alarmes : **10:30** (commencer la soumission) et **11:00** (deadline).

### 5.1 Vidéo (9:00)

- [ ] Montage minimal : couper les attentes de popup. Viser 2 min 30 à 3 min.
- [ ] Upload YouTube **non répertorié** (ou Loom). Tester le lien en navigation privée.
- [ ] Coller le lien dans `README.md` → ligne **Demo video**.

### 5.2 Deck (9:30)

- [ ] Prendre les captures dans `docs/screenshots/` (produites par l'agent QA) : liste dans `PITCH.md` §B, slide 3.
- [ ] 5 slides (`PITCH.md` §B). Export PDF. Lien → `README.md` ligne **Pitch deck**.

### 5.3 README (10:00)

- [ ] **Status / what works** : cocher **uniquement** ce qui a marché pour de vrai à l'enregistrement.
  - Mode escrow OK → cocher « Escrow create » + « Escrow release ».
  - Mode direct utilisé → cocher seulement « Plan B: direct USDC payment ».
  - « Wallet login » → coché si la connexion Freighter a marché.
- [ ] **Testnet addresses** : les 3 `G…` + le `C…` du contrat de la vidéo.
- [ ] Colonne stellar.expert :
  - compte : `https://stellar.expert/explorer/testnet/account/G…`
  - contrat : `https://stellar.expert/explorer/testnet/contract/C…`
  - (copier les liens du bas du panneau : **Contrat escrow**, **Libération des fonds**)
- [ ] **Team** : noms, rôles, liens.
- [ ] `git add README.md docs/ && git commit -m "docs: demo links + testnet addresses" && git push`

### 5.4 Soumission (10:30 → au plus tard 10:55)

- [ ] https://app.hackmeridian.com → formulaire de soumission.
- [ ] Repo GitHub, lien vidéo, lien deck, track **Composed**.
- [ ] **Envoyer avant 11:00**. Capture d'écran de la confirmation.
