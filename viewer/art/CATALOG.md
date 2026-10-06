# Sprite catalog

All names in the atlas (`viewer/sprites_data.js`, built by `python scripts/build_sprites.py` from the sheets here).
Draw any of them with `Sprites.draw(g, name, x, y, {s, flip, alpha})` (bottom-centre at x, y, map pixels; 16 px
tiles, a villager is 22 px tall). Sizes are set in `SIZE` in the build script. All art: SpriteCook, gpt-image-2.

## In use

| Sheet | Names |
|---|---|
| `terrain.png` | `tex_grass`, `tex_grass2`, `tex_flowers`, `tex_dirt`, `tex_cobble`, `tex_soil`, `tex_soil_wet`, `tex_sand`, `tex_water`, `tex_deep`, `tex_planks`, `tex_gravel`, `tex_wheat`, `tex_crops`, `tex_moss`, `tex_slabs` (48x48, seamless; used: grass, grass2, flowers, dirt, cobble, soil, water, deep, planks, gravel, moss) |
| `buildings.png` | `house1..3` (+ `_r0.._r5` roof colours), `market`, `smithy`, `mine`, `coop`, `hives`, `well` |
| `houses.png` | `house1a/b/c` (stone, log, plaster cottage), `house2a/b/c` (tudor, brick, porch), `house3a/b/c` (manor, balcony, townhouse), each with `_r0.._r5`; a home picks one of four looks per level by its owner's name |
| `nature.png`, `farm.png`, `fx.png` | trees, bushes, rocks, soil stages, cow, hen, hive, fence, scarecrow, lamp, fire0-3, tools, food (see `SHEETS`) |
| `landscape.png` | `reeds`, `lilypads`, `signpost` (also: `bridge`, `pier`, `rowboat`, `stepping_stones`, `pond_small`, `quarry_pit`, `fallen_log`, `campfire`, `flowerbed`, `tall_grass`, `mushroom_ring`, `woodpile`, `notice_board`) |
| `yard.png` | `fence_h`, `fence_v` (all fences) (also: `fence_corner`, `fence_gate`, `picket_fence`, `stone_wall`, `for_sale`, `lot_stakes`, `bed_empty`, `bed_sprouts`, `bed_ripe`, `mailbox`, `pigsty`, `small_barn`, `doghouse`, `path_slab`) |
| `mine.png` | `mine_cart`, `coal_crate`, `rubble` (also: `mine_big`, `rails`, `ore_pile`, `amethyst_rock`, `emerald_rock`; fights: `d20`, `d6`, `fight_dust`, `hit_star`, `heart`, `heart_broken`, `bandage`, `dizzy`, see `Sprites.brawl`) |
| `chars1..4.png` | villagers `v0..v23` x `down`, `step`, `up`, `side`; `Sprites.villager(k)` builds the walk sheet |

## Ready for later (not drawn yet)

| Sheet | Names |
|---|---|
| `weapons.png` | `shovel`, `pitchfork`, `club`, `knife`, `wood_sword`, `sword`, `axe2`, `sickle`, `scythe`, `spear`, `slingshot`, `shield`, `bow`, `crowbar`, `torch`, `rolling_pin` (drawn pointing up-right, ~10 px) |
| `animals.png` | `pig`, `sheep`, `goat`, `cow2`, `hen2`, `rooster`, `duck`, `chick`, `horse`, `dog`, `cat`, `rabbit`, `sheep_shorn`, `pig_black`, `cow_lying`, `hen_nest` (side view, facing right) |
| `items.png` | `egg_basket`, `milk`, `honey`, `wool`, `cheese`, `carrots`, `cabbage`, `pumpkin`, `corn`, `grain_sack`, `apple`, `berries`, `iron_ingot`, `gold_ingot`, `gem`, `coin_pouch` (icons) |
| `property.png` | `foundation`, `house_frame`, `scaffold` (building stages), `planks_stack`, `bricks`, `stone_blocks`, `sawhorse`, `ladder`, `sold_sign`, `deed`, `key`, `padlock`, `treasure_chest`, `strongbox`, `wanted_poster`, `stocks` |
| `business.png` | `forge`, `store`, `bakery`, `tavern`, `windmill`, `barn`, `town_hall`, `warehouse`, `chapel` |
| `business2.png` | `smithy2`, `butcher`, `tailor`, `carpenter`, `fishmonger`, `bank`, `stable`, `pottery`, `herbalist` |

New art: add a sheet here (objects in a grid on a transparent or white background), list it in `SHEETS` and `SIZE`
in `scripts/build_sprites.py`, run it, and draw by name. Roof recolouring works for red-roofed houses (`ROOF_HUE`).
