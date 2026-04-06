# Redshift AOV Parameter IDs - Cinema 4D 2026

> **Why this file exists**: Maxon does NOT document the internal parameter IDs
> for Redshift AOV objects in their Python SDK. All IDs in this file were
> discovered by probing RSAOV and RS VideoPost objects at runtime, comparing
> values before and after manual changes in the AOV Manager UI.
>
> These IDs may change between RS/C4D versions. If something breaks after an
> update, re-probe using the technique described in the Discovery Method section.

---

## RSAOV Object — Direct Output Parameters

The primary output method for production. Each AOV has its own Direct Output config.

| ID | Name | Type | Values | Verified |
|----|------|------|--------|----------|
| 5001 | Direct Output > Enabled | int | 0=off, 1=on | Yes — toggled on/off, confirmed in UI |
| 6000 | Direct > Path | str | `$filepath$filename_$pass` (default) | Yes — read matches UI |
| 6001 | Direct > Data Type | int | 0=RGB, 1=RGBA, 3=Scalar (auto for Depth) | Yes — changed RGB→RGBA, confirmed |
| 6003 | Direct > Format + Bit Depth | int | 3=OpenEXR Half Float (16-bit), 4=OpenEXR Float (32-bit) | Yes — changed 16→32 on Depth, confirmed |
| 6005 | Direct > Storage | int | 0=Scanline, 1=Tiled | Assumed from RS docs |
| 6006 | Direct > Compression | int | 95 (default) | Read-only probe |
| 6007 | Direct > DWA Compression | float | 45.0 (default, "perceptually lossless") | Read-only probe |
| 6008 | Direct > Effective Path | str | Computed, read-only | Yes — shows resolved path |

### IDs with unknown purpose (always constant in probes)
| ID | Value | Notes |
|----|-------|-------|
| 6002 | 0 | Always 0 across all AOV types. Unknown purpose. |
| 6004 | Compression | 1=Default, 201=ZIP, 202=ZIPS, 203=PIZ, 206=DWAA, 207=DWAB. Was misidentified as bit depth initially. |
| 6009 | None | Empty / not set |

---

## RSAOV Object — Multi-Pass Parameters

C4D-integrated output method. Less control than Direct Output.

| ID / Constant | Name | Type | Values | Verified |
|---------------|------|------|--------|----------|
| 5000 / `REDSHIFT_AOV_MULTIPASS_ENABLED` | Multi-Pass > Enabled | int | 0=off, 1=on | Yes |
| 1002 / `REDSHIFT_AOV_BITS_PER_CHANNEL` | Multi-Pass > Bits Per Channel | int | 0=8-bit, 1=16-bit half, 2=32-bit float | Yes |

---

## RSAOV Object — General Parameters

| ID / Constant | Name | Type | Values | Verified |
|---------------|------|------|--------|----------|
| `REDSHIFT_AOV_TYPE` | AOV Type | int | See type table below | Yes |
| `REDSHIFT_AOV_NAME` | Display Name | str | User-editable name | Yes |
| `REDSHIFT_AOV_ENABLED` | Master Enable | bool | True/False | Yes |

### AOV Option Params (ID range 1000-1029)
| ID | Name | Type | Default | Notes |
|----|------|------|---------|-------|
| 1000 | (AOV Type numeric) | int | varies | Mirrors REDSHIFT_AOV_TYPE |
| 1001 | (AOV Name) | str | varies | Mirrors REDSHIFT_AOV_NAME |
| 1002 | Multi-Pass Bit Depth | int | 2 (32-bit) | Multi-Pass only |
| 1003 | (unknown) | int | 1 | |
| 1004 | Depth: Filter Type | int | 0=Full, 1=Min Depth, 2=Max Depth, 3=Center Sample | 3 for Nuke (no interpolation) |
| 1005 | (unknown) | Vector | (1,1,1) | |
| 1006 | Apply Color Processing | int | 1=on | Should be 0 for compositing |
| 1007 | (unknown) | int | 0 | |
| 1008 | MV: Output Raw Vectors | int | 0=off, 1=on | ON for Nuke (raw pixel displacement) |
| 1009 | MV: No Clamp | int | 0=off, 1=on | ON for Nuke (preserve full motion range) |
| 1010 | MV: Max Motion (pixels) | int | 8 | Irrelevant when No Clamp=ON |
| 1011 | MV: Image Output Min | float | 0.0 | Irrelevant when Raw Vectors=ON |
| 1012 | MV: Image Output Max | float | 1.0 | Irrelevant when Raw Vectors=ON |
| 1013 | MV: Filtering | int | 1=on, 0=off | OFF for Nuke (prevents edge smearing) |
| 1019 | Depth: Depth Mode | int | 0=Z, 1=Z Normalized, 2=Z Normalized Inverted | 0 for Nuke (planar Z) |
| 1020 | Depth: Use Camera Near/Far | int | 1=on, 0=off | OFF for Nuke (raw world units) |
| 1021 | Depth: Minimum Depth | float | 0.0 | |
| 1022 | Depth: Maximum Depth | float | 10000.0 | |
| 1024 | Depth: Env Rays to Black | int | 1=on | ON (sky=0, maskable in comp) |

---

## RS VideoPost — Caustics Parameters

Located in RS Render Settings > Caustics tab.

| ID | Name | Type | Values | Verified |
|----|------|------|--------|----------|
| 9013 | Enabled | int | 0=off, 1=on | Yes — toggled on/off, confirmed |
| 9014 | Caustics Engine | int | 2=Brute Force | Read-only (always 2 in tests) |
| 9015 | Global Caustics | int | 0=off, 1=on | Read from probe |
| 9016 | Reflection Caustics | int | 0=off, 1=on | Read from probe |
| 9017 | Refraction Caustics | int | 0=off, 1=on | Read from probe |
| 9018 | Light Casts Caustics | int | 0=off, 1=on | Read from probe |
| 9019 | Disable Intensity Clamp | int | 0=off, 1=on | Read from probe |
| 9020 | Brute Force Rays | int | 256 (default) | Read from probe |
| 9021 | Indirect Caustics | int | 0=off, 1=on | Read from probe |

---

## AOV Type Constants

These exist as named constants in the `c4d` module (`c4d.REDSHIFT_AOV_TYPE_*`).

| AOV | Constant Name | Numeric ID |
|-----|---------------|------------|
| Depth | `REDSHIFT_AOV_TYPE_DEPTH` | 1 |
| Object-Space Position | `REDSHIFT_AOV_TYPE_OBJECT_SPACE_POSITION` | 2 |
| Motion Vectors | `REDSHIFT_AOV_TYPE_MOTION_VECTORS` | 3 |
| Diffuse Lighting | `REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING` | 5 |
| World Position | `REDSHIFT_AOV_TYPE_WORLD_POSITION` | 8 |
| Reflections | `REDSHIFT_AOV_TYPE_REFLECTIONS` | 11 |
| Normals | `REDSHIFT_AOV_TYPE_NORMALS` | 24 |
| Cryptomatte | `REDSHIFT_AOV_TYPE_CRYPTOMATTE` | 42 |
| GI | `REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION` | discovered via fallback probe |
| Specular Lighting | `REDSHIFT_AOV_TYPE_SPECULAR_LIGHTING` | exists, ID not logged |
| Emission | `REDSHIFT_AOV_TYPE_EMISSION` | exists, ID not logged |
| SSS | `REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER` | exists, ID not logged |
| Refractions | `REDSHIFT_AOV_TYPE_REFRACTIONS` | exists, ID not logged |
| Ambient Occlusion | `REDSHIFT_AOV_TYPE_AMBIENT_OCCLUSION` | exists, ID not logged |
| Diffuse Filter | `REDSHIFT_AOV_TYPE_DIFFUSE_FILTER` | exists, ID not logged |
| Reflection Filter | `REDSHIFT_AOV_TYPE_REFLECTION_FILTER` | exists, ID not logged |
| Diffuse Lighting Raw | `REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING_RAW` | exists, ID not logged |
| Volume Lighting | `REDSHIFT_AOV_TYPE_VOLUME_LIGHTING` | exists, ID not logged |
| Volume Fog Tint | `REDSHIFT_AOV_TYPE_VOLUME_FOG_TINT` | exists, ID not logged |
| Volume Fog Emission | `REDSHIFT_AOV_TYPE_VOLUME_FOG_EMISSION` | exists, ID not logged |
| Shadows | `REDSHIFT_AOV_TYPE_SHADOWS` | exists, ID not logged |
| Caustics | `REDSHIFT_AOV_TYPE_CAUSTICS` | exists, ID not logged |
| Bump Normals | `REDSHIFT_AOV_TYPE_BUMP_NORMALS` | exists, ID not logged |

### Constants that DO NOT exist (tried and failed)
- `REDSHIFT_AOV_DIRECT_ENABLED` — use raw ID 5001 instead
- `REDSHIFT_AOV_TYPE_GI` — use `REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION`
- `REDSHIFT_AOV_TYPE_SSS` — use `REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER`

---

## RS Object Plugin IDs (Scene Detection)

| Object | Plugin ID | Used For |
|--------|-----------|----------|
| RS Environment | 1036757 | Global fog/atmosphere → triggers Volume AOVs |
| RS Volume | 1038655 | Localized volumes (smoke/fire) → triggers Volume AOVs |
| RS Light | 1036751 | Redshift light (+ additional types: 1036754, 1038653, 1036950, 1034355, 1036753) |
| RS Camera | 1057516 | Redshift camera |
| RS Texture Sampler (legacy shader) | 1036227 | Legacy GV texture node |
| Alembic Generator | 1028083 | Alembic file reference |
| Alembic Tag | 1028081 | Alembic tag on objects |

---

## RS Node Material

| Item | Value |
|------|-------|
| Node Space ID | `com.redshift3d.redshift4c4d.class.nodespace` |
| Render Engine ID | 1036219 |
| Graph access | `mat.GetNodeMaterialReference().GetGraph(RS_NODESPACE)` |
| Root node | `graph.GetViewRoot()` (NOT `GetRoot()` — deprecated since 2025) |
| Port values | `port.GetPortValue()` (NOT `GetDefaultValue()` — deprecated since 2024.4) |
| Texture path | Stored in nested sub-ports of TextureSampler nodes. Recursive scan required. |
| maxon.Url → path | `val.GetSystemPath()` or `val.ToString()` |

---

## YS Guardian AOV Configuration

### Per-AOV Settings Applied by Plugin

| Setting | Beauty AOVs | Utility AOVs | Source |
|---------|-------------|--------------|--------|
| Direct Output | ON (5001=1) | ON (5001=1) | All AOVs use Direct |
| Multi-Pass | OFF (5000=0) | OFF (5000=0) | Disabled for all |
| Data Type | RGBA (6001=1) | RGB (6001=0) | Beauty needs alpha for transparency |
| Format + Depth | EXR 16-bit (6003=3) | EXR 32-bit (6003=4) | Utility needs float precision |
| Compression | Default (6006=95) | Default | Not modified |
| DWA | 45.0 (6007=45.0) | 45.0 | Not modified (perceptually lossless) |
| Storage | Scanline (6005=0) | Scanline | Not modified |

### Beauty AOVs (RGBA, EXR 16-bit half)
Diffuse Lighting, GI, Specular Lighting, Reflections, SSS, Refractions,
Emission, Caustics*, Volume Lighting*, Volume Fog Tint*, Volume Fog Emission*,
Shadows, Diffuse Filter, Reflection Filter, Diffuse Lighting Raw,
Refractions Raw, Ambient Occlusion

### Utility AOVs (RGB, EXR 32-bit float)
Depth, Motion Vectors, Cryptomatte, World Position

### Utility AOVs (RGB, EXR 16-bit half)
Normals, Bump Normals

*Conditional: Caustics added only when Caustics Enabled (9013=1).
Volume AOVs added only when RS Environment (1036757) or RS Volume (1038655) in scene.

### Beauty Rebuild Equation
```
Beauty = (Diffuse + GI + Specular + Reflections + SSS + Refractions
         + Emission + Caustics) × Volume Fog Tint
         + Volume Lighting + Volume Fog Emission
```

---

## Discovery Method

To find unknown parameter IDs:

1. Create/select an AOV in the AOV Manager
2. Note the current value of the setting you want to control
3. Add probe code to dump a range of param IDs:
```python
for pid in range(START, END):
    try:
        val = aov.GetParameter(pid)
        if val is not None:
            print(f"id={pid} val={val} type={type(val).__name__}")
    except:
        pass
```
4. Change the setting manually in the AOV Manager UI
5. Run the probe again and compare — the changed ID is your target

Known ID ranges:
- 1000-1009: AOV options (type, name, denoise, color processing)
- 5000-5001: Output enables (Multi-Pass, Direct)
- 6000-6009: Direct Output config (path, data type, format, compression)
- 9010-9022: RS VideoPost Caustics tab
