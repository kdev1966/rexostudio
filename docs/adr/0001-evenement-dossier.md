# ADR 0001 — Un événement = un dossier de projet

- **Statut** : accepté
- **Date** : 16 novembre 2026
- **Décideur** : porteur du projet

## Contexte

Jusqu'ici, un « projet » Rexo Studio (ex-MontageIA) était **une vidéo** : un fichier importé,
sa transcription et son plan de coupe, rangés dans `workspace/` (média dans
`workspace/media/<date>/`, fiche dans `workspace/projects/project_<id>.json`, rendus mêlés dans
`workspace/exports/`). Un studio travaille par **événement** : une noce, ce sont des heures de
rushes, des photos, des musiques, des montages et plusieurs livrables, à garder ensemble et à
archiver d'un bloc.

## Décision

1. **Le projet devient l'événement.** Chaque événement a son propre dossier, sous une racine
   unique : `~/RexoStudio/Evenements/` sur le disque interne de l'iMac (aucune autorisation
   macOS à demander : ni Bureau, ni Documents, ni disque externe).
2. **Nom du dossier** : `AAAA-MM-JJ_Type_Noms` — ex. `2026-11-22_Mariage_Sarra-et-Ahmed`.
   La date en tête classe les événements tout seuls. Types : `Mariage`, `Fiancailles`, `Henne`,
   `Anniversaire`, `Circoncision`, `Diplome`, `Fete`
   (Circoncision et Diplôme ajoutés le 16 novembre 2026). Les noms sont nettoyés (espaces → `-`, aucun `/` ni `:`) ; les
   lettres accentuées et arabes sont gardées.
3. **Structure fixe** :

   ```
   AAAA-MM-JJ_Type_Noms/
   ├── 01_Rushes/       copie vérifiée des cartes mémoire, jamais modifiée (Carte_1/, Carte_2/…)
   ├── 02_Photos/       photos originales
   ├── 03_Audio/        musiques choisies, enregistrements à part
   ├── 04_Proxies/      copies allégées pour le montage (recréables, effaçables)
   ├── 05_Montage/      projets FilmCraft, sélections
   ├── 06_Rendus/       Film_complet/, Teaser/, Photos_animees/
   ├── 07_Livraison/    ce qui part chez le client
   └── .rexo/           données de Rexo Studio (fiche, analyses, décisions), masqué
   ```

4. **La fiche de l'événement** (`.rexo/evenement.json`) : type, date, noms, lieu, notes ;
   les chemins qu'elle contient sont **relatifs au dossier de l'événement**, pour qu'il puisse
   être déplacé ou archivé sans rien réécrire.
5. **Rien n'est effacé définitivement** par Rexo Studio. À la demande du studio (16 novembre
   2026), l'interface permet de supprimer un rush, une photo, une carte importée, le contenu
   d'un dossier ou l'événement entier : tout part dans la **Corbeille du Mac** (API système),
   récupérable tant qu'elle n'est pas vidée. Confirmation obligatoire ; pour un événement
   entier, il faut taper « SUPPRIMER ». Refusé pendant un traitement en cours.
6. **Les anciens projets** (une vidéo) restent lisibles ; ils pourront être rattachés à un
   événement.

## Conséquences

- L'import (M1) copie la carte mémoire dans `01_Rushes/Carte_n/` avec contrôle d'empreinte.
- Les analyses, proxies et rendus vont dans les dossiers de l'événement, plus dans
  `workspace/exports` ; `workspace/` ne garde que ce qui est commun (caches des modèles).
- L'interface s'organise autour de la **liste des événements**, puis des plans d'un événement.
- Un événement est autonome : déplacé ou archivé sur un disque externe en un seul dossier ;
  la portabilité vers Windows est conservée (noms de fichiers sans caractères interdits).
