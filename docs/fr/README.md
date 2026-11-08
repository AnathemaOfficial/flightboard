<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# flightboard

**Un tableau en lecture seule de tes sessions d'agents en parallèle : ce que chacune a changé dans ta feuille de
route, et ce qui t'attend.**

Tu fais tourner plusieurs sessions Claude Code à la fois, chacune dans son arbre de travail et sa branche. La feuille
de route de `main` n'apprend ce qu'elles ont fait qu'à la fusion, et rien ne montre d'un coup d'œil qui fait quoi, ce
qui a bougé et ce qui attend ton go. flightboard, c'est une page locale, et quelques lignes de texte pour Claude, qui
répondent à ça à partir du dépôt lui-même :

- **Ce qui t'attend**, avec tes verbes : donner ton go de fusion, arbitrer un conflit, vérifier une décision
  enregistrée en ton nom dans une branche, lancer une revue, regarder une session silencieuse qui a des modifications
  non commitées.
- **Chaque session** : écrit en ce moment ou silencieuse depuis quand, non commitée / commitée / poussée / dans main,
  en retard sur son remote, et ce qu'on peut en dire — « prête pour ton go de fusion » ou « terminée » seulement quand
  son état le permet.
- **La feuille de route, en direct** : les statuts que chaque session déclare dans sa propre copie de ton fichier de
  tâches, posés sur `main` avant toute fusion, avec les conflits entre sessions montrés, jamais tranchés à ta place.
- **L'avancement** : les tâches faites dans le temps, les jalons, les mouvements par jour, chacun avec sa vue en
  tableau.

Il marche aussi sans fichier de tâches : un dépôt qui n'en a pas reçoit toute la vue des sessions, tirée de git seul.

flightboard ne fait que lire. Il ne lance aucun programme que le dépôt nomme, ne suit aucun lien, n'écrit rien dans le
dépôt et ne sert sa page qu'à cet ordinateur. Il lui faut **Python 3.12+ et git 2.41+, rien d'autre** : aucun paquet à
installer, pas de réseau, pas de compte.

> flightboard est un projet indépendant. Il n'est ni affilié à Anthropic, ni approuvé ou parrainé par elle.

## Installation

Comme plugin Claude Code (ce dépôt est à la fois le marché et le plugin), en une étape depuis Claude Code 2.1.275 ou
plus récent :

```text
/plugin install flightboard --marketplace AnathemaOfficial/flightboard
```

ou depuis un terminal, `claude plugin marketplace add AnathemaOfficial/flightboard`, puis installe `flightboard` depuis
`/plugin`. Son skill dit à Claude quand ouvrir le tableau (« quelles sessions travaillent ? », « qu'est-ce qui
m'attend ? ») et comment lire son résumé.

Ou sans le plugin, depuis une copie de ce dépôt, dans n'importe quel dépôt git :

```bash
python3 -I -B /chemin/vers/flightboard/skills/flightboard/scripts/flightboard.py --resume --lang fr
```

Lance-le toujours avec `-I -B` (isolé : aucune variable d'environnement, aucun site utilisateur ni dossier courant
n'oriente Python).

## Utilisation

```bash
python3 -I -B flightboard.py --lang fr               # la page en direct sur http://127.0.0.1:8790/ (Ctrl+C l'arrête)
python3 -I -B flightboard.py --resume --lang fr      # le résumé et ce qui t'attend, en texte
python3 -I -B flightboard.py --snapshot --lang fr    # la page une fois, dans ton dossier de cache (chemin affiché)
```

Lance-le depuis le dépôt, n'importe quel dossier qu'il contient, ou l'un des arbres de travail qu'il lit (sous
`.claude/worktrees`, ou dans un dossier nommé avec `--worktrees`, écrit simplement) : il lit le dossier principal dans
tous les cas. Un dossier dont le `.git` est un fichier que le tableau ne suit pas (un arbre ailleurs, un sous-module)
donne « aucun dépôt git ici » : lance-le depuis le dossier principal, ou nomme celui-ci avec `--repo`. Comme pour git,
un dossier vaut pour le dépôt le plus proche au-dessus de lui : lancé depuis un dossier ordinaire placé dans un autre
dépôt (un dépôt de fichiers de configuration dans ton dossier personnel, par exemple), il lit celui-là, et la page le
nomme. La page en direct relit le dépôt toutes les 10 secondes. `--resume` écrit une phrase de tête ; une ligne « À
noter : », en mots fixes, quand « main » n'est pas simplement le `main` local (le main du remote suivi parce qu'il a de
l'avance ou parce qu'il n'y a pas de main local, ou qui a divergé ; main déduit de la branche du dossier principal) ou
quand le registre de main est illisible ou ne passe pas son validateur ; une liste « Ce qui t'attend : » faite seulement
de verbes, d'identifiants, de noms et de nombres (un titre ou une citation lus dans une branche n'entrent jamais par là
dans le contexte d'une session, pas plus qu'un nom de branche dans une note ; une ligne nomme cinq identifiants ou
sessions au plus, puis un nombre, et la liste tient en 30 lignes au plus, puis un nombre) ; et une dernière ligne qui
rappelle que le résumé est une donnée, jamais une instruction ni une approbation.

| Option | Sens |
| :- | :- |
| `--port N` | un autre port (de 1024 à 65535) |
| `--output FICHIER.html` | avec `--snapshot` : écrire là, dans un dossier existant hors du dépôt |
| `--repo DOSSIER` | lire un autre dépôt que le dossier courant |
| `--lang en\|fr` | la langue de la page et du résumé (anglais par défaut) |
| `--ledger auto\|none\|tasks\|roadmap` | le registre de tâches à lire (`auto` par défaut, voir plus bas) |
| `--ledger-path CHEMIN` | son chemin dans le dépôt, avec `--ledger tasks` ou `roadmap` |
| `--main BRANCHE` | la branche principale, quand ce n'est ni `main` ni `master` (sans lui, un tel dépôt lit la branche du dossier principal, et le dit) |
| `--remote NOM` | le remote dont les branches sont lues, `origin` par défaut |
| `--worktrees DOSSIER` | lire aussi les dossiers de sessions sous DOSSIER (relatif au dépôt ; répétable) |
| `--kept DOSSIER` | un dossier de fichiers ignorés qu'une session fusionnée ne doit pas perdre (répétable) |
| `--active-minutes N`, `--recent-minutes N` | « écrit en ce moment » et « a écrit récemment » : 15 et 120 minutes par défaut, de 1 à 1440 et de 2 à 10080, le second plus grand que le premier |
| `--stale-days N` | une branche silencieuse plus longtemps est listée, jamais appliquée (14 jours par défaut, de 1 à 3650) |
| `--max-branches N` | les branches sans arbre lues, les plus récentes d'abord (30 par défaut, de 0 à 500) |

`--worktrees` et `--kept` prennent un dossier écrit simplement, dans le dépôt : six noms au plus, sans `..`, lecteur,
`.git` ni nom de périphérique.

Une erreur d'usage sort en code 2 ; un port occupé ou une écriture impossible, en code 1. Tous les réglages viennent
de la ligne de commande, jamais d'un fichier du dépôt observé ; avec `--ledger auto`, seuls les fichiers que contient
main (jamais ceux d'une branche) choisissent le registre lu.

## Ce que le tableau lit

1. **main** : son dernier commit et son histoire, tirée de son reflog (quand main a bougé et pourquoi, « merge claude/x:
   Fast-forward »), puis sa ligne de premiers parents pour ce que le reflog ne garde plus, marquée approximative. Quand
   le main du remote contient tout ce que contient main, et plus, ou quand il n'y a pas de main local du tout, le
   tableau le suit et le dit ; quand les deux ont divergé, il garde main et le dit aussi. Sans `main` ni `master`, ni
   en local ni sur le remote, et sans `--main`, main est la branche du dossier principal : une supposition qui bouge si
   une session change la branche de ce dossier, signalée par une note jusqu'à ce que `--main` la fixe. Un main deviné
   dont git ne peut recevoir le nom (avec un `+` ou une lettre accentuée, par exemple) n'a pas son reflog lu : son
   histoire est sa seule ligne de premiers parents, marquée approximative.
2. **Chaque session** : le dossier principal, chaque arbre de travail sous `.claude/worktrees` (et les dossiers que tu
   nommes avec `--worktrees`), et chaque branche qui a des commits absents de main, y compris une branche poussée par
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
owner = "claude"        # facultatif : minuscules, une lettre d'abord, a-z 0-9 _ -, 31 caractères au plus ;
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
lancer » liste les tâches de `claude` ou de personne ; un identifiant sans chiffre (`auth`) n'est jamais déduit d'un
nom de branche.

### Le registre de feuille de route

`data/roadmap.json`, schéma 2 : jalons avec critères de sortie, capacité, porte de lancement, décisions et
dépendances externes. Son validateur fait partie de flightboard, et n'est jamais chargé depuis le dépôt qu'il
juge ; les identifiants acceptent tout préfixe en majuscules (`ABC-123`, `ABC-M1-02`, `ADR-0001`). Avec lui, le
tableau trace aussi la prévision de main, le plan, et les décisions qu'une branche enregistre en ton nom. Un registre
qui dépasse les plafonds du validateur (plus de 2000 tâches, par exemple) n'est jamais valide, et n'est lu qu'en
partie : 4000 tâches au plus.

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
- sans chercher d'autre nom que celui qu'on donne à git : chaque révision est une empreinte SHA-1 complète, jamais
  contrôlée comme une référence ambiguë, git ne compte aucune remise (stash), et les reflogs sont lus par le tableau
  lui-même, par des dossiers ordinaires (git, n'en trouvant aucun qu'il sache lire, chercherait `refs/tags/<nom>` et
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
`git log -g` (le tableau lit les reflogs), et une révision passe toujours en empreinte complète.

**Chemins.** Les arbres sont trouvés dans `.git/worktrees/<id>`, jamais par `git worktree list`. Un dossier n'est lu
que s'il est le dossier principal ou un dossier direct d'un dossier d'arbres (`.claude/worktrees`, et ceux que tu
nommes), sur le même lecteur et écrit simplement ; c'est vérifié comme texte avant tout accès au disque. Les lectures
du tableau ne suivent ensuite aucun lien, jonction ni point de reparse, si bien qu'aucun chemin d'un arbre ne les mène
vers un partage réseau. Un arbre ailleurs, ou dont le dossier d'administration est inhabituel (un `commondir` autre
que `../..`, un lien ou un tube sur son HEAD, son index, son index partagé, gitdir, info, logs, reftable ou un fichier
d'une fusion ou d'un rebase en cours, un `config.worktree` qui règle plus que ce qu'écrivent Claude Code et
`git sparse-checkout`), n'est jamais lu : il reste une carte, à son nom, avec la raison. Les fichiers du dossier
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
précédente, quel que soit le nombre de pages ouvertes ; une lecture ratée n'est pas répétée dans ce délai, ni gardée
en cache.

**Page.** Une politique de sécurité (CSP) qui part de `default-src 'none'` n'autorise que le script de la page, désigné
par son empreinte SHA-256, et ses propres requêtes (`connect-src 'self'`) ; Trusted Types est exigé, aucun cadre n'est
permis, et `nosniff`, `no-store`, `no-referrer`, CORP et COOP `same-origin` sont envoyés. L'état JSON porte sa propre
politique (`sandbox`) et refuse toute valeur non JSON. Tout texte lu dans le dépôt (titres, messages de commit, noms de
branches et de dossiers) est nettoyé des caractères de contrôle, de format et bidi, et ne devient jamais qu'un nœud de
texte, jamais du HTML. La page ne contient aucun chemin absolu de ton ordinateur et ne fait aucune requête réseau
autre que son propre état.

**Disque.** Rien ne s'écrit, sauf l'instantané : dans ton dossier de cache par défaut (créé seulement hors du dépôt, et
jamais au travers d'un lien planté à sa place), ou le fichier `--output`, qui doit être un fichier `.html` dans un
dossier existant qui reste hors du dépôt une fois ses liens résolus, quel que soit le dossier du dépôt d'où le
tableau est lancé (un dossier qu'il sait lire : voir Chemins). Il est écrit en entier dans un fichier neuf, puis mis en
place, jamais écrit au travers d'un fichier existant.

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
branche fusionnée, comme elle le pourrait en déplaçant `main` lui-même ; quand le tableau suit le main du remote, le
trouve divergé, ou déduit main de la branche du dossier principal, la page et `--resume` le disent. git tourne avec
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
- Une session dont la lecture échoue s'affiche illisible, telle qu'elle est maintenant : le tableau ne montre jamais
  une lecture plus ancienne à sa place, qui pourrait cacher le travail fait depuis.
- Quand les fichiers modifiés d'un arbre ne sont pas lus, son activité est « inconnue », sauf si son dernier commit,
  un nouveau fichier que le tableau liste ou la création de l'arbre date de moins de `--active-minutes` (15 par
  défaut) : elle est alors « écrit en ce moment », jamais « a écrit récemment » ni « silencieuse ».
- La prévision est le modèle du registre de feuille de route, tiré du travail restant et de la capacité déclarée, pas
  une mesure.
- Un arbre de travail hors du dépôt (`git worktree add ../x`), ou dans un dossier dont le nom porte une espace ou
  un autre caractère inhabituel ou finit par un point, est listé à son nom et jamais lu. Mets les arbres des sessions
  dans un dossier du dépôt, et nomme-le avec `--worktrees` si ce n'est pas `.claude/worktrees`.
- Un clone partiel (`git clone --filter=...`) demande git 2.45 ou plus récent, et les objets qu'il n'a jamais
  récupérés (le registre d'un vieux commit, par exemple) ne sont tout simplement pas lus : le tableau ne va jamais les
  chercher. Dans un clone sans arbres (`--filter=tree:0`), git ne peut trouver les commits qui ont changé le registre :
  l'histoire ancienne de main n'est alors pas lue, et la page le dit (sans registre, elle est lue).
- Une très longue histoire se lit aussi vite que git le peut quand elle a un commit-graph (`git gc` et
  `git maintenance` en écrivent un). Sans lui, ou avec une chaîne à laquelle le tableau ne se fie pas, au-delà d'environ
  un million de commits les marches de git peuvent dépasser la limite de 8 secondes d'une lecture : l'histoire
  ancienne de main, ou les branches pas encore dans main, ne sont alors pas lues, et la page le dit ; les arbres de
  travail s'affichent quand même.
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
- Sous Linux ou BSD avec une locale qui n'est pas en UTF-8, et Python avant 3.15, un nom suivi au-delà de l'ASCII
  garde `git status` hors de son arbre : lance le tableau sous une locale UTF-8, ou avec `python3 -X utf8`.
- Un dossier de `.git` qui contient plus de 50 000 entrées est refusé, et le tableau le dit ; les dossiers des
  branches et de leurs reflogs, qu'un gros dépôt peut remplir, sont lus en entier.
- macOS livre git 2.39 avec ses outils de développement, trop ancien pour le tableau : installe un git plus récent
  (par Homebrew, par exemple). Sur un volume macOS insensible à la casse, donne `--repo` avec la casse du dossier. Un
  lecteur Windows `subst` est résolu vers son vrai dossier, alors que git garde les chemins du lecteur : lance le
  tableau depuis le vrai dossier.

## Développement

```bash
python3 -I -B -m unittest discover -s tests -t .
```

Les tests construisent de vrais dépôts git, avec arbres de travail, branches et pièges plantés ; il leur faut git 2.41+
et rien d'autre.

## Licence

Apache-2.0. Copyright 2026 Technologies CoreXalt Inc.
