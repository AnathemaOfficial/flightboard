<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
<p align="center"><img src="../../assets/wordmark.svg" alt="flightboard" width="312"></p>

# flightboard

[English](../../README.md)

**Un tableau local en lecture seule de tes sessions d'agents en parallèle : leurs changements dans Git, leur
avancement déclaré et ce qui attend ton intervention.**

flightboard réunit le dépôt principal, ses arbres de travail autorisés et les branches qui ne sont pas encore dans
`main`. Il montre les fichiers modifiés, les commits, les tâches déclarées et les conflits entre sessions. Avec un
fichier de tâches, il compare les déclarations de chaque session à la feuille de route de `main` avant toute fusion.
Sans fichier de tâches, il fournit la vue des sessions à partir de Git seul.

Il ne lit pas les conversations, les API des fournisseurs ni la CI, et ne fait jamais de `fetch`. Claude Code,
Codex et d'autres outils peuvent suivre le même flux, dès lors qu'ils travaillent dans des branches et arbres Git.
Une session silencieuse peut encore réfléchir, lire ou attendre une réponse : le tableau n'en déduit pas qu'elle a
terminé. Il n'approuve aucune fusion et ne supprime rien.

Il lui faut **Python 3.12+ et Git 2.41+**, sans paquet Python supplémentaire ni compte. Ses lectures contrôlées
n'écrivent rien dans le dépôt ou dans les racines d'arbres autorisées ; le serveur reste sur cet ordinateur. Les
contrôles et leurs limites sont détaillés plus bas.

> flightboard est un projet indépendant ; les noms de produits et modèles décrivent les flux Git qu'il peut observer.

## Ouvrir le tableau avec ton agent

Si le skill Codex ou le plugin Claude Code est déjà installé pour ton utilisateur, tu peux l'utiliser directement
dans tes autres projets. Sinon, suis l'[installation unique](#installation-unique) ci-dessous.

1. Ouvre une session Codex ou Claude Code dans le dépôt que tu veux observer.
2. Demande **« Ouvre Flightboard pour ce dépôt en français »** ou **« Ouvre Flightboard pour ce dépôt en anglais »**.
   Tu peux aussi nommer le dépôt : « Ouvre Flightboard pour le dépôt `/chemin/absolu/vers/mon-projet` en français ».
3. L'agent lance le serveur pour ce dépôt et ouvre l'adresse locale dans le navigateur. Par défaut, c'est
   [http://localhost:8790/](http://localhost:8790/). Utilise l'adresse annoncée par l'agent.

Pour appeler le skill explicitement dans le chat :

```text
Codex : $flightboard Ouvre le tableau de ce dépôt en français.
Claude Code : /flightboard:flightboard Ouvre le tableau de ce dépôt en français.
```

Pour le statut en texte, demande plutôt **« Avec Flightboard, résume ce qui m'attend dans ce dépôt en français »** :
l'agent utilise alors `--resume`, sans serveur web.

**Un serveur lit un seul dépôt et ses arbres autorisés.** Pour observer plusieurs projets à la fois, demande un
serveur par projet : le premier sur `8790`, le deuxième sur `8791`, le troisième sur `8792` (avec `--port` pour choisir).
Par exemple : « Ouvre Flightboard pour `/chemin/absolu/vers/autre-projet` en français sur le port 8791 ».
Le deuxième tableau sera alors à [http://localhost:8791/](http://localhost:8791/) ; le troisième à
[http://localhost:8792/](http://localhost:8792/). Un port occupé demande de choisir un autre port ; le serveur ne
bascule pas automatiquement.

La page se rafraîchit toutes les **10 secondes**. **Fermer l'onglet n'arrête pas le serveur** : tu peux rouvrir son
adresse tant qu'il tourne. Pour l'arrêter, utilise `Ctrl+C` dans le terminal qui l'a lancé. Si l'agent l'a lancé en
arrière-plan, demande-lui d'arrêter le processus Flightboard qu'il a démarré pour ce dépôt et ce port. Après un arrêt
ou un redémarrage de l'ordinateur, redemande l'ouverture du tableau, ou active le démarrage Windows facultatif
ci-dessous.

### Démarrage automatique Windows pour plusieurs dépôts

L'outil facultatif de démarrage mémorise plusieurs tableaux et les lance à **l'ouverture de ta session Windows**.
Ils restent indépendants de Codex et Claude : fermer et rouvrir ces applications ne demande pas de les relancer.
Un superviseur contrôle les processus et les ports locaux environ chaque minute, puis relance les serveurs absents,
sans ouvrir de navigateur. Ces contrôles ne lisent pas Git et ne demandent pas les pages des tableaux.

Installe-le une fois avec un Python 3.12+ fonctionnel et son `pythonw.exe` correspondant. Pour le skill utilisateur
Codex, dans PowerShell :

```powershell
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard_startup.py" install
```

Depuis une copie du dépôt, utilise plutôt `./skills/flightboard/scripts/flightboard_startup.py`, en te plaçant à sa
racine. Pour Claude Code, utilise le même outil dans le dossier `scripts` de son skill installé. L'installation
copie le moteur dans `$env:LOCALAPPDATA/Flightboard/startup/engine`, crée le raccourci `Flightboard.lnk` dans le
dossier Démarrage de ton utilisateur et lance immédiatement le superviseur. Aucun compte administrateur ni
changement à Codex ou Claude n'est nécessaire. Relance `install` depuis une version mise à jour de Flightboard
pour mettre à jour cette copie du moteur.

Pour mémoriser un autre dépôt :

1. Demande à ton agent d'ouvrir son tableau Flightboard, sur un port distinct, avec **`--repo` et le chemin absolu du
   dépôt**. Conserve les options des racines de worktrees nécessaires dans cette commande.
2. Laisse tourner le serveur au moins une minute. Le superviseur mémorise son port, sa langue et ses options de lecture.
3. Après ta prochaine connexion Windows, rouvre son adresse mise en favori. Les nouvelles sessions Git de ce dépôt
   apparaissent selon les règles de worktrees déjà autorisées. Ouvrir seulement un chat dans un nouveau dépôt ne
   mémorise pas de tableau.

La découverte accepte seulement les serveurs en direct lancés avec `-I -B`, un `--repo` absolu explicite, un moteur
et un interpréteur Python autorisés, et un port local appartenant à leur processus. `install` autorise son moteur
source et son interpréteur, ainsi que la copie stable. Pour inclure une autre installation Codex ou Claude, lance
aussi `install` depuis celle-ci, ou ajoute explicitement ses chemins absolus avec les options répétables
`--trust-engine FILE` et `--trust-python FILE` de `install`. Un nouveau chemin de plugin après mise à jour peut
demander cette étape à nouveau. La découverte n'autorise aucune racine de worktrees supplémentaire.

Pour consulter ou modifier la configuration, utilise la copie stable :

```powershell
$startupTool = "$env:LOCALAPPDATA/Flightboard/startup/engine/flightboard_startup.py"
py -3 -I -B $startupTool status
py -3 -I -B $startupTool forget --repo "$env:USERPROFILE/projects/projet-a"
py -3 -I -B $startupTool disable
py -3 -I -B $startupTool enable
```

Remplace le dépôt d'exemple par son chemin absolu. `forget` l'enlève de la liste mémorisée et l'exclut des prochaines
découvertes. `disable` retire le raccourci et demande au superviseur de quitter ; ces deux commandes laissent les
serveurs déjà ouverts en marche. `enable` réactive le démarrage et la supervision. `once` exécute un seul contrôle ;
`run` lance le superviseur au premier plan pour un diagnostic.
Pour suivre à nouveau un dépôt oublié, retire son chemin de `excluded_repos` dans `config.json`, puis rouvre son tableau.

Configuration, état et journaux tournants restent dans `$env:LOCALAPPDATA/Flightboard/startup`. Conserve le Python
choisi. Un lecteur de dépôt indisponible est réessayé ; un port occupé par un autre processus est signalé et laissé
intact. Un serveur encore présent mais sans port d'écoute est signalé, sans être arrêté de force. Cet outil ne
réunit pas les dépôts en un tableau unique.

## Installation unique

Installe Flightboard une fois pour ton utilisateur ; tu n'as pas à le recopier dans chaque dépôt observé.
Les deux intégrations utilisent le même moteur dans `skills/flightboard/scripts` et le même tableau web.
Python et Git sont exécutés localement.

### Codex : le skill utilisateur ou le plugin

**Choisis une seule des deux options**, pour éviter que le même skill soit découvert deux fois.

- **Skill utilisateur** : depuis une copie propre de ce dépôt, copie le dossier `skills/flightboard`, avec son
  `SKILL.md` et son dossier `scripts`, dans `~/.agents/skills/flightboard`. Sous Windows, la destination est
  `$env:USERPROFILE/.agents/skills/flightboard`. Exclus `__pycache__` et les fichiers `*.pyc` de la copie. Ce skill
  utilisateur peut ensuite servir dans tes différents projets ; voir la
  [documentation officielle des skills Codex](https://learn.chatgpt.com/docs/build-skills).
- **Plugin Codex** : depuis un terminal, en remplaçant le chemin par celui de ta copie locale :

  ```bash
  codex plugin marketplace add "/chemin/absolu/vers/flightboard"
  codex plugin add flightboard@flightboard
  ```

  Le marché local pointe vers le plugin commun à `./` ; voir le
  [guide OpenAI de distribution des plugins](https://developers.openai.com/plugins/build/plugins).

Après l'installation, ouvre une session Codex dans le projet à observer et utilise la demande ci-dessus ou
`$flightboard`. Le skill n'est pas lancé à l'ouverture d'un chat.

### Claude Code : le plugin utilisateur

Depuis un terminal, clone ce dépôt si tu ne l'as pas déjà, puis ajoute son marché local et installe le plugin pour
ton utilisateur :

```bash
git clone https://github.com/AnathemaOfficial/flightboard.git "/chemin/absolu/vers/flightboard"
claude plugin marketplace add "/chemin/absolu/vers/flightboard"
claude plugin install flightboard@flightboard --scope user
```

Remplace `/chemin/absolu/vers/flightboard` par le dossier où tu conserves ta copie. Si elle existe déjà, commence par
`claude plugin marketplace add`. L'installation utilisateur rend le plugin disponible dans tes projets ; les
portées d'installation et les commandes sont décrites dans la
[documentation officielle des plugins Claude Code](https://code.claude.com/docs/en/discover-plugins).
Ouvre ensuite une session Claude Code dans le dépôt à observer et utilise la demande ci-dessus ou
`/flightboard:flightboard`.

## Lancer directement depuis un terminal

L'intégration à un agent est facultative. Place-toi dans le dépôt que tu veux observer, puis lance le script de ta
copie de Flightboard. Garde toujours `-I -B` : Python est isolé des variables d'environnement, du site utilisateur
et du dossier courant. Vérifie que l'interpréteur est Python 3.12 ou plus récent.

```bash
python3 -I -B "/chemin/absolu/vers/flightboard/skills/flightboard/scripts/flightboard.py" --repo "$PWD" --lang fr
```

Ouvre [http://localhost:8790/](http://localhost:8790/) dans ton navigateur et garde ce terminal ouvert. `Ctrl+C`
arrête le serveur. Ajoute `--port 8791` pour lancer un autre dépôt sur un autre port.

Sous Windows, si tu as installé le **skill utilisateur Codex**, ces commandes PowerShell utilisent directement sa
copie installée. Lance-les depuis le dépôt à observer :

```powershell
py -3 --version
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard.py" --repo "$PWD" --lang fr
```

Pour obtenir seulement le résumé en texte :

```powershell
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard.py" --repo "$PWD" --resume --lang fr
```

Si `py -3` n'est pas disponible, utilise un `python` fonctionnel en version 3.12 ou plus récente. La présence d'une
commande `python3` sous Windows ne garantit pas qu'elle fonctionne : elle peut ouvrir le Microsoft Store.
Avec la copie du dépôt, ajoute de même `--resume` à la commande pour le texte, ou `--snapshot` pour écrire la page
une fois dans ton dossier de cache (son chemin est affiché). `--lang en` choisit l'anglais pour toutes les sorties.

### Quels arbres de travail sont inclus ?

Le dossier principal et les arbres sous `.claude/worktrees` sont inclus par défaut. Pour inclure un dossier
`.worktrees` dans le dépôt, demande-le explicitement à l'agent ou ajoute `--worktrees .worktrees` à la commande.
Pour les arbres Codex externes sous ta racine utilisateur, demande explicitement cette racine ou ajoute en
PowerShell :

```powershell
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard.py" --repo "$PWD" --lang fr --worktrees-root "$env:USERPROFILE/.codex/worktrees"
```

Cette autorisation ne porte que sur les arbres **enregistrés pour ce dépôt**, un ou deux composants simples sous
la racine. Elle ne lit pas tous les autres projets qui s'y trouvent. Les contrôles de chemin peuvent encore refuser
un arbre ; une carte dont les fichiers n'ont pas été lus reste inconnue pour cette partie de son état.

Pour un gros dépôt, chaque lecture partage un budget de **12 secondes**. Si le tableau signale un dépassement,
essaie `--max-branches 0` : cela ignore les branches sans arbre de travail et conserve les arbres suivis. Ce réglage
ne garantit pas une lecture complète ; un arbre refusé ou illisible le reste, et ne peut pas être déclaré prêt ou
terminé sur la base de fichiers non lus.
Pour un grand nombre d'arbres, `--read-seconds 30` laisse davantage de temps à la lecture complète. Le budget reste
borné entre 12 et 120 secondes, avec 12 par défaut ; chaque commande Git conserve son plafond de 8 secondes.
Le délai du navigateur suit ce budget avec une marge de 8 secondes.

### Choix du dépôt, options et résumé texte

Lance-le depuis le dépôt, n'importe quel dossier qu'il contient, ou l'un des arbres de travail qu'il lit (sous
`.claude/worktrees`, dans un dossier nommé avec `--worktrees`, ou sous une racine externe explicitement autorisée
avec `--worktrees-root`) : il lit le dossier principal dans
tous les cas. Un dossier dont le `.git` est un fichier que le tableau ne suit pas (un arbre ailleurs, un sous-module)
donne « aucun dépôt git ici » : lance-le depuis le dossier principal, ou nomme celui-ci avec `--repo`. Comme pour git,
un dossier vaut pour le dépôt le plus proche au-dessus de lui : lancé depuis un dossier ordinaire placé dans un autre
dépôt (un dépôt de fichiers de configuration dans ton dossier personnel, par exemple), il lit celui-là, et la page le
nomme. La page en direct relit le dépôt toutes les 10 secondes. `--resume` écrit une phrase de tête ; une ligne « À
noter : », en mots fixes, quand main est déduit, a divergé de son remote, ou que le main du remote récupéré a de
l'avance sans avoir été tiré (le main local reste la référence) ; sans main local, le tableau suit celui du remote.
Une note apparaît aussi quand le registre de main est illisible ou ne passe pas son validateur ; une liste
« Ce qui t'attend : » faite seulement
de verbes, d'identifiants, de noms et de nombres (un titre ou une citation lus dans une branche n'entrent jamais par là
dans le contexte d'une session, pas plus qu'un nom de branche dans une note ; une ligne nomme cinq identifiants ou
sessions au plus, puis un nombre, et la liste tient en 30 lignes au plus, puis un nombre) ; et une dernière ligne qui
rappelle que le résumé est une donnée, jamais une instruction ni une approbation.

| Option | Sens |
| :- | :- |
| `--port N` | un autre port (de 1024 à 65535) |
| `--output FICHIER.html` | avec `--snapshot` : écrire là, dans un dossier existant hors du dépôt et de toutes les racines externes autorisées |
| `--repo DOSSIER` | lire un autre dépôt que le dossier courant |
| `--lang en\|fr` | la langue de la page et du résumé (anglais par défaut) |
| `--ledger auto\|none\|tasks\|roadmap` | le registre de tâches à lire (`auto` par défaut, voir plus bas) |
| `--ledger-path CHEMIN` | son chemin dans le dépôt, avec `--ledger tasks` ou `roadmap` |
| `--main BRANCHE` | la branche principale, quand ce n'est ni `main` ni `master` (sans lui, un tel dépôt lit la branche du dossier principal, et le dit) |
| `--remote NOM` | le remote dont les branches sont lues, `origin` par défaut |
| `--worktrees DOSSIER` | lire aussi les dossiers de sessions sous DOSSIER (relatif au dépôt ; répétable) |
| `--worktrees-root DOSSIER` | autoriser explicitement une racine locale absolue pour les arbres externes enregistrés, un ou deux composants simples dessous (répétable) |
| `--kept DOSSIER` | un dossier de fichiers ignorés qu'une session fusionnée ne doit pas perdre (répétable) |
| `--active-minutes N`, `--recent-minutes N` | « écrit en ce moment » et « a écrit récemment » : 15 et 120 minutes par défaut, de 1 à 1440 et de 2 à 10080, le second plus grand que le premier |
| `--stale-days N` | une branche silencieuse plus longtemps est listée, jamais appliquée (14 jours par défaut, de 1 à 3650) |
| `--max-branches N` | les branches sans arbre lues, les plus récentes d'abord (30 par défaut, de 0 à 500) |
| `--read-seconds N` | budget partagé de lecture en secondes (12 par défaut, de 12 à 120) ; chaque commande Git reste plafonnée à 8 secondes |

`--worktrees` et `--kept` prennent un dossier écrit simplement, dans le dépôt : six noms au plus, sans `..`, lecteur,
`.git` ni nom de périphérique.

Les racines externes sont facultatives et explicites : `--worktrees-root "$HOME/.codex/worktrees"` peut par exemple
autoriser des arbres Codex enregistrés sous `<racine>/<hash>/<projet>`. La racine est un dossier local absolu, sans
traversée, chemin UNC ni périphérique ; elle et le chemin jusqu'à chaque arbre doivent être sans lien symbolique,
jonction ni point de réanalyse. Seuls les arbres enregistrés dans le `.git/worktrees` de ce dépôt sont considérés.
Nommer une racine ne parcourt pas les autres dépôts et n'autorise pas tous ses descendants. Les snapshots sont
interdits partout dans chaque racine autorisée, même dans ses autres enfants. Redonne cette option si tu lances le
tableau depuis un arbre externe autorisé.

Une erreur d'usage sort en code 2 ; un port occupé ou une écriture impossible, en code 1. Tous les réglages viennent
de la ligne de commande, jamais d'un fichier du dépôt observé ; avec `--ledger auto`, seuls les fichiers que contient
main (jamais ceux d'une branche) choisissent le registre lu.

## Ce que le tableau lit

1. **main** : son dernier commit et son histoire, tirée de son reflog (quand main a bougé et pourquoi, « merge claude/x:
   Fast-forward »), puis sa ligne de premiers parents pour ce que le reflog ne garde plus, marquée approximative. Quand
   le main du remote récupéré a de l'avance, le main local reste la référence : une note dit que ces commits n'ont pas
   été tirés. Le tableau ne suit le main du remote qu'en l'absence de main local. Il signale aussi une divergence.
   Sans `main` ni `master`, ni
   en local ni sur le remote, et sans `--main`, main est la branche du dossier principal : une supposition qui bouge si
   une session change la branche de ce dossier, signalée par une note jusqu'à ce que `--main` la fixe. Un main deviné
   dont git ne peut recevoir le nom (avec un `+` ou une lettre accentuée, par exemple) n'a pas son reflog lu : son
   histoire est sa seule ligne de premiers parents, marquée approximative.
2. **Chaque session** : le dossier principal, chaque arbre de travail sous `.claude/worktrees` (et les dossiers que tu
   nommes avec `--worktrees`, plus les arbres enregistrés sous les racines explicites `--worktrees-root`), et chaque
   branche qui a des commits absents de main, y compris une branche poussée par
   une session dans le nuage et déjà récupérée. Pour chacune : son registre (la copie de travail pour un arbre,
   changements non commités compris ; le dernier commit pour une branche), sa base commune avec main, son avance et
   son retard, ses fichiers suivis modifiés, ses nouveaux fichiers, et quand ils ont été écrits.
3. **Rien d'autre** : ni GitHub, ni le réseau, ni les transcriptions des sessions, ni les autres dépôts. La CI n'y
   paraît donc pas.

## Les registres

`--ledger auto` (par défaut) prend le premier fichier que main contient parmi `data/roadmap.json` (le registre de
feuille de route), `tasks.toml` et `tasks.json` (un fichier de tâches simple). Sans aucun, ou quand la copie de main
est illisible, le tableau est celui de git seul, et le dit.

### Un fichier de tâches simple

```toml
# tasks.toml (ou la même chose dans tasks.json)
[statuses]              # facultatif : tes mots pour les statuts de flightboard
todo = "planned"
doing = "in_progress"
review = "awaiting_review"

[[milestones]]          # facultatif
id = "M1"
title = "Première version"

[[tasks]]
id = "AUTH-1"           # une lettre ou un chiffre d'abord, puis lettres, chiffres, . _ - ;
                        # une lettre au moins, 40 caractères au plus
title = "Page de connexion"
status = "doing"        # planned, ready, in_progress, awaiting_review, done, blocked, dropped, ou tes mots
owner = "codex"         # facultatif : minuscules, une lettre d'abord, a-z 0-9 _ -, 31 caractères au plus ;
                        # les tâches de "owner" (toi) et de "reviewer" ne bougent jamais depuis une branche
milestone = "M1"        # facultatif
depends_on = ["AUTH-0"] # facultatif : identifiants d'autres tâches de ce fichier
priority = "P1"         # facultatif, de P0 à P9
acceptance = ["Un utilisateur peut se connecter"]  # facultatif

[[tasks]]
id = "AUTH-0"
title = "Table des utilisateurs"
status = "done"
```

Son validateur est petit et structurel : identifiants uniques, statuts qui se rattachent à ceux de flightboard,
dépendances qui existent, aucun cycle. Une branche dont le fichier échoue est listée, jamais appliquée ; de même pour
une branche qui déclare plus de 2000 tâches, lue en partie. Un fichier de tâches inutilisable dit pourquoi sur la
page, et `--resume` dit qu'il l'est ; dans l'histoire de main, une version sans une seule tâche utilisable (tous les
statuts inconnus, par exemple) est sautée, jamais lue comme si toutes les tâches avaient disparu. « Prochaines à
lancer » liste les tâches de tout agent dont le nom est sûr, ou de personne ; `owner` et `reviewer` sont des rôles
humains exclus de cette liste. Un identifiant sans chiffre (`auth`) n'est jamais déduit d'un
nom de branche.

### Le registre de feuille de route

`data/roadmap.json`, schéma 2 : jalons avec critères de sortie, capacité, porte de lancement, décisions et
dépendances externes. Son validateur fait partie de flightboard, et n'est jamais chargé depuis le dépôt qu'il
juge ; les identifiants acceptent tout préfixe en majuscules (`ABC-123`, `ABC-M1-02`, `ADR-0001`). Avec lui, le
tableau trace aussi la prévision de main, le plan, et les décisions qu'une branche enregistre en ton nom. Un registre
qui dépasse les plafonds du validateur (plus de 2000 tâches, par exemple) n'est jamais valide, et n'est lu qu'en
partie : 4000 tâches au plus.

Les propriétaires agents utilisent les mêmes noms en minuscules que le fichier de tâches simple : `claude`,
`codex`, `qwen`, `mimo`, `minimax`, `kimi`, ou un autre nom sûr. Leur comportement est identique ; `owner` et
`reviewer` restent des rôles humains. Dans `capacity`, `agent_sessions_per_week` est la capacité commune de tous les
agents de code. L'ancienne clé `claude_sessions_per_week` reste acceptée ; si les deux sont présentes, elles doivent
contenir le même entier positif. `review_slots_per_week` et `owner_hours_per_week` gardent le relecteur humain et le
propriétaire séparés. Renommer un agent ne change pas la prévision. Les dépendances sont vérifiées en entier,
indépendamment des limites d'affichage.

### La vue en direct

- Les changements d'une session, c'est son registre comparé à **sa base commune avec main**, jamais à main lui-même :
  une branche en retard ne fait reculer aucune tâche.
- Le registre d'une branche est une déclaration d'agent, pas un fait. La vue en direct ajoute à main seulement les
  changements de statut et les tâches nouvelles, seulement d'un registre que son validateur accepte, et jamais pour
  une tâche à toi ou au relecteur, qui ne bouge que dans main. Décisions, jalons, capacité et porte de lancement ne
  sont jamais appliqués : la page les montre, à vérifier.
- Un changement s'applique quand main a encore le statut de départ de la session, ou a déjà le même. Sinon c'est un
  conflit, et le statut de main reste, comme quand deux sessions changent une tâche différemment. Un même identifiant
  ajouté par deux sessions avec un autre contenu est signalé, jamais fusionné.
- Les chiffres de main restent ceux de main ; ce que déclarent les sessions est compté à part.
- Ce que déclarent les branches ne fait jamais grossir la page sans limite : une carte nomme 40 tâches, puis un
  nombre ; la page garde le détail de 500 tâches au plus ; ce qui t'attend tient en 30 éléments, puis un nombre.

### Ce qu'on peut dire d'une session

- **Prête pour ton go de fusion** : commitée, silencieuse depuis `--active-minutes` (15 par défaut), ses fichiers
  modifiés lus, rien de refusé ; avec un registre, chaque tâche qu'elle porte en revue ou faite dans son propre
  registre ; sans registre, une branche locale poussée telle quelle (une branche qui n'existe que sur le remote est
  poussée par nature, ce qui ne dit rien).
- **Terminée** : tout dans main, ses fichiers lus, et chaque tâche qu'elle portait faite ou abandonnée dans main.
  Sans registre, rien ne dit qu'une session a fini : aucune n'est jamais dite terminée, car silencieuse et fusionnée
  peut encore vouloir dire « attend une revue ».
- Une session dont les fichiers modifiés ne sont pas lus n'est jamais dite prête ni terminée, et `--resume` le dit.
- Du travail dans le stash, des commits détachés qu'aucune branche ne garde, un HEAD illisible ou une chaîne de
  références symboliques incertaine empêchent aussi de conclure prête ou terminée. Un stash dont l'attribution est
  incertaine retient les cartes concernées ; une distance Git inconnue s'affiche inconnue, jamais nulle. Ces contrôles
  ne font pas du tableau un outil de nettoyage.
- « Dans main » veut dire atteignable depuis main. Une branche fusionnée par squash ou par rebase (un flux de pull
  request courant) garde ses propres commits : elle reste listée jusqu'à ce que tu la supprimes. Tenue par un arbre de
  travail, elle peut être dite « prête pour ton go de fusion » tout ce temps ; sans arbre, elle perd ce statut une fois
  silencieuse au-delà du délai (`--stale-days`), et n'est plus que listée. Le tableau ne compare aucun patch.

## Sécurité

flightboard lit un dépôt où écrivent des agents. Il y traite tout comme une donnée, et suppose qu'une session pourrait
tendre un piège au prochain programme qui lit son dossier.

**Git.** Avant toute commande git sur le dépôt, flightboard regarde son `.git` par `lstat` et de petites lectures,
jamais au travers d'un lien. git suit à chaque commande un lien planté sur l'une de ses entrées (configuration, index,
info, objects, refs, logs, shallow, reftable, le fichier partagé d'un index scindé, l'état d'une fusion, d'un rebase
ou d'une bissection…, et les entrées directes de `refs`, `refs/heads`, des références du remote, de `objects`,
`objects/info`, `objects/pack`, `logs/refs`, des reflogs des branches et des dossiers de rebase et de sequencer), une
inclusion de configuration (`include`, `includeIf`), un `core.worktree`, un fichier `commondir` et un emprunt d'objets
(`objects/info/alternates`), et il attend sur un tube planté là où il attend un fichier : s'il en trouve un,
flightboard ne lance aucune commande git sur le dépôt et dit pourquoi. Les petits fichiers que le tableau lit lui-même
(un HEAD, un `gitdir`, un reflog) ne sont lus que s'ils sont des fichiers ordinaires, sans jamais attendre ni passer
par un lien. Il ne lit aucun dépôt à magasin de références reftable (son `tables.list` nomme les fichiers que git
ouvre) ni à magasin d'objets SHA-256 (l'arbre vide que nomme le tableau y serait un nom de référence qu'une session
pourrait écrire), et le dit. La configuration est lue par le git installé lui-même, sur une copie de ses octets passée
à son entrée standard (`git config --file - --no-includes`, sans configuration système ni globale ni dépôt autour) :
aucune écriture que git accepte (une marque d'ordre des octets, plusieurs en-têtes sur une ligne, une valeur continuée
à la ligne suivante, un retour chariot seul) n'en cache un ; une configuration que git lui-même ne saurait lire arrête
aussi le tableau. Puis une liste fixe de lectures, chacune avec un `--git-dir` explicite, s'exécute :

- avec les attributs de l'arbre vide de git (`--attr-source`), sans fichier d'attributs, d'exclusions ni de mailmap
  de l'utilisateur ni fichier d'ordre de diff (un chemin y pourrait nommer un partage réseau), donc sans textconv ni
  LFS ;
- sans le multi-pack-index (un nom de pack y est un nom de fichier que git ouvre tel quel, `..` compris), avec le
  commit-graph seulement quand chaque ligne de sa chaîne est une simple empreinte d'objet (git ouvre aussi chaque ligne
  comme un nom de fichier), et sans suivre de renommage dans une marche de l'histoire ;
- avec des empreintes SHA-1 complètes comme arguments de révision, sans contrôle de référence ambiguë. Les cibles
  symboliques sont analysées comme données et vérifiées dans la liste partagée des références ; git ne compte aucun
  stash, et les reflogs (stash et déplacements de HEAD détaché compris) sont lus par le tableau lui-même, par des
  dossiers ordinaires (git, n'en trouvant aucun qu'il sache lire, chercherait `refs/tags/<nom>` et
  ses pareils), si bien que git ne cherche jamais `.git/<empreinte>` ni `refs/tags/<nom>` ;
- avec l'extraction partielle (sparse checkout) coupée pour les commandes qui lisent des noms d'index que le tableau
  n'a pas encore contrôlés (`git ls-files`, `git check-ignore`) : git chercherait sinon sur le disque chaque nom
  « skip-worktree » de l'index, où qu'il pointe, puisqu'il n'en contrôle aucun. `git status`, lancé seulement une fois
  chaque nom passé par les contrôles ci-dessous, garde l'extraction partielle du dépôt : un fichier qu'une session a
  écrit hors de ses motifs compte comme modifié, comme git le compte. git ne change jamais un index complet en index
  partiel (`index.sparse`) et lit chaque index avec un seul fil (`index.threads`), entrée après entrée, comme le
  tableau le parcourt. Un index que git prendrait pour un index partiel (une seule entrée qui est un dossier suffit)
  n'est jamais donné à git, qui écrit dans `.git/objects` pour en lire un, ni un index scindé, dont git touche la
  partie partagée à chaque lecture : les fichiers modifiés et nouveaux de cet arbre ne sont pas lus ;
- sans jamais aller chercher d'objet (`GIT_NO_LAZY_FETCH`) : le remote d'un clone partiel n'est jamais sollicité pour
  un objet manquant, donc aucun upload-pack, ssh ni autre programme que nomme sa configuration ne démarre. Un git plus
  ancien que 2.45 ignore ce réglage : avec lui, un clone partiel (un remote promisor, un remote avec un filtre de clone
  partiel, ou `extensions.partialClone`) n'est pas lu du tout, et le tableau dit pourquoi ;
- avec chaque pilote de filtre que la configuration définit neutralisé pour toute la lecture
  (`-c filter.<nom>.clean=` et ses pareils), quels que soient les attributs qui le nomment entre-temps. Un nom de
  pilote inhabituel, plus de 40 pilotes, ou un `.git/info/attributes` rempli arrêtent la lecture des fichiers
  modifiés, et le tableau le dit ;
- sans jamais parcourir le contenu non suivi : un fichier `.git` planté dans un nouveau dossier pourrait sinon envoyer
  git sur un partage réseau ;
- après un contrôle de chaque chemin que l'index suit, fait sur le disque sans jamais regarder au travers d'un lien :
  un fichier suivi devenu dossier ou lien, un sous-module qui contient un `.git` ou remplacé par un lien, un lien à la
  place d'un dossier suivi, un nom suivi qui sort de l'arbre ou qui n'est pas en UTF-8 (le tableau chercherait un
  autre chemin que git), un chemin suivi de 260 caractères ou plus sous Windows, ou plus de 50 000 fichiers suivis
  gardent `git status` hors de cet arbre ;
- sous Windows, avec le vrai git plutôt qu'un de ses lanceurs (`Git\cmd`, `Git\bin`), pour que le délai de 8
  secondes arrête git lui-même (tuer un lanceur laisserait son git tourner), et avec `core.longpaths` coupé : git
  n'atteint alors aucun chemin de 260 caractères ou plus, que les contrôles du tableau pourraient ne pas voir (le
  réglage par défaut de Windows) et prendraient pour un fichier supprimé ;
- sans verrou optionnel (une lecture ne réécrit jamais l'index d'une session), sans objet de remplacement ni greffe (ni
  une entrée de `refs/replace`, quoi que dise `core.useReplaceRefs`, ni une ligne de `info/grafts` ne change ce que
  contiennent les commits de main), sans fsmonitor ni vérification de signature, avec git trouvé par un chemin absolu et
  un environnement réduit à une courte liste : aucune clé d'API n'atteint git ni ce qu'il lancerait.

Aucune commande `git diff` (`git status` compare les fichiers de la même façon, avec les réglages ci-dessus), aucun
`git log -g` (le tableau lit les reflogs) ; les arguments de révision donnés à git sont des empreintes SHA-1 complètes.

**Chemins.** Les arbres sont trouvés dans `.git/worktrees/<id>`, jamais par `git worktree list`. Un dossier n'est lu
que s'il est le dossier principal, un enfant direct d'un dossier d'arbres interne (`.claude/worktrees`, et ceux que tu
nommes), ou un ou deux composants simples sous une racine locale externe explicitement autorisée. Un arbre externe
doit être enregistré dans ce dépôt et son marqueur doit correspondre à son dossier d'administration. Ces frontières
sont vérifiées avant lecture du contenu. Les lectures
du tableau ne suivent ensuite aucun lien, jonction ni point de reparse, si bien qu'aucun chemin d'un arbre ne les mène
vers un partage réseau. Un arbre ailleurs, ou dont le dossier d'administration est inhabituel (un `commondir` autre
que `../..`, un lien ou un tube sur son HEAD, son index, son index partagé, gitdir, info, logs, reftable ou un fichier
d'une fusion ou d'un rebase en cours, un `config.worktree` qui règle plus que les booléens autorisés ou le marqueur
exact `codex.localenvironmentconfigpath = __none__`), n'est jamais lu : il reste une carte, à son nom, avec la raison.
Le marqueur Codex est une métadonnée, jamais un chemin ouvert ; les autres valeurs de cette clé restent refusées.
Les fichiers du dossier
d'administration sont lus comme git les lit (un `commondir` de `../..` suivi d'une seule fin de ligne, par exemple),
pour que le tableau et git ne désignent jamais deux dossiers différents. Lancé depuis un dossier dont le `.git` n'est
pas un vrai dossier git à lui (un arbre que le tableau ne lit pas, un sous-module, un dossier dont le dépôt git est
rangé ailleurs, un `.git` inhabituel ou vide), le tableau ne lit rien et ne regarde jamais ce que nomme un fichier
`.git` ; il ne peut pas savoir où ce dépôt s'arrête, alors `--output` y est refusé, et l'instantané, une page
d'erreur, ne peut aller que dans le dossier de cache.

**Serveur.** Il n'écoute que `127.0.0.1`, et `[::1]` au même port (le navigateur essaie `::1` en premier pour
`localhost` : aucun autre programme ne peut y répondre à sa place), et contrôle chaque requête avant tout travail. Il
refuse un `Host` autre que `127.0.0.1:<port>` ou `localhost:<port>` (rebinding DNS), une `Origin` d'ailleurs (`null`
compris), un `Sec-Fetch-Site` same-site ou cross-site, l'état chargé comme script, image ou cadre (`Sec-Fetch-Dest`),
toute méthode autre que `GET` et `HEAD`, et tout chemin autre que `/` et `/state.json`. Une requête refusée ne lit
jamais le dépôt. Le dépôt est lu au plus une fois toutes les 5 secondes, comptées depuis la fin de la lecture
précédente, quel que soit le nombre de pages ouvertes ; une lecture ratée n'est pas répétée dans ce délai. Une lecture
partage un budget de 12 secondes par défaut entre ses opérations contrôlées (`--read-seconds` accepte 12 à 120),
avec un plafond de 8 secondes par commande git. Le navigateur interrompt une requête d'état après ce budget plus
8 secondes (20 par défaut) ; le délai socket de 10 secondes du serveur borne
séparément la réception HTTP. Une lecture complète ratée affiche une erreur explicite et retire les anciens verdicts
des sessions jusqu'au prochain succès. Une fiche de tâche ouverte est actualisée ou marquée indisponible.

**Page.** Une politique de sécurité (CSP) qui part de `default-src 'none'` n'autorise que le script de la page, désigné
par son empreinte SHA-256, et ses propres requêtes (`connect-src 'self'`) ; Trusted Types est exigé, aucun cadre n'est
permis, et `nosniff`, `no-store`, `no-referrer`, CORP et COOP `same-origin` sont envoyés. L'état JSON porte sa propre
politique (`sandbox`) et refuse toute valeur non JSON. Tout texte lu dans le dépôt (titres, messages de commit, noms de
branches et de dossiers) est nettoyé des caractères de contrôle, de format et bidi, et ne devient jamais qu'un nœud de
texte, jamais du HTML. La page ne contient aucun chemin absolu de ton ordinateur et ne fait aucune requête réseau
autre que son propre état.

**Disque.** Les modes du tableau n'écrivent que l'instantané : dans ton dossier de cache par défaut (créé seulement hors du dépôt, et
jamais au travers d'un lien planté à sa place), ou le fichier `--output`, qui doit être un fichier `.html` dans un
dossier existant qui reste hors du dépôt et de toutes les racines externes autorisées une fois ses liens résolus,
quel que soit le dossier du dépôt d'où le
tableau est lancé (un dossier qu'il sait lire : voir Chemins). Il est écrit en entier dans un fichier neuf, puis mis en
place, jamais écrit au travers d'un fichier existant.
L'outil facultatif de démarrage Windows conserve aussi son moteur copié, sa configuration, son état et ses journaux
tournants dans les données locales d'application de ton utilisateur, et gère son raccourci dans ton dossier
Démarrage. Il n'écrit pas dans un dépôt observé et n'autorise aucune racine de worktrees supplémentaire.

**Portée.** Le tableau n'approuve rien et n'autorise aucune action : il lit.

**Limites, dites telles quelles.** Une session qui peut écrire dans `.git` peut y planter un piège plus fin que ceux que
le tableau regarde (un lien sur un fichier d'objets, par exemple), ou faire la course avec une lecture : réécrire un
fichier que le tableau vient de contrôler (un nouveau pilote de filtre et `info/attributes`, une chaîne de
commit-graph) avant que git le lise. git le suivrait alors, partage réseau compris. Tout git lancé dans ce dépôt — par
Claude Code, un éditeur ou toi — y est exposé de la même façon : le tableau n'élargit pas cette exposition, il la
réduit. Les liens sur les entrées de `.git` nommées plus haut sont refusés, mais tous les fichiers de `.git` ne sont
pas regardés : un lien sur un autre fichier que git ouvre par son nom reste possible, que ce soit un objet isolé, une
référence ou un fichier de reflog dans un dossier de branches, ou toute entrée de `.git` ou du dossier
d'administration d'un arbre que nomme une référence symbolique (`ref: <nom>`) ou une ligne de reflog (dans un arbre
détaché, `git status` cherche le nom vers lequel son dernier checkout s'est déplacé) ; un tube à cet endroit fait
attendre git jusqu'à la limite de 8 secondes, et la lecture échoue. Le tableau croit ce que disent
les références, celles des remotes comprises : une session qui peut écrire des références peut faire paraître sa
branche fusionnée, comme elle le pourrait en déplaçant `main` lui-même ; la page et `--resume` signalent un remote
récupéré en avance sur main local, une référence présente seulement sur le remote, une divergence ou une supposition
depuis la branche du dossier principal. git tourne avec
l'arbre qu'il lit pour dossier courant (Windows y cherche des bibliothèques en dernier). Une extension du navigateur
qui a accès au site peut lire la page. Pour signaler une vulnérabilité, voir [SECURITY.md](../../SECURITY.md).

## Limites

- « Écrit en ce moment » veut dire qu'un fichier ou un commit vient d'être écrit. Une session qui réfléchit, lit,
  attend la CI ou ta réponse paraît silencieuse.
- Une session qui ne marque sa tâche « en cours » qu'au commit reste « prévue » dans la vue en direct jusque-là ; le
  tableau déduit alors la tâche du nom de la branche et de ses commits, sans la compter.
- Une branche poussée par une session dans le nuage n'apparaît qu'une fois récupérée : le tableau ne fait jamais de
  `fetch`. Quand une session a continué ailleurs alors que son arbre local est resté en arrière, le tableau lit l'arbre
  local et le dit en retard sur son remote.
- Un nouveau dossier est regardé sur trois niveaux. Ignoré plus profond, ou s'il contient lui-même un dépôt imbriqué,
  il compte comme un nouveau fichier : l'erreur va du côté prudent, et la session n'est jamais dite terminée pour
  autant. Un dossier qu'on ne peut lister (ses permissions, par exemple) n'est jamais pris pour un dossier vide : les
  nouveaux fichiers de cet arbre ne sont pas lus.
- Une session dont la lecture échoue dans un snapshot réussi est marquée illisible. Si toute la lecture en direct
  échoue, la page retire les anciens verdicts des sessions et annonce l'erreur. Les nouveaux essais ne transforment
  jamais les anciennes données en preuve qu'une session a terminé.
- Quand les fichiers modifiés d'un arbre ne sont pas lus, son activité est « inconnue », sauf si son dernier commit,
  un nouveau fichier que le tableau liste ou la création de l'arbre date de moins de `--active-minutes` (15 par
  défaut) : elle est alors « écrit en ce moment », jamais « a écrit récemment » ni « silencieuse ».
- La prévision est le modèle du registre de feuille de route, tiré du travail restant et de la capacité déclarée, pas
  une mesure.
- Un arbre externe est listé mais ses fichiers ne sont pas lus tant que sa racine locale n'est pas explicitement
  autorisée avec `--worktrees-root` et que son chemin ne passe pas les contrôles d'enregistrement, de profondeur et
  de dossiers ordinaires. Ses un ou deux composants sous la racine doivent être des noms simples : espaces,
  caractères inhabituels et points finaux y sont refusés.
- Un clone partiel (`git clone --filter=...`) demande git 2.45 ou plus récent, et les objets qu'il n'a jamais
  récupérés (le registre d'un vieux commit, par exemple) ne sont tout simplement pas lus : le tableau ne va jamais les
  chercher. Dans un clone sans arbres (`--filter=tree:0`), git ne peut trouver les commits qui ont changé le registre :
  l'histoire ancienne de main n'est alors pas lue, et la page le dit (sans registre, elle est lue).
- Une très longue histoire se lit aussi vite que git le peut quand elle a un commit-graph (`git gc` et
  `git maintenance` en écrivent un). Sans lui, ou avec une chaîne à laquelle le tableau ne se fie pas, une marche peut
  dépasser le plafond de 8 secondes par commande. L'histoire ou la liste de branches concernée est alors non lue ;
  épuiser le budget commun de lecture (12 secondes par défaut) peut faire échouer tout le rafraîchissement. La page signale des
  preuves incomplètes ou périmées, sans en déduire un état propre.
- Un arbre à index partiel (`git sparse-checkout set --sparse-index`, `index.sparse`) ou à index scindé
  (`core.splitIndex`, `git update-index --split-index`) a ses fichiers modifiés et nouveaux non lus : git écrit dans
  `.git/objects` pour lire le premier, et touche la partie partagée du second. Une extraction partielle sans index
  partiel se lit comme git la lit. Un index jusqu'à 64 Mo aussi ; au-delà, ses fichiers modifiés et nouveaux ne sont
  pas lus non plus.
- Une configuration git de plus de 1 Mo, ou que git liste au-delà de 4 Mo (git répète le nom d'une section pour chacune
  de ses clés : un long nom de sous-section sur beaucoup de clés se liste bien plus gros qu'il n'est), n'est pas
  pesée : le dépôt n'est pas lu, et la page dit sa configuration illisible.
- Sous Windows, un arbre qui suit un chemin de 260 caractères ou plus (comptés comme Windows les compte : un caractère
  hors du plan de base, un émoji par exemple, compte double), ou un nom dont une partie finit par un point ou une
  espace ou porte le nom d'un périphérique (`nul`, `con`, `com1`…), a ses fichiers modifiés non lus, et un dépôt dont
  les chemins propres atteignent cette longueur ne peut être lu : le tableau lance git avec `core.longpaths` coupé.
- Un reflog est lu sur ses 2 derniers Mo : les déplacements plus anciens de main viennent alors de sa ligne de premiers
  parents, marqués approximatifs.
- L'attribution des stashes et l'histoire détachée sont prudentes et bornées. Des preuves illisibles ou tronquées
  peuvent retenir des sessions ; un vieux commit détaché absent des reflogs conservés peut ne plus être détectable.
  Vérifie Git directement avant de supprimer un arbre ou une branche.
- Une coupure dans le statut suivi, l'énumération des nouveaux fichiers ou une lecture expirée est une preuve
  incomplète, pas un arbre propre. Les fichiers non lus et les états inconnus empêchent de conclure prête/terminée ;
  les dates d'activité, identifiants déduits et courtes listes de commits restent des indices, pas une conversation
  ni une preuve d'activité chez un fournisseur.
- Sous Linux ou BSD avec une locale qui n'est pas en UTF-8, et Python avant 3.15, un nom suivi au-delà de l'ASCII
  garde `git status` hors de son arbre : lance le tableau sous une locale UTF-8, ou avec `python3 -X utf8`.
- Un dossier de `.git` qui contient plus de 50 000 entrées est refusé, et le tableau le dit ; les dossiers des
  branches et de leurs reflogs, qu'un gros dépôt peut remplir, sont lus en entier.
- macOS livre git 2.39 avec ses outils de développement, trop ancien pour le tableau : installe un git plus récent
  (par Homebrew, par exemple). Sur un volume macOS insensible à la casse, donne `--repo` avec la casse du dossier. Un
  lecteur Windows `subst` est résolu vers son vrai dossier, alors que git garde les chemins du lecteur : lance le
  tableau depuis le vrai dossier.

## Développement

L'attribution d'une session lit jusqu'à 1 000 commits et 4 000 caractères par sujet ; la carte n'affiche que huit
commits. Une histoire illisible, incomplète ou un sujet dépassant ce plafond bloque les verdicts prête/terminée.
Les journaux HEAD et stash doivent être lus intégralement dans les limites de 1 000 entrées et 2 Mo : au-delà,
le travail est inconnu et n'est jamais considéré comme entièrement commité.

```bash
python3 -I -B -m unittest discover -s tests -t .
```

Les tests construisent de vrais dépôts git, avec arbres de travail, branches et pièges plantés ; il leur faut git 2.41+
et rien d'autre.
Ils utilisent des fixtures locales ; ils ne certifient pas des sessions réelles Claude, Codex ou d'autres
fournisseurs, ni le lancement automatique à l'ouverture d'un chat desktop.

## Licence

Apache-2.0. Copyright 2026 Technologies CoreXalt Inc.
