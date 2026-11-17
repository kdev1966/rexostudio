"""Carte graphique des outils Craft (PhotoCraft, FilmCraft, EffectCraft, TextureCraft,
MaterialCraft) : toujours la carte econome, integree. Sur le MacBook Pro a deux cartes,
la Radeon dediee fait echouer les rendus (« GPU readback timed out »)."""

CRAFT_GPU_ENV = {"WGPU_POWER_PREF": "low"}
