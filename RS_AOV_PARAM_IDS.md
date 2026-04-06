# Redshift AOV Parameter IDs - Cinema 4D 2026

Discovered by probing RS VideoPost and RSAOV objects.
These IDs are NOT exposed as named constants in the c4d Python module.

## RS VideoPost (Render Settings)

### Caustics Tab
| ID | Name | Type | Values |
|----|------|------|--------|
| 9013 | Caustics > Enabled | int | 0=off, 1=on |
| 9014 | Caustics Engine | int | 2=Brute Force |
| 9015 | Global Caustics | int | 0=off, 1=on |
| 9016 | Reflection Caustics | int | 0=off, 1=on |
| 9017 | Refraction Caustics | int | 0=off, 1=on |
| 9018 | Light Casts Caustics | int | 0=off, 1=on |
| 9019 | Disable Intensity Clamp | int | 0=off, 1=on |
| 9020 | Brute Force Rays | int | default=256 |
| 9021 | Indirect Caustics | int | 0=off, 1=on |
| 9010 | (unknown) | int | 200 |
| 9011 | (unknown) | float | 0.1 |
| 9022 | (unknown) | int | 100000 |

## RSAOV Object (Per-AOV Settings)

### Named Constants (exist in c4d module)
| Constant | ID | Purpose |
|----------|-----|---------|
| REDSHIFT_AOV_TYPE | — | AOV type enum |
| REDSHIFT_AOV_NAME | — | AOV display name |
| REDSHIFT_AOV_ENABLED | — | Master enable |
| REDSHIFT_AOV_MULTIPASS_ENABLED | 5000 | Multi-Pass output enable |
| REDSHIFT_AOV_MULTIPASS_BIT_DEPTH | 1002 | Multi-Pass bits per channel |
| REDSHIFT_AOV_BITS_PER_CHANNEL | 1002 | Alias for above |

### Discovered IDs (no named constant)
| ID | Name | Type | Values | Section |
|----|------|------|--------|---------|
| 5000 | Multi-Pass > Enabled | int | 0=off, 1=on | Multi-Pass Output |
| 5001 | Direct Output > Enabled | int | 0=off, 1=on | Direct Output |
| 6000 | Direct > Path | str | `$filepath$filename_$pass` | Direct Output |
| 6001 | Direct > Data Type | int | 0=RGB, 3=? | Direct Output |
| 6002 | Direct > Data Type | int | 0=RGB, 1=RGBA | Direct Output |
| 6003 | Direct > Format+BitDepth | int | 3=OpenEXR 16-bit half, 4=OpenEXR 32-bit float | Direct Output |
| 6004 | Direct > (unknown, always 1) | int | 1 (read-only?) | Direct Output |
| 6005 | Direct > Storage | int | 0=Scanline, 1=Tiled | Direct Output |
| 6006 | Direct > Compression quality | int | 95 | Direct Output |
| 6007 | Direct > DWA Compression | float | 45.0 | Direct Output |
| 6008 | Direct > Effective Path | str | (read-only, computed) | Direct Output |

### AOV Type Constants (exist in c4d module)
Discovered by `getattr(c4d, "REDSHIFT_AOV_TYPE_*")`:

| AOV | Constant | Numeric ID |
|-----|----------|------------|
| Depth | REDSHIFT_AOV_TYPE_DEPTH | 1 |
| Cryptomatte | REDSHIFT_AOV_TYPE_CRYPTOMATTE | 42 |
| World Position | REDSHIFT_AOV_TYPE_WORLD_POSITION | 8 |
| Normals | REDSHIFT_AOV_TYPE_NORMALS | 24 |
| Motion Vectors | REDSHIFT_AOV_TYPE_MOTION_VECTORS | 3 |
| Diffuse Lighting | REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING | 5 |
| Reflections | REDSHIFT_AOV_TYPE_REFLECTIONS | 11 |
| Object-Space Position | REDSHIFT_AOV_TYPE_OBJECT_SPACE_POSITION | 2 |
| GI | REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION | (probed) |
| Specular Lighting | REDSHIFT_AOV_TYPE_SPECULAR_LIGHTING | (probed) |
| Emission | REDSHIFT_AOV_TYPE_EMISSION | (probed) |
| SSS | REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER | (probed) |
| Refractions | REDSHIFT_AOV_TYPE_REFRACTIONS | (probed) |
| Ambient Occlusion | REDSHIFT_AOV_TYPE_AMBIENT_OCCLUSION | (probed) |
| Diffuse Filter | REDSHIFT_AOV_TYPE_DIFFUSE_FILTER | (probed) |
| Volume Lighting | REDSHIFT_AOV_TYPE_VOLUME_LIGHTING | (probed) |
| Volume Fog Tint | REDSHIFT_AOV_TYPE_VOLUME_FOG_TINT | (probed) |
| Volume Fog Emission | REDSHIFT_AOV_TYPE_VOLUME_FOG_EMISSION | (probed) |
| Shadows | REDSHIFT_AOV_TYPE_SHADOWS | (probed) |
| Caustics | REDSHIFT_AOV_TYPE_CAUSTICS | (probed) |
| Bump Normals | REDSHIFT_AOV_TYPE_BUMP_NORMALS | (probed) |
| Diffuse Lighting Raw | REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING_RAW | (probed) |

### RS Object Detection
| Object | Plugin ID | Purpose |
|--------|-----------|---------|
| RS Environment | 1036757 | Global fog/atmosphere (triggers Volume AOVs) |
| RS Volume | 1038655 | Localized volumes like smoke/fire (triggers Volume AOVs) |
| RS Light | 1036751 | Redshift light |
| RS Camera | 1057516 | Redshift camera |

## Notes
- `FindAddVideoPost` creates the VP if it doesn't exist — use carefully
- AOV params are set via `RSAOV.SetParameter(id, value)` not `aov[id] = value`
- Multi-Pass bit depth (1002) is separate from Direct Output bit depth (6004)
- Cryptomatte requires Direct Output only (Multi-Pass produces broken results)
- `REDSHIFT_AOV_DIRECT_ENABLED` does NOT exist as a named constant — use raw ID 5001
