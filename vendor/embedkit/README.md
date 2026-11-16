# embedkit

Socle d'IA embarquée réutilisable, indépendant des applications qui l'utilisent (voir `docs/PRD.md` §6.2).

État (M0, en cours) :

| Module | Rôle | État |
|---|---|---|
| `hardware` | CPU, cœurs, RAM, AVX2, accélérateurs, niveau recommandé | ✅ |
| `registry` | manifestes YAML des modèles, validation, choix par tâche et niveau | ✅ |
| `licenses` | refus par défaut des modèles sans licence commerciale | ✅ |
| `store` | téléchargement Hugging Face (reprise, sha256, révision épinglée), cache, hors ligne strict | ✅ |
| `runtimes/onnx` | ONNX Runtime, repli OpenCV DNN (ADR 0003), chargement paresseux, `close()` / `with` | ✅ |
| `tasks.DepthEstimator` | profondeur relative (1 = proche) ; niveau 0 : dégradé vertical | ✅ |
| `bench` | temps et pic de RAM par modèle, chacun dans son processus | ✅ |
| `tasks.TextRecognizer` | lecture d'une ligne de texte (modèles CTC type PaddleOCR) ; niveau 0 : pas de texte | ✅ |
| `tasks.Inpainter` | reconstitution d'une zone masquée (pipeline ONNX type MI-GAN) ; niveau 0 : `cv2.inpaint` (Telea) | ✅ |
| `tasks.Segmenter` | détourage par clics ou cadre (paire ONNX type SAM : encodeur une fois par image, décodeur par invite) ; niveau 0 : GrabCut | ✅ |

## Commandes

```bash
embedkit hardware                 # la machine et le niveau recommandé
embedkit models list              # modèles déclarés, licence, installés ou non (hors ligne)
embedkit models pull <id>|--all   # télécharger (refuse un modèle non commercial sauf --allow-noncommercial)
embedkit models verify [<id>]     # contrôler le sha256 des fichiers installés
embedkit models bench [<id>]      # temps de chargement, d'inférence et pic de RAM
embedkit licenses audit           # échoue si un modèle n'a pas de licence commerciale
```

## Manifestes

Un fichier YAML par modèle (format : PRD §6.2). Ordre de lecture, le dernier l'emporte pour un même `id` :

1. `embedkit/models/*.yaml` (livrés avec embedkit) ;
2. les dossiers de `EMBEDKIT_MODELS_PATH` (séparés par `:`) ;
3. les dossiers passés par l'application (`Registry(extra_dirs=…)` ou `--models-path`).

Une application déclare ainsi ses propres modèles sans qu'embedkit la connaisse.

Une source peut être un dépôt Hugging Face à un commit épinglé (`repo`, `file`, `revision`) ou une adresse fixe (`url`, `revision` = nom de la publication). Les fichiers annexes (`extras`, par exemple le dictionnaire d'un modèle OCR) ont chacun leur sha256 ; `store.extra_path(m, "dict")` donne leur chemin.

## Variables d'environnement

| Variable | Effet |
|---|---|
| `EMBEDKIT_CACHE` | dossier des modèles (défaut `~/.cache/embedkit`) |
| `EMBEDKIT_OFFLINE=1` | aucune requête réseau |
| `EMBEDKIT_ALLOW_NONCOMMERCIAL=1` | autoriser les modèles sans licence commerciale (avec avertissement) |
| `EMBEDKIT_HF_ENDPOINT` | miroir de Hugging Face |
| `EMBEDKIT_MODELS_PATH` | dossiers de manifestes supplémentaires |

## Exemple

```python
from embedkit.tasks import DepthEstimator

with DepthEstimator.load() as est:   # niveau choisi selon la machine, modèle téléchargé si besoin
    depth = est(image_bgr)           # HxW float32, 1 = le plus proche
```

## Modèles livrés

| Modèle | Tâche | Licence | Mesuré sur la machine de référence |
|---|---|---|---|
| `depth-anything-v2-small` (FP32, 94,5 Mo) | profondeur | Apache 2.0 | 0,57 s de chargement, 536 ms par image 518², 390 Mo de RAM ; ne se charge pas sous OpenCV DNN |
| `paddleocr-arabic-v5-rec` (7,7 Mo + dictionnaire) | OCR, une ligne | Apache 2.0 | 0,19 s de chargement, 20 ms par ligne, 68 Mo de RAM |
| `migan-512` (26,8 Mo) | reconstitution | MIT | 0,35 s de chargement, 0,6 à 1,1 s par case, 850 Mo de RAM |
| `mobilesam` (28,2 + 15,7 Mo) | détourage | Apache-2.0 | 0,39 s de chargement, encodeur 0,61 s par case, 560 Mo de RAM |
