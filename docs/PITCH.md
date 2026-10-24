# Lowbid 📉 — Pitch

> Aligné sur l'UI réelle (libellés copiés des templates). Le pas-à-pas des clics est dans [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) §3.
> Montants **testnet, ≤ 10 USDC** (le faucet Circle donne 10 USDC / 24 h) : budget **10**, Yanis **9**, Nora **9,20 refusé → 7,50**, paiement **9 USDC**.

## A. Script vidéo (2 min 30 à 3 min)

**0:00 — Le problème** *(face caméra ou slide 1)*
« Quand on est freelance, on se fait payer en retard. Parfois jamais. Et quand on est une petite entreprise, on paie souvent trop cher, parce qu'on n'a qu'un seul devis sous les yeux. Au milieu, les plateformes prennent 10 à 20 % et gardent l'argent des semaines. Lowbid règle les deux problèmes à la fois. »

**0:30 — Démo : poster, enchères, choix** *(écran)*
« Je suis Claire, je gère une PME. Je clique sur "Connecter mon wallet Freighter" et je signe : pas de compte, pas de mot de passe. Je poste mon besoin : une landing page, budget maximum 10 dollars — on est sur testnet —, 10 jours maximum, compétences django, stellar et ui. Les enchères ferment dans deux heures ; pour la démo, je clôturerai à la main.
Yanis propose 9 dollars en 5 jours. Nora tente 9,20 : refusé, il faut passer sous la meilleure offre. Elle descend à 7,50, en 9 jours.
Je clôture. Lowbid note chaque offre sur le prix, le délai et les compétences : Yanis reçoit le badge "Recommandé". Si le prix compte plus pour moi, je pousse ce curseur : c'est Nora qui passe devant. Mais c'est moi qui décide. Je choisis Yanis : plus rapide, toutes les compétences. »

**1:30 — Escrow créé** *(écran, puis onglet stellar.expert)*
« Je clique sur "Créer l'escrow" et je signe dans Freighter : Trustless Work déploie un contrat sur Stellar. Puis "Bloquer les fonds" : mes 9 USDC partent dans le contrat. Ils ne vont pas chez le freelance, et ils ne restent pas chez nous non plus. Voilà le contrat, public, sur stellar.expert. Yanis sait que l'argent existe avant de commencer à travailler. »

**2:00 — Release, le solde monte** *(écran : panneau paiement, ligne « Solde USDC du freelance »)*
« Yanis livre : il déclare la livraison et signe de son côté. Je vérifie, je clique "Valider la livraison", puis "Libérer les fonds". Regardez son solde : il vient de monter, en cinq secondes. Pas de virement, pas trente jours d'attente. »

> **Variante paiement direct** (si `LOWBID_PAYMENT_MODE=direct`, voir runbook §1.10 / §4.2) — remplace 1:30 et 2:00 :
> **1:30** « Ici, le paiement part de wallet à wallet, sans escrow : c'est notre mode de secours. Yanis déclare sa livraison. »
> **2:00** « Je vérifie, je clique "Valider et payer", je signe une seule fois dans Freighter. Regardez son solde : il vient de monter, en cinq secondes. Voilà la transaction sur stellar.expert. Pas de virement, pas trente jours d'attente. »
> Ne jamais dire « escrow » ni « contrat » dans cette variante.

**2:30 — Pourquoi Stellar** *(slide 4)*
« Pourquoi Stellar ? Parce que le dollar numérique, l'USDC, y circule en cinq secondes pour une fraction de centime. Parce que le contrat qui garde l'argent tourne sur Soroban, sans banque au milieu. Et parce que le wallet, Freighter, sert à la fois d'identité et de signature. Trois briques, un seul parcours. Lowbid : les freelances se battent sur le prix, et ils sont sûrs d'être payés. »

*(Environ 300 mots parlés, soit 2 min 30 à débit normal, attentes comprises. Lire à voix haute une fois chronométré avant d'enregistrer. Couper au montage les attentes de popup Freighter.)*

## B. Deck en 5 slides

**Slide 1 — Problème**
- Freelances payés en retard, voire jamais.
- Clients qui paient trop cher : un seul devis, aucune comparaison.
- Plateformes : 10 à 20 % de commission, fonds bloqués des semaines.
- Personne n'a confiance, donc tout le monde paie un intermédiaire.
- *Note orateur : un chiffre, une phrase par problème, pas plus de 30 secondes.*

**Slide 2 — Solution**
- Le client poste un besoin avec un budget et un délai maximum.
- Les freelances enchérissent à la baisse, chaque offre doit battre la précédente.
- Un score prix + délai + compétences recommande, le client choisit.
- Paiement en USDC bloqué dans un escrow, libéré à la validation.
- *Note orateur : insister sur « le client choisit » avant qu'un juré parle de course au moins-disant.*

**Slide 3 — Démo (captures)**
- Formulaire « Poster un besoin ».
- Détail du besoin : timer, offres, refus d'une offre trop haute, badge « Recommandé », curseurs.
- Panneau « Paiement en escrow » : étapes + lien stellar.expert du contrat.
- « Solde USDC du freelance » avant / après la libération.
- Captures à prendre dans `docs/screenshots/` (noms à vérifier avec ce que l'agent QA a déposé) :
  - `01-landing.png` — landing, bouton « Connecter mon wallet Freighter »
  - `02-poster-un-besoin.png` — formulaire rempli (10 USDC, 10 jours, django / stellar / ui)
  - `03-encheres-ouvertes.png` — besoin ouvert, compte à rebours, offres en direct
  - `04-offre-refusee.png` — « Doit être strictement inférieur à 9.00 USDC. »
  - `05-classement-recommande.png` — besoin clôturé, curseurs « Vos priorités », badge « Recommandé »
  - `06-escrow-fonds-bloques.png` — panneau « Paiement en escrow », étape « Fonds bloqués »
  - `07-fonds-liberes.png` — « Fonds libérés vers le freelance. Merci ! » + solde du freelance
  - `08-stellar-expert.png` — page stellar.expert du contrat ou de la libération
  - `09-mobile.png` — détail d'un besoin sur téléphone (optionnel)
- *Note orateur : les captures servent de filet si la démo live ne passe pas.*

**Slide 4 — Stack Stellar (schéma)**
- Freighter : connexion par message signé, signature de chaque paiement.
- USDC sur Stellar testnet : ~5 s, frais ≈ 0,00001 XLM.
- Trustless Work : escrow Soroban créé et libéré via son API, appelée par Django.
- Django + JS vanilla + `@stellar/stellar-sdk` ; Plan B : paiement USDC direct.
- *Note orateur : montrer le schéma Client / Lowbid / Stellar du README et dire « track Composed ».*

**Slide 5 — Suite**
- Réputation via Stellar Passport, litiges via le rôle dispute resolver de Trustless Work.
- Sortie en euros via un anchor (SEP-24).
- Enchères cachées (commit-reveal), puis enchères stockées dans un contrat Soroban.
- Explication IA de la recommandation : deux phrases « pourquoi cette personne ».
- *Note orateur : finir sur la phrase de pitch, pas sur la roadmap.*

## C. Questions des jurés

**1. Une enchère inversée, ça ne pousse pas les prix vers le bas jusqu'au travail bâclé ?**
Non, parce que le prix ne pèse que 40 % du score : le délai et les compétences comptent pour 60 %. Et surtout, le client choisit librement. Le badge « Recommandé » est une aide, il peut retenir une offre plus chère — c'est exactement ce qu'on fait dans la démo.

**2. Et si le freelance ne livre pas ?**
Les fonds restent dans l'escrow : ils ne partent chez le freelance qu'après validation du client. Pour les désaccords, Trustless Work prévoit un rôle d'arbitre (dispute resolver) ; le contrat est déjà créé avec l'adresse de la plateforme dans ce rôle, mais on n'a pas branché le flux de litige pendant le hackathon.

**3. Pourquoi pas le mainnet ?**
Pour ne pas manipuler de vrais fonds pendant un hackathon. Le code est le même : on change le réseau, l'émetteur USDC et l'URL de Trustless Work. C'est aussi pour ça que la démo joue avec 10 USDC : c'est ce que donne le faucet de test.

**4. Combien coûte une transaction ?**
Environ 0,00001 XLM de frais réseau par opération, soit une fraction de centime. Le contrat prévoit une commission plateforme (`platformFee`) ; en démo elle est réglée au minimum. Un modèle viable serait 2 à 3 %, bien en dessous des 10 à 20 % des plateformes.

**5. Comment empêcher les fausses offres très basses ?**
Chaque offre est liée à un wallet connecté par signature : pas d'offre anonyme. Un freelance n'a qu'une offre active par besoin, et le client n'est pas obligé de retenir la moins chère. Gagner sans livrer ne rapporte rien, l'argent reste bloqué. La réputation (Stellar Passport) et un petit dépôt de garantie sont les prochaines protections.

**6. Pourquoi Django et pas React ?**
Rendu côté serveur, moins de pièces, plus rapide à construire en un week-end et plus robuste en démo. La partie Stellar tourne dans le navigateur avec le SDK officiel et Freighter : c'est là que la signature doit se faire, et un framework n'y change rien.

**7. Qu'est-ce qui est on-chain, honnêtement ?**
On-chain : l'escrow Soroban (création, dépôt des USDC, livraison, validation, libération) et les paiements USDC. Off-chain, dans SQLite : les besoins, les enchères, le score et le choix du client. La connexion est vérifiée par signature Freighter côté serveur. Mettre les enchères dans un contrat Soroban fait partie de la suite.

**8. Et après le hackathon ?**
Réputation, litiges, sortie en euros via un anchor, enchères cachées, puis enchères on-chain. On veut d'abord tester avec une dizaine de PME et de freelances réels sur testnet.

**9. Qu'est-ce qui a vraiment tourné en live, et qu'est-ce qui est construit d'après la doc ?**
Ce que vous voyez dans la vidéo a tourné sur le testnet Stellar, avec de vrais USDC de test : chaque lien stellar.expert du README le prouve. Le README coche uniquement les étapes qui ont marché à l'enregistrement. L'intégration Trustless Work a été écrite pendant le build d'après le code source de leur SDK et leur référence d'API, sans accès réseau ; on l'a validée la veille par un test de bout en bout sur testnet. Un point reste à confirmer côté vendeur : l'unité exacte de la commission plateforme, d'où la valeur minimale. *(Si la vidéo est en mode direct : « l'escrow est codé et testé hors ligne, mais en live on a utilisé notre mode de secours, le paiement direct ; le README le dit ».)*

**10. Pourquoi le client signe quatre fois ?**
Parce que chaque mouvement d'argent ou changement d'état du contrat est signé par la personne concernée, dans son propre wallet : créer le contrat, y déposer les USDC, valider la livraison, libérer les fonds. Le freelance signe sa déclaration de livraison. Lowbid ne détient aucune clé privée : Trustless Work prépare des transactions non signées, Freighter les signe, et personne d'autre ne peut déplacer les fonds. C'est le prix d'un paiement sans intermédiaire de confiance. En production, on enchaînera deux signatures sur un seul clic (créer + bloquer, valider + libérer), sans jamais garder de clé côté serveur.

## D. Checklist jour de démo

> Version détaillée et cochable : [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).

- [ ] **3 alarmes** : la veille au soir (charger les appareils), 2 h avant (répétition complète), 30 min avant (vérification finale). Puis **10:30** (soumission) et **11:00** (deadline).
- [ ] **Comptes alimentés** : client, freelance 1, freelance 2 (+ plateforme) ont des XLM (Friendbot) ; le client a **≥ 10 USDC** testnet (faucet sur les 4 comptes, regroupé sur le client).
- [ ] **Montants ≤ 10 USDC** partout : budget 10, offres 9 → 9,20 refusé → 7,50.
- [ ] **Trustlines USDC** créées sur les 4 comptes (sinon le freelance ne peut pas recevoir).
- [ ] **3 profils Chrome** (Client, Freelance 1, Freelance 2), Freighter réglé sur **TESTNET** dans chacun, rien d'autre d'installé.
- [ ] **Onglets ouverts à l'avance** : deck + landing Lowbid (client, déconnecté), `/besoins/` (Yanis et Nora, connectés), stellar.expert sur le compte de Yanis.
- [ ] **Besoin de secours** déjà en état « attribué » (Yanis choisi à 9 USDC, escrow pas encore créé).
- [ ] **Plan B testé** : `LOWBID_PAYMENT_MODE=direct` + redémarrage (≈ 10 s) → bouton « Valider et payer ».
- [ ] **Vidéo de secours** en local (la répétition de la veille), et partage de connexion du téléphone prêt.
- [ ] Zoom du navigateur à **110 %**, thème sombre, barre de favoris masquée, notifications coupées, écran de veille désactivé.
