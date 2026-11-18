# Wii Sports Resort — Golf Randomizer

Mod Riivolution pour le golf de Wii Sports Resort : **les trous changent à chaque partie**.

Les cartes de Nintendo servent de base (mer, falaises, décor), mais tout le reste est refait : green et drapeaux déplacés, fairway qui tourne, étangs déplacés, relief, bunkers, arbres, carte en miroir. 18 trous (Resort et Classic), 16 variantes chacun, et la Wii ajoute encore son propre relief au chargement : deux parties ne se ressemblent jamais.

## Installation

Il te faut ton propre dump de **Wii Sports Resort PAL (RZTP01, rév. 1)**. Aucun fichier du jeu n'est fourni.

1. Génère les cartes depuis ton dump (voir plus bas). Tu obtiens un dossier `full` et un fichier `wsrgolf_full.xml`.
2. Copie-les sur ta carte SD :
   - `wsrgolf_full.xml` → `/riivolution/`
   - le dossier `full` → `/wsrgolf/full/`
3. Lance **Riivolution** sur la Wii, choisis Wii Sports Resort, active l'option **Golf generateur**, puis lance le jeu.

Sur **Dolphin** : même arborescence dans le dossier `Load/Riivolution`, puis clic droit sur le jeu → *Start with Riivolution Patches*.

## Générer les cartes

Python 3 avec `numpy`, `scipy`, `shapely`, `triangle`, `Pillow`, plus `gcc` et `powerpc-linux-gnu-gcc`. Les scripts supposent le projet dans `/home/user/wsr`, ton dump extrait dans `/home/user/wsr/files` et la sortie dans `/home/user/wsr/out` : adapte ces chemins à ta machine.

```sh
NMODE=2 MIRROR=1 python3 ingame/build_pool3.py pool 16 23000     # variantes
cd ingame/gen && python3 build.py                                 # générateur Wii
python3 make_full.py 16 pool full "Golf Randomizer"               # option Riivolution
cd .. && python3 fix_pool.py pool full "Golf Randomizer"          # vérifications
```

## Contenu

- `tools/` : lecture/écriture des formats du jeu (BRRES, KCL, PMP, U8/Yaz0) et génération des variantes.
- `ingame/` : assemblage de l'option Riivolution et code qui tourne sur la Wii (`gen/`).
- `scripts/` : tests et rendus.
