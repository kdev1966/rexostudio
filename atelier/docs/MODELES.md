# Fabriquer les animations de Rexo Studio (atelier)

Ce guide s'adresse aux techniciens de l'atelier, qui préparent les décors 3D (Blender),
les matériaux (MaterialCraft, TextureCraft) et les titres (EffectCraft). Le photographe
ne voit rien de tout cela. Il reçoit une **bibliothèque d'animations** toutes prêtes,
livrée à part, et Rexo Studio la remplit tout seul pour chaque couple : il y place les
photos détourées des mariés, les noms et la date.

Pour chaque modèle, le guide donne :
- ce que vous fabriquez ;
- les noms que Rexo Studio attend ;
- ce qu'il ne faut pas faire ;
- comment le tester.

---

## 1. Comment Rexo Studio utilise vos modèles

```
ATELIER (techniciens)
Votre décor .blend  ──►  python3 -m atelier animation …  ──►  paquet d'animation
                         (décor + vol de la caméra drone, SANS les mariés)
                                   │  python3 -m atelier livrer  ──►  zip
─────────────────────────────────────────────────────────────────────────────
REXO STUDIO (photographe)          │  scripts/installer_animations.py
Photo des mariés    ──►  Rexo détoure les mariés
                                   │
                          EffectCraft place les photos dans les emplacements
                          que vous avez prévus, ajoute votre titre, rend la vidéo
                                   │
                          FilmCraft : le clip arrive dans le projet de l'événement
```

Votre décor ne contient donc **jamais** de photo : il contient des **emplacements**,
des formes nommées que Rexo Studio remplace par les vraies photos. L'animation
générique d'un décor est calculée une seule fois par mouvement de caméra. Si vous
modifiez le `.blend`, elle est refaite automatiquement.

---

## 2. Le décor 3D (Blender)

### Version et format

- **Blender 3.6 LTS** uniquement. Blender 4 ne démarre pas sur l'iMac de production.
- Moteur de rendu : **EEVEE**.
- Unités : le **mètre**.
- Le sol est à la hauteur **z = 0**.
- Les mariés se tiennent au **centre de la scène**, à l'origine (0, 0, 0). Ils regardent
  vers **−Y** : la caméra arrive par l'avant, depuis le côté des Y négatifs.
- Enregistrez le fichier sous `scenes/<nom>.blend` dans l'atelier, en minuscules et
  sans espace, par exemple `salle_des_fetes.blend`. Le titre affiché dans Rexo Studio
  se donne au rendu (`--titre`).
- **Emballez les textures dans le fichier** : *File ▸ External Data ▸ Pack Resources*.
  Le fichier doit fonctionner seul, sur une autre machine.

### Les objets obligatoires

| Nom exact | Ce que c'est | Règles |
|---|---|---|
| `DRONE` | La caméra de la scène (*Scene ▸ Camera*) | Contrainte **Track To** vers `VISE` (axe *-Z*, haut *Y*). Focale conseillée : 35 mm. **Pas d'animation** : Rexo Studio ajoute lui-même les mouvements. |
| `VISE` | Un objet vide (*Empty*) | Le point que la caméra regarde, en général le buste des mariés, vers (0, 0, 1,25). |
| Au moins un emplacement `PHOTO_…` | Voir ci-dessous | Sans emplacement, Rexo Studio refuse le modèle. |

### Les emplacements de photos

Les deux types d'emplacements se fabriquent de la même façon :
- un **plan maillé** (*Mesh*) dressé à la verticale, dans le plan X-Z de l'objet ;
- la face visible tournée vers **−Y** ;
- la **taille du plan** égale à la place réservée à la photo, en mètres.

**`PHOTO_DEBOUT_<NOM>` : une personne détourée, debout dans la scène**

Exemple : `PHOTO_DEBOUT_MARIES`. C'est cet emplacement-là qui reçoit les mariés.
- **Origine de l'objet aux pieds.** La photo est posée au sol à cet endroit.
- **La hauteur du plan** donne la taille de la personne, par exemple 1,85 m. La photo
  est mise à cette hauteur, et sa largeur suit ses proportions.
- **La forme du plan donne l'ombre au sol.** L'emplacement est invisible pour la
  caméra, mais son ombre est rendue. Un ovale de 1,2 × 1,85 m donne une ombre de couple
  naturelle ; un rectangle donne une ombre en carton.
- Mettez une contrainte **Locked Track** vers `DRONE` (axe *-Y*, verrou *Z*). L'ombre
  tourne alors avec la photo, qui fait toujours face à la caméra.

**`PHOTO_CADRE_<NOM>` : une photo à plat et fixe**

Exemple : un tableau au mur, un chevalet, un écran. Rexo Studio y met la photo
choisie, améliorée mais non détourée.
- **Origine de l'objet au centre du plan.**
- **Rotation autour de la verticale (Z) seulement.** Pas d'inclinaison avant ou arrière :
  un chevalet penché est dessiné penché, mais son emplacement reste droit.
- La photo est contenue dans le plan, sans déborder.
- Placez votre cadre doré ou votre bordure **juste derrière** le plan, de 1 à 3 cm.

### Ce qui passe devant les photos : la collection `PREMIER_PLAN`

Facultatif : des branches, des pétales, un voilage qui passe devant les mariés.
- Mettez ces objets dans une collection nommée exactement `PREMIER_PLAN`.
- Rexo Studio les rend à part, sur fond transparent, et les pose **par-dessus** les
  photos.
- Hors de cette collection, **rien ne doit passer entre la caméra et les mariés**. Sinon,
  la photo ajoutée ensuite apparaîtrait devant l'objet au lieu d'être cachée par lui.

### La zone de vol de la caméra

Rexo Studio fait voler la caméra autour de l'avant de la scène :
- **rotation** : jusqu'à ±40° de part et d'autre de l'axe −Y ;
- **distance** : de 3,6 à 15 m des mariés ;
- **hauteur** : de 1,4 à 8 m.

| Mouvement | Trajet |
|---|---|
| Séquence | approche depuis le ciel, tour, envol |
| Approche | du ciel vers les mariés |
| Orbite | tour de −38° à +38° à 4,6 m |
| Envol | des mariés vers le ciel |
| Spirale | descente en tournant |

Dans ce volume :
- **pas de colonne, de mur ni d'arbre** entre la caméra et les mariés ;
- placez les grands éléments **derrière** les mariés (côté +Y) ou sur les côtés, au-delà
  de 15 m vers l'avant ;
- le décor doit tenir l'image **jusqu'à 15 m de recul et 8 m de haut** : prévoyez un sol
  assez grand et un fond, comme un ciel, des arbres lointains ou des lumières.

### Lumière et vitesse de rendu

L'iMac a une petite carte graphique : chaque seconde de vidéo compte 30 images à
calculer. Repère sur le jardin d'exemple : 1,7 s par image en qualité normale.

- **Pas de profondeur de champ.** Elle triple le temps de rendu. Rexo Studio la réserve
  à la qualité « fine ».
- **Le bloom (halo des lumières) va bien**, ainsi que les ombres douces.
- **Un métal pur ne reflète que son environnement.** Dans une scène de nuit au ciel noir,
  l'or sort noir. Baissez le métal (≈ 0,3) ou donnez un éclairage d'ambiance au monde.
- Textures en **1 024 ou 2 048 px**, pas plus.
- Évitez les centaines de lumières ou d'objets réfléchissants : préférez des petites
  sphères émissives pour les guirlandes.

### Le modèle d'exemple

`blender/build_template_jardin_nuit.py` et `build_template_patio_nuit.py` construisent
`jardin_nuit.blend` et `patio_nuit.blend` (`python3 -m atelier scene patio_nuit`) en suivant toutes ces
règles : sol en marbre, colonnes derrière les mariés, arche dorée, chevalet avec un
`PHOTO_CADRE_PHOTO`, ovale `PHOTO_DEBOUT_MARIES`. Ouvrez-le dans Blender 3.6 pour voir
un modèle conforme.

---

## 3. Les matériaux (TextureCraft et MaterialCraft)

Les textures des décors se rangent dans `textures/<matériau>/` (atelier), sous des noms
fixes : `<matériau>_BaseColor.png`, `_Roughness`, `_Normal`, `_Metallic`, `_Height`.

**Un matériau tout prêt de TextureCraft** (marbre, or, chêne, velours… 93 au choix) :

```bash
python3 -m atelier textures --liste            # les matériaux disponibles
python3 -m atelier textures marble velvet      # les prépare
```

**Un matériau sur mesure de MaterialCraft**, par exemple un zellige ou un tissu brodé :

1. Construisez le graphe dans MaterialCraft. Il doit avoir des sorties `basecolor`,
   `normal` et `roughness`, plus `metallic` et `height` si besoin. Les fichiers `.sbs` de
   Substance Designer marchent aussi.
2. **Exposez les réglages utiles** (couleur principale, couleur des motifs, échelle),
   avec des identifiants simples comme `couleur` ou `motif`. Ce sont eux que Rexo Studio
   pourra changer, par exemple aux couleurs d'un mariage.
3. Enregistrez le paquet (`.mcraft`). Rexo Studio ne le modifie jamais.
4. Préparez les textures :

```bash
python3 -m atelier materialcraft zellige.mcraft zellige_or couleur=#c8a040
```

Dans Blender, utilisez ces images dans le matériau : *Image Texture* reliée à
*Principled BSDF*, avec les cartes Roughness, Normal et Metallic en *Non-Color*. Puis
emballez-les dans le `.blend` (voir plus haut).

---

## 4. Les titres (EffectCraft)

Les titres se posent par-dessus la vidéo : à la fin du clip drone et du générique des
moments forts.

- Faites une composition **1920 × 1080**, de 4 à 6 s, **sans fond**. La vidéo doit se
  voir derrière.
- Gardez la zone des mariés libre : en général le **bas** ou le **haut** de l'image.
- Deux textes, ajoutés dans le panneau **Essential Graphics** sous les noms **`Title`** et
  **`Subtitle`** (ou `Titre` et `Sous-titre`). Rexo Studio y écrit les noms des mariés
  et la date.
- Exportez : *Essential Graphics ▸ Export Template* vers `<nom>.ectemplate`. Le titre se
  livre avec les animations, et s'installe dans le dossier `bibliotheque/titres` de Rexo Studio.
- Les animations d'entrée et de sortie (fondu, écriture lettre par lettre…) sont les
  vôtres : Rexo Studio ne fait que remplir les textes et placer le titre à la fin.

---

## 5. Rendre, tester et livrer

```bash
python3 -m atelier liste                                    # décors, paquets prêts
python3 -m atelier animation salle_des_fetes orbite 1 brouillon   # essai rapide (1 s)
open livraison/salle_des_fetes__orbite__1s/decor.mp4
cat  livraison/salle_des_fetes__orbite__1s/animation.json   # emplacements trouvés

python3 -m atelier animation salle_des_fetes sequence 9 normal --titre "Salle des fêtes — drone"
python3 -m atelier livrer                                   # zip de tous les paquets prêts
```

Mouvements : `sequence`, `approche`, `orbite`, `envol`, `spirale`. Qualités : `brouillon`
(essais), `normal` (livraison), `fin` (avec profondeur de champ, trois fois plus lent).

Puis, dans Rexo Studio :
1. installez la livraison : `python3 scripts/installer_animations.py animations_….zip` ;
2. ouvrez la galerie photos d'un événement, cliquez sur ✨, puis « Clip drone 3D » ;
3. choisissez l'animation et lancez avec une vraie photo de mariés en pied.

**À vérifier sur le clip :**
- les pieds des mariés touchent le sol, et leur ombre est sous eux ;
- rien ne passe devant eux, sauf le `PREMIER_PLAN` ;
- les photos des `PHOTO_CADRE_*` sont bien dans leur cadre ;
- le titre ne couvre pas les visages ;
- le temps de rendu par image dans le journal reste raisonnable : moins de 2 s sur l'iMac
  en qualité normale.

**Messages d'erreur fréquents :**

| Message | Cause |
|---|---|
| « aucun emplacement PHOTO_DEBOUT_* ni PHOTO_CADRE_* » | Noms mal écrits, ou objets qui ne sont pas des maillages. |
| « Ignoré (paquet incomplet ou format inconnu) » à l'installation | Un fichier du paquet manque : refaire `python3 -m atelier animation …`. |
| « n'a pas d'emplacement PHOTO_DEBOUT_MARIES » | Le clip drone exige cet emplacement pour les mariés. |
| `KeyError: 'VISE'` | L'objet vide `VISE` manque. |
| Les mariés flottent ou s'enfoncent | L'origine de `PHOTO_DEBOUT_…` n'est pas aux pieds, ou le sol n'est pas à z = 0. |
