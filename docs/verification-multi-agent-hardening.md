<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc. -->
# Bilan de reprise multi-agents — 9 novembre 2026

Les correctifs du tableau SYFOS ont été adaptés au moteur autonome de flightboard. Les huit défauts de l'audit ont
été traités, puis une relecture indépendante a conduit à renforcer les historiques incomplets, les identités de
sessions et les compteurs en conflit. La branche de travail est `codex/multi-agent-hardening`, sur la base
`6b8544b1b35baee973e253152691e83520c9e576`.

## Résultat fonctionnel

Le suivi Git et les registres ne dépendent plus d'un propriétaire nommé Claude. Codex, Claude et d'autres agents
peuvent contribuer au même tableau. Les noms d'agent sont des identifiants simples ; les rôles `owner` et `reviewer`
restent protégés. La capacité commune utilise `agent_sessions_per_week`, avec compatibilité de l'ancienne clé
`claude_sessions_per_week` et refus des valeurs contradictoires.

Les worktrees externes de Codex sont lus seulement après autorisation de leur dossier parent par
`--worktrees-root DIR`, répétable. Les dispositions parent/arbre et parent/groupe/projet sont prises en charge,
y compris quand le dépôt et les worktrees sont sur des disques différents. L'arbre doit être enregistré dans ce
dépôt et son marqueur `.git` doit correspondre réciproquement au dossier administratif. Les chemins UNC, lecteurs
réseau Windows, liens et jonctions sont refusés. Aucun autre projet n'est recherché automatiquement.

Le skill partagé contient une commande portable et des instructions d'installation facultative pour Codex. Le
plugin Claude est conservé. Aucune installation n'a été exécutée dans la configuration personnelle.

## Reprise des protections Claude

La source consultée est le lot SYF-139 encore non commité, sur la base SYFOS `568916b`. Cette reprise adapte les
protections aux formats de registre et au remote configurables de flightboard ; elle ne copie pas les dépendances
internes de SYFOS. Les annonces historiques de 723 tests ne servent pas de preuve pour ce dépôt.

- Ouvertures Windows qui refusent une rupture d'oplock au lieu d'attendre ; essais avec deux oplocks exclusifs réels.
- Processus Git et flux bornés, y compris lorsqu'un descendant conserve les pipes ; budget commun de lecture.
- Contrôle des références symboliques, des noms ambigus sous Windows et des dossiers de références privés.
- Contrôle réciproque des worktrees, refus des doublons et limites explicites sur les enregistrements et les parcours.
- Rétention des sessions contenant un stash, un commit détaché délaissé ou des preuves illisibles.
- Blocage des copies de branches distantes quand un worktree local associé détient encore du travail.
- Vérification de l'ascendance des entrées du reflog de main ; baseline locale conservée si le remote est en avance.
- Vérification du registre par ses octets, même quand taille et dates ont été restaurées ; les modifications détectées
  dans le registre empêchent de présenter la session comme entièrement commitée.

## Les huit défauts de l'audit

| Défaut | Comportement corrigé | Régression principale |
| --- | --- | --- |
| 200 candidats ignorés masquent du travail | Dépassement rendu inconnu ; aucun verdict prêt/terminé | `test_ported_safety.py` |
| Conflit après 2 000 modifications | Conflit conservé dans la lecture du statut | `test_ported_safety.py` |
| Quatrième tâche oubliée | Toutes les tâches reconnues participent aux décisions | `test_ported_sessions.py` |
| 31e dépendance oubliée | Liste complète utilisée pour autoriser un démarrage | `test_audit_logic.py` |
| Collision limitée au titre/jalon | Comparaison des métadonnées complètes avant limites d'affichage | `test_audit_logic.py` |
| Fiche ouverte périmée | Rafraîchissement automatique ; indisponibilité explicitement affichée | `test_live_page.py` et navigateur |
| Voyant vert après erreur | État d'erreur annoncé ; anciens verdicts retirés ; reprise automatique | `test_live_page.py` et navigateur |
| Mouvement annulé encore compté | Sources annulées exclues du journal appliqué et des compteurs | `test_audit_logic.py` |

Les protections supplémentaires de la relecture couvrent aussi les identifiants de session stables lorsque deux
worktrees Codex ont le même nom, les nouvelles tâches en conflit, les historiques de commits incomplets et les
journaux HEAD malformés ou tronqués. Une tâche nouvelle en conflit ne présente plus un statut arbitraire dans sa fiche.

## Vérifications

| Vérification finale | Résultat |
| --- | --- |
| Windows, Python 3.14.0, Git 2.51.2 | 382 tests, aucun échec, 2 ignorés ; 293,214 s |
| WSL Ubuntu, Python 3.12.3, Git 2.43.0 | 382 tests, aucun échec, 16 ignorés ; 63,157 s |
| Régressions JavaScript | Sept groupes de vérifications exécutant le code du template |
| Serveur HTTP réel | 17 contrôles réussis, IPv4/IPv6, origines, méthodes et chemins |
| Plugin et marketplace | Deux validations strictes avec Claude Code 2.1.311 réussies |
| Résumé français et snapshot | Codes de sortie 0 sur le dépôt réel |
| CLI avec la racine Codex locale | Résumé réussi ; aucun worktree d'un autre dépôt lu |
| Dépôt synthétique sur deux disques | Dépôt et worktree externe lus ; branche Codex et branche Claude présentes ; tâche Kimi proposée |
| Navigateur | Fiche actualisée, erreur globale, perte de connexion, anciens verdicts retirés et récupération vérifiés |

Les cas WSL ignorés dépendent de Windows, de Git plus récent ou du runtime Node facultatif. Les scénarios propres
aux oplocks Windows et les vérifications JavaScript ont été exécutés sur Windows. Le validateur de plugin signale
uniquement l'icône absente, sans échec de validation.

La suite compte 69 tests supplémentaires par rapport aux 313 tests du dépôt initial. Les cinq vérifications
d'hygiène ont également été rejouées après rédaction du bilan ; elles passent. `git diff --check` ne signale aucune
erreur. Les serveurs et dépôts synthétiques du scénario navigateur ont été arrêtés et nettoyés après vérification.

## Utilisation

Depuis la racine du dépôt observé, remplacer les paramètres entre chevrons par les chemins choisis :

```text
python -I -B <skill-directory>/scripts/flightboard.py --lang fr --worktrees-root <codex-worktrees-directory>
```

Avec un dossier de worktrees à l'intérieur du dépôt, utiliser `--worktrees .agents/worktrees`. Les paramètres
externes ne sont pas lus dans le registre du projet ; ils restent une décision explicite de lancement.

## Limites

Le tableau observe les traces Git et les registres, pas les conversations ni les états internes des fournisseurs.
Les essais emploient des dépôts et branches synthétiques représentant plusieurs agents ; ils ne constituent pas un
test d'inférence Qwen, MiMo, MiniMax ou Kimi, ni une installation réelle du plugin dans une session Claude.

Les historiques d'attribution sont bornés à 1 000 commits et 4 000 caractères par sujet, avec huit commits affichés.
Une lecture coupée ou manquante rend les verdicts impossibles plutôt que d'affirmer que le travail est fini. Les
journaux HEAD et stash dépassant 1 000 entrées ou 2 Mo sont également inconnus. Un commit déjà absent des reflogs
conservés ne peut pas être retrouvé par ce mécanisme.

Les limites de sécurité détaillées dans [SECURITY.md](../SECURITY.md), notamment les courses de fichiers et les
pièges fins possibles dans un dossier `.git` modifiable, restent applicables. macOS et la CI distante ne sont pas
qualifiés par cette exécution. Aucun changement de configuration personnelle ni publication n'a été effectué.
