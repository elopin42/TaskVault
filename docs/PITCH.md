# Lowbid 📉 — Pitch

## A. Script vidéo (2 min 30 à 3 min)

**0:00 — Le problème** *(face caméra ou slide 1)*
« Quand on est freelance, on se fait payer en retard. Parfois jamais. Et quand on est une petite entreprise, on paie souvent trop cher, parce qu'on n'a qu'un seul devis sous les yeux. Au milieu, les plateformes prennent 10 à 20 % et gardent l'argent des semaines. Lowbid règle les deux problèmes à la fois. »

**0:30 — Démo : poster, 3 enchères, gagnant** *(écran)*
« Je suis Claire, je gère une PME. Je connecte mon wallet Freighter : pas de compte, pas de mot de passe. Je poste mon besoin : une landing page, budget maximum 500 dollars, 10 jours maximum, compétences Django, Stellar et UI. Les enchères ferment dans deux heures, ici on a accéléré.
Trois freelances arrivent. Le premier propose 450 dollars en 8 jours. Le deuxième descend à 420. Le troisième essaie 430 : refusé, il faut faire moins que la dernière offre. Il repasse à 400.
Le timer s'arrête. Lowbid note chaque offre sur le prix, le délai et les compétences, et met un badge "Recommandé". Mais c'est moi qui décide. Je peux bouger ces curseurs si le prix compte plus pour moi. Je choisis. »

**1:30 — Escrow créé** *(écran, puis onglet stellar.expert)*
« Je clique sur "Payer" et je signe dans Freighter. L'argent ne part pas chez le freelance, et il ne reste pas chez nous non plus : il est bloqué dans un contrat sur Stellar, grâce à Trustless Work. Voilà la transaction, publique, sur stellar.expert. Le freelance sait que l'argent existe avant de commencer à travailler. »

**2:00 — Release, le solde monte** *(écran, wallet du freelance)*
« Le freelance livre. Je vérifie, je valide. Le contrat libère les USDC. Regardez son solde : il vient de monter, en cinq secondes. Pas de virement, pas d'attente de trente jours. »

**2:30 — Pourquoi Stellar** *(slide 4)*
« Pourquoi Stellar ? Parce que le dollar numérique, l'USDC, y circule en cinq secondes pour une fraction de centime. Parce que le contrat qui garde l'argent tourne sur Soroban, sans banque au milieu. Et parce que le wallet, Freighter, sert à la fois d'identité et de signature. Trois briques, un seul parcours. Lowbid : les freelances se battent sur le prix, et ils sont sûrs d'être payés. »

*(Environ 330 mots, soit 2 min 30 à débit normal. Lire à voix haute une fois chronométré avant d'enregistrer.)*

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
- Détail du besoin : timer, 3 enchères, badge « Recommandé », curseurs.
- Panneau paiement : escrow créé + lien stellar.expert.
- Wallet du freelance avant / après la libération.
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
Non, parce que le prix ne pèse que 40 % du score : le délai et les compétences comptent pour 60 %. Et surtout, le client choisit librement. Le badge « Recommandé » est une aide, il peut retenir une offre plus chère.

**2. Et si le freelance ne livre pas ?**
Les fonds restent dans l'escrow : ils ne partent chez le freelance qu'après validation du client. Pour les désaccords, Trustless Work prévoit un rôle d'arbitre (dispute resolver) ; on ne l'a pas branché pendant le hackathon, c'est la prochaine étape.

**3. Pourquoi pas le mainnet ?**
Pour ne pas manipuler de vrais fonds pendant un hackathon. Le code est le même : on change le réseau, l'émetteur USDC et l'URL de Trustless Work.

**4. Combien coûte une transaction ?**
Environ 0,00001 XLM de frais réseau par opération, soit une fraction de centime. Lowbid ne prend pas de commission aujourd'hui ; un modèle viable serait 2 à 3 %, bien en dessous des 10 à 20 % des plateformes.

**5. Comment empêcher les fausses offres très basses ?**
Chaque offre est signée par un wallet : pas d'offre anonyme. Un freelance n'a qu'une offre active par besoin, et le client n'est pas obligé de retenir la moins chère. Gagner sans livrer ne rapporte rien, l'argent reste bloqué. La réputation (Stellar Passport) et un petit dépôt de garantie sont les prochaines protections.

**6. Pourquoi Django et pas React ?**
Rendu côté serveur, moins de pièces, plus rapide à construire en un week-end et plus robuste en démo. La partie Stellar tourne dans le navigateur avec le SDK officiel et Freighter : c'est là que la signature doit se faire, et un framework n'y change rien.

**7. Qu'est-ce qui est on-chain, honnêtement ?**
On-chain : l'escrow Soroban (création, dépôt des USDC, libération) et les paiements USDC. Off-chain, dans SQLite : les besoins, les enchères, le score et le choix du client. La connexion est vérifiée par signature Freighter côté serveur. Mettre les enchères dans un contrat Soroban fait partie de la suite.

**8. Et après le hackathon ?**
Réputation, litiges, sortie en euros via un anchor, enchères cachées, puis enchères on-chain. On veut d'abord tester avec une dizaine de PME et de freelances réels sur testnet.

## D. Checklist jour de démo

- [ ] **3 alarmes** : la veille au soir (charger les appareils), 2 h avant (répétition complète), 30 min avant (vérification finale).
- [ ] **Comptes alimentés** : client, freelance 1, freelance 2 ont des XLM (Friendbot) et le client a assez d'USDC testnet pour au moins 3 paiements.
- [ ] **Trustlines USDC** créées sur les 3 comptes (sinon le freelance ne peut pas recevoir).
- [ ] **Profil navigateur dédié** avec Freighter réglé sur **TESTNET**, les 3 comptes importés, rien d'autre d'installé.
- [ ] **Onglets ouverts à l'avance** : Lowbid (vue client), Lowbid (vue freelance), stellar.expert sur le compte du freelance, le deck.
- [ ] **Besoin de secours** déjà en état `closed` avec 3 offres, au cas où le timer en direct prend trop de temps.
- [ ] **Plan B testé** : le paiement direct USDC fonctionne si Trustless Work ne répond pas.
- [ ] **Vidéo de secours** en local (pas en streaming) si le wifi tombe, et partage de connexion du téléphone prêt.
- [ ] Zoom du navigateur à 125 %, notifications coupées, écran de veille désactivé.
