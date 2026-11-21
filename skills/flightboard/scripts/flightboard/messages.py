# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The one message catalog of flightboard: English by default, French kept (--lang fr).

The code decides with codes (a reason, a stage, a kind); words come only from here. TEXT is what Python words (the
summary, what waits, reasons); PAGE is what the page words, sent to it in its JSON data block with LABELS, since the
page's security policy lets exactly one inline script run. A plural is a pair (one, many), chosen by the language's own
rule. Placeholders are {names}, filled with text that only ever becomes a text node. Standard library only.
"""
from __future__ import annotations

LANGS = ("en", "fr")
LOCALES = {"en": "en", "fr": "fr-CA"}

TEXT: dict[str, dict[str, object]] = {
    "en": {
        "status.removed": "removed",
        "side": "{where}: {status}",
        "commits": ("{n} commit", "{n} commits"),
        "pushed": "pushed",
        "not_pushed": "not pushed yet",
        "detached": "(detached)",
        "verb.merge": "Give your merge go",
        "verb.conflict": "Arbitrate",
        "verb.collision": "Tell apart",
        "verb.check": "Check",
        "verb.alert": "Look at the session",
        "verb.review": "Start the review",
        "verb.session": "Look at the session",
        "wait.tracking": "{name}: observed file activity is newer than its task ledger; check the associated lot",
        "wait.tracking_safe": "Recent file activity is newer than the task ledger; check its lot association.",
        "wait.merge": "{tasks} · {name}, {commits}, {pushed}",
        "wait.merge_git": "{name}, {commits}, {pushed}",
        "wait.conflict": "{tid}, changed in several places: {sides}",
        "wait.conflict_titled": "{tid} {title}, changed in several places: {sides}",
        "wait.collision": "two different tasks carry the id {tid}: {where}",
        "wait.orphan": "{tid} is changed in {name} ({status}), but main no longer holds it",
        "quote": ": “{quote}”",
        "unknown_status": "unknown status",
        "wait.decision": "{did} ({status}), recorded in your name in {name}{quote}",
        "wait.decision_safe": "{did} ({status}), recorded in your name in {name} (quote on the page)",
        "whose.owner": "your",
        "whose.reviewer": "the reviewer's",
        "wait.governed": "{name} marks {tid} {status}: {whose} task, it moves only in main, with your agreement",
        "wait.governed_titled": "{name} marks {tid} ({title}) {status}: {whose} task, it moves only in main, with "
                                "your agreement",
        "wait.governed_new": "{name} adds {tid}, {whose} task ({status}): it enters only through main, with your "
                             "agreement",
        "git_conflict": "git conflict",
        "git_operation": "git operation",
        "wait.alert": "{name}: {what}",
        "wait.invalid_safe": "{name}: invalid ledger (details on the page)",
        "slots": " ({slots})",
        "review_slots": ("{n} review planned per week", "{n} reviews planned per week"),
        "wait.session": "{name}: uncommitted changes, quiet; it may be waiting for you in its coding-agent tool",
        "summary.open": "{sessions}, {writing}",
        "summary.sessions": ("{n} open session", "{n} open sessions"),
        "summary.writing": ("{n} writing now", "{n} writing now"),
        "summary.ready": ("{n} ready for your merge go ({names})", "{n} ready for your merge go ({names})"),
        "summary.review": ("{n} task in review", "{n} tasks in review"),
        "summary.done": "{done} in main out of {active}",
        "summary.done_count": ("{n} done", "{n} done"),
        "summary.extra": (", {n} more declared in the branches", ", {n} more declared in the branches"),
        "summary.join": "; ",
        "summary.error": "Reading impossible: {reason}.",
        "source.git": "Git",
        "source.git_read": "read",
        "source.read": ("{n} session read", "{n} sessions read"),
        "source.main": "Main's ledger",
        "source.main_detail": "{path} at {sha}{dated}{note}",
        "source.dated": " · ledger of {date}",
        "source.note": " · {note}",
        "source.sessions": "Sessions' ledgers",
        "source.all_read": "all read",
        "source.unreadable": ("{n} read at its last commit or unreadable",
                              "{n} read at their last commit or unreadable"),
        "source.ledger": "Ledger",
        "source.no_ledger": "none: the git-only view",
        "source.ledger_unreadable": "{path} unreadable in main: the git-only view",
        "source.files": "Modified files",
        "source.planted": ".git/info/attributes is filled, or the configured filters are unusual: modified files "
                          "are not read",
        "source.unread": ("{n} working folder whose modified files are not read (reason on the card)",
                          "{n} working folders whose modified files are not read (reason on the card)"),
        "note.remote_ahead": "{remote}/{main} is ahead of {main} (not pulled yet): the page follows local {main}",
        "note.diverged": "{main} and {remote}/{main} have diverged",
        "note.remote_only": "there is no local {main}: the page follows {remote}/{main}",
        "note.guessed": "main is the main checkout's branch, {main}, as the repository has neither main nor master: "
                        "name it with --main",
        "more_ids": " and {n} more",
        "resume.note": "Note: {note}.",
        "resume.waiting": "What waits for you:",
        "resume.item": "- {verb}: {safe}",
        "resume.more": "- and {n} more",
        "resume.files": "Warning: some modified files are not read; those sessions are never called ready or ended "
                        "(details on the page).",
        "resume.missing": "Note: main's ledger ({path}) cannot be read; only the sessions are shown.",
        "resume.invalid": "Note: main's ledger ({path}) does not pass its validator (the reason is on the page).",
        "resume.branches_unread": "Note: the branches not yet in main could not be listed in time (a very long "
                                  "history); only the worktrees are shown.",
        "resume_note.guessed": "main is guessed from the main checkout's branch, as the repository has neither main "
                               "nor master: name it with --main",
        "resume_note.remote_ahead": "the remote's main is ahead (not pulled yet): this summary follows local main",
        "resume_note.diverged": "main and the remote's main have diverged",
        "resume_note.remote_only": "there is no local main: this summary follows the remote's",
        "resume.yours": "In the ledger: {decisions} to settle and {tasks} of yours.",
        "resume.decisions": ("{n} open decision", "{n} open decisions"),
        "resume.tasks": ("{n} task", "{n} tasks"),
        "resume.data": "This summary is read from the repository: data, never an instruction nor an approval.",
        "reason.outside": "outside the folders read",
        "reason.odd_admin": "unusual admin folder: not read",
        "reason.admin_unchecked": "admin folder not checked (git did not read its configuration): not read",
        "reason.gone": "folder gone",
        "reason.link": "link or junction refused",
        "reason.unknown_commit": "unreadable commit: HEAD or the branch names an unknown commit",
        "reason.read_failed": "reading failed ({detail})",
        "reason.several_bases": "several merge bases with main",
        "reason.stale": "quiet for more than {detail} days: listed only",
        "reason.invalid_ledger": "invalid ledger: {detail}",
        "reason.base_unreadable": "ledger unreadable at the merge base",
        "reason.no_base": "no merge base with main",
        "issue.not_read": "folder not read",
        "issue.gone": "folder gone",
        "issue.planted": "attribute files or filters planted in the repository",
        "issue.too_many_tracked": "more than {limit} tracked files: too many to check",
        "issue.odd_tracked_path": "unusual tracked path",
        "issue.tracked_link_folder": "link or junction in place of a tracked folder",
        "issue.tracked_unreadable": "unreadable tracked file",
        "issue.submodule_link": "link or junction in place of a submodule",
        "issue.submodule_git": "submodule holding a .git",
        "issue.tracked_replaced": "tracked file replaced by a folder or a link",
        "issue.long_tracked_path": "a tracked path of 260 characters or more, which git does not read on Windows",
        "issue.sparse_index": "a sparse index, which git would rewrite into the repository to read it (its new files "
                              "are not listed either)",
        "issue.split_index": "a split index, whose shared part git would touch to read it (its new files are not "
                             "listed either)",
        "issue.index_too_big": "an index over 64 MB, too big to check (its new files are not listed either)",
        "issue.folder_unlisted": "a folder that cannot be listed (its new files are not listed)",
        "issue.unreadable": "session unreadable",
        "error.git_failed": "git reading failed: {detail}",
        "error.read_failed": "reading failed ({detail})",
        "error.no_repository": "no git repository here: run the command from the repository's folder, or name it "
                               "with --repo",
        "error.git_dir_link": "git is not run: the .git folder is a link",
        "error.git_trap": "git is not run on this repository: {detail} (see SECURITY.md)",
        "error.git_too_old": "git 2.41 or newer is required",
        "error.no_main": "main branch not found (main or master; name it with --main)",
        "error.unavailable": "the state could not be made; the page tries again on its own",
        "trap.link": "a link in .git ({entry})",
        "trap.special": "a pipe, a socket or a device in .git ({entry})",
        "trap.many": "more than {limit} entries in a folder of .git ({entry})",
        "trap.commondir": "a commondir file in .git",
        "trap.alternates": "borrowed objects (objects/info/alternates)",
        "trap.alternates_unreadable": "unreadable borrowed objects",
        "trap.config_unreadable": "an unreadable git configuration ({entry})",
        "trap.include": "a configuration include",
        "trap.core_worktree": "a core.worktree",
        "trap.ref_storage": "a reftable ref store, which the board does not read",
        "trap.object_format": "a SHA-256 object store, which the board does not read",
        "trap.main_worktree_config": "a configuration of the main checkout's own",
        "trap.promisor": "a partial clone's remote, which git older than 2.45 could fetch from through a program its "
                         "configuration names (update git)",
    },
    "fr": {
        "status.removed": "retirée",
        "side": "{where} : {status}",
        "commits": ("{n} commit", "{n} commits"),
        "pushed": "poussée",
        "not_pushed": "pas encore poussée",
        "detached": "(détachée)",
        "verb.merge": "Donner ton go de fusion",
        "verb.conflict": "Arbitrer",
        "verb.collision": "Départager",
        "verb.check": "Vérifier",
        "verb.alert": "Regarder la session",
        "verb.review": "Lancer la revue",
        "verb.session": "Regarder la session",
        "wait.tracking": "{name} : de l’activité est observée après l’enregistrement du registre ; "
                         "vérifie le lot associé",
        "wait.tracking_safe": "De l’activité est observée après l’enregistrement du registre ; "
                              "vérifie son rattachement aux lots.",
        "wait.merge": "{tasks} · {name}, {commits}, {pushed}",
        "wait.merge_git": "{name}, {commits}, {pushed}",
        "wait.conflict": "{tid}, changée à plusieurs endroits : {sides}",
        "wait.conflict_titled": "{tid} {title}, changée à plusieurs endroits : {sides}",
        "wait.collision": "deux tâches différentes portent l'identifiant {tid} : {where}",
        "wait.orphan": "{tid} est changée dans {name} ({status}), mais main ne l'a plus",
        "quote": " : « {quote} »",
        "unknown_status": "statut inconnu",
        "wait.decision": "{did} ({status}), enregistrée en ton nom dans {name}{quote}",
        "wait.decision_safe": "{did} ({status}), enregistrée en ton nom dans {name} (citation sur la page)",
        "whose.owner": "à toi",
        "whose.reviewer": "au relecteur",
        "wait.governed": "{name} marque {tid} {status} : une tâche {whose}, elle ne bouge que dans main, sur ton "
                         "accord",
        "wait.governed_titled": "{name} marque {tid} ({title}) {status} : une tâche {whose}, elle ne bouge que dans "
                                "main, sur ton accord",
        "wait.governed_new": "{name} ajoute {tid}, une tâche {whose} ({status}) : elle n'entre que par main, sur ton "
                             "accord",
        "git_conflict": "conflit git",
        "git_operation": "opération git",
        "wait.alert": "{name} : {what}",
        "wait.invalid_safe": "{name} : registre invalide (détail sur la page)",
        "slots": " ({slots})",
        "review_slots": ("{n} revue prévue par semaine", "{n} revues prévues par semaine"),
        "wait.session": "{name} : modifs non commitées, silencieuse ; elle t'attend peut-être dans son outil d'agent",
        "summary.open": "{sessions}, {writing}",
        "summary.sessions": ("{n} session ouverte", "{n} sessions ouvertes"),
        "summary.writing": ("{n} écrit en ce moment", "{n} écrivent en ce moment"),
        "summary.ready": ("{n} prête pour ton go de fusion ({names})", "{n} prêtes pour ton go de fusion ({names})"),
        "summary.review": ("{n} tâche en revue", "{n} tâches en revue"),
        "summary.done": "{done} dans main sur {active}",
        "summary.done_count": ("{n} faite", "{n} faites"),
        "summary.extra": (", {n} de plus déclarée dans les branches", ", {n} de plus déclarées dans les branches"),
        "summary.join": " ; ",
        "summary.error": "Lecture impossible : {reason}.",
        "source.git": "Git",
        "source.git_read": "lu",
        "source.read": ("{n} session lue", "{n} sessions lues"),
        "source.main": "Registre de main",
        "source.main_detail": "{path} à {sha}{dated}{note}",
        "source.dated": " · registre du {date}",
        "source.note": " · {note}",
        "source.sessions": "Registres des sessions",
        "source.all_read": "tous lus",
        "source.unreadable": ("{n} lu au dernier commit ou illisible", "{n} lus au dernier commit ou illisibles"),
        "source.ledger": "Registre",
        "source.no_ledger": "aucun : la vue git seule",
        "source.ledger_unreadable": "{path} illisible dans main : la vue git seule",
        "source.files": "Fichiers modifiés",
        "source.planted": ".git/info/attributes est rempli, ou les filtres configurés sont inhabituels : les "
                          "fichiers modifiés ne sont pas lus",
        "source.unread": ("{n} dossier de travail dont les fichiers modifiés ne sont pas lus (raison sur la carte)",
                          "{n} dossiers de travail dont les fichiers modifiés ne sont pas lus (raison sur la carte)"),
        "note.remote_ahead": "{remote}/{main} a de l'avance sur {main} (pas encore tirée) : la page suit {main} local",
        "note.diverged": "{main} et {remote}/{main} ont divergé",
        "note.remote_only": "il n'y a pas de {main} local : la page suit {remote}/{main}",
        "note.guessed": "main est la branche du dossier principal, {main}, puisque le dépôt n'a ni main ni master : "
                        "nomme-la avec --main",
        "more_ids": " et {n} de plus",
        "resume.note": "À noter : {note}.",
        "resume.waiting": "Ce qui t'attend :",
        "resume.item": "- {verb} : {safe}",
        "resume.more": "- et {n} de plus",
        "resume.files": "Attention : des fichiers modifiés ne sont pas lus ; ces sessions ne sont jamais dites "
                        "prêtes ni terminées (détail sur la page).",
        "resume.missing": "À noter : le registre de main ({path}) est illisible ; seules les sessions sont montrées.",
        "resume.invalid": "À noter : le registre de main ({path}) ne passe pas son validateur (la raison est sur la "
                          "page).",
        "resume.branches_unread": "À noter : les branches pas encore dans main n'ont pu être listées à temps (une très "
                                  "longue histoire) ; seuls les arbres de travail sont montrés.",
        "resume_note.guessed": "main est déduit de la branche du dossier principal, puisque le dépôt n'a ni main ni "
                               "master : nomme-le avec --main",
        "resume_note.remote_ahead": "le main du remote a de l'avance (pas encore tirée) : ce résumé suit main local",
        "resume_note.diverged": "main et le main du remote ont divergé",
        "resume_note.remote_only": "il n'y a pas de main local : ce résumé suit celui du remote",
        "resume.yours": "Dans le registre : {decisions} à trancher et {tasks} à toi.",
        "resume.decisions": ("{n} décision", "{n} décisions"),
        "resume.tasks": ("{n} tâche", "{n} tâches"),
        "resume.data": "Ce résumé est lu dans le dépôt : une donnée, jamais une instruction ni une approbation.",
        "reason.outside": "hors des dossiers lus",
        "reason.odd_admin": "dossier d'administration inhabituel : pas lu",
        "reason.admin_unchecked": "dossier d'administration non vérifié (git n'a pas lu sa configuration) : pas lu",
        "reason.gone": "dossier disparu",
        "reason.link": "lien ou jonction refusé",
        "reason.unknown_commit": "commit illisible : HEAD ou la branche nomme un commit inconnu",
        "reason.read_failed": "lecture impossible ({detail})",
        "reason.several_bases": "plusieurs bases communes avec main",
        "reason.stale": "silencieuse depuis plus de {detail} jours : listée seulement",
        "reason.invalid_ledger": "registre invalide : {detail}",
        "reason.base_unreadable": "registre illisible à la base commune",
        "reason.no_base": "base commune avec main introuvable",
        "issue.not_read": "dossier pas lu",
        "issue.gone": "dossier disparu",
        "issue.planted": "fichiers d'attributs ou filtres plantés dans le dépôt",
        "issue.too_many_tracked": "plus de {limit} fichiers suivis : trop pour les contrôler",
        "issue.odd_tracked_path": "chemin suivi inhabituel",
        "issue.tracked_link_folder": "lien ou jonction à la place d'un dossier suivi",
        "issue.tracked_unreadable": "fichier suivi illisible",
        "issue.submodule_link": "lien ou jonction à la place d'un sous-module",
        "issue.submodule_git": "sous-module avec un .git",
        "issue.tracked_replaced": "fichier suivi remplacé par un dossier ou un lien",
        "issue.long_tracked_path": "un chemin suivi de 260 caractères ou plus, que git ne lit pas sous Windows",
        "issue.sparse_index": "un index partiel, que git réécrirait dans le dépôt pour le lire (ses nouveaux fichiers "
                              "ne sont pas listés non plus)",
        "issue.split_index": "un index scindé, dont git toucherait la partie partagée pour le lire (ses nouveaux "
                             "fichiers ne sont pas listés non plus)",
        "issue.index_too_big": "un index de plus de 64 Mo, trop gros pour le contrôler (ses nouveaux fichiers ne sont "
                               "pas listés non plus)",
        "issue.folder_unlisted": "un dossier qu'on ne peut lister (ses nouveaux fichiers ne sont pas listés)",
        "issue.unreadable": "session illisible",
        "error.git_failed": "lecture git impossible : {detail}",
        "error.read_failed": "lecture impossible ({detail})",
        "error.no_repository": "aucun dépôt git ici : lance la commande depuis le dossier du dépôt, ou nomme-le "
                               "avec --repo",
        "error.git_dir_link": "git n'est pas lancé : le dossier .git est un lien",
        "error.git_trap": "git n'est pas lancé sur ce dépôt : {detail} (voir SECURITY.md)",
        "error.git_too_old": "git 2.41 ou plus récent est requis",
        "error.no_main": "branche principale introuvable (main ou master ; nomme-la avec --main)",
        "error.unavailable": "l'état n'a pas pu être produit ; la page réessaie toute seule",
        "trap.link": "un lien dans .git ({entry})",
        "trap.special": "un tube, un socket ou un périphérique dans .git ({entry})",
        "trap.many": "plus de {limit} entrées dans un dossier de .git ({entry})",
        "trap.commondir": "un fichier commondir dans .git",
        "trap.alternates": "un emprunt d'objets (objects/info/alternates)",
        "trap.alternates_unreadable": "un emprunt d'objets illisible",
        "trap.config_unreadable": "une configuration git illisible ({entry})",
        "trap.include": "une inclusion de configuration",
        "trap.core_worktree": "un core.worktree",
        "trap.ref_storage": "un magasin de références reftable, que le tableau ne lit pas",
        "trap.object_format": "un magasin d'objets SHA-256, que le tableau ne lit pas",
        "trap.main_worktree_config": "une configuration git propre au dossier principal",
        "trap.promisor": "le remote d'un clone partiel, d'où un git plus ancien que 2.45 pourrait aller chercher des "
                         "objets par un programme que nomme sa configuration (mets git à jour)",
    },
}

LABELS: dict[str, dict[str, dict[str, str]]] = {
    "en": {
        "status": {"planned": "Planned", "ready": "Ready", "in_progress": "In progress",
                   "awaiting_review": "Awaiting review", "done": "Done", "blocked": "Blocked", "dropped": "Dropped"},
        "owner": {"claude": "Claude", "codex": "Codex", "owner": "you", "reviewer": "reviewer"},
        "decision": {"adopted": "adopted", "open": "to settle", "superseded": "superseded"},
        "release": {"1.0": "version 1.0", "later": "after 1.0"},
        "activity": {"active": "writing now", "recent": "wrote recently", "quiet": "quiet",
                     "unknown": "activity unknown"},
        "stage": {"uncommitted": "uncommitted changes", "committed": "committed, not pushed", "pushed": "pushed",
                  "behind_origin": "behind its remote: the session went on elsewhere", "merged": "in main",
                  "up_to_date": "up to date", "conflict": "in conflict", "operation": "git operation in progress",
                  "unknown": "relationship to main unknown"},
        "advice": {"ready_to_merge": "ready for your merge go", "open": "not yet in main",
                   "ended": "ended: all in main", "keep_for_review": "in main, in review: keep the session for fixes",
                   "keep_files": "in main, but kept files wait in its folder", "merged": "in main",
                   "gone": "folder gone: git worktree prune removes it from the list"},
        "kind": {"checkout": "main checkout of the repository", "worktree": "worktree",
                 "branch": "branch without a worktree", "remote": "pushed branch, seen at the last fetch"},
        "ledger": {"ok": "ledger read", "absent": "no ledger", "none": "no ledger",
                   "writing": "working copy unreadable (being written or in conflict): read at the last commit",
                   "too_big": "ledger too big: read at the last commit",
                   "unreadable": "ledger unreadable: not a ledger of this format",
                   "merging": "merge in progress: read at the last commit",
                   "stale": "reading failed: last good reading"},
        "operation": {"rebase": "rebase in progress", "merge": "merge in progress",
                      "cherry-pick": "cherry-pick in progress", "revert": "revert in progress",
                      "bisect": "bisect in progress"},
        "source": {"ok": "up to date", "partial": "partial", "unreadable": "unreadable", "absent": "absent"},
        "section": {"milestones": "milestones", "capacity": "capacity", "launch_gate": "launch gate",
                    "external_dependencies": "external dependencies", "statuses": "status words",
                    "decisions": "decisions"},
    },
    "fr": {
        "status": {"planned": "Prévue", "ready": "Prête", "in_progress": "En cours",
                   "awaiting_review": "En attente de revue", "done": "Faite", "blocked": "Bloquée",
                   "dropped": "Abandonnée"},
        "owner": {"claude": "Claude", "codex": "Codex", "owner": "toi", "reviewer": "relecteur"},
        "decision": {"adopted": "adoptée", "open": "à trancher", "superseded": "remplacée"},
        "release": {"1.0": "version 1.0", "later": "hors 1.0"},
        "activity": {"active": "écrit en ce moment", "recent": "a écrit récemment", "quiet": "silencieuse",
                     "unknown": "activité inconnue"},
        "stage": {"uncommitted": "modifs non commitées", "committed": "commité, pas poussé", "pushed": "poussé",
                  "behind_origin": "en retard sur son remote : la session a continué ailleurs",
                  "merged": "dans main", "up_to_date": "à jour", "conflict": "en conflit",
                  "operation": "opération git en cours", "unknown": "rattachement à main inconnu"},
        "advice": {"ready_to_merge": "prête pour ton go de fusion", "open": "pas encore dans main",
                   "ended": "terminée : tout est dans main",
                   "keep_for_review": "dans main, en revue : garde la session pour les corrections",
                   "keep_files": "dans main, mais des fichiers à garder attendent dans son dossier",
                   "merged": "dans main",
                   "gone": "dossier disparu : « git worktree prune » le retire de la liste"},
        "kind": {"checkout": "dossier principal du dépôt", "worktree": "arbre de travail",
                 "branch": "branche sans arbre", "remote": "branche poussée, vue au dernier fetch"},
        "ledger": {"ok": "registre lu", "absent": "pas de registre", "none": "pas de registre",
                   "writing": "copie de travail illisible (en écriture ou en conflit) : lue au dernier commit",
                   "too_big": "registre trop gros : lu au dernier commit",
                   "unreadable": "registre illisible : pas un registre de ce format",
                   "merging": "fusion en cours : lue au dernier commit",
                   "stale": "lecture impossible : dernière lecture valide"},
        "operation": {"rebase": "rebase en cours", "merge": "fusion en cours", "cherry-pick": "cherry-pick en cours",
                      "revert": "revert en cours", "bisect": "bisect en cours"},
        "source": {"ok": "à jour", "partial": "partielle", "unreadable": "illisible", "absent": "absente"},
        "section": {"milestones": "jalons", "capacity": "capacité", "launch_gate": "porte de lancement",
                    "external_dependencies": "dépendances externes", "statuses": "mots de statut",
                    "decisions": "décisions"},
    },
}

PAGE: dict[str, dict[str, object]] = {
    "en": {
        "page.title": "flightboard",
        "page.mode_live": "live", "page.mode_lost": "connection lost", "page.mode_snapshot": "snapshot",
        "page.snapshot_of": "Snapshot of {when}",
        "page.lost": "Connection lost · last reading {ago}",
        "page.live_read": "Live · read {n} s ago",
        "page.spoken_live": "Live", "page.spoken_lost": "Connection lost: start the server again",
        "page.spoken_snapshot": "Snapshot",
        "page.subject": "“{subject}”",
        "page.ledger_of": " · main’s ledger dated {date}",
        "page.board_read_at": "Board reading: {when}",
        "page.observed_activity": "Observed local activity",
        "page.ledger_saved_at": "Working ledger saved",
        "page.date_unknown": "Not observed",
        "page.tracking_check": "Tracking to check",
        "page.tracking_info": "Activity since the ledger was saved",
        "page.tracking_unknown": "Association not evaluated",
        "page.tracking_unassigned": "No lot is identified for this session. "
                                    "Check which lot the recent work belongs to.",
        "page.tracking_settled": "The identified lots are in review or finished. "
                                 "Check the association of the recent work.",
        "page.tracking_ongoing": "Work can legitimately continue on an existing lot. "
                                 "These dates do not establish coverage.",
        "page.tracking_unreadable": "The working files or ledger could not be fully read.",
        "page.tracking_partial": "Activity dating is incomplete; these observations "
                                 "cannot establish the lot association.",
        "page.tracking_dates": "Reliable activity and working-ledger dates are unavailable.",
        "page.tracking_partial_note": "Partial observation: {reasons}.",
        "page.tracking_partial_limit": "activity-dating entry limit reached",
        "page.tracking_partial_depth": "reading depth limit reached",
        "page.tracking_partial_folder": "a folder was not fully observed",
        "page.tracking_partial_unsafe": "an unsafe or special entry was excluded",
        "page.tracking_partial_deleted": "a deleted file has no observable time",
        "page.tracking_partial_ignore": "ignore rules could not be evaluated",
        "page.tracking_partial_unreadable": "some metadata could not be read",
        "page.tracking_partial_unspecified": "some entries could not be dated",
        "page.tracking_task_state": "The associated lot status is unavailable or unknown.",
        "page.unreadable": "Reading impossible: {reason}",
        "page.invalid_main": "Main's ledger does not pass its validator: {error}",
        "page.cannot_read": "The page could not read the repository: {reason}. It tries again on its own.",
        "page.ledger_missing": "Main's ledger ({path}) cannot be read: the page shows the sessions only.",
        "page.failed_at": "Last successful reading at {when}. {reason}. Previous data is out of date; session "
                          "verdicts are unavailable until the connection recovers. Retrying automatically.",
        "page.less_than_minute": "less than a minute", "page.minutes": "{n} min", "page.hours": "{n} h",
        "page.days": "{n} d",
        "page.ago": "{span} ago", "page.since": "for {span}", "page.waiting_since": "waiting for {span}",
        "page.wrote": "wrote {span} ago", "page.quiet_for": "quiet for {span}", "page.opened": "opened {span} ago",
        "page.last_activity": "last activity {span} ago",
        "page.on_time": "on time", "page.days_ahead": "{n} d ahead", "page.days_late": "{n} d late",
        "page.removed": "removed", "page.new_status": "new: {status}", "page.removed_was": "removed (was {status})",
        "page.declared_in": " (declared in {name}, not applied here)",
        "page.not_in_main": " (new, not yet in main)", "page.in_main": " (in main: {status})",
        "page.acceptance": "Acceptance criteria", "page.dependencies": "Dependencies", "page.awaited": " (awaited)",
        "page.close": "Close",
        "page.pair": "{name}: ",
        "page.table": "See as a table",
        "page.waiting": "What waits for you",
        "page.verb": "{verb}:",
        "page.nothing_waits": "Nothing waits for you on the sessions' side.",
        "page.nothing_readable": "Nothing readable for now.",
        "page.more_items": ["{n} more item", "{n} more items"],
        "page.beyond": "And {n} more, beyond what the page lists. ",
        "page.yours": "In the ledger: {decisions} to settle and {tasks} of yours.",
        "page.decisions_n": ["{n} decision", "{n} decisions"], "page.tasks_n": ["{n} task", "{n} tasks"],
        "page.sessions": "Sessions",
        "page.sessions_lead": "A session is a git working folder (often a coding agent's worktree) or a branch not "
                              "yet in main. It can come from Claude, Codex or another tool. Quiet does not mean "
                              "finished: check its conversation in the tool that runs it.",
        "page.writing_now": "writing now", "page.activity_unknown": "activity unknown",
        "page.new_task": "new task, {status}", "page.removed_from": "removed from the ledger (was {status})",
        "page.uncommitted": "uncommitted", "page.back": "move back",
        "page.checkout_title": "Main checkout",
        "page.new_session": "New session: task not known yet",
        "page.commits_out": ["{n} commit out of main", "{n} commits out of main"],
        "page.no_commit_out": "no commit out of main",
        "page.behind": ["{n} commit behind main", "{n} commits behind main"],
        "page.modified": ["{n} modified file", "{n} modified files"],
        "page.untracked": ["{n} new file", "{n} new files"],
        "page.conflicted": ["{n} file in conflict", "{n} files in conflict"],
        "page.kept": ["{n} kept file", "{n} kept files"],
        "page.changes_aria": "Changed statuses",
        "page.more_changes": ["And {n} more change (counted, not listed).",
                              "And {n} more changes (counted, not listed)."],
        "page.files_not_read": "Modified files not read ({issue}): the page calls it neither ready nor ended.",
        "page.also": "Also: ", "page.works_on": "Works on ",
        "page.inferred_status": " ({status} in the ledger)",
        "page.inferred_tail": ", inferred from names and commits.",
        "page.no_change": "No status changed in the ledger.",
        "page.records": "Records ", "page.records_tail": ": to check before the merge.",
        "page.quote_inline": " “{quote}”",
        "page.also_changes": "Also changes: {sections} (never applied here).",
        "page.not_applied": "Not applied here: {reason}",
        "page.note_reason": "Note: {reason}",
        "page.more_tasks": ["And {n} more task (counted, not listed).", "And {n} more tasks (counted, not listed)."],
        "page.last_commit": "Last commit ", "page.colon": ": ", "page.pushed_tag": " · pushed",
        "page.ended": ["{n} ended session: all in main and its tasks done or dropped",
                       "{n} ended sessions: all in main and their tasks done or dropped"],
        "page.no_session": "No open session.", "page.sessions_unreadable": "Sessions unreadable for now.",
        "page.next": "Next to start", "page.next_meta": "dependencies met, nobody on it",
        "page.no_next": "No ready task without taker.", "page.next_unreadable": "Unreadable for now.",
        "page.events": "Latest moves", "page.main_moves": "Latest moves of main",
        "page.new_tag": "new", "page.approx": " (approximate date)",
        "page.declared_tail": " · declared, not yet in main",
        "page.no_events": "No move read.",
        "page.earlier_moves": ["{n} earlier move", "{n} earlier moves"],
        "page.progress": "Progress",
        "page.figures": "Figures", "page.figures_unreadable": "unreadable for now: the page tries again on its own",
        "page.meter": "{done} in main, {extra} in the sessions, {review} in review and {progress} in progress, "
                      "out of {scale}",
        "page.meter_tail": ", counting those the sessions add",
        "page.done_n": ["{n} done", "{n} done"],
        "page.more_declared": ["{n} more declared", "{n} more declared"],
        "page.done_in_main": "Done in main",
        "page.tasks_done": ["{n} task done", "{n} tasks done"], "page.out_of": " out of {n}",
        "page.extra_sessions": [", and {n} more declared in the sessions", ", and {n} more declared in the sessions"],
        "page.v10": " · version 1.0: {done} out of {active}",
        "page.in_review": "In review",
        "page.awaits_review": ["awaits a review before it is done", "await a review before they are done"],
        "page.no_review": "no task awaits a review",
        "page.in_progress": "In progress",
        "page.blocked": ["{n} blocked task", "{n} blocked tasks"],
        "page.in_main_and_sessions": "in main and the sessions",
        "page.launch": "Launch 1.0", "page.on_plan": " against the plan ({date}), per main",
        "page.no_forecast": "forecast unavailable",
        "page.burnup": "Tasks done over time",
        "page.burnup_caption": "Each step is a move of main that changed the ledger. The dotted end adds what the "
                               "sessions declare without being merged.",
        "page.scope": "Scope", "page.scope_10": "Version 1.0", "page.scope_all": "All",
        "page.no_history": "No readable history yet.",
        "page.now_with_sessions": "Now, with the sessions",
        "page.s_total": "Tasks in total", "page.s_review": "Done or in review", "page.s_done": "Done",
        "page.review_queue": "review queue: {n}",
        "page.burnup_aria": "Tasks done over time, now: done {done}; done or in review {review}; tasks in total "
                            "{scope}. Left and right arrows to browse.",
        "page.declared_dash": "declared in the sessions, not yet in main",
        "page.plan_line": "plan (planned ends of milestones)",
        "page.h_moment": "Moment", "page.h_commit": "Commit", "page.now_row": "now (with the sessions)",
        "page.milestones": "Milestones",
        "page.milestones_caption": "One bar per milestone, one colour per status. The lighter part is declared in a "
                                   "session, not yet in main. On the right, the date main forecasts, when the ledger "
                                   "has one.",
        "page.no_milestones": "No readable milestone.",
        "page.declared_in_session": ["declared in a session", "declared in a session"],
        "page.segment_aria": "{milestone} · {status}: {n}",
        "page.not_yet_main": ", {declared}, not yet in main",
        "page.lighter": "lighter: declared in a session",
        "page.h_milestone": "Milestone", "page.h_declared": "Declared in a session",
        "page.h_forecast": "Forecast (main)",
        "page.daily": "Moves per day",
        "page.daily_caption": "New tasks and moves to In progress, Awaiting review or Done each day. Main is solid; "
                              "session declarations are lighter. A task can contribute several moves.",
        "page.no_moves": "No readable move.",
        "page.d_new_main": "New tasks in main", "page.d_progress_main": "Moved to In progress in main",
        "page.d_done_main": "Done in main", "page.d_review_main": "In review in main",
        "page.d_new_live": "New tasks, declared in a session",
        "page.d_progress_live": "Moved to In progress, declared in a session",
        "page.d_done_live": "Done, declared in a session", "page.d_review_live": "In review, declared in a session",
        "page.h_day": "Day",
        "page.sources": "Sources: ",
        "page.branches_cut": ["{n} older branch not read.", "{n} older branches not read."],
        "page.branches_unread": "The branches not yet in main could not be listed in time (a very long history, "
                                "say); the worktrees still show.",
        "page.history_cut": "The history shows main's last {n} moves.",
        "page.history_unread": "main's older history could not be read (a clone without trees, or a history too long "
                               "to walk in time).",
        "page.footer": "Served by flightboard {version}. It reads main, every worktree and every branch not yet in "
                       "main, read-only; it reads neither GitHub nor the network. What a session declares stays a "
                       "claim until it is in main: the page approves nothing and authorizes no action.",
        "page.chart_unavailable": "Chart unavailable.",
    },
    "fr": {
        "page.title": "flightboard",
        "page.mode_live": "en direct", "page.mode_lost": "connexion perdue", "page.mode_snapshot": "instantané",
        "page.snapshot_of": "Instantané du {when}",
        "page.lost": "Connexion perdue · dernière lecture {ago}",
        "page.live_read": "En direct · lu il y a {n} s",
        "page.spoken_live": "En direct", "page.spoken_lost": "Connexion perdue : relance le serveur",
        "page.spoken_snapshot": "Instantané",
        "page.subject": "« {subject} »",
        "page.ledger_of": " · registre de main daté du {date}",
        "page.board_read_at": "Lecture du tableau : {when}",
        "page.observed_activity": "Activité locale observée",
        "page.ledger_saved_at": "Registre de travail enregistré",
        "page.date_unknown": "Non observée",
        "page.tracking_check": "Suivi à vérifier",
        "page.tracking_info": "Activité depuis l’enregistrement du registre",
        "page.tracking_unknown": "Rattachement non évalué",
        "page.tracking_unassigned": "Aucun lot n’est identifié pour cette session. "
                                    "Vérifie à quel lot rattacher le travail récent.",
        "page.tracking_settled": "Les lots identifiés sont en revue ou terminés. "
                                 "Vérifie le rattachement du travail récent.",
        "page.tracking_ongoing": "Le travail peut continuer normalement sur un lot existant. "
                                 "Ces dates ne prouvent pas sa couverture.",
        "page.tracking_unreadable": "Les fichiers de travail ou le registre n’ont pas pu être lus complètement.",
        "page.tracking_partial": "La datation de l’activité est partielle ; ces observations "
                                 "ne permettent pas d’établir le rattachement.",
        "page.tracking_dates": "Les dates fiables d’activité et d’enregistrement du registre ne sont pas disponibles.",
        "page.tracking_partial_note": "Observation partielle : {reasons}.",
        "page.tracking_partial_limit": "limite d’éléments datables atteinte",
        "page.tracking_partial_depth": "profondeur maximale de lecture atteinte",
        "page.tracking_partial_folder": "contenu d’un dossier non entièrement observé",
        "page.tracking_partial_unsafe": "entrée non sûre ou spéciale écartée",
        "page.tracking_partial_deleted": "fichier supprimé sans date observable",
        "page.tracking_partial_ignore": "règles d’exclusion non évaluées",
        "page.tracking_partial_unreadable": "certaines métadonnées sont illisibles",
        "page.tracking_partial_unspecified": "certains éléments n’ont pas pu être datés",
        "page.tracking_task_state": "Le statut du lot associé est indisponible ou inconnu.",
        "page.unreadable": "Lecture impossible : {reason}",
        "page.invalid_main": "Le registre de main ne passe pas son validateur : {error}",
        "page.cannot_read": "La page n’a pas pu lire le dépôt : {reason}. Elle réessaie toute seule.",
        "page.ledger_missing": "Le registre de main ({path}) est illisible : la page ne montre que les sessions.",
        "page.failed_at": "Dernière lecture réussie à {when}. {reason}. Les données précédentes sont périmées ; les "
                          "verdicts des sessions sont indisponibles jusqu'au retour de la connexion. Nouvel essai automatique.",
        "page.less_than_minute": "moins d’une minute", "page.minutes": "{n} min", "page.hours": "{n} h",
        "page.days": "{n} j",
        "page.ago": "il y a {span}", "page.since": "depuis {span}", "page.waiting_since": "en attente depuis {span}",
        "page.wrote": "a écrit il y a {span}", "page.quiet_for": "silencieuse depuis {span}",
        "page.opened": "ouverte il y a {span}", "page.last_activity": "dernière activité il y a {span}",
        "page.on_time": "à l’heure", "page.days_ahead": "{n} j d’avance", "page.days_late": "{n} j de retard",
        "page.removed": "retirée", "page.new_status": "nouvelle : {status}",
        "page.removed_was": "retirée (était {status})",
        "page.declared_in": " (déclarée dans {name}, pas appliquée ici)",
        "page.not_in_main": " (nouvelle, pas encore dans main)", "page.in_main": " (dans main : {status})",
        "page.acceptance": "Critères d’acceptation", "page.dependencies": "Dépendances", "page.awaited": " (attendue)",
        "page.close": "Fermer",
        "page.pair": "{name} : ",
        "page.table": "Voir en tableau",
        "page.waiting": "Ce qui t’attend",
        "page.verb": "{verb} :",
        "page.nothing_waits": "Rien ne t’attend du côté des sessions.",
        "page.nothing_readable": "Rien de lisible pour l’instant.",
        "page.more_items": ["{n} autre élément", "{n} autres éléments"],
        "page.beyond": "Et {n} de plus, au-delà de ce que la page liste. ",
        "page.yours": "Dans le registre : {decisions} à trancher et {tasks} à toi.",
        "page.decisions_n": ["{n} décision", "{n} décisions"], "page.tasks_n": ["{n} tâche", "{n} tâches"],
        "page.sessions": "Sessions",
        "page.sessions_lead": "Une session, c’est un dossier de travail git (souvent l'arbre d'un agent) ou une "
                              "branche qui n’est pas encore dans main. Elle peut venir de Claude, Codex ou d'un autre "
                              "outil. Silencieuse ne veut pas dire finie : vérifie sa conversation dans cet outil.",
        "page.writing_now": "écrit en ce moment", "page.activity_unknown": "activité inconnue",
        "page.new_task": "nouvelle tâche, {status}", "page.removed_from": "retirée du registre (était {status})",
        "page.uncommitted": "non commité", "page.back": "recul",
        "page.checkout_title": "Dépôt principal",
        "page.new_session": "Nouvelle session : tâche pas encore connue",
        "page.commits_out": ["{n} commit hors de main", "{n} commits hors de main"],
        "page.no_commit_out": "aucun commit hors de main",
        "page.behind": ["{n} commit de retard sur main", "{n} commits de retard sur main"],
        "page.modified": ["{n} fichier modifié", "{n} fichiers modifiés"],
        "page.untracked": ["{n} nouveau fichier", "{n} nouveaux fichiers"],
        "page.conflicted": ["{n} fichier en conflit", "{n} fichiers en conflit"],
        "page.kept": ["{n} fichier à garder", "{n} fichiers à garder"],
        "page.changes_aria": "Statuts changés",
        "page.more_changes": ["Et {n} autre changement (compté, non listé).",
                              "Et {n} autres changements (comptés, non listés)."],
        "page.files_not_read": "Fichiers modifiés pas lus ({issue}) : la page ne la dit ni prête ni terminée.",
        "page.also": "Aussi : ", "page.works_on": "Travaille sur ",
        "page.inferred_status": " ({status} au registre)",
        "page.inferred_tail": ", déduit des noms et des commits.",
        "page.no_change": "Aucun statut changé dans le registre.",
        "page.records": "Enregistre ", "page.records_tail": " : à vérifier avant la fusion.",
        "page.quote_inline": " « {quote} »",
        "page.also_changes": "Change aussi : {sections} (jamais appliqué ici).",
        "page.not_applied": "Pas appliqué ici : {reason}",
        "page.note_reason": "À noter : {reason}",
        "page.more_tasks": ["Et {n} autre tâche (comptée, non listée).", "Et {n} autres tâches (comptées, non listées)."],
        "page.last_commit": "Dernier commit ", "page.colon": " : ", "page.pushed_tag": " · poussé",
        "page.ended": ["{n} session terminée : tout est dans main et ses tâches sont faites ou abandonnées",
                       "{n} sessions terminées : tout est dans main et leurs tâches sont faites ou abandonnées"],
        "page.no_session": "Aucune session ouverte.", "page.sessions_unreadable": "Sessions illisibles pour l’instant.",
        "page.next": "Prochaines à lancer", "page.next_meta": "dépendances remplies, personne dessus",
        "page.no_next": "Aucune tâche prête sans preneur.", "page.next_unreadable": "Illisibles pour l’instant.",
        "page.events": "Derniers mouvements", "page.main_moves": "Derniers mouvements de main",
        "page.new_tag": "nouveau", "page.approx": " (date approximative)",
        "page.declared_tail": " · déclaré, pas encore dans main",
        "page.no_events": "Aucun mouvement lu.",
        "page.earlier_moves": ["{n} mouvement précédent", "{n} mouvements précédents"],
        "page.progress": "Avancement",
        "page.figures": "Chiffres", "page.figures_unreadable": "illisibles pour l’instant : la page réessaie toute seule",
        "page.meter": "{done} dans main, {extra} dans les sessions, {review} en revue et {progress} en cours, sur "
                      "{scale}",
        "page.meter_tail": ", en comptant celles que les sessions ajoutent",
        "page.done_n": ["{n} faite", "{n} faites"],
        "page.more_declared": ["{n} de plus déclarée", "{n} de plus déclarées"],
        "page.done_in_main": "Faites dans main",
        "page.tasks_done": ["{n} tâche faite", "{n} tâches faites"], "page.out_of": " sur {n}",
        "page.extra_sessions": [", et {n} de plus déclarée dans les sessions",
                                ", et {n} de plus déclarées dans les sessions"],
        "page.v10": " · version 1.0 : {done} sur {active}",
        "page.in_review": "En revue",
        "page.awaits_review": ["attend une revue avant d’être faite", "attendent une revue avant d’être faites"],
        "page.no_review": "aucune tâche n’attend de revue",
        "page.in_progress": "En cours",
        "page.blocked": ["{n} tâche bloquée", "{n} tâches bloquées"],
        "page.in_main_and_sessions": "dans main et les sessions",
        "page.launch": "Lancement 1.0", "page.on_plan": " sur le plan ({date}), selon main",
        "page.no_forecast": "prévision indisponible",
        "page.burnup": "Tâches faites dans le temps",
        "page.burnup_caption": "Chaque marche est un déplacement de main qui a changé le registre. Le pointillé, à "
                               "droite, ajoute ce que les sessions déclarent sans être fusionnées.",
        "page.scope": "Périmètre", "page.scope_10": "Version 1.0", "page.scope_all": "Tout",
        "page.no_history": "Pas encore d’histoire lisible.",
        "page.now_with_sessions": "Maintenant, avec les sessions",
        "page.s_total": "Tâches au total", "page.s_review": "Faites ou en revue", "page.s_done": "Faites",
        "page.review_queue": "file de revue : {n}",
        "page.burnup_aria": "Tâches faites dans le temps, maintenant : faites {done} ; faites ou en revue {review} ; "
                            "tâches au total {scope}. Flèches gauche et droite pour parcourir.",
        "page.declared_dash": "déclaré dans les sessions, pas encore dans main",
        "page.plan_line": "plan (fins de jalons prévues)",
        "page.h_moment": "Moment", "page.h_commit": "Commit", "page.now_row": "maintenant (avec les sessions)",
        "page.milestones": "Jalons",
        "page.milestones_caption": "Une barre par jalon, une couleur par statut. La partie plus claire est déclarée "
                                   "dans une session, pas encore dans main. À droite, la date prévue selon main, "
                                   "quand le registre en a une.",
        "page.no_milestones": "Aucun jalon lisible.",
        "page.declared_in_session": ["déclarée dans une session", "déclarées dans une session"],
        "page.segment_aria": "{milestone} · {status} : {n}",
        "page.not_yet_main": ", {declared}, pas encore dans main",
        "page.lighter": "plus clair : déclaré dans une session",
        "page.h_milestone": "Jalon", "page.h_declared": "Déclarées dans une session",
        "page.h_forecast": "Prévision (main)",
        "page.daily": "Mouvements par jour",
        "page.daily_caption": "Nouveaux lots et passages à En cours, En attente de revue ou Faite chaque jour. Main "
                              "en plein, déclarations des sessions en plus clair. Un lot peut compter plusieurs mouvements.",
        "page.no_moves": "Aucun mouvement lisible.",
        "page.d_new_main": "Nouveaux lots dans main", "page.d_progress_main": "Passages à En cours dans main",
        "page.d_done_main": "Faites dans main", "page.d_review_main": "En revue dans main",
        "page.d_new_live": "Nouveaux lots, déclarés dans une session",
        "page.d_progress_live": "Passages à En cours, déclarés dans une session",
        "page.d_done_live": "Faites, déclarées dans une session",
        "page.d_review_live": "En revue, déclarées dans une session",
        "page.h_day": "Jour",
        "page.sources": "Sources : ",
        "page.branches_cut": ["{n} branche ancienne pas lue.", "{n} branches anciennes pas lues."],
        "page.branches_unread": "Les branches pas encore dans main n’ont pu être listées à temps (une très longue "
                                "histoire, par exemple) ; les arbres de travail s’affichent quand même.",
        "page.history_cut": "L’histoire montre les {n} derniers déplacements de main.",
        "page.history_unread": "L’histoire ancienne de main n’a pu être lue (un clone sans arbres, ou une histoire "
                               "trop longue pour être parcourue à temps).",
        "page.footer": "Servie par flightboard {version}. Elle lit main, chaque arbre de travail et chaque branche "
                       "qui n’est pas encore dans main, en lecture seule ; elle ne lit ni GitHub ni le réseau. Ce "
                       "qu’une session déclare reste une déclaration tant qu’elle n’est pas dans main : la page "
                       "n’approuve rien et n’autorise aucune action.",
        "page.chart_unavailable": "Graphique indisponible.",
    },
}


# Codes shared by the safety readers and collector; source text never provides one of these messages.
TEXT["en"].update({
    "reason.head_unreadable": "HEAD is unreadable: the worktree's branch is unknown",
    "reason.head_elsewhere": "HEAD names a branch the board cannot find",
    "reason.head_symbolic": "a symbolic branch points outside the shared branches: the worktree's commit is unknown",
    "reason.distance_unreadable": "distance to main could not be read",
    "reason.commit_history_unreadable": "the session's commit history could not be read completely",
    "reason.commit_history_cut": "the session's commit history exceeds the reading limit: no ready or ended verdict",
    "reason.held_unknown": "an unreadable worktree may hold this branch",
    "reason.held_worktree": "a worktree holds the local branch with uncommitted, unread or stashed work",
    "reason.held_detached": "a detached worktree on this commit or beyond it holds unfinished work",
    "reason.working_ledger_unreadable": "the current working ledger cannot be read: its last commit is not its current state",
    "reason.duplicate_admin": "several git admin folders name the same worktree",
    "reason.unknown_admin": "an admin folder could not be checked: its worktree is unknown",
    "issue.head_log_unreadable": "the worktree's HEAD reflog cannot be read; work left behind is unknown",
    "issue.assumed_tracked": "an assume-unchanged index entry may hide modified work",
    "issue.skipped_tracked": "a skip-worktree index entry is present on disk and may hide modified work",
    "error.ambiguous_refs": "branch names differ only by spelling Windows may confuse; the reading is refused",
    "error.too_many_refs": "too many branch references to check safely",
    "error.worktrees_unreadable": "the registered worktrees could not all be listed safely",
    "error.too_many_worktrees": "registered worktree limit exceeded; adjust --max-worktrees (1 to 1000) after checking the repository",
    "trap.name": "a name in .git that Windows may read differently ({entry})",
    "left_behind": ("{n} commit left on a detached HEAD: keep the session", "{n} commits left on a detached HEAD: keep the session"),
})
TEXT["fr"].update({
    "reason.head_unreadable": "HEAD illisible : la branche de l'arbre est inconnue",
    "reason.head_elsewhere": "HEAD nomme une branche que le tableau ne trouve pas",
    "reason.head_symbolic": "une branche symbolique mène hors des branches partagées : le commit de l'arbre est inconnu",
    "reason.distance_unreadable": "la distance à main n'a pu être lue",
    "reason.commit_history_unreadable": "l'historique des commits de la session n'a pu être lu complètement",
    "reason.commit_history_cut": "l'historique des commits dépasse la limite de lecture : aucun verdict prête ou terminée",
    "reason.held_unknown": "un arbre illisible pourrait tenir cette branche",
    "reason.held_worktree": "un arbre tient la branche locale avec du travail non commité, pas lu ou mis de côté",
    "reason.held_detached": "un arbre détaché sur ce commit, ou plus loin, tient du travail non terminé",
    "reason.working_ledger_unreadable": "le registre de travail actuel est illisible : son dernier commit ne décrit pas son état actuel",
    "reason.duplicate_admin": "plusieurs dossiers administratifs git nomment le même arbre",
    "reason.unknown_admin": "un dossier administratif n'a pu être vérifié : son arbre est inconnu",
    "issue.head_log_unreadable": "le journal HEAD de l'arbre est illisible ; le travail délaissé est inconnu",
    "issue.assumed_tracked": "une entrée assume-unchanged de l'index peut masquer du travail modifié",
    "issue.skipped_tracked": "une entrée skip-worktree présente sur disque peut masquer du travail modifié",
    "error.ambiguous_refs": "des noms de branche ne diffèrent que par une écriture que Windows peut confondre : lecture refusée",
    "error.too_many_refs": "trop de références de branches pour les vérifier complètement",
    "error.worktrees_unreadable": "la liste des arbres enregistrés n'a pu être vérifiée complètement",
    "error.too_many_worktrees": "limite d'arbres enregistrés dépassée ; ajuste --max-worktrees (1 à 1000) après vérification du dépôt",
    "trap.name": "un nom dans .git que Windows peut lire autrement ({entry})",
    "left_behind": ("{n} commit délaissé sur un HEAD détaché : garde la session", "{n} commits délaissés sur un HEAD détaché : garde la session"),
})
for _locale in LANGS:
    LABELS[_locale]["owner"].update({"qwen": "Qwen", "mimo": "MiMo", "minimax": "MiniMax", "kimi": "Kimi", "agent": "Agent"})
LABELS["en"]["stash"] = {"stashed": "work set aside in the stash: keep the session", "unknown": "stash unreadable: work is unknown", "unmatched": "a stash cannot be tied to a session: keep the sessions"}
LABELS["fr"]["stash"] = {"stashed": "travail mis de côté dans le stash : garde la session", "unknown": "stash illisible : le travail est inconnu", "unmatched": "un stash ne peut être relié à une session : garde les sessions"}
PAGE["en"].update({
    "page.mode_failed": "reading failed", "page.read_failed": "Reading failed · retrying automatically",
    "page.spoken_failed": "Reading failed: session verdicts are unavailable",
    "page.task_unavailable": "This task is not available in the current reading. Its previous state is no longer shown.",
    "page.task_conflict": "Conflicting declarations: no branch status is applied until you resolve the conflict.",
    "page.left_behind": ["{n} commit left on a detached HEAD: keep the session", "{n} commits left on a detached HEAD: keep the session"],
})
PAGE["fr"].update({
    "page.mode_failed": "lecture impossible", "page.read_failed": "Lecture impossible · nouvel essai automatique",
    "page.spoken_failed": "Lecture impossible : les verdicts des sessions sont indisponibles",
    "page.task_unavailable": "Cette tâche est indisponible dans la lecture actuelle. Son état précédent n'est plus montré.",
    "page.task_conflict": "Déclarations en conflit : aucun statut de branche n'est appliqué tant que le conflit n'est pas résolu.",
    "page.left_behind": ["{n} commit délaissé sur un HEAD détaché : garde la session", "{n} commits délaissés sur un HEAD détaché : garde la session"],
})
TEXT["en"]["summary.loading"] = "Reading the repository…"
TEXT["fr"]["summary.loading"] = "Lecture du dépôt en cours…"
LABELS["en"]["source"]["loading"] = "reading"
LABELS["fr"]["source"]["loading"] = "lecture en cours"
PAGE["en"].update({
    "page.loading": "Reading the repository…", "page.mode_loading": "reading",
    "page.loading_detail": "The board will fill automatically when the reading completes. Large repositories may take longer.",
    "page.spoken_loading": "Reading the repository: session states are not available yet",
    "page.initial_failed": "The initial reading has not completed. Retrying automatically.",
})
PAGE["fr"].update({
    "page.loading": "Lecture du dépôt en cours…", "page.mode_loading": "lecture en cours",
    "page.loading_detail": "Le tableau se remplira automatiquement à la fin de la lecture. Un gros dépôt peut demander davantage de temps.",
    "page.spoken_loading": "Lecture du dépôt : les états des sessions ne sont pas encore disponibles",
    "page.initial_failed": "La première lecture n'est pas terminée. Nouvel essai automatique.",
})


def _lang(lang: str) -> str:
    return lang if lang in LANGS else "en"


def _one(lang: str, n: int) -> bool:
    """The language's own plural rule: French says "0 session ouverte", English "0 open sessions"."""
    return n in (0, 1) if _lang(lang) == "fr" else n == 1


def _entry(lang: str, key: str) -> object:
    found = TEXT[_lang(lang)].get(key)
    return found if found is not None else TEXT["en"].get(key, key)


TEXT["en"]["source.working_unknown"] = "Committed ledgers readable; {n} working ledgers not verified."
TEXT["fr"]["source.working_unknown"] = "Registres commités lisibles; {n} registres de travail non vérifiés."

PAGE["en"].update({
    "page.publication": "Git / GitHub and publication",
    "page.publication_local": "Local main", "page.publication_remote": "GitHub observation",
    "page.publication_coverage": "Working-file coverage", "page.publication_pending": "Publication queue",
    "page.publication_queue": "Branches, commits and working folders", "page.publication_alerts": "Publication alerts",
    "page.publication_coverage_details": "Coverage of each registered worktree",
    "page.publication_files_read": "Working files read", "page.publication_files_partial": "Partial file scan",
    "page.publication_files_gone": "Folder missing", "page.publication_ledger_read": "Working ledger read",
    "page.publication_ledger_unknown": "Working ledger not verified",
    "page.publication_source_working_files": "Observed working files",
    "page.publication_note": "Observation only. Shared commits are counted once in the total; branch counts overlap. "
                             "Files need review before committing. An open PR is not approval or product activation.",
    "page.publication_main_equal": "Same commit", "page.publication_main_ahead": "Local main ahead",
    "page.publication_main_behind": "Local main behind", "page.publication_main_diverged": "Main diverged",
    "page.publication_main_unknown": "Comparison incomplete",
    "page.publication_delta": "{ahead} ahead · {behind} behind",
    "page.publication_remote_disabled": "Not checked online", "page.publication_remote_pending": "Check pending",
    "page.publication_remote_fresh": "Checked recently", "page.publication_remote_partial": "Partial observation",
    "page.publication_remote_stale": "Observation expired", "page.publication_remote_error": "Check failed",
    "page.publication_remote_error_detail": "The latest check failed; previous data may remain visible.",
    "page.publication_checked": "Last successful check: {when}",
    "page.publication_covered": "{read} / {total} worktrees read",
    "page.publication_unread": "{n} worktrees with incomplete file coverage",
    "page.publication_commits": "{n} commits absent from the observed heads",
    "page.publication_candidates": "{n} candidate commits; publication unconfirmed",
    "page.publication_incomplete": "An incomplete comparison cannot confirm synchronization.",
    "page.publication_source_github": "Verified GitHub heads",
    "page.publication_source_local_tracking_refs": "Local remote references; GitHub not verified",
    "page.publication_source_local_main": "Compared with local main only",
    "page.publication_source_unknown": "Comparison source unknown",
    "page.publication_files": "{n} uncommitted files", "page.publication_files_unknown": "Working files unknown",
    "page.publication_queue_unpublished": "Not in the observed published heads",
    "page.publication_queue_candidate": "Publication to verify", "page.publication_queue_dirty": "Local work",
    "page.publication_queue_unknown": "Incomplete observation", "page.publication_queue_uncommitted": "Local work",
    "page.publication_pr": "Open PR at the last observation",
    "page.publication_queue_pr_open": "Published; review open",
    "page.publication_alert_publication_review": "Published work has open PRs",
    "page.publication_aliases_more": "{branches} additional branches · {worktrees} additional worktrees",
    "page.publication_queue_more": "{n} additional queue entries omitted from this bounded view.",
    "page.publication_pr_more": "{n} additional PRs omitted from this bounded entry.",
    "page.publication_empty": "No publication gap detected in the observed scope.",
    "page.publication_no_verified_queue": "No confirmed publication entries; coverage remains incomplete.",
    "page.publication_first_seen": "First observed:",
    "page.publication_alert_publication_pending": "Local commits await publication review",
    "page.publication_alert_uncommitted_work": "Uncommitted work",
    "page.publication_alert_worktree_coverage": "Worktree coverage incomplete",
    "page.publication_alert_github_unavailable": "Current GitHub state is not verified",
    "page.publication_alert_main_ahead": "Local main ahead",
    "page.publication_alert_main_behind": "Local main behind",
    "page.publication_alert_main_diverged": "Main has diverged",
    "page.publication_alert_publication_unknown": "Publication comparison incomplete",
    "page.publication_alert_publication_overdue": "Publication gap observed for over 24 hours",
    "page.publication_reason_outside": "Outside allowed roots", "page.publication_reason_partial": "Partial scan",
    "page.publication_reason_unreadable": "Unreadable", "page.publication_reason_gone": "Folder missing",
})
PAGE["fr"].update({
    "page.publication": "Git / GitHub et publication",
    "page.publication_local": "Main local", "page.publication_remote": "Observation GitHub",
    "page.publication_coverage": "Couverture des fichiers de travail", "page.publication_pending": "File de publication",
    "page.publication_queue": "Branches, commits et dossiers de travail", "page.publication_alerts": "Alertes de publication",
    "page.publication_coverage_details": "Couverture de chaque worktree enregistré",
    "page.publication_files_read": "Fichiers de travail lus", "page.publication_files_partial": "Scan des fichiers partiel",
    "page.publication_files_gone": "Dossier absent", "page.publication_ledger_read": "Registre de travail lu",
    "page.publication_ledger_unknown": "Registre de travail non vérifié",
    "page.publication_source_working_files": "Fichiers de travail observés",
    "page.publication_note": "Observation seulement. Les commits partagés sont comptés une fois dans le total; "
                             "les comptes par branche se chevauchent. Les fichiers sont à examiner avant tout commit. "
                             "Une PR ouverte ne vaut ni approbation ni activation du produit.",
    "page.publication_main_equal": "Même commit", "page.publication_main_ahead": "Main local en avance",
    "page.publication_main_behind": "Main local en retard", "page.publication_main_diverged": "Main a divergé",
    "page.publication_main_unknown": "Comparaison incomplète",
    "page.publication_delta": "{ahead} en avance · {behind} en retard",
    "page.publication_remote_disabled": "Non vérifié en ligne", "page.publication_remote_pending": "Vérification en cours",
    "page.publication_remote_fresh": "Vérifié récemment", "page.publication_remote_partial": "Observation partielle",
    "page.publication_remote_stale": "Observation expirée", "page.publication_remote_error": "Vérification échouée",
    "page.publication_remote_error_detail": "La dernière vérification a échoué; les anciennes données peuvent rester affichées.",
    "page.publication_checked": "Dernière vérification réussie : {when}",
    "page.publication_covered": "{read} / {total} worktrees lus",
    "page.publication_unread": "{n} worktrees avec une couverture de fichiers incomplète",
    "page.publication_commits": "{n} commits absents des têtes observées",
    "page.publication_candidates": "{n} commits candidats; publication non confirmée",
    "page.publication_incomplete": "Une comparaison incomplète ne permet pas de confirmer la synchronisation.",
    "page.publication_source_github": "Têtes GitHub vérifiées",
    "page.publication_source_local_tracking_refs": "Références distantes locales; GitHub non vérifié",
    "page.publication_source_local_main": "Comparé à main local seulement",
    "page.publication_source_unknown": "Source de comparaison inconnue",
    "page.publication_files": "{n} fichiers non commités", "page.publication_files_unknown": "Fichiers de travail inconnus",
    "page.publication_queue_unpublished": "Absent des têtes publiées observées",
    "page.publication_queue_candidate": "Publication à vérifier", "page.publication_queue_dirty": "Travail local",
    "page.publication_queue_unknown": "Observation incomplète", "page.publication_queue_uncommitted": "Travail local",
    "page.publication_pr": "PR ouverte à la dernière observation",
    "page.publication_queue_pr_open": "Publié; revue ouverte",
    "page.publication_alert_publication_review": "Du travail publié a des PR ouvertes",
    "page.publication_aliases_more": "{branches} autres branches · {worktrees} autres worktrees",
    "page.publication_queue_more": "{n} autres entrées omises de cette vue bornée.",
    "page.publication_pr_more": "{n} autres PR omises de cette entrée bornée.",
    "page.publication_empty": "Aucun écart de publication détecté dans le périmètre observé.",
    "page.publication_no_verified_queue": "Aucune entrée de publication confirmée; la couverture reste incomplète.",
    "page.publication_first_seen": "Première observation :",
    "page.publication_alert_publication_pending": "Des commits locaux attendent une revue de publication",
    "page.publication_alert_uncommitted_work": "Travail non commité",
    "page.publication_alert_worktree_coverage": "Couverture des worktrees incomplète",
    "page.publication_alert_github_unavailable": "L’état actuel de GitHub n’est pas vérifié",
    "page.publication_alert_main_ahead": "Main local en avance",
    "page.publication_alert_main_behind": "Main local en retard",
    "page.publication_alert_main_diverged": "Main a divergé",
    "page.publication_alert_publication_unknown": "Comparaison de publication incomplète",
    "page.publication_alert_publication_overdue": "Écart de publication observé depuis plus de 24 heures",
    "page.publication_reason_outside": "Hors des racines autorisées", "page.publication_reason_partial": "Scan partiel",
    "page.publication_reason_unreadable": "Illisible", "page.publication_reason_gone": "Dossier absent",
})


def say(lang: str, key: str, **params: object) -> str:
    """A message, its {names} filled."""
    entry = _entry(lang, key)
    template = entry[1] if isinstance(entry, tuple) else entry
    return str(template).format(**params) if params else str(template)


def count(lang: str, key: str, n: int, **params: object) -> str:
    """A message about n things, in its singular or plural form."""
    entry = _entry(lang, key)
    template = entry[0 if _one(lang, n) else 1] if isinstance(entry, tuple) else entry
    return str(template).format(n=n, **params)


def label(lang: str, group: str, code: object, default: str | None = None) -> str:
    """The word for a code (a status, a stage, a kind…); default, or the code itself, when the catalog has none."""
    found = LABELS[_lang(lang)].get(group, {}).get(code) if isinstance(code, str) else None
    return found if found is not None else (default if default is not None else str(code))


def reason(lang: str, code: str, detail: str = "") -> str:
    """Why a session is not read or not applied."""
    return say(lang, "reason." + code, detail=detail) if f"reason.{code}" in TEXT["en"] else code


def issue(lang: str, code: str) -> str:
    """Why a session's modified files were not read."""
    from .gitreads import MAX_STAGED  # read at call time: a test may lower the cap
    return say(lang, "issue." + code, limit=MAX_STAGED) if f"issue.{code}" in TEXT["en"] else code


def publication_reason(lang: str, code: str) -> str:
    """Coverage uses the existing complete reason/issue vocabulary, without exposing missing catalog keys."""
    if f"reason.{code}" in TEXT["en"]:
        return reason(lang, code, "—")
    if f"issue.{code}" in TEXT["en"]:
        return issue(lang, code)
    messages = PAGE[_lang(lang)]
    return str(messages.get("page.publication_reason_" + code, messages["page.publication_reason_unreadable"]))


def trap(lang: str, problem: str) -> str:
    """What in .git stops every git command: a code, "link:<entry>", "many:<folder>" and "config_unreadable:<name>"
    naming the file."""
    from .files import MAX_GIT_FOLDER_ENTRIES
    code, _, entry = problem.partition(":")
    if f"trap.{code}" not in TEXT["en"]:
        return code
    return say(lang, "trap." + code, entry=entry, limit=MAX_GIT_FOLDER_ENTRIES)


def error(lang: str, code: str, detail: str = "") -> str:
    """Why nothing could be read."""
    if code == "git_trap":
        detail = trap(lang, detail)
    return say(lang, "error." + code, detail=detail) if f"error.{code}" in TEXT["en"] else code


def page(lang: str) -> dict:
    """What the page needs to speak the language: its words and the labels of the codes it shows."""
    chosen = _lang(lang)
    return {"lang": chosen, "locale": LOCALES[chosen], "messages": PAGE[chosen], "labels": LABELS[chosen]}
