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
2. Il poste un besoin : titre, description, **budget max (USDC)**, **délai max (jours)**, jusqu'à 3 tags de compétences, fin des enchères (ex. dans 2 h).
3. Les freelances connectent leur propre wallet Freighter.
4. Chaque freelance enchérit : prix, délai en jours, tags, message court. Le prix doit être **strictement inférieur** à la dernière offre.
5. À la fin du timer, le besoin est fermé : plus aucune enchère.
6. Lowbid calcule un score par offre et affiche la liste triée ; la meilleure reçoit le badge **« Recommandé »**.
7. Le client peut repondérer prix / délai / compétences avec 3 curseurs.
8. **Le client choisit** n'importe quelle offre. La recommandation est une aide, pas une règle.
9. Le client clique sur **« Payer »** : Trustless Work crée un escrow Soroban qui bloque les USDC.
10. Le freelance livre, le client valide, l'escrow libère les USDC vers le wallet du freelance.

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
- R10. Seul l'auteur du besoin peut choisir le gagnant, payer et valider la livraison.
- R11. Après le choix, l'offre retenue passe à `won` et toutes les autres à `lost` (« non retenues »).
- R12. Le bouton « Payer » n'existe que pour un besoin `awarded` ; le montant de l'escrow est exactement le prix de l'offre retenue.
- R13. La libération des fonds n'est possible qu'après une livraison déclarée par le freelance et validée par le client.
- R14. Un besoin peut être annulé par le client tant qu'il n'est pas `funded`. Ensuite, l'argent est dans l'escrow et n'en sort que par release (ou litige, hors scope).

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

### Besoin

```
open ──(timer fini)──> closed ──(client choisit)──> awarded ──(escrow créé)──> funded
                                                                                  │
                         released <──(client valide, escrow libère)── delivered <─┘
                                                                  (freelance livre)

open / closed / awarded ──(client annule)──> cancelled
```

| État | Signification |
|---|---|
| `open` | Enchères ouvertes, timer en cours |
| `closed` | Timer fini, scores calculés, le client n'a pas encore choisi |
| `awarded` | Une offre est retenue, paiement pas encore fait |
| `funded` | Escrow Trustless Work créé, USDC bloqués |
| `delivered` | Le freelance a déclaré la livraison |
| `released` | Le client a validé, les USDC sont sur le wallet du freelance |
| `cancelled` | Annulé par le client avant financement |

Un besoin `closed` sans aucune enchère reste visible avec le message « Aucune offre » et peut être annulé.

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
- La phrase de pitch, un bouton « Connecter Freighter », un schéma en 3 étapes (poster, enchérir, payer).
- Un encart « Testnet uniquement » avec un lien pour installer Freighter.

**Liste des besoins**
- Cartes : titre, budget max, délai max, tags, nombre d'offres, meilleure offre actuelle, temps restant.
- Filtre par tag ; les besoins `open` d'abord.

**Détail d'un besoin**
- En-tête : titre, description, budget max, délai max, tags, état.
- Timer visible en permanence (passe en `closed` à zéro, sans recharger la page).
- Liste des enchères : prix, délai, tags, message, adresse abrégée du freelance, score une fois fermé, badge « Recommandé ».
- Formulaire d'enchère (freelance connecté, besoin `open`) avec le prix plafond affiché : « Doit être inférieur à X USDC ».
- Vue client après le timer : 3 curseurs + bouton « Choisir » sur chaque offre.

**Poster un besoin**
- Titre, description, budget max, délai max, 3 tags max, durée des enchères (30 min, 1 h, 2 h, 24 h).
- Validation en direct ; publication liée à l'adresse du wallet connecté.

**Mes enchères**
- Pour le freelance : chaque besoin où il a enchéri, son offre, son état (`active`, `outbid`, `won`, `lost`), et l'état du paiement s'il a gagné.
- Bouton « Déclarer la livraison » sur un besoin `funded` gagné.

**Panneau Paiement / escrow** (dans le détail d'un besoin `awarded` et après)
- Montant, adresse du freelance, bouton « Payer » (signature dans Freighter).
- Suivi : escrow créé → livré → libéré, avec à chaque étape le **lien stellar.expert** de la transaction ou du contrat.
- Bouton « Valider et libérer les fonds » pour le client sur un besoin `delivered`.
- Si le mode Plan B est actif : un bandeau clair « Paiement direct, sans escrow ».

## 7. Hors scope hackathon

- Mainnet et vrais fonds.
- Litiges et arbitrage (rôle dispute resolver de Trustless Work).
- Réputation des freelances (Stellar Passport, historique).
- Enchères cachées (commit-reveal).
- Stockage des enchères on-chain dans un contrat Soroban : aujourd'hui elles sont en base SQLite.
- Sortie en euros via un anchor (SEP-24).
- Explication IA de la recommandation.
- Paiements par jalons, plusieurs livrables, messagerie, notifications e-mail.
- Comptes multi-utilisateurs par entreprise.
