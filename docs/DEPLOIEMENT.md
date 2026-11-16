# Déployer Rexo Studio sur une nouvelle machine

Procédure complète et vérifiable : chaque composant est installé par un script du dépôt,
avec des versions figées et des empreintes SHA-256, puis contrôlé par un vrai essai.
Machine de référence : **iMac late 2015** (iMac16,2, i5-5575R 4 cœurs, 16 Go, Iris Pro 6200,
macOS 12.7.6). Développement : MacBook Pro 2015 (i7-4870HQ, macOS 12.7.6).

## 1. Prérequis

| Élément | Pourquoi | Vérifier |
|---|---|---|
| Mac **Intel** (x86_64), **macOS 12** ou plus | Vision (détourage), paquets compilés figés | `uname -m`, `sw_vers` |
| Outils en ligne de commande d'Apple | `swiftc` (outil Vision), `git`, `make` | `xcode-select -p` (sinon `xcode-select --install`) |
| Python 3.9 du système | cœur de Rexo Studio (bibliothèque standard seulement) | `python3 --version` |
| Accès Internet **pendant l'installation** | téléchargements vérifiés ; ensuite tout marche hors ligne | — |
| FilmCraft ≥ 0.20 (facultatif) | envoi des sélections de rushes | `/Applications/FilmCraft.app` |
| PhotoCraft ≥ 0.23 (facultatif) | cadre autour des mariés, retouche | `/Applications/PhotoCraft.app` |
| ~8 Go libres | modèles (≈ 3 Go), outils, environnement d'effets (≈ 400 Mo) | `df -h ~` |

Sur un Mac **Apple Silicon (arm64)**, les versions figées de l'environnement d'effets
sont à refaire (le script refuse de continuer plutôt que d'installer autre chose).

## 2. Récupérer le code

Le dossier du projet ne doit **pas** être sur le Bureau, dans Documents ni dans
Téléchargements : macOS interdit à l'icône de lancement de lire ces dossiers.

```bash
git clone ssh://<machine-de-dev>/…/RexoStudio ~/RexoStudio   # ou copie du dépôt
cd ~/RexoStudio
```

Mise à jour d'une machine déjà installée depuis le MacBook (méthode utilisée pour l'iMac) :

```bash
# sur le MacBook (remote « imac » = ssh://najehstudio@192.168.1.166/Users/najehstudio/RexoStudio)
git push imac main:deploy-incoming
# sur l'iMac
cd ~/RexoStudio && git merge --ff-only deploy-incoming
```

## 3. Installer (dans cet ordre)

```bash
./scripts/install_models.sh       # ffmpeg/ffprobe, whisper.cpp, llama.cpp + Gemma 4 E2B, modèles Whisper
./scripts/build_native.sh         # bin/rexo-segment (détourage Apple Vision), compilé sur la machine
./scripts/install_effects_env.sh  # .effets/ : Python 3.11 autonome + ONNX + MobileSAM, MI-GAN, Depth Anything
./scripts/install_launcher.sh     # icône « Rexo Studio » sur le Bureau
```

Chaque script est relançable : ce qui est déjà en place et vérifié est gardé.

| Script | Installe | Où | Figé par |
|---|---|---|---|
| `install_models.sh` | ffmpeg 9.0.2, whisper.cpp v1.9.5, llama.cpp b12428, Gemma 4 E2B Q4_0, Whisper, VAD Silero | `bin/`, `models/` | commits Git + SHA-256 (en tête du script) |
| `build_native.sh` | `rexo-segment` | `bin/` | source `native/segment.swift` |
| `install_effects_env.sh` | Python 3.11.17, onnxruntime 1.19.2, numpy 2.4.6, opencv 4.10.0.84, pyyaml 6.0.3 + dépendances | `.effets/` | SHA-256 de Python dans le script ; `scripts/effets-requirements.txt` (`--require-hashes`, `--only-binary`) |
| (même script) | modèles MobileSAM, MI-GAN 512, Depth Anything V2 Small | `~/.local/share/kdev-models/embedkit` | manifestes `vendor/embedkit/embedkit/models/*.yaml` (révision + SHA-256) |

Pourquoi ces versions : ce sont les **dernières publiées en paquets compilés pour Mac Intel
sous macOS 12** (vérifié le 16/11/2026). Au-delà, pip recompile OpenCV depuis les sources
(plus de 10 minutes, résultat non reproductible) : `--only-binary` l'interdit.

Le cœur reste en Python 3.9 sans dépendance ; l'environnement d'effets tourne dans un
processus séparé (un plantage n'emporte pas l'interface). Tout retirer : supprimer
`.effets/` et les modèles du magasin.

## 4. Vérifier

```bash
./scripts/check_install.sh                 # tout, avec de vrais essais sur des images synthétiques
./scripts/check_install.sh --photo P.jpg   # + détourage et effacement sur une vraie photo (contrôle visuel)
./scripts/check_install.sh --quick         # sans les tests unitaires
```

Ce qui est contrôlé :

| Contrôle | Essai réel |
|---|---|
| Emplacement du projet | pas dans un dossier protégé |
| Cœur | `python3 -m unittest discover -s tests` (tous les tests unitaires) |
| Outils | présence de `bin/` et des modèles |
| Vision | `rexo-segment blur` sur une image synthétique |
| PhotoCraft | Sélection d'objet dans un cadre, sans interface ; PSD à calques avec masque modifiable |
| Environnement d'effets | versions, SHA-256 des modèles, puis `scripts/effets_smoke.py` : MobileSAM détoure un disque (recouvrement > 0,8), MI-GAN l'efface, Depth Anything rend une carte |

Après l'installation, évaluer aussi l'assistant à consigne avec le vrai modèle (environ
2 minutes) : `python3 scripts/eval_consignes.py` — score attendu ≥ 9/10 (10/10 sur l'iMac
le 16/11/2026). À relancer après toute modification du prompt ou du modèle.

Aucune photo de client n'est utilisée par ces contrôles. `--photo` écrit ses résultats
dans un dossier temporaire affiché à la fin.

## 5. Autorisations macOS (premier lancement)

- **Accès aux volumes amovibles** : demandé au premier import d'une carte mémoire ; accepter.
- **Session à distance (SSH)** : pour administrer la machine depuis le MacBook, activer
  Réglages > Partage > Session à distance, et donner l'accès complet au disque à `sshd`.
- L'icône lit le projet seulement hors des dossiers protégés (voir §2).

## 6. Mesures de référence (iMac, pour comparer une nouvelle machine)

| Opération | Temps mesuré | Date |
|---|---|---|
| Vision : détourage / noir et blanc / fond flou, photo 2048 px | 2,1 à 2,3 s (premier appel ≈ 3,2 s) | 16/11/2026 |
| Vision + cadre PhotoCraft (robe et traîne) | 3,0 à 4,3 s | 16/11/2026 |
| Plan de coupe, llama.cpp + Gemma 4 E2B | film002 82 s, cafe 16 s | 16/11/2026 |
| MobileSAM : sélection d'un objet dans un cadre, photo 2048 px | 1,2 s | 16/11/2026 |
| MI-GAN : effacement de l'objet (vase, photo 1) | 1,0 s | 16/11/2026 |
| Essais de `check_install.sh` (image 640 px) : MobileSAM / MI-GAN / Depth Anything | 1,2 s / 0,9 s / 0,9 s | 16/11/2026 |
| `install_effects_env.sh` complet (téléchargements compris) | 1 min 18 s | 16/11/2026 |
| **Pleine résolution** (Nikon D780, 5368 × 3579, 19 Mpx) : détourage / noir et blanc / fond flou | 3,4 / 2,6 / 2,7 s | 16/11/2026 |
| Pleine résolution, avec cadre PhotoCraft : fond flou / détourage | 4,8 / 5,7 s | 16/11/2026 |
| Pleine résolution : effacer un objet (galerie) | 4,1 s (155 s avant la correction du 16/11) | 16/11/2026 |
| Assistant : plan d'une consigne (Gemma 4 E2B) | 6 à 8 s (premier appel ≈ 35 s : chargement du modèle) | 16/11/2026 |
| Assistant : exécution (cadre + fond flou ; effacer + style sur 19 Mpx ; style + recadrage) | 3,8 s ; 4,4 s ; 2,4 s | 16/11/2026 |
| `scripts/eval_consignes.py` (10 consignes du studio, français et tunisien) | 10/10 | 16/11/2026 |
| PSD à calques pour PhotoCraft (19 Mpx, masque modifiable) | 6,5 s, 146 à 175 Mo | 16/11/2026 |

`check_install.sh` affiche les temps de MobileSAM, MI-GAN et Depth Anything : reporter
ici ceux d'une nouvelle machine de production pour les comparer.

## 7. Journal des installations

| Date | Machine | Résultat |
|---|---|---|
| 16/11/2026 | iMac (production) | `check_install.sh` tout vert : 162 tests, outils, Vision, FilmCraft 0.20.1, PhotoCraft 0.23.1, environnement d'effets. Premier passage : échec de MobileSAM par CoreML (Iris Pro) → embedkit forcé sur le processeur (vendor/ORIGINE.md). |
