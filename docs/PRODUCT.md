# Lowbid 📉 — Spécification produit

> Le client poste un besoin et un budget max. Les freelances enchérissent à la baisse. Le gagnant est payé en USDC via un escrow on-chain.

Version hackathon (Hack Meridian, réseau Stellar **testnet** uniquement).

## 1. Personas

**Claire, gérante d'une PME (le client)**
- 12 salariés, a besoin d'une landing page ou d'un petit outil interne deux ou trois fois par an.
- Ne sait pas si 400 ou 1 200 € est un prix juste : elle n'a jamais plus d'un devis à comparer.
- Veut payer seulement quand le travail est livré, sans passer par une plateforme qui prend 20 %.

**Yanis, freelance dev / designer**
- Indépendant, 3 ans d'expérience, Django et UI.
- A déjà attendu 60 jours un virement, et une fois n'a jamais été payé.
- Veut savoir que l'argent existe *avant* de commencer, et le recevoir en quelques secondes à la livraison.

## 2. Le parcours en 10 étapes

1. Le client connecte son wallet **Freighter** (testnet). La connexion = un message signé, pas de mot de passe.
2. Il poste un besoin : titre, description, **budget max (USDC)**, **délai max (jours)**, jusqu'à 3 tags de compétences, durée des enchères (30 min, 2 h, 24 h ou 3 jours ; 2 h par défaut).
3. Les freelances connectent leur propre wallet Freighter.
4. Chaque freelance enchérit : prix, délai en jours, tags, message court. Le prix doit être **strictement inférieur** à la dernière offre.
5. À la fin du timer — ou plus tôt si le client clique sur « Clôturer les enchères maintenant » — le besoin est fermé : plus aucune enchère.
6. Lowbid calcule un score par offre et affiche la liste triée ; la meilleure reçoit le badge **« Recommandé »**.
7. Le client peut repondérer prix / délai / compétences avec 3 curseurs.
8. **Le client choisit** n'importe quelle offre. La recommandation est une aide, pas une règle.
9. Le client finance : **« Créer l'escrow »** (Trustless Work déploie un contrat Soroban, une signature Freighter) puis **« Bloquer les fonds »** (les USDC partent dans le contrat, deuxième signature).
10. Le freelance clique sur **« Déclarer la livraison »**, le client sur **« Valider la livraison »** puis **« Libérer les fonds »** : l'escrow verse les USDC sur le wallet du freelance (moins les frais).

**Plan B (mode direct, sans escrow).** Si Trustless Work est indisponible (`LOWBID_PAYMENT_MODE=direct`), les étapes 9 et 10 se réduisent à un seul paiement USDC signé par le client : **« Payer le freelance »**, ou **« Valider et payer »** si le freelance a déjà déclaré la livraison (déclaration facultative, sans transaction).

## 3. Règles métier (énoncés testables)

**Enchères**
- R1. Une enchère dont le prix n'est pas strictement inférieur à la dernière offre du besoin est refusée.
- R2. Une enchère dont le prix dépasse le budget max est refusée (prix ≤ budget max).
- R3. Une enchère dont le délai dépasse le délai max est refusée (délai ≤ délai max).
- R4. Une enchère reçue après la deadline est refusée, même si la page était encore ouverte.
- R5. Le client ne peut pas enchérir sur son propre besoin (même adresse Stellar = refus).
- R6. Un freelance a au plus une enchère active par besoin. Une nouvelle enchère du même freelance remplace l'ancienne si elle est plus basse (et respecte R1) ; sinon elle est refusée et l'ancienne reste active.
- R7. Le prix et le délai sont des nombres strictement positifs ; le prix a au plus 7 décimales (précision USDC sur Stellar).
- R8. Il faut un wallet connecté pour poster un besoin ou enchérir.

**Choix et paiement**
- R9. Le client peut choisir n'importe quelle offre active, pas seulement celle qui porte le badge « Recommandé ».
- R10. Seul l'auteur du besoin peut clôturer, annuler, choisir le gagnant, payer, valider la livraison et libérer les fonds. Seul le freelance retenu peut déclarer la livraison. Chaque étape est vérifiée côté serveur contre le wallet de la session.
- R11. Après le choix, l'offre retenue passe à `won` et toutes les autres offres actives à `lost` (« non retenues ») ; les offres déjà `outbid` le restent.
- R12. Le panneau de paiement n'apparaît qu'à partir d'un besoin `awarded`. En mode escrow, le client signe deux transactions dans l'ordre : « Créer l'escrow » puis « Bloquer les fonds ». En mode direct, un seul bouton : « Payer le freelance » (« Valider et payer » si la livraison est déjà déclarée). Le montant est exactement le prix de l'offre retenue ; en mode escrow, les frais (plateforme + protocole) sont prélevés à la libération, sur ce montant.
- R13. En mode escrow, les fonds ne sont libérés qu'après une livraison déclarée par le freelance puis validée par le client (« Valider la livraison », puis « Libérer les fonds » : deux signatures). En mode direct (Plan B), le client peut payer dès l'attribution, avant toute déclaration de livraison : choix délibéré du MVP, documenté dans `docs/ARCHITECTURE.md`.
- R14. Un besoin peut être annulé par le client tant qu'il est `open`, `closed` ou `awarded` (un escrow créé mais pas encore financé n'engage aucun fonds). En mode escrow, dès que les fonds sont bloqués (`funded`), l'argent n'en sort que par la libération (ou un litige, hors scope). En mode direct, l'annulation n'est plus possible une fois la livraison déclarée (`delivered`).
- R15. Le client peut clôturer les enchères avant la fin du timer (« Clôturer les enchères maintenant ») ; le besoin passe aussitôt à `closed`.

## 4. Le score

```
score = wP * (1 - prix / budget_max)
      + wD * (1 - délai / délai_max)
      + wT * (tags communs / tags demandés)
```

- Poids par défaut : **wP = 40, wD = 30, wT = 30**.
- Chaque terme entre parenthèses est borné à `[0, 1]` avant pondération (un terme négatif compte 0).
- Si le client n'a demandé aucun tag, le terme compétences vaut 1 pour tout le monde (neutre).
- Le score est sur 100. En cas d'égalité, l'offre la moins chère passe devant, puis la plus ancienne.

### Exemple chiffré

Besoin : budget max **500 USDC**, délai max **10 jours**, tags demandés **[django, stellar, ui]** (3 tags).

> Ces montants servent à illustrer le calcul. La démo live reste **≤ 10 USDC** (le faucet Circle donne 10 USDC par adresse et par 24 h) : budget 10, offres 9 → 9,20 refusée → 7,50 (voir `docs/DEMO_RUNBOOK.md`). Le score ne dépend que des rapports prix / budget et délai / délai max, donc l'échelle ne change rien.

| | Offre A | Offre B |
|---|---|---|
| Prix | 450 USDC | 380 USDC |
| Délai | 8 j | 12 j |
| Tags en commun | 2 / 3 | 1 / 3 |

**Exemple 1 — Offre A (poids 40/30/30)**
- Prix : 1 − 450/500 = 0,10 → 40 × 0,10 = **4,0**
- Délai : 1 − 8/10 = 0,20 → 30 × 0,20 = **6,0**
- Compétences : 2/3 = 0,667 → 30 × 0,667 = **20,0**
- **Score A = 30,0**

**Exemple 2 — Offre B (poids 40/30/30)**
- Prix : 1 − 380/500 = 0,24 → 40 × 0,24 = **9,6**
- Délai : 1 − 12/10 = −0,20 → borné à 0 → **0,0**
- Compétences : 1/3 = 0,333 → 30 × 0,333 = **10,0**
- **Score B = 19,6**

B est 70 USDC moins chère et gagne sur le prix (9,6 contre 4,0), mais **A est recommandée** (30,0 contre 19,6) : elle tient le délai et couvre deux compétences sur trois.

> Note d'honnêteté : avec la règle R3 (délai ≤ délai max), l'offre B serait refusée au formulaire. Elle sert ici à montrer le bornage à 0 ; le calcul reste défensif si R3 est un jour assouplie.

**Effet des curseurs.** Si le client met les poids à 70 / 10 / 20 (il veut surtout payer moins) :
- A = 70 × 0,10 + 10 × 0,20 + 20 × 0,667 = 7,0 + 2,0 + 13,3 = **22,3**
- B = 70 × 0,24 + 10 × 0 + 20 × 0,333 = 16,8 + 0 + 6,7 = **23,5**

B passe devant. Même données, autre priorité, autre recommandation : c'est pour ça que le client garde la main.

### Curseurs

- Trois curseurs : Prix, Délai, Compétences. Valeurs par défaut 40 / 30 / 30.
- La somme fait **toujours 100** : bouger un curseur répartit la différence sur les deux autres, au prorata.
- Chaque poids est un entier entre 0 et 100.
- Le recalcul est immédiat côté navigateur ; le badge « Recommandé » suit les curseurs.
- Les curseurs ne changent que l'affichage du client : ils ne modifient pas les offres et ne choisissent rien à sa place.

## 5. États

Deux machines à états : le **besoin** (`Need.status`, app `auctions`) et la ligne **Escrow** (`Escrow.status`, app `payments`, une par besoin attribué, créée à la première action de paiement). Le mode (`escrow` ou `direct`) est figé sur cette ligne à ce moment-là ; tant qu'elle est `created` (rien on-chain), il peut encore basculer.

### Besoin

```
open ──(timer fini ou clôture manuelle)──> closed ──(client choisit)──> awarded

Mode escrow :
awarded ──(fonds bloqués)──> funded ──(freelance livre)──> delivered ──(fonds libérés)──> released

Mode direct (Plan B) :
awarded ──(freelance déclare, facultatif)──> delivered ──(client paie)──> released
awarded ─────────────────(client paie directement)───────────────────────> released

open / closed / awarded ──(client annule)──> cancelled
```

| État | Signification |
|---|---|
| `open` | Enchères ouvertes, timer en cours |
| `closed` | Timer fini (ou clôture manuelle), scores calculés, le client n'a pas encore choisi |
| `awarded` | Une offre est retenue, fonds pas encore bloqués (en mode escrow, l'escrow peut déjà être créé) |
| `funded` | Mode escrow uniquement : USDC bloqués dans l'escrow Trustless Work |
| `delivered` | Le freelance a déclaré la livraison |
| `released` | Les USDC sont sur le wallet du freelance (libérés par l'escrow, ou payés en direct) — libellé « Payé » |
| `cancelled` | Annulé par le client (depuis `open`, `closed` ou `awarded`) |

Un besoin `closed` sans aucune enchère reste visible avec le message « Aucune offre » et peut être annulé.

### Escrow (paiement)

| État | Libellé UI | Mode | Signification |
|---|---|---|---|
| `created` | En préparation | les deux | Ligne créée, rien on-chain |
| `deployed` | Escrow créé | escrow | Contrat Soroban déployé, pas encore financé |
| `funded` | Fonds bloqués | escrow | USDC dans le contrat |
| `delivered` | Livré | les deux | Le freelance a déclaré la livraison (jalon on-chain en mode escrow, simple note en base en mode direct) |
| `approved` | Livraison validée | escrow | Le client a approuvé le jalon, fonds toujours bloqués |
| `released` | Fonds libérés | escrow | L'escrow a versé les USDC au freelance |
| `paid` | Payé | direct | Paiement USDC direct confirmé par Horizon |

Le modèle définit aussi `failed`, mais le flux ne l'utilise pas : un refus de Trustless Work ou d'Horizon ne change pas l'état, le message est gardé et l'utilisateur réessaie.

**Mode escrow — une étape = une signature Freighter**

| Étape | Qui signe | Bouton | Escrow avant → après | Besoin avant → après |
|---|---|---|---|---|
| `deploy` | client | « Créer l'escrow » | `created` → `deployed` | `awarded` (inchangé) |
| `fund` | client | « Bloquer les fonds » | `deployed` → `funded` | `awarded` → `funded` |
| `deliver` | freelance retenu | « Déclarer la livraison » | `funded` → `delivered` | `funded` → `delivered` |
| `approve` | client | « Valider la livraison » | `delivered` → `approved` | `delivered` (inchangé) |
| `release` | client | « Libérer les fonds » | `approved` → `released` | `delivered` → `released` |

**Mode direct (Plan B) — pas de `funded` ni d'`approved`**

| Étape | Qui signe | Bouton | Escrow avant → après | Besoin avant → après |
|---|---|---|---|---|
| `deliver` (facultatif) | freelance retenu, **sans transaction** | « Déclarer la livraison » | `created` → `delivered` | `awarded` → `delivered` |
| `direct_pay` | client | « Payer le freelance », ou « Valider et payer » après livraison | `created` / `delivered` → `paid` | `awarded` / `delivered` → `released` |

### Enchère

| État | Signification |
|---|---|
| `active` | Meilleure offre actuelle de ce freelance sur ce besoin |
| `outbid` | Remplacée par une offre plus basse du même freelance |
| `won` | Choisie par le client |
| `lost` | Non retenue après le choix du client |

Note : `outbid` décrit le remplacement par le *même* freelance (R6). Les offres plus chères des autres freelances restent `active` jusqu'au choix : le client peut les retenir.

## 6. Écrans

**Landing**
- La phrase de pitch, un bouton « Connecter mon wallet Freighter » (une fois connecté : « Poster un besoin » et « Voir les besoins »), un schéma en 3 étapes (poster, enchérir à la baisse, escrow USDC sur Soroban).
- Un badge « Hack Meridian · Stellar testnet » ; le lien « Installer Freighter » est dans le pied de page de toutes les pages.
- Dans la barre de navigation, le bouton s'appelle « Connecter le wallet » (« Connecter » sur mobile) ; connecté, il affiche l'adresse abrégée avec un menu (copier, déconnexion).

**Liste des besoins**
- Cartes : titre, tags (cliquables), budget max, meilleure offre actuelle, nombre d'enchères + délai max, temps restant, client.
- Onglets « Ouverts » (par défaut), « Terminés », « Tous » ; filtre par tag (`?tag=`).

**Détail d'un besoin**
- En-tête : titre, description, budget max, délai max, tags, état ; tuiles Budget max / Meilleure offre / Enchères / Temps restant.
- Timer visible en permanence (passe en `closed` à zéro, sans recharger la page).
- Liste des enchères : prix, délai, tags, message, adresse abrégée du freelance, score une fois fermé, badge « Recommandé ».
- Formulaire d'enchère (freelance connecté, besoin `open`) avec le prix plafond affiché : « Doit être inférieur à X USDC » ; bouton « Envoyer mon offre » (« Remplacer mon offre » s'il en a déjà une).
- Vue client pendant les enchères : « Clôturer les enchères maintenant » et « Annuler le besoin ».
- Vue client après le timer : 3 curseurs (« Vos priorités ») + bouton « Choisir » sur chaque offre.

**Poster un besoin**
- Titre, description, budget max, délai max, 3 tags max, durée des enchères : **30 min, 2 h (par défaut), 24 h, 3 jours**. Avec `?demo=1` dans l'URL (lien « Mode démo (5 min) » sous le champ), l'option « 5 min (démo) » apparaît en tête et devient la valeur par défaut.
- Compteur de tags en direct (« 2 / 3 compétences ») ; validation côté serveur, erreurs affichées sous chaque champ ; publication liée à l'adresse du wallet connecté.

**Mes enchères**
- Pour le freelance : chaque besoin où il a enchéri, son offre, son état (`active`, `outbid`, `won`, `lost`) et, s'il a gagné, l'état du paiement (badge) avec un lien « Voir le paiement ».
- Pas de bouton d'action ici : « Déclarer la livraison » se fait dans le panneau de paiement de la page du besoin (le lien y mène directement, ancre `#paiement`).

**Panneau Paiement** (dans le détail d'un besoin `awarded` et après)
- Titre « Paiement en escrow » (mode escrow) ; montant, adresse du freelance, solde USDC du freelance lu en direct sur Horizon.
- Une frise d'avancement : Escrow créé → Fonds bloqués → Livré → Fonds libérés (mode direct : Livré → Payé).
- Un seul bouton à la fois, celui de l'étape en cours, visible seulement par la personne qui doit signer (les autres voient « En attente de … ») : « Créer l'escrow », « Bloquer les fonds », « Déclarer la livraison » (avec une note de livraison facultative), « Valider la livraison », « Libérer les fonds ». Chaque bouton = une signature Freighter.
- Un bouton « Ajouter la trustline USDC » pour le client et le freelance.
- À chaque étape, le **lien stellar.expert** de la transaction ou du contrat.
- Si le mode Plan B est actif : titre « Paiement direct USDC » avec un badge « Plan B », sous-titre « Paiement USDC de wallet à wallet sur Stellar, sans escrow. », et les boutons « Déclarer la livraison » (freelance, sans transaction) et « Payer le freelance » / « Valider et payer » (client).

## 7. Hors scope hackathon

- Mainnet et vrais fonds.
- Litiges et arbitrage (rôle dispute resolver de Trustless Work).
- Réputation des freelances (Stellar Passport, historique).
- Enchères cachées (commit-reveal).
- Stockage des enchères on-chain dans un contrat Soroban : aujourd'hui elles sont en base Django (SQLite par défaut, PostgreSQL si `DJANGO_DB_HOST` est défini).
- Sortie en euros via un anchor (SEP-24).
- Explication IA de la recommandation.
- Paiements par jalons, plusieurs livrables, messagerie, notifications e-mail.
- Comptes multi-utilisateurs par entreprise.
