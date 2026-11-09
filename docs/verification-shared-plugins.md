<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Vérification des plugins et du skill local — 2026-11-09

Claude Code et Codex utilisent le même skill, le même moteur dans `skills/flightboard/scripts` et le même dashboard
web. Le manifeste portable `plugin.json` déclare le besoin d'exécution locale ; `.agents/plugins/marketplace.json`
expose ce plugin à Codex. Les manifestes Claude sont conservés. Aucun code du moteur ni du dashboard n'a changé.

## Vérifications exécutées

- `codex plugin marketplace add <copie-locale> --json`, puis `codex plugin add flightboard@flightboard --json`
  et `codex plugin list --marketplace flightboard --json` : installation et activation confirmées dans un
  `CODEX_HOME` temporaire, sans installer un deuxième exemplaire dans la configuration personnelle.
- Skill personnel installé avec Skill Installer depuis le commit publié `adbb849`, puis actualisé avec le
  `SKILL.md` et les métadonnées Codex de cette modification. Les 25 fichiers du skill correspondent à la source par
  SHA-256 ; aucun cache Python n'est copié.
- `quick_validate.py` de Skill Creator : skill source et skill installé valides. PyYAML est un outil de validation,
  pas une dépendance du moteur.
- Moteur installé exécuté sous Windows avec Python 3.14 et Git 2.51.2 : `--repo <flightboard> --resume --lang fr`
  réussit. Un second agent a suivi le skill installé indépendamment et obtenu le même résumé avec `py -3 -I -B`.
- Serveur lancé depuis le skill personnel avec `-I -B --repo <flightboard> --lang fr` : ligne `SERVING`, page et
  `/state.json` en HTTP 200, dépôt attendu, écoute limitée à `127.0.0.1` et `::1`. Ouverture réelle dans le navigateur :
  page française en direct et modifications locales visibles.
- Tests ciblés : 5 contrôles d'hygiène, 1 test du JavaScript réel de la page (7 vérifications), 43 tests HTTP/serveur
  et 16 tests des modes de lecture, soit **65 tests réussis**.
- Claude Code `2.1.311 plugin validate --strict` : marché et manifeste valides. Avertissement non bloquant existant :
  icône du plugin absente.
- `git diff --check` : réussi.

Les commandes de tests utilisent `python -I -B -m unittest discover -s tests -t . -p <fichier>`, pour
`test_hygiene.py`, `test_live_page.py`, `test_server.py` et `test_modes.py`.

## Portée

L'installation personnelle concerne le skill Codex. L'installation du plugin Codex a été qualifiée séparément dans
un environnement temporaire pour éviter une double découverte du même skill. Le plugin Claude a été validé ; une
nouvelle conversation Claude réelle n'a pas été exécutée. Les autres applications IA ne sont pas qualifiées ici.

Ces vérifications complètent la qualification antérieure du moteur ; elles ne constituent pas une nouvelle
exécution de toute la matrice Windows/Linux/macOS. Les plugins nécessitent toujours Python 3.12+ et Git 2.41+.
La publication dans un annuaire public, un exécutable autonome et un tableau agrégeant plusieurs dépôts ne font pas
partie de cette modification.
