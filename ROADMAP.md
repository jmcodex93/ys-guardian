# YS Guardian — Roadmap

## Completed (v1.0.4 → v1.3.0)

### Fase 1 — Fix & Foundation ✅
- [x] Fix bug: safe_print used before definition
- [x] Fix bug: duplicate widget IDs in class G
- [x] Cross-platform: replace os.startfile with platform-aware opener
- [x] Add CoreMessage() for instant scene change reaction
- [x] Clean dead code: remove unused IDs, imports, threading

### Fase 2 — UI Upgrade ✅
- [x] Section headers with BORDER_WITH_TITLE_BOLD
- [x] Per-check Select/Info/Fix buttons (1 click instead of checkbox + Select)
- [x] Fix truncated labels (Shot ID, Artist)
- [x] Data-driven StatusArea renderer (lookup table, pre-allocated colors)
- [x] Reorganize layout by workflow: Scene Info → QC → Scene Tools → Render → Output

### Fase 3 — New QC Checks ✅
- [x] Unused materials (Select + Fix, cycling one-by-one)
- [x] Default naming conventions (Select, cycling)
- [x] Output path validation (tokens, empty paths)
- [x] Missing textures (files not found on disk)
- [x] RS Node texture paths via maxon API (recursive port scan)
- [x] Unify 3 texture checks into single "Assets" check

### Fase 4 — Power Features ✅
- [x] Auto-fix: lights → group, camera shift → reset, unused mats → delete
- [x] Export QC Report (JSON with score, scene stats, all check details)
- [x] Scene complexity stats (objects, polygons, materials, lights)

### Snapshot System Rewrite ✅
- [x] Cross-platform EXR→PNG via external Python + OpenEXR
- [x] Full ACES pipeline: ACEScg → sRGB matrix → ACES tonemap → sRGB OETF
- [x] Configurable RS snapshot directory (UI button + persisted settings)
- [x] Auto-discover system Python on macOS + Windows

### RS AOV Management ✅
- [x] 2-tier system: Essentials (11) / Production (17+)
- [x] Beauty pass in Essentials for rebuild verification
- [x] Conditional AOVs: Caustics (auto-detect setting), Volumes (auto-detect objects)
- [x] Compositor target dropdown: Nuke vs After Effects (persisted)
- [x] Multi-Part EXR checkbox (persisted)
- [x] Per-AOV Direct Output config: bit depth, data type, compression
- [x] Depth config per compositor: Z raw (Nuke) vs Z Normalized Inverted (AE/Frischluft)
- [x] Motion Vectors per compositor: Raw (Nuke) vs Normalized 0-1 (AE/RSMB Pro)
- [x] Global Multi-Part settings: 32-bit Float + DWAB 45
- [x] All param IDs documented in RS_AOV_PARAM_IDS.md
- [x] Named constants used throughout (discovered via dir(c4d))

### Render Presets ✅
- [x] Resolution display next to dropdown
- [x] Reset All from template (with confirmation)
- [x] Force 9:16 ↔ 16:9 toggle (reversible)
- [x] Rename buttons: Force → Reset All / Force 9:16

### Code Quality ✅
- [x] Replace 40 bare except: with except Exception:
- [x] Remove dead code (~400 lines: _force_vertical_aspect, _search_3d_model, _ask_chatgpt, etc.)
- [x] CoreMessage dirty-flag pattern (no more cache clearing on every EVMSG_CHANGE)
- [x] CHECK_COOLDOWN 0.1s → 0.5s
- [x] Safe name access for dead C4D objects (_safe_name helper)
- [x] Widget IDs renamed to match function (BTN_FORCE_VERTICAL, BTN_RESET_ALL, etc.)

---

## Pending — Next Phases

### Priority 1 — High Impact, Medium Effort

#### Take-based QC
Validate per-take configuration for multi-shot scenes:
- Each take has correct camera assigned
- Each take has correct render preset
- Each take has configured output path
- Report missing/misconfigured takes in QC

**Why**: Multi-take scenes are standard in production. A missing camera or wrong preset on one take means broken renders that only surface at render time.

#### Scene Collector / Package
Prepare scene for delivery or render farm:
- Collect all assets (textures, alembics, references)
- Verify all paths are relative
- Copy to organized output structure
- Generate manifest/report

**Why**: The most common production failure is missing assets on the render farm. Automating collection prevents this.

### Priority 2 — Medium Impact, Medium Effort

#### MessageData Plugin
Background monitoring even when the panel is closed:
- Register a MessageData plugin alongside CommandData
- Listen to EVMSG_CHANGE globally
- Show notification when opening a scene with QC issues
- Optional: console warning on scene save if issues exist

**Why**: Artists forget to open the panel. Background monitoring catches problems earlier.

#### Light Groups AOV
Auto-detect lights in the scene and create light group AOVs:
- Scan for RS lights and their names/groups
- Create per-group AOVs (Key, Fill, Rim, etc.)
- Configure as RGBA + DWAB like other beauty AOVs

**Why**: Light groups are essential for commercial/advertising work where per-light control is needed in post.

#### Apply Color Processing OFF
Automatically disable "Apply Color Processing" (ID 1006=0) on all AOVs:
- Compositors need linear data, not baked color transforms
- Currently left at default (1=on) which bakes OCIO view transform

**Why**: If Apply Color Processing is on, the AOVs won't composite correctly — the data is no longer linear.

### Priority 3 — Lower Impact, Easy

#### Template Configurable
Let the supervisor choose the template .c4d file:
- Add "..." button next to Reset All
- Path saved in settings (like snapshot dir)
- Supervisor puts template on shared server
- All artists use same template without modifying plugin

#### Dropdown Dinámico de Presets
Show whatever presets exist in the scene, not just the 4 hardcoded:
- Read all RenderData names from the document
- Populate dropdown dynamically
- Still highlight non-standard names in QC

#### Keyboard Shortcuts
Register shortcuts for frequent actions:
- Export QC Report
- Refresh checks
- Open/close panel

#### Cleanup Old Auxiliary Files
Remove files no longer imported:
- `redshift_snapshot_manager_fixed.py`
- `exr_to_png_converter_simple.py`
- `python_path_config.py`

These are kept for reference but add confusion. Could be moved to a `legacy/` folder.

---

## Research Notes

### RS AOV System
- All parameter IDs documented in `RS_AOV_PARAM_IDS.md`
- Named constants exist in c4d module but are NOT in Maxon's SDK docs
- Discovery method: `dir(c4d)` filter + manual probe comparison
- Multi-Part EXR overrides per-AOV bit depth/compression with global settings
- Caustics detection: RS VideoPost param 9013
- Volume detection: scene scan for RS Environment (1036757) / RS Volume (1038655)
- C4D 2026 API changes: GetViewRoot (not GetRoot), GetPortValue (not GetDefaultValue)

### Snapshot System
- BaseBitmap.GetPixelDirect clamps HDR to 0-1 — cannot do ACES tonemap in C4D Python
- External Python + OpenEXR is the only way to read raw float data
- ACES pipeline: ACEScg→sRGB matrix → 0.6 exposure → tone map curve → sRGB OETF
- macOS Python: /usr/bin/python3 with pip3 install OpenEXR numpy Pillow

### Compositing Compatibility
- Frischluft Lenscare: works with both raw Z and normalized — but Z Normalized Inverted is plug-and-play
- RSMB Pro: expects normalized 0-1 (0.5=no motion), NOT raw displacement
- Nuke ZDefocus: expects raw Z in world units
- Nuke VectorBlur: expects raw pixel displacement
- Depth Filter Type: always Center Sample (no interpolation at edges)
- Motion Vector Filtering: always OFF (prevents smearing)

### Sources
- [Maxon RS AOV Documentation](https://help.maxon.net/r3d/cinema/en-us/#html/Intro+to+AOVs.html)
- [Compositing Mentor CG Series](https://compositingmentor.com/category/cg-compositing-series/)
- [RE:Vision RSMB Motion Vector Format](https://revisionfx.com/faq/motion_vector/)
- [Frischluft Lenscare](https://www.frischluft.com/lenscare/)
- RS resource files: `vprsrenderer.h`, `drsaov.h` in C4D 2026 plugins folder
