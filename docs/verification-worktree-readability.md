<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Lecture des worktrees SLAPY et Express — 9 novembre 2026

Les 15 refus de lecture SLAPY et le refus Express ont été résolus dans les deux installations locales de
Flightboard, sur la base `e369b8e`. Aucun fichier de configuration Git des projets observés n'a été modifié.

## Causes et corrections

| Cause observée | SLAPY | Express | Correction |
| :- | -: | -: | :- |
| Worktrees enregistrés hors des racines autorisées | 7 | 0 | Ajouter leurs deux racines locales aux paramètres de lancement, après contrôle des dossiers et marqueurs réciproques |
| Métadonnée Codex refusée dans `config.worktree` | 8 | 1 | Accepter exactement `codex.localenvironmentconfigpath = __none__` après parsing par Git |

Les neuf dossiers administratifs sont normaux : fichiers ordinaires, `commondir` exact `../..`, absence de liens ou
de points de réanalyse et marqueurs `.git` réciproques. La sentinelle Codex est une métadonnée ; Flightboard n'ouvre
pas sa valeur. Les autres valeurs, clés inconnues, includes et réglages de hooks restent refusés.

Les sept worktrees externes existent et passent les mêmes contrôles. Les deux nouvelles racines ne déclenchent
aucun parcours des autres projets : la découverte part des seuls admins enregistrés dans SLAPY.

Une lecture complète des 43 sessions SLAPY a aussi révélé que le budget initial de 12 secondes pouvait être dépassé.
L'option `--read-seconds N` conserve 12 secondes par défaut et accepte 12 à 120. SLAPY utilise 30 secondes ; Express
conserve 12. Chaque commande Git garde son plafond de 8 secondes. Le navigateur attend le budget configuré plus
8 secondes, y compris après une réponse d'erreur, avant d'interrompre une requête.

## Vérifications

- Les régressions Codex et budget ont échoué sur le code antérieur, puis réussi après correction. Elles vérifient
  aussi les configurations dangereuses, leur remplacement puis leur restauration sur le même collecteur.
- Suite complète Windows, Python 3.14 : **394 cas, 392 réussis, 2 ignorés**, en 330,693 secondes.
- Suite complète WSL Ubuntu, Python 3.12 : **394 cas, 378 réussis, 16 ignorés**, en 66,793 secondes.
- Le test de la page exécute **9 vérifications JavaScript**, dont le délai adapté et la récupération après erreur.
- Les suites affichent un `ResourceWarning` non bloquant concernant un sous-processus de test. Cet avertissement
  était déjà présent dans les journaux Windows et WSL de la qualification précédente ; aucun échec de test n'est
  observé ici, et les processus nommés par les avertissements ne tournent plus au contrôle final.
- Les 25 fichiers de chaque installation locale, Codex et Claude, correspondent à la source par SHA-256.
- Un collecteur SLAPY neuf depuis le plugin installé lit les 43 sessions en **20,896 secondes**, sans worktree non
  lu, pendant l'exécution des tests. Le budget de 30 secondes est donc utile au chargement initial.
- Les pages et `/state.json` des deux serveurs répondent en HTTP 200. Après rechargement dans le navigateur, les
  deux pages exécutent le script corrigé et restent « En direct ». Une nouvelle observation 108 secondes plus tard
  confirme le rafraîchissement et l'absence de lecture partielle.
- Les 43 empreintes des fichiers Git contrôlés avant et après sont identiques.

| Tableau local | Sessions affichées | Worktrees non lus | Budget de lecture |
| :- | -: | -: | -: |
| SLAPY, port 8791 | 43 | **0** | 30 s |
| SLAPY Express, port 8792 | 15 | **0** | 12 s |

SLAPY reste lancé avec `--max-branches 0` : les branches sans worktree sont exclues. Les avertissements de stash
restent des informations Git distinctes des refus de lecture ; ils n'ont pas été supprimés ou contournés. Les
deux tableaux utilisent la vue Git seule, sans registre de tâches détecté. Ces vérifications ne qualifient pas
l'activité réelle d'un fournisseur IA ni les conversations des agents.
