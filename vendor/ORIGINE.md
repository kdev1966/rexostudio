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
- **Mise à jour** : recopier le dossier depuis rawi (sans `__pycache__`, `.pytest_cache`,
  `.ruff_cache`, `*.egg-info`), noter ici le nouveau commit, relancer
  `./scripts/check_install.sh`.
