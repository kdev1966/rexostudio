# PRD — MontageIA pour studios photo et vidéo d'événements

**Version du document** : 1.0 — 16 novembre 2026
**État du code** : MontageIA fonctionnel sur l'iMac du studio (transcription, plan de coupe
pour la parole, rendus 16:9 / 9:16, envoi vers FilmCraft, IA locale llama.cpp + Gemma 4 E2B).

---

## 1. Vision

Aider un studio de photographie qui filme et monte des **mariages, anniversaires et fêtes**
à livrer plus vite de meilleurs films, avec une IA :

- **100 % locale** : les images des familles ne quittent jamais la machine du studio ;
- **utilisable sur une machine modeste** : la référence est l'iMac 2015 du studio (voir §6) ;
- **qui prépare sans décider à la place du monteur** : chaque proposition se vérifie, se
  corrige, puis se finit dans le logiciel de montage (FilmCraft).

MontageIA a d'abord été pensé pour des vidéos parlées face caméra (couper hésitations et
digressions). Un film de fête est surtout fait de musique, d'ambiance, de danse et de
quelques discours : ce document réoriente le produit vers ce besoin.

## 2. Décisions de cadrage (16 novembre 2026)

| Sujet | Décision |
|---|---|
| Base | MontageIA évolue (pas de nouveau projet) ; un nouveau nom pourra venir plus tard. |
| Public | **Ce studio d'abord** (outil interne) ; élargi à d'autres studios si le projet est confirmé. |
| Plateformes | **macOS d'abord**, jusqu'à confirmation du projet ; Windows ensuite. |
| Logiciel de montage | FilmCraft (déjà piloté) ; d'autres plus tard si besoin. |
| Langue de l'interface | Français. Contenus traités en français et en arabe tunisien. |
| Sous-titres | Gardés, mais **pas une priorité** pour un studio photo. |
| Priorité | **Les moments forts.** |

## 3. Le studio et son flux de travail

- **Une seule caméra** par événement.
- **Livrables** : film complet, **teaser pour les réseaux sociaux** (vertical), photos + vidéo.
- **À préciser** (Q1–Q4, §10) : modèle et format de la caméra, volume de rushes par
  événement, arrivée des fichiers sur l'iMac.

## 4. Objectifs et non-objectifs

### Objectifs

1. **O1 — Moins de temps à dérusher** : savoir en quelques minutes quels plans garder.
2. **O2 — Trouver les moments forts** sans tout revoir : entrée des mariés, youyous,
   applaudissements, danse, gâteau, discours.
3. **O3 — Un teaser prêt à retoucher** en quelques minutes, calé sur une musique.
4. **O4 — Des effets qui font la différence** (détourage du couple, photos animées en 3D),
   sur des moments choisis.
5. **O5 — Garder le monteur maître** : tout est proposé, rien n'est imposé ; finition dans FilmCraft.

### Non-objectifs

- **Reconnaître ou identifier les invités** (reconnaissance faciale) : question de vie privée.
  On note des plans, on ne reconnaît pas des personnes.
- **Une vraie caméra à 360° autour des mariés** : impossible avec une seule caméra (il manque
  l'arrière de la scène) ; on propose des effets de profondeur réalistes (§5, M4).
- **Remplacer le logiciel de montage** : pas de timeline d'édition dans MontageIA.
- **Le cloud** : aucun service en ligne, aucune clé d'API.

## 5. Modules et exigences

Priorités : **P1** indispensable au premier lot ; **P2** ensuite ; **P3** maintenu, sans investissement.

| Module | Priorité | Ce que voit le monteur |
|---|---|---|
| **M1 — Tri des rushes** | P1 | Pour chaque fichier : note de qualité (flou, image tremblée, trop sombre / brûlée, plan noir ou figé, trop court) et classement par heure de tournage. Les plans à jeter sont signalés, jamais supprimés. |
| **M2 — Moments forts** | P1 | Une liste de moments notés, écoutables (▶) : youyous, applaudissements et cris de joie, départ de musique, mouvement intense (danse, cortège), discours. Chapitres de l'événement. Marqueurs dans FilmCraft. |
| **M3 — Teaser et film souvenir** | P1 | Choix d'une musique et d'une durée (30 / 60 s) : meilleurs moments de bonne qualité, coupés sur le rythme, en 9:16 (cadrage qui suit les visages) et 16:9. Retouche dans FilmCraft. |
| **M4 — Effets IA** | P2 | Sur un plan ou une photo choisis : détourage des mariés (désignés par un clic), mariés en couleur sur fond noir et blanc, fond flouté, titre glissé derrière le couple, ralenti fluide ; **photos du studio animées en 3D** (calques + profondeur + décor reconstitué). |
| **M5 — Son** | P2 | Volume égalisé, musique baissée automatiquement sous les discours, réduction du bruit (vent, brouhaha). |
| **M6 — Livraison** | P2 | Rendus 16:9 / 9:16, miniatures, textes pour les réseaux sociaux (français / arabe), fiche de l'événement (mariés, date, lieu) pour les titres. |
| **M7 — Discours et sous-titres** | P3 | Existant : transcription (français, arabe tunisien), nettoyage d'un discours, sous-titres. |

### Exigences par module (critères d'acceptation, mesurés sur de vrais rushes du studio)

- **M1** : analyse d'une heure de rushes en moins de 15 min sur l'iMac (à confirmer par la
  mesure) ; aucun plan jugé « à jeter » qui soit en réalité bon, sur un échantillon vérifié
  par le monteur.
- **M2** : sur un mariage réel, au moins 8 des 10 moments que le monteur aurait choisis sont
  dans les 20 premiers proposés ; les youyous et applaudissements sont repérés.
- **M3** : teaser rendu en moins de 5 min ; coupes sur le temps fort de la musique ; aucun
  plan flou ou tremblé.
- **M4** : le voile de la mariée reste propre sur le détourage, ou le plan est signalé
  « effet non conseillé » ; temps par plan affiché avant le calcul.
- **M5** : la musique est audible mais n'écrase jamais un discours.

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
- **Détourage** (M4) : MobileSAM (par clic, Apache-2.0) pour désigner les mariés ; Apple
  Vision (intégré à macOS 12, sans téléchargement) comme solution rapide sur les plans où le
  couple est seul. Profondeur : Depth Anything V2 Small ; décor reconstitué : MI-GAN.
- Chaque choix important fait l'objet d'une décision dans `docs/adr/`.

## 8. Feuille de route

| Jalon | Contenu | Condition pour passer au suivant |
|---|---|---|
| **J0** | Échantillons réels du studio (vidéo + photos, avec son accord) ; réponses Q1–Q4 | fichiers déposés sur l'iMac |
| **J1** | M1 tri des rushes | critères M1 validés par le monteur |
| **J2** | M2 moments forts (son puis image) | critères M2 |
| **J3** | M3 teaser sur musique | un teaser réel jugé « publiable après retouche » |
| **J4** | M4 prototype : photos animées en 3D, couleur sur fond noir et blanc | validation visuelle du studio, temps mesurés |
| **J5** | M5 son ; M6 livraison | — |
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
- **Q5** — Reprise d'embedkit (rawi) : copie figée dans MontageIA ou dépendance.
- **Q6** — Musiques des teasers : bibliothèque du studio ou musiques libres de droits ?
