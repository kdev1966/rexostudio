# Code repris d'autres projets

## embedkit

- **Origine** : projet rawi du même développeur, `~/Desktop/Tools/film/rawi/packages/embedkit`
  (dépôt `github.com/kdev1966/rawi`), commit local `cb7c213` (v0.3 étape 3, ADR 0008 de rawi),
  copié le 16 novembre 2026.
- **Licence** : Apache-2.0.
- **Pourquoi une copie** : ce commit n'est pas publié sur GitHub ; l'iMac reçoit le code de
  Rexo Studio par git, embedkit arrive ainsi avec lui. Il est utilisé tel quel par
  l'environnement d'effets (`.effets/`, voir `scripts/install_effects_env.sh`), via
  `PYTHONPATH=vendor/embedkit`, jamais par le cœur de Rexo Studio (bibliothèque standard).
- **Modification locale (à reporter dans rawi)** : `embedkit/runtimes/onnx.py` n'utilise
  plus « tous les fournisseurs disponibles » mais le processeur seul, sauf si
  `EMBEDKIT_ONNX_PROVIDERS` en liste d'autres. Le paquet onnxruntime 1.19.2 de PyPI inclut
  CoreML, qui échoue à l'exécution sur l'Iris Pro 6200 de l'iMac (« Error computing NN
  outputs », vu par `check_install.sh` le 16/11/2026) ; le build conda de rawi n'a que le CPU.
- **Mise à jour** : recopier le dossier depuis rawi (sans `__pycache__`, `.pytest_cache`,
  `.ruff_cache`, `*.egg-info`), noter ici le nouveau commit, relancer
  `./scripts/check_install.sh`.
