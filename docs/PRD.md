# PRD — Rexo Studio : dérushage et post-production pour studios photo et vidéo d'événements

**Version du document** : 1.5 — 16 novembre 2026
**État du code** : Rexo Studio (anciennement MontageIA) fonctionnel sur l'iMac du studio (transcription, plan de coupe
pour la parole, rendus 16:9 / 9:16, envoi vers FilmCraft, IA locale llama.cpp + Gemma 4 E2B).

### Historique

| Version | Changements |
|---|---|
| 1.0 | Première version : réorientation vers les studios d'événements. |
| 1.2 | **Un événement = un dossier de projet** (ADR 0001) : `~/RexoStudio/Evenements/AAAA-MM-JJ_Type_Noms/` avec 01_Rushes … 07_Livraison ; types Mariage, Fiançailles, Henné, Anniversaire, Fête. |
| 1.5 | Types d'événements **Circoncision** et **Diplôme** ajoutés (demande du studio). |
| 1.4 | **M1 dérushage, première version codée** : import vérifié (SHA-256) des cartes, heure de tournage, défauts (noir, sombre, surexposé, flou, tremblé, très court), choix « Garder », proxies, sélection vers FilmCraft. Restent pour M1 : quasi-doublons, plan figé, critères validés par le monteur sur de vrais rushes. |
| 1.3 | **L'accueil de l'interface = la liste des événements** avec une recherche (noms, lieu, notes, type, date, sans accents) et un filtre par type ; création d'un événement et ouverture de ses dossiers dans le Finder (M0, première version codée). |
| 1.1 | **Le dérushage et la post-production des vidéos de mariage deviennent le cœur du projet** : dérushage complet (import, proxies, sélection) et post-production (son, stabilisation, couleurs, bruit) en P1 ; le teaser suit ; effets IA ensuite. |

---

## 1. Vision

Aider un studio de photographie qui filme et monte des **mariages, anniversaires et fêtes**
à livrer plus vite de meilleurs films, avec une IA :

- **100 % locale** : les images des familles ne quittent jamais la machine du studio ;
- **utilisable sur une machine modeste** : la référence est l'iMac 2015 du studio (voir §6) ;
- **qui prépare sans décider à la place du monteur** : chaque proposition se vérifie, se
  corrige, puis se finit dans le logiciel de montage (FilmCraft).

Rexo Studio a d'abord été pensé pour des vidéos parlées face caméra (couper hésitations et
digressions). Un film de fête est surtout fait de musique, d'ambiance, de danse et de
quelques discours : ce document réoriente le produit vers ce besoin.

## 2. Décisions de cadrage (16 novembre 2026)

| Sujet | Décision |
|---|---|
| Base | MontageIA évolue (pas de nouveau projet) et devient **Rexo Studio** (nom choisi le 16/11/2026 ; noms internes inchangés). |
| Public | **Ce studio d'abord** (outil interne) ; élargi à d'autres studios si le projet est confirmé. |
| Plateformes | **macOS d'abord**, jusqu'à confirmation du projet ; Windows ensuite. |
| Logiciel de montage | FilmCraft (déjà piloté) ; d'autres plus tard si besoin. |
| Langue de l'interface | Français. Contenus traités en français et en arabe tunisien. |
| Sous-titres | Gardés, mais **pas une priorité** pour un studio photo. |
| Priorité | **Le dérushage et la post-production des vidéos de mariage**, guidés par les moments forts. |

## 3. Le studio et son flux de travail

- **Une seule caméra** par événement.
- **Livrables** : film complet, **teaser pour les réseaux sociaux** (vertical), photos + vidéo.
- **Types d'événements** : mariage, fiançailles, henné, anniversaire, autre fête.
- **Un dossier par événement** (ADR 0001), sous `~/RexoStudio/Evenements/` :
  `AAAA-MM-JJ_Type_Noms/` avec `01_Rushes`, `02_Photos`, `03_Audio`, `04_Proxies`,
  `05_Montage`, `06_Rendus`, `07_Livraison` et `.rexo/` (données de l'application).
- **À préciser** (Q1–Q4, §10) : modèle et format de la caméra, volume de rushes par
  événement, arrivée des fichiers sur l'iMac.

## 4. Objectifs et non-objectifs

### Objectifs

1. **O1 — Dérushage rapide** : de la carte mémoire à une sélection classée et prête à
   monter, sans revoir toutes les heures de rushes.
2. **O2 — Trouver les moments forts** : entrée des mariés, youyous, applaudissements, danse,
   gâteau, discours.
3. **O3 — Post-production assistée** : son propre, images stables, couleurs homogènes d'un
   plan à l'autre, bruit réduit sur les plans de soirée.
4. **O4 — Un teaser prêt à retoucher** en quelques minutes, calé sur une musique.
5. **O5 — Des effets qui font la différence** (détourage du couple, photos animées en 3D),
   sur des moments choisis.
6. **O6 — Garder le monteur maître** : tout est proposé, rien n'est imposé ; finition dans FilmCraft.

### Non-objectifs

- **Reconnaître ou identifier les invités** (reconnaissance faciale) : question de vie privée.
  On note des plans, on ne reconnaît pas des personnes.
- **Une vraie caméra à 360° autour des mariés** : impossible avec une seule caméra (il manque
  l'arrière de la scène) ; on propose des effets de profondeur réalistes (§5, M4).
- **Remplacer le logiciel de montage** : pas de timeline d'édition dans Rexo Studio.
- **Le cloud** : aucun service en ligne, aucune clé d'API.

## 5. Modules et exigences

Priorités : **P1** indispensable au premier lot ; **P2** ensuite ; **P3** maintenu, sans investissement.

| Module | Priorité | Ce que voit le monteur |
|---|---|---|
| **M0 — Événements** | **P1** | **Page d'accueil** : les dossiers d'événements en cartes, avec une **recherche** (noms, lieu, notes, type, date ou mois) et un filtre par type. Créer un événement (type, date, noms, lieu) : son dossier et ses sous-dossiers sont créés ; ouvrir le dossier dans le Finder ; archiver (déplacer vers un disque) ; libérer la place des proxies après livraison. |
| **M1 — Dérushage** | **P1** | **Import** du dossier de la carte mémoire dans `01_Rushes/Carte_n/` (copie vérifiée, rushes jamais modifiés) ; **classement par heure de tournage** ; **note de qualité** par plan (flou, tremblé, trop sombre / brûlé, plan noir ou figé, trop court) ; **doublons et quasi-doublons** repérés ; **sélection** : à garder / à vérifier / à écarter (jamais supprimé) ; **proxies** (copies allégées) pour un montage fluide sur l'iMac ; envoi de la sélection classée dans FilmCraft, avec marqueurs. |
| **M2 — Moments forts** | **P1** | Moments notés et écoutables (▶) : youyous, applaudissements et cris de joie, départ de musique, mouvement intense (danse, cortège), discours ; chapitres de l'événement (préparatifs, entrée, cérémonie, gâteau, danse). Ils guident le dérushage, le teaser et le film complet. |
| **M3 — Post-production** | **P1** | **Son** : volume égalisé, musique baissée sous les discours, réduction du bruit (vent, brouhaha). **Image** : stabilisation des plans tremblés, couleurs harmonisées d'un plan à l'autre (exposition, balance des blancs), correction du scintillement des éclairages de salle, réduction du bruit des plans de soirée, « looks » couleur. Appliqué plan par plan ou sur toute la sélection, avec aperçu avant / après. |
| **M4 — Teaser et film souvenir** | P1 | Choix d'une musique et d'une durée (30 / 60 s) : meilleurs moments de bonne qualité, coupés sur le rythme, en 9:16 (cadrage qui suit les visages) et 16:9 ; transitions ; ralenti sur les moments clés. Retouche dans FilmCraft. |
| **M5 — Effets IA** | P2 | Sur un plan ou une photo choisis : détourage des mariés (désignés par un clic), mariés en couleur sur fond noir et blanc, fond flouté, titre glissé derrière le couple ; **photos du studio animées en 3D** (calques + profondeur + décor reconstitué). |
| **M6 — Livraison** | P2 | Rendus 16:9 / 9:16, miniatures, textes pour les réseaux sociaux (français / arabe), fiche de l'événement (mariés, date, lieu) pour les titres. |
| **M7 — Discours et sous-titres** | P3 | Existant : transcription (français, arabe tunisien), nettoyage d'un discours, sous-titres. |

### Exigences par module (critères d'acceptation, mesurés sur de vrais rushes du studio)

- **M1** : analyse d'une heure de rushes en moins de 15 min sur l'iMac, proxies compris (à
  confirmer par la mesure) ; aucun plan classé « à écarter » qui soit en réalité bon, sur un
  échantillon vérifié par le monteur ; rushes d'origine jamais modifiés (empreinte vérifiée
  après copie) ; montage des proxies fluide dans FilmCraft.
- **M2** : sur un mariage réel, au moins 8 des 10 moments que le monteur aurait choisis sont
  dans les 20 premiers proposés ; les youyous et applaudissements sont repérés.
- **M3** : la musique est audible mais n'écrase jamais un discours ; deux plans consécutifs de
  la même scène ont des couleurs jugées homogènes par le monteur ; la stabilisation ne
  déforme pas l'image ; chaque traitement a un aperçu avant / après et peut être annulé.
- **M4** : teaser rendu en moins de 5 min ; coupes sur le temps fort de la musique ; aucun
  plan flou ou tremblé.
- **M5** : le voile de la mariée reste propre sur le détourage, ou le plan est signalé
  « effet non conseillé » ; temps par plan affiché avant le calcul.

## 6. Contraintes

- **Machine de référence** : iMac 27" 2015 (i5-5575R 4 cœurs, 16 Go, Iris Pro 6200, macOS 12.7.6,
  sans GPU utilisable). Toute fonction est **mesurée** sur cette machine avant d'être retenue.
- **Local et hors ligne** après installation.
- **Licences** : uniquement des modèles et composants autorisant l'**usage commercial**
  (le studio vend ses films). Exemple : Depth Anything V2 *Small* (Apache-2.0), pas les
  variantes Base / Large (non commerciales).
- **Portabilité** : pas de nouvelle dépendance propre au Mac sans l'isoler ; les moteurs
  choisis existent sous Windows (§7).
- **Données des clients** : aucune copie hors de l'espace de travail ; suppression d'un
  projet sur demande.

## 7. Architecture

- **Cœur** : Python 3.9, bibliothèque standard uniquement ; serveur web local + interface
  dans le navigateur ; lancement par icône.
- **Moteurs** dans des **processus séparés** (un plantage n'emporte pas l'interface) :
  ffmpeg / ffprobe (analyse et rendu), whisper.cpp (parole), llama.cpp + Gemma 4 E2B
  (textes, classement), et pour M4 un **environnement d'effets** (ONNX Runtime, NumPy,
  OpenCV) sur le modèle de rawi (`~/Desktop/Tools/film/rawi`, ADR 0003, 0007, 0008).
- **Modèles** : versions figées et empreintes SHA-256 ; magasin partagé
  `~/.local/share/kdev-models` réutilisé quand il existe.
- **Analyse vidéo** (M1, M2) : filtres ffmpeg déjà présents (`blurdetect`, `vidstabdetect`,
  `signalstats`, `blackdetect`, `freezedetect`, `scdet`, `ebur128`, `astats`) sur une copie
  basse résolution et basse cadence, pour tenir les temps sur l'iMac.
- **Post-production** (M3) : filtres ffmpeg déjà présents — son : `afftdn`, `anlmdn`,
  `highpass`, `sidechaincompress`, `loudnorm` ; image : `vidstabdetect` / `vidstabtransform`,
  `grayworld` / `greyedge` (balance des blancs), `eq`, `curves`, `haldclut` (looks),
  `deflicker`, `hqdn3d` / `nlmeans` (bruit), `minterpolate` (ralenti), `xfade` (transitions).
  Les traitements sont décrits par plan dans le projet (non destructifs) et appliqués au rendu.
- **Détourage** (M4) : MobileSAM (par clic, Apache-2.0) pour désigner les mariés ; Apple
  Vision (intégré à macOS 12, sans téléchargement) comme solution rapide sur les plans où le
  couple est seul. Profondeur : Depth Anything V2 Small ; décor reconstitué : MI-GAN.
- Chaque choix important fait l'objet d'une décision dans `docs/adr/`.

## 8. Feuille de route

| Jalon | Contenu | Condition pour passer au suivant |
|---|---|---|
| **J0** | Échantillons réels du studio (vidéo + photos, avec son accord) ; réponses Q1–Q4 | fichiers déposés sur l'iMac |
| **J1** | M0 événements (dossiers, fiche, liste) ; M1 dérushage : import, classement, note de qualité, proxies, sélection vers FilmCraft | critères M1 validés par le monteur |
| **J2** | M2 moments forts (son puis image) | critères M2 |
| **J3** | M3 post-production : son, puis stabilisation, couleurs, bruit | critères M3 |
| **J4** | M4 teaser sur musique | un teaser réel jugé « publiable après retouche » |
| **J5** | M5 effets IA (photos animées en 3D, couleur sur fond noir et blanc) ; M6 livraison | validation visuelle du studio, temps mesurés |
| **Plus tard** | Windows ; autres logiciels de montage ; autres studios | confirmation totale du projet |

## 9. Risques

| Risque | Parade |
|---|---|
| Temps d'analyse trop longs sur l'iMac 2015 | Analyse en basse résolution / basse cadence ; mesure avant tout choix. |
| Youyous et applaudissements mal reconnus | Réglage sur de vrais enregistrements du studio (J0), pas sur des exemples d'Internet. |
| Détourage abîmant le voile ou les cheveux | Signaler l'effet comme « non conseillé » sur ce plan ; essayer un modèle de détourage fin. |
| Droits d'auteur des musiques sur les réseaux sociaux | Bibliothèque de musiques libres de droits pour les teasers. |
| Matériel du studio remplacé | Les choix restent valables (moteurs portables) ; réglages repris par la mesure. |

## 10. Questions ouvertes

- **Q1** — Caméra du studio : modèle, format (MP4 / MOV / MTS, HD / 4K).
- **Q2** — Volume par événement : heures et gigaoctets de rushes, nombre de fichiers.
- **Q3** — Arrivée sur l'iMac : copie de la carte mémoire dans un dossier ?
- **Q4** — Photos : nombre par événement, format (JPEG / RAW).
- **Q5** — Reprise d'embedkit (rawi) : copie figée dans Rexo Studio ou dépendance.
- **Q6** — Musiques des teasers : bibliothèque du studio ou musiques libres de droits ?
