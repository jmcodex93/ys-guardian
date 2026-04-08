# YS Guardian — Roadmap

## Completed (v1.0.4 → v1.4.0)

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

### v1.4.0 Features ✅

#### Take-based QC ✅
- [x] Validate camera assigned per take
- [x] Validate output path contains $take token per take
- [x] Handle inherited render data from Main Take
- [x] Info button with per-take detail
- [x] Included in QC report export

#### Scene Collector ✅
- [x] Pre-flight: runs all 10 QC checks, shows summary, offers auto-fix
- [x] Collect: calls c4d.documents.SaveProject() (native asset collection)
- [x] Manifest: generates ys_guardian_manifest.json with scene info, assets, missing list
- [x] Complements C4D native — does NOT duplicate it

#### Light Groups AOV ✅
- [x] Independent button (not tied to Essentials/Production)
- [x] Scans lights for group assignments (RS Light + RS Object Tag + RS Sky)
- [x] Diagnostic: shows groups found, ungrouped lights
- [x] Toggle: activate/deactivate "All Light Groups" on Beauty AOV only
- [x] Show AOVs displays Light Groups status + group names
- [x] Avoids explosion problem (only on Beauty, not per material AOV)

#### Apply Color Processing ✅ (Investigated, left at default)
- [x] Investigated: in ACEScg pipeline, ON/OFF produces identical results
- [x] Decision: leave at RS default (ON) — no-op in properly configured OCIO pipeline
- [x] Documented in RS_AOV_PARAM_IDS.md

#### Other v1.4.0 changes ✅
- [x] UI reorganized by workflow: QC → Scene Tools → Render → Output
- [x] Render section unified (Presets + AOVs)
- [x] Reset All from template + Force 9:16 toggle
- [x] Resolution display next to preset dropdown
- [x] Legacy snapshot files moved to plugin/legacy/

---

## Pending — Next Phases

### v1.5.0 — Production Workflow (Tier A: High impact, easy)

#### Smart Incremental Save
One-click version bump with required comment:
- `scene_v001.c4d` → `scene_v002.c4d` automatically
- Prompt for comment on save (stored in sidecar JSON)
- Version history browseable from the panel
- No external tools needed — pure file convention

**Why**: No versioning exists. Artists overwrite or manually rename. Mistakes are unrecoverable.

#### Scene Notes / TODO
Per-scene notes and checklist visible in the panel:
- Comment field stored in document UserData or sidecar JSON
- TODO checklist (e.g., "Fix lighting on s020", "Client feedback: warmer tones")
- Persists between sessions
- Included in QC export and Scene Collector manifest

**Why**: Context gets lost between sessions and between artists. Notes in Slack/email get buried.

#### Review Slate on Snapshots
Burn metadata into Save Still PNGs:
- Shot ID, Artist name, Frame number, Date, Resolution
- Small overlay bar at bottom (like editorial slates)
- Supervisor instantly knows the context of every image

**Why**: Unnamed PNGs on a server are useless without context. Every image should be self-documenting.

#### FPS + Frame Range Validation (QC check #11)
New quality check:
- Verify project FPS matches studio standard (configurable: 24/25/30)
- Verify frame range is not "Current Frame" (animation renders)
- Verify frame range makes sense (start < end, reasonable length)
- Warn if "All Frames" selected (renders entire timeline)

**Why**: Wrong FPS or frame range are silent errors that waste hours of render time.

### v1.6.0 — Multi-Format & Asset Health (Tier B: High impact, medium effort)

#### Multi-Format Render Setup
One-click duplicate render settings for multiple aspect ratios:
- 16:9 (landscape), 9:16 (Reels/Stories), 1:1 (Instagram), 4:5 (Feed)
- Each format gets correct resolution + output path with format token
- Camera framing guide per format (if possible)
- Essential for social media motion graphics delivery

**Why**: Studios deliver the same animation in 3-5 formats. Manual duplication is error-prone and slow.

#### Texture Repathing Tool
Bulk find-and-replace for texture paths:
- Show all textures with current paths
- Find/replace path prefixes (e.g., `/Users/old/` → `/server/project/`)
- One-click "make all relative"
- Works with classic shaders AND RS node materials

**Why**: Moving projects between machines/servers breaks all texture paths. This is a daily pain point.

#### Post-Render Validation
Verify render output after completion:
- Check all expected AOV files exist
- Detect zero-byte files (failed frames)
- Verify frame sequence completeness (no gaps: frame 1-100 should have 100 files)
- Report missing/corrupt frames

**Why**: Discovering missing frames after a 12-hour render wastes another render cycle.

#### Scene Complexity Budget
Visual budget meter for scene resources:
- Total polygon count vs configurable budget
- Texture memory estimate vs GPU VRAM
- Object count, light count
- Green/yellow/red status per metric
- Configurable thresholds per studio

**Why**: Artists don't realize a scene is too heavy until render fails with out-of-memory.

### Backlog — Consider Later

#### MessageData Plugin
Background monitoring with panel closed. Invasive — reconsider when plugin is mature.

#### Template Configurable
Supervisor chooses .c4d template from shared server. Add "..." button next to Reset All.

#### Dropdown Dinámico de Presets
Show presets that exist in scene, not just hardcoded 4.

#### Keyboard Shortcuts
Atajos for Export QC, refresh, panel toggle.

#### Denoise Toggle per AOV
Auto-enable denoise on noisy passes (GI, SSS). Needs param ID probe.

#### Slack/Teams Webhook
Notify channel on Collect Scene or QC pass. Low effort, nice-to-have.

#### Comp Tag Manager
Bulk view/edit Object Buffer IDs, detect duplicates.

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
