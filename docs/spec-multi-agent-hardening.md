---
title: Flightboard fiable pour plusieurs agents
type: feature
created: 2026-11-09
status: done
baseline_commit: 6b8544b1b35baee973e253152691e83520c9e576
context: []
---
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc. -->

<frozen-after-approval reason="Demande explicite de reprendre, corriger et tester">

## Intent

**Problem:** Le moteur extrait de SYFOS manque les derniers correctifs SYF-139 et huit cas limites de l'audit. Ses conventions de chemins et de tâches privilégient Claude, ce qui limite son usage avec Codex et les autres agents.

**Approach:** Adapter les protections pertinentes du correctif Claude aux modules autonomes de flightboard, corriger les régressions démontrées, puis rendre le suivi Git et la planification indépendants du fournisseur. Le tableau reste local et en lecture seule.

## Boundaries & Constraints

**Always:** Python standard uniquement, commandes isolées avec -I -B, textes anglais et français, contrôles de chemins et de requêtes conservés. Les décisions utilisent toutes les données lues; les plafonds de présentation ne doivent pas devenir des omissions silencieuses. Une lecture incomplète bloque les conclusions prêt/terminé. Les racines externes sont choisies explicitement par la ligne de commande et ne sont jamais dérivées des fichiers observés.

**Ask First:** Publication, push ou action sur un service externe qui modifierait son état.

**Never:** Modifier le dépôt SYFOS, installer un skill dans la configuration personnelle, lire les conversations des agents, lancer un fournisseur IA, fusionner ou supprimer une session depuis le tableau, scanner automatiquement les autres projets de l'utilisateur.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| --- | --- | --- | --- |
| Travail masqué | 200 fichiers ignorés puis un fichier utile | Travail restant détecté | Lecture partielle signalée si plafond atteint |
| Conflit tardif | 2000 modifications avant un conflit | Conflit visible | Aucun verdict fondé sur une liste tronquée |
| Session incomplète | Stash, commit détaché délaissé ou arbre illisible | Jamais prêt/terminé | Raison explicite |
| Références ambiguës | Branche symbolique locale à un arbre ou noms confondus par Windows | Lecture prudente | Aucune substitution de commit |
| Dépendances | 31e dépendance bloquée, 4e tâche non terminée | Attente conservée | Limites uniquement au rendu |
| Collision | Même nouvel id, métadonnées différentes | Collision affichée | Aucune fusion arbitraire |
| Codex externe | Worktree enregistré sous une racine externe autorisée | Modifications et registre lus | Lien, racine réseau ou autre projet refusés |
| Actualisation | Échec global, requête bloquée ou fiche ouverte | État périmé annoncé; fiche actualisée | Délai de requête et reprise automatique |

</frozen-after-approval>

## Code Map

- `skills/flightboard/scripts/flightboard/files.py`, `gitreads.py`, `gitconfig.py` : chemins, index et processus.
- `collector.py`, `held.py`, `view.py` : identité des sessions, complétude, stashes et verdicts.
- `ledgers/`, `overlay.py` : validation et décisions sur toutes les tâches et dépendances.
- `config.py`, `cli.py` : racines explicitement autorisées et modes d'exécution.
- `template.html`, `messages.py` : rafraîchissement, fiches et raisons bilingues.
- `skills/flightboard/SKILL.md`, `README.md`, `docs/fr/README.md`, `SECURITY.md` : usage multi-agents et limites.

## Tasks & Acceptance

**Execution:**
- [x] Porter les protections Git/fichiers et les tester sur des dépôts temporaires réels.
- [x] Porter les règles de rétention et corriger les huit cas de l'audit avec régressions ciblées.
- [x] Ajouter `--worktrees-root` répétable pour les worktrees externes enregistrés, dont la disposition Codex à deux niveaux.
- [x] Généraliser propriétaires et capacité de travail à tous les agents, en conservant les anciens registres.
- [x] Actualiser les textes, le skill partagé et les guides pour Claude, Codex et les autres outils Git.
- [x] Exécuter la suite complète, les validations strictes et les scénarios HTTP/navigateur; consigner les limites.

**Acceptance Criteria:**
- Given un dépôt observé, when une lecture échoue ou est incomplète, then aucun état précédent ne devient une nouvelle preuve de préparation ou de fin de session.
- Given deux agents utilisant les mêmes fichiers et branches, when seul leur nom change, then le suivi et la planification donnent les mêmes conclusions.
- Given un worktree externe non autorisé, when le tableau lit son enregistrement Git, then son contenu reste illisible; une racine autorisée permet seulement les arbres de ce dépôt.
- Given un registre ancien utilisant `claude_sessions_per_week`, when il est lu, then il garde son sens; la nouvelle clé `agent_sessions_per_week` représente tous les agents.
- Given l'application lancée, when les données changent, then la fiche ouverte et les indicateurs de fraîcheur correspondent à la nouvelle lecture.

## Spec Change Log

- La relecture a révélé des plafonds d'historique utilisés comme preuve complète : séparer les huit commits affichés
  de l'attribution complète bornée et bloquer les verdicts si cette attribution est inconnue. Conserver les limites
  de mémoire, la validation Git et le budget global.
- Deux worktrees Codex peuvent avoir le même nom : les jointures utilisent désormais leur identifiant stable,
  indépendamment du libellé affiché. Conserver les textes sûrs dans le résumé destiné aux agents.
- Les nouvelles tâches en conflit sont exclues des compteurs et affichent une incertitude explicite. Les tâches
  déjà présentes dans main conservent son statut, même après annulation d'une première application.
- Les erreurs de transport retirent les anciens verdicts comme les échecs globaux de lecture. La reprise recrée
  la vue même lorsque son contenu est identique à celui de la dernière lecture réussie.

## Design Notes

La compatibilité porte sur les traces Git, pas sur une connexion aux conversations ou aux fournisseurs. Les racines externes sont locales, sans lien ni jonction, et autorisent des worktrees enregistrés sur un ou deux niveaux pour couvrir les dispositions usuelles des outils. Le dossier Git commun reste contrôlé dans le dépôt principal. La branche locale principale reste la référence quand la copie distante est simplement en avance, avec une note explicite.

## Verification

**Commands:**
- `python -I -B -m unittest discover -s tests -t .` : aucun échec.
- `python -I -B skills/flightboard/scripts/flightboard.py --resume --lang fr` : résumé cohérent.
- `npx --yes @anthropic-ai/claude-code@2.1.311 plugin validate --strict .` : manifests valides.
- Essais HTTP, snapshot et navigateur sur dépôts synthétiques : lecture, actualisation et limites vérifiées.

## Suggested Review Order

**Collecte et frontières**

- Comprendre le budget commun et la construction prudente des verdicts.
  [collector.py:91](../skills/flightboard/scripts/flightboard/collector.py#L91)
- Vérifier les chemins externes explicitement autorisés avant toute lecture.
  [files.py:86](../skills/flightboard/scripts/flightboard/files.py#L86)
- Examiner les délais des processus et l'ouverture native sans attente d'oplock.
  [processes.py:50](../skills/flightboard/scripts/flightboard/processes.py#L50)
  [readio.py:76](../skills/flightboard/scripts/flightboard/readio.py#L76)

**Décisions et affichage**

- Suivre l'identité des sources et l'annulation des déclarations contradictoires.
  [overlay.py:94](../skills/flightboard/scripts/flightboard/overlay.py#L94)
- Vérifier les propriétaires génériques et l'exclusion des nouvelles tâches en conflit.
  [base.py:70](../skills/flightboard/scripts/flightboard/ledgers/base.py#L70)
- Examiner la fiche actualisée et les états d'erreur du navigateur.
  [template.html:234](../skills/flightboard/scripts/flightboard/template.html#L234)
  [template.html:717](../skills/flightboard/scripts/flightboard/template.html#L717)

**Preuves et usage**

- Rejouer les scénarios externes et les régressions sémantiques.
  [test_external_worktrees.py:68](../tests/test_external_worktrees.py#L68)
  [test_audit_logic.py:30](../tests/test_audit_logic.py#L30)
- Consulter les résultats, la commande portable et les limites restantes.
  [Bilan de vérification](verification-multi-agent-hardening.md)
