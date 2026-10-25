# TaskVault — Brief complet pour préparer la présentation

> Document autonome à coller dans un assistant IA (Gemini, etc.) pour préparer le pitch, le deck et la vidéo.
> Tout ce qui est écrit ici est vérifié dans le code et la doc du repo. Les libellés de l'interface sont en anglais (copiés tels quels).

---

## 0. Ce que je te demande (consigne pour l'IA)

Tu m'aides à préparer la présentation de **TaskVault** pour le hackathon **Hack Meridian (Stellar)**, track **Composed**.
Je veux :
1. Un **deck de 5 à 7 slides** (titre, problème, solution, démo, stack Stellar, pourquoi c'est solide, suite).
2. Un **script vidéo de 2:30 à 3:00** (voix off en français, interface en anglais).
3. Des **réponses courtes** aux questions probables du jury.
Ton : direct, concret, une idée par slide, pas de jargon inutile. Ne jamais inventer de chiffre ou de fonctionnalité qui n'est pas dans ce brief.

---

## 1. Le pitch en une phrase

**« Une entreprise découpe son projet en tâches à prix fixe ; l'argent de chaque tâche est bloqué sur Stellar avant que le travail commence, et versé au wallet du freelance dès que l'entreprise valide. »**

Version anglaise : *"A company splits its project into fixed-price tasks; each task's money is locked on Stellar before the work starts and released to the freelance's wallet the moment the company approves."*

Slogan de fin : **« TaskVault: fixed prices, earned trust, guaranteed payment. »**

---

## 2. Le problème

- **Freelances payés en retard, ou jamais.** (Persona Yanis : a déjà attendu 60 jours un virement, et une fois n'a jamais été payé.)
- **Les petites entreprises** qui répartissent un projet entre plusieurs freelances jonglent avec devis, factures et confiance, une personne à la fois, sans historique partagé.
- **Les grandes plateformes** prennent typiquement **10 à 20 %** de commission (grilles publiques des grosses marketplaces) et gardent l'argent jusqu'à leur cycle de paiement.
- **La course au prix le plus bas** (enchères inversées) produit du travail bâclé et pénalise les bons freelances.

---

## 3. La solution : comment ça marche

1. **L'entreprise** se connecte avec son wallet **Freighter** : un message signé, **pas de compte, pas de mot de passe**.
2. Elle crée un **projet** et le découpe en **tâches**, chacune avec un **prix fixe en USDC** et jusqu'à 3 compétences (tags).
3. **Les freelances** se connectent avec leur propre wallet et voient un **kanban** des tâches (Open, Taken, Delivered, Paid).
4. Un freelance **postule** avec un message court et ses compétences. **Pas de prix à négocier** : c'est l'entreprise qui fixe le prix.
5. TaskVault **classe les candidats** avec un **score déterministe et explicable** (pas d'IA, pas de boîte noire). Deux badges : **« Validated »** et **« Recommended »**.
6. **L'entreprise choisit** qui elle veut. Le score est un conseil, pas une règle (le bouton « Choose » est sur chaque ligne).
7. **« Fund the project »** : pour chaque tâche attribuée, un **escrow Trustless Work est déployé sur Soroban** (smart contract Stellar) avec le freelance comme bénéficiaire, puis l'entreprise y dépose le prix de la tâche. **L'argent n'est plus chez l'entreprise, et pas encore chez le freelance.**
8. Le freelance **livre** : il colle le lien (PR, démo, repo) et signe → le lien est **enregistré on-chain comme preuve de livraison**.
9. L'entreprise vérifie, **note de 1 à 5 étoiles**, signe l'approbation puis la **libération des fonds** → les USDC arrivent dans le wallet du freelance **en ~5 secondes**. La tâche passe « Paid ». Quand toutes les tâches sont payées, le projet est « Closed ».

**Effet boule de neige :** à la tâche suivante, un freelance qui a bien livré pour cette entreprise remonte en tête de sa liste, avec « Validated » + « Recommended ». **La confiance se gagne tâche par tâche.**

---

## 4. Pourquoi le produit est bien (les arguments forts)

### Pour le freelance
- **Il sait que l'argent existe avant d'écrire une ligne de code** : il est verrouillé dans un contrat public, visible sur stellar.expert.
- **Payé en secondes**, en dollar stable (USDC), directement dans **son** wallet. Pas de virement, pas de 30 jours.
- **Pas de course au moins-disant** : on se bat sur la compétence et l'historique, pas sur le prix.
- **Il signe lui-même sa livraison** : personne ne peut la déclarer à sa place.

### Pour l'entreprise
- **Elle fixe le prix** et **paie uniquement un travail livré et validé**.
- **Elle voit tout de suite** quels freelances ont déjà bien travaillé pour elle (score + badges).
- **Elle garde le dernier mot** : le score aide, il ne décide pas.
- **Un tableau de bord** lui dit quoi faire ensuite (candidats à choisir, tâches à financer, livraisons à valider, paiements à signer).

### Pour tout le monde
- **Personne ne peut partir avec l'argent** : ni l'entreprise, ni le freelance, ni la plateforme. **TaskVault ne détient jamais de clé privée** ; chaque mouvement d'argent est signé par la personne concernée dans son propre wallet.
- **Score transparent** : n'importe qui peut le recalculer à la main (voir §6).
- **Équitable pour les nouveaux** : un nouveau peut avoir jusqu'à 20 points grâce à ses compétences, et l'historique ne compte que l'expérience *de cette entreprise* avec lui (être bien noté ailleurs n'écrase pas un nouveau ici).

### Un escrow PAR tâche (choix technique malin, à mettre en avant)
- Chaque tâche a son propre contrat, avec exactement le prix de la tâche.
- Pourquoi pas un seul escrow par projet ? Trustless Work v1 fixe le bénéficiaire au déploiement et le gèle une fois financé ; or les tâches trouvent leur freelance à des moments différents.
- Le multi-release a été étudié puis rejeté : un seul prestataire par escrow, donc les freelances n'auraient pas pu signer leur propre livraison.

---

## 5. Pourquoi Stellar (track Composed = 3 briques assemblées en 1 flux)

| Brique | Rôle dans TaskVault |
|--------|---------------------|
| **Freighter** | L'identité **et** la signature. Connexion par message signé (SEP-53). Chaque étape de paiement est signée dans le wallet de l'utilisateur. |
| **USDC sur Stellar** | Paiement en dollar stable, réglé en **~5 secondes**, frais réseau d'environ **0,00001 XLM** pour un paiement classique (les appels Soroban de l'escrow ajoutent des frais de ressources, toujours une fraction de centime). |
| **Trustless Work (Soroban)** | Un **escrow single-release par tâche** : déploiement, financement, livraison (lien en preuve), approbation, libération. |

- **Pas de banque dans la boucle**, pas de commission de 10–20 %, pas de délai de virement.
- **Mode de secours honnête** : si l'escrow échoue en démo, on bascule (`LOWBID_PAYMENT_MODE=direct` + redémarrage, ~10 s) sur un **paiement USDC direct** wallet à wallet. Ça se règle toujours sur Stellar en quelques secondes, mais **sans la garantie de l'escrow** (rien n'est bloqué avant le travail). L'interface l'affiche clairement (badge « no escrow »).

---

## 6. Le score (à montrer sur une slide)

```
score = 40 × [le freelance a déjà au moins 1 tâche PAYÉE par cette entreprise]
      +  8 × note moyenne donnée par cette entreprise (0 sans note)
      + 20 × (tags en commun / tags de la tâche)
```
Maximum **100**.
- **« Validated »** = déjà payé par cette entreprise avec une note moyenne ≥ 3.
- **« Recommended »** = meilleur score parmi les candidats en attente.

**Exemple de la démo**, tâche « Freighter integration » (tags `stellar, js`) :
- **Yanis** (A) : déjà payé 5/5 pour la landing page, postule avec `stellar` → 40 + 5×8 + 20×½ = **90**
- **Nora** (B) : première collaboration, postule avec `stellar, js` → 0 + 0 + 20×2/2 = **20**

---

## 7. Pourquoi c'est solide techniquement (preuves de qualité)

- **245 tests automatisés** Django (règles métier, score, flux de paiement dans les deux modes, réseau simulé).
- **Un test end-to-end complet dans un vrai navigateur** (Playwright) : entreprise + 3 freelances, avec un Freighter simulé et un faux Horizon, donc le paiement est **vraiment signé et soumis**. Toute erreur JavaScript fait échouer le test.
- **24 règles produit écrites et testées** (R1–R24 dans `docs/PRODUCT.md`).
- **Architecture propre** : les règles métier vivent à un seul endroit ; seul le module `payments` touche à la blockchain ; une tâche ne peut passer « Paid » que par une seule fonction.
- **Responsive de 320 px à grand écran**, barre d'onglets mobile, pas de scroll horizontal, cibles tactiles 44 px.
- **Rien ne charge depuis un CDN** (tout est auto-hébergé) : la démo marche même avec un réseau capricieux.
- **Configurable sans toucher au code** : réseau, asset de paiement, clé Trustless Work, mode de paiement → tout passe par `.env`. Passer en mainnet = changer la config.
- Stack : Python 3.13, Django 5.2 (pages rendues côté serveur), JavaScript vanilla, `@stellar/stellar-sdk`, Freighter API, Tailwind compilé.

---

## 8. Ce qui est on-chain vs off-chain (honnêteté = crédibilité devant le jury)

- **On-chain** : l'escrow Soroban de chaque tâche (déploiement, financement, livraison avec le lien en preuve, approbation, libération) et les paiements USDC.
- **Off-chain (base de données)** : projets, tâches, candidatures, scores, notes, choix de l'entreprise.
- **Connexion** : vérifiée côté serveur à partir d'une signature Freighter.
- **Testnet uniquement** pendant le hackathon (pour ne pas manipuler de vrais fonds). Le faucet de test donne 10 USDC par jour → les prix de la démo sont petits (3 / 5 / 2 USDC).

---

## 9. Personas (pour raconter l'histoire)

- **Claire**, dirige **Studio Nova** (12 personnes). Livre 2–3 petits projets web par an, ne peut pas tout staffer. Sait ce que vaut chaque tâche, veut fixer le prix elle-même et ne payer que le travail livré.
- **Yanis**, freelance Django/UI, 3 ans d'expérience. A attendu 60 jours un virement, et une fois n'a jamais été payé. Veut une preuve que l'argent existe **avant** de commencer.
- **Nora**, freelance Stellar/JS. Très compétente, aucun historique avec Studio Nova. Veut une chance équitable.

---

## 10. Scénario de la démo (ce qu'on voit à l'écran)

1. Claire crée le projet **« Booking platform for a yoga studio »** avec 3 tâches : **T1 « Landing page » 3 USDC** (`django, ui`), T2 « Freighter integration » 5 USDC (`stellar, js`), T3 « Dashboard » 2 USDC (`django, charts`).
2. Yanis postule à T1 avec `django, ui`, Nora avec `django`. La page de Claire se met à jour en direct : **Yanis 20.0 « Recommended »**, Nora 10.0.
3. Claire clique **« Choose »** sur Yanis. T1 passe « Taken », Nora « Not selected ».
4. **« Fund the project »** → 2 signatures (« Create the escrow », « Lock the funds »). 3 USDC quittent le wallet de Claire vers le contrat. On montre le contrat sur stellar.expert.
5. Yanis colle son lien de PR → **« Declare the delivery »** → 1 signature.
6. Claire : **« Validate + rate »**, 5 étoiles, « Validate and release 3.00 USDC » → 2 signatures (approve, release).
7. **Le solde USDC de Yanis monte en direct** dans le panneau. stellar.expert montre la libération.
8. Tâche T2 : Yanis et Nora postulent → **Yanis 90.0 « Validated » + « Recommended »**, Nora 20.0.

Signatures : entreprise 4 (en 2 clics, car l'app enchaîne), freelance 1. En mode direct : entreprise 1, freelance 0.

---

## 11. Script vidéo de référence (2:45, voix off FR, à adapter)

- **0:00 — Le problème** : « Les freelances sont payés en retard, parfois jamais. Les petites entreprises qui répartissent un projet entre plusieurs freelances jonglent avec les devis, les factures et la confiance. Entre les deux, les grandes plateformes prennent 10 à 20 % et gardent l'argent. TaskVault règle les deux côtés. »
- **0:25 — Projet, tâches, candidats** : « Je suis Claire, je dirige Studio Nova. Je connecte mon wallet Freighter et je signe : pas de compte, pas de mot de passe. Je découpe mon projet en trois tâches à prix fixe. Yanis et Nora postulent : un message et leurs compétences. Personne ne négocie, le prix c'est moi qui le fixe. TaskVault les classe avec un score simple et explicable, Yanis est « Recommended ». Je le choisis. »
- **1:10 — Financement** : « Fund the project. Deux signatures : Trustless Work déploie un escrow pour cette tâche sur Stellar, avec Yanis comme bénéficiaire, et mes 3 USDC y entrent. Ils ne sont pas encore chez Yanis, et plus chez nous. Voici le contrat, public, sur stellar.expert. Yanis sait que l'argent existe avant d'écrire une ligne de code. »
- **1:45 — Livraison, note, paiement** : « Yanis livre : il colle son lien et signe ; le lien est enregistré on-chain comme preuve. Je vérifie, cinq étoiles, je signe deux fois : approuver, libérer. Regardez son solde : il vient de monter, en cinq secondes. Pas de virement, pas de trente jours. »
- **2:15 — L'effet boule de neige** : « Tâche suivante. Nora colle mieux aux compétences, mais Yanis a déjà bien livré pour moi : il est « Validated » et en tête, 90 contre 20. L'entreprise décide toujours, mais la confiance se gagne tâche par tâche. »
- **2:35 — Pourquoi Stellar** : « Parce que les dollars numériques, l'USDC, se règlent en cinq secondes pour une fraction de centime. Parce que le contrat qui garde l'argent tourne sur Soroban, sans banque au milieu. Et parce que le wallet, Freighter, est à la fois l'identité et la signature. Trois briques, un seul flux. TaskVault : prix fixes, confiance méritée, paiement garanti. »

⚠️ Si la démo tourne en **mode direct** : ne jamais dire « escrow » ni « contrat ». Dire « ici le paiement va de wallet à wallet, c'est notre mode de secours ».

---

## 12. Questions probables du jury (réponses courtes)

1. **Pourquoi des prix fixes ?** Parce que la course au moins cher produit du travail bâclé. L'entreprise sait ce que vaut une tâche ; les freelances se battent sur la compétence et l'historique.
2. **Le score n'est-il pas injuste pour les nouveaux ?** Un nouveau peut avoir 20 points via ses compétences, l'entreprise peut choisir n'importe qui, et une seule livraison payée notée ≥ 3 suffit pour devenir « Validated ».
3. **Et si le freelance ne livre jamais ?** L'argent reste dans l'escrow, il ne bouge qu'après approbation + libération par l'entreprise. Trustless Work a un rôle d'arbitre de litige (déjà configuré sur le wallet de la plateforme) ; les écrans de litige ne sont pas encore construits.
4. **Pourquoi un escrow par tâche ?** Voir §4 : le bénéficiaire est fixé au déploiement et chaque freelance signe sa propre livraison.
5. **Pourquoi 4 signatures côté entreprise ?** Chaque mouvement d'argent est signé par la personne concernée ; TaskVault ne détient aucune clé. L'app les enchaîne : ça fait 2 clics.
6. **Pourquoi pas le mainnet ?** Pour ne pas manipuler de vrais fonds pendant un hackathon. Le code est le même, seule la config change.
7. **Combien coûte une transaction ?** ~0,00001 XLM pour un paiement classique ; les appels Soroban ajoutent des frais de ressources, toujours une fraction de centime. Pas encore de modèle économique codé ; hypothèse : 2–3 % de frais, loin des 10–20 % habituels.
8. **Qu'est-ce qui est vraiment on-chain ?** Voir §8.
9. **Pourquoi Django et pas React ?** Rendu serveur = moins de pièces mobiles, plus rapide à construire, plus robuste en démo. La partie Stellar tourne dans le navigateur avec le SDK officiel et Freighter, là où la signature doit se faire.

---

## 13. Prochaines étapes (slide « Next »)

- **Litiges** via le rôle d'arbitre de Trustless Work (déjà branché sur le wallet plateforme).
- **Réputation portable** (notes et tâches payées) au-delà d'une seule entreprise.
- **Retrait en euros** via un anchor Stellar (SEP-24).
- Finir sur le pitch en une phrase, pas sur la roadmap.

---

## 14. Captures d'écran disponibles (`docs/screenshots/`)

À joindre au deck (générées automatiquement par le test e2e, en mode direct) :
- `01-landing.png` : page d'accueil (cube 3D animé)
- `03-projet-entreprise.png` : page projet (tâches, statuts, candidats, panneau de financement)
- `04-tache-candidats.png` : candidats classés, « Recommended », bouton « Choose »
- `05-tache-livree-freelance.png` : vue du freelance après la livraison
- `06-valider-noter.png` : formulaire de note 5 étoiles
- `07-tableau-kanban.png` : kanban du freelance
- `08-tache-valide-recommande.png` : **A 90.0 « Validated » + « Recommended » vs B 20.0** (la plus parlante)
- `10-tableau-de-bord.png` : tableau de bord (à faire, KPIs, activité)
- `11-profil.png` : profil public d'un wallet
- `14-paiement-tache.png` : « Task paid », hashs liés à stellar.expert, solde du freelance
- `15-financement-projet.png` : financement du projet
- Mobile : `mobile-landing.png`, `mobile-kanban.png`, `mobile-tache-candidats.png`, `mobile-tableau-de-bord.png`

---

## 15. Infos pratiques

- **Nom** : TaskVault (anciennement Lowbid, une enchère inversée, remplacée par le tableau de tâches).
- **Hackathon** : Hack Meridian (Stellar), track **Composed** (Freighter + USDC + Trustless Work).
- **Réseau** : Stellar testnet, USDC de test Circle.
- **Liens à compléter** : vidéo de démo, deck, adresses testnet + contrat escrow de T1 sur stellar.expert (tableau vide dans le README, à remplir après la répétition).
