# Rexo Atelier

Atelier des techniciens : il fabrique les **animations 3D** livrées à Rexo Studio.
Rexo Studio, l'outil du photographe, ne fait jamais de 3D. Il reçoit une bibliothèque
d'animations toutes prêtes, à la demande, et y place les photos des mariés avec EffectCraft.

| Dossier | Contenu |
|---|---|
| `blender/` | scripts Blender 3.6 : décors (`build_template_*.py`), outils communs (`scene_kit.py`), mouvements de drone (`drone_paths.py`), rendu d'une animation (`export_generic.py`) |
| `atelier/` | commande `python3 -m atelier` : textures (TextureCraft, MaterialCraft), décors, rendu, livraison |
| `docs/MODELES.md` | le guide : règles des décors, emplacements de photos, textures, titres, essais |
| `scenes/`, `textures/`, `livraison/` | fabrications (hors git, gros fichiers) |

```bash
python3 -m atelier textures marble tiles_ceramic clay brass   # textures TextureCraft
python3 -m atelier scene patio_nuit                           # scenes/patio_nuit.blend
python3 -m atelier animation patio_nuit sequence 9 normal --titre "Patio andalou de nuit"
python3 -m atelier livrer                                     # livraison/animations_<date>.zip
```

Puis, dans Rexo Studio : `python3 scripts/installer_animations.py animations_<date>.zip`.

Prérequis : Blender 3.6 LTS (`scripts/install_blender.sh` ; pas Blender 4, qui exige
Metal et plante sur l'iMac), TextureCraft et MaterialCraft (même éditeur que les outils
Craft de Rexo Studio). Les outils Craft sont lancés sur la carte graphique intégrée
(`WGPU_POWER_PREF=low`) : jamais la Radeon dédiée du MacBook Pro.

Format d'un paquet (« rexo-animation », version 1) : voir `atelier/animation.py`.
