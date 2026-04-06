# -*- coding: utf-8 -*-
import c4d
from c4d import plugins, gui, documents
import os
import json
import time
import sys
import webbrowser
from collections import defaultdict

# ---------------- Safe Print Function ----------------
def safe_print(msg):
    """Print to console with null safety"""
    try:
        if msg is not None:
            print(f"[YS Guardian] {msg}")
    except (UnicodeEncodeError, AttributeError):
        pass  # Print failed, continue silently

# ---------------- Platform Utilities ----------------
def open_in_explorer(path):
    """Open a file or folder in the system file manager (cross-platform)"""
    import subprocess
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        safe_print(f"Could not open path: {path} - {e}")

# Import maxon for node material access
try:
    import maxon
    MAXON_AVAILABLE = True
except ImportError:
    MAXON_AVAILABLE = False

# Import Redshift module for AOV management
try:
    import redshift
    REDSHIFT_AVAILABLE = True
except ImportError:
    REDSHIFT_AVAILABLE = False

# Import maxon module path
sys.path.insert(0, os.path.dirname(__file__))

# Plugin ID - change if ID collision
PLUGIN_ID = 2099069
PLUGIN_NAME = "YS Guardian v1.2.0"

# Preset names - normalized to lowercase with underscores
# The system accepts both "pre_render" and "pre-render" (case-insensitive)
PRESETS = ["previz", "pre_render", "render", "stills"]

def normalize_preset_name(name):
    """Normalize preset name: lowercase, replace hyphens/spaces with underscores"""
    if not name:
        return ""
    return name.strip().lower().replace("-", "_").replace(" ", "_")

# Performance settings for watcher
MAX_OBJECTS_PER_CHECK = 1000  # Process in chunks
CACHE_DURATION = 2.0  # Cache results for 2 seconds (optimized for performance)
CHECK_COOLDOWN = 0.5  # Minimum time between checks

# Global settings file for artist name
SETTINGS_FILE = "ys_guardian_settings.json"

# ---------------- Settings Persistence ----------------
class GlobalSettings:
    """Manages computer-level settings (not scene-specific)"""

    @staticmethod
    def get_settings_path():
        prefs_path = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
        return os.path.join(prefs_path, SETTINGS_FILE)

    @staticmethod
    def _load():
        settings_path = GlobalSettings.get_settings_path()
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def _save(settings):
        try:
            with open(GlobalSettings.get_settings_path(), 'w') as f:
                json.dump(settings, f, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def get(key, default=''):
        return GlobalSettings._load().get(key, default)

    @staticmethod
    def set(key, value):
        settings = GlobalSettings._load()
        settings[key] = value
        return GlobalSettings._save(settings)

    @staticmethod
    def load_artist_name():
        return GlobalSettings.get('artist_name', '')

    @staticmethod
    def save_artist_name(artist_name):
        return GlobalSettings.set('artist_name', artist_name)

    @staticmethod
    def get_snapshot_dir():
        """Get configured RS snapshot directory, or platform default"""
        saved = GlobalSettings.get('snapshot_dir', '')
        if saved:
            return saved
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Caches/Redshift/Snapshots")
        return r"C:\cache\rs snapshots"

    @staticmethod
    def set_snapshot_dir(path):
        return GlobalSettings.set('snapshot_dir', path)

# ---------------- Performance Cache ----------------
class CheckCache:
    def __init__(self):
        self.cache = {}
        self.last_update = 0
        self.doc_id = None
        self.ancestor_vis_cache = {}  # Persistent ancestor visibility cache

    def get(self, doc, key):
        doc_id = id(doc)
        now = time.time()

        if (self.doc_id == doc_id and
            key in self.cache and
            now - self.last_update < CACHE_DURATION):
            return self.cache[key]
        return None

    def set(self, doc, key, value):
        self.doc_id = id(doc)
        self.cache[key] = value
        self.last_update = time.time()

    def get_ancestor_visibility(self, obj):
        """Get cached ancestor visibility or calculate and cache"""
        obj_id = id(obj)
        if obj_id in self.ancestor_vis_cache:
            return self.ancestor_vis_cache[obj_id]
        return None

    def set_ancestor_visibility(self, obj, vis_tuple):
        """Cache ancestor visibility for object"""
        obj_id = id(obj)
        self.ancestor_vis_cache[obj_id] = vis_tuple

    def clear(self):
        self.cache.clear()
        self.ancestor_vis_cache.clear()
        self.doc_id = None

# Global cache instance
check_cache = CheckCache()

def _safe_name(obj):
    """Get object name safely, returns 'unknown' if object is dead"""
    try:
        return obj.GetName() or "unnamed"
    except Exception:
        return "unknown"

# ---------------- utils ----------------
def _iter_objs(op, max_count=None):
    """Optimized object iterator with limit"""
    count = 0
    stack = [op]

    while stack and (max_count is None or count < max_count):
        current = stack.pop()
        if current is None:
            continue

        yield current
        count += 1

        child = current.GetDown()
        if child:
            stack.append(child)

        sibling = current.GetNext()
        if sibling:
            stack.append(sibling)

def _any_ancestor_named(o, names_lower):
    """Check if any ancestor has one of the specified names"""
    if not o:
        return False

    p = o.GetUp()
    depth = 0
    max_depth = 100

    while p and depth < max_depth:
        try:
            nm = (p.GetName() or "").strip().lower()
            if nm in names_lower:
                return True
        except Exception:
            pass
        p = p.GetUp()
        depth += 1
    return False

# ---------------- lights (optimized) ----------------
RS_LIGHT_ID = 1036751  # Redshift Light
C4D_LIGHT_ID = c4d.Olight
LIGHT_TYPE_CACHE = {}  # Cache light type checks

def _is_light_obj(op):
    """Optimized light detection with caching"""
    if not op:
        return False

    op_id = op.GetType()

    # Check cache first
    if op_id in LIGHT_TYPE_CACHE:
        return LIGHT_TYPE_CACHE[op_id]

    is_light = False

    try:
        # Fast checks first
        if op_id == C4D_LIGHT_ID or op_id == RS_LIGHT_ID:
            is_light = True
        elif op.CheckType(C4D_LIGHT_ID):
            is_light = True
        else:
            # Additional Redshift light types
            if op_id in (1036754, 1038653, 1036950, 1034355, 1036753):  # RS lights
                is_light = True
            else:
                # Slow check last
                tn = (op.GetTypeName() or "").lower()
                if "light" in tn:
                    is_light = True
    except Exception:
        pass

    # Cache result
    LIGHT_TYPE_CACHE[op_id] = is_light
    return is_light

def check_lights(doc):
    """Check for lights outside proper containers - accepts 'light', 'lights', or 'lighting'"""
    cached = check_cache.get(doc, "lights")
    if cached is not None:
        return cached

    offenders = []
    names = {"light", "lights", "lighting"}
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "lights", offenders)
        return offenders

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            if not _is_light_obj(o):
                continue

            if _any_ancestor_named(o, names):
                continue

            offenders.append(o)

            # Early exit if too many issues
            if len(offenders) > 50:
                safe_print(f"Too many light issues found ({len(offenders)}+), stopping check")
                break

    except Exception as e:
        safe_print(f"Error checking lights: {e}")

    check_cache.set(doc, "lights", offenders)
    return offenders

# ---------------- visibility traps (optimized) ----------------
def check_visibility_traps(doc):
    """Check for visibility inconsistencies between viewport and render"""
    cached = check_cache.get(doc, "vis")
    if cached is not None:
        return cached

    traps = []
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "vis", traps)
        return traps

    def ed(o):
        try:
            return o[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR]
        except Exception:
            return c4d.OBJECT_ON

    def rd(o):
        try:
            return o[c4d.ID_BASEOBJECT_VISIBILITY_RENDER]
        except Exception:
            return c4d.OBJECT_ON

    try:
        # Performance optimization: Use persistent ancestor visibility cache
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                obj_id = id(o)
                ed_vis = ed(o)
                rd_vis = rd(o)

                # Check direct visibility trap
                if ed_vis == c4d.OBJECT_OFF and rd_vis != c4d.OBJECT_OFF:
                    traps.append(o)
                    continue

                # Check ancestor visibility using persistent cache
                p = o.GetUp()
                if p:
                    # Try persistent cache first
                    cached_vis = check_cache.get_ancestor_visibility(p)

                    if cached_vis is not None:
                        ancE, ancR = cached_vis
                    else:
                        # Calculate ancestor visibility and cache it
                        ancE = False
                        ancR = False
                        temp_p = p
                        depth = 0

                        while temp_p and depth < 50:
                            if ed(temp_p) == c4d.OBJECT_OFF:
                                ancE = True
                            if rd(temp_p) == c4d.OBJECT_OFF:
                                ancR = True
                            temp_p = temp_p.GetUp()
                            depth += 1

                        # Store in persistent cache for reuse across timer ticks
                        check_cache.set_ancestor_visibility(p, (ancE, ancR))

                    if (ancE and ed_vis == c4d.OBJECT_ON) or (ancR and rd_vis == c4d.OBJECT_ON):
                        traps.append(o)

                # Early exit
                if len(traps) > 50:
                    safe_print(f"Too many visibility issues ({len(traps)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking visibility: {e}")

    check_cache.set(doc, "vis", traps)
    return traps

# ---------------- keyframe sanity (optimized) ----------------
def check_keys(doc):
    """Check for multi-axis position/rotation keyframes"""
    cached = check_cache.get(doc, "keys")
    if cached is not None:
        return cached

    offenders = []
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "keys", offenders)
        return offenders

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                tracks = o.GetCTracks()
                if not tracks:
                    continue

                pos_axes = set()
                rot_axes = set()

                for tr in tracks:
                    try:
                        did = tr.GetDescriptionID()
                        if not did or did.GetDepth() < 1:
                            continue

                        first_id = did[0].id

                        if first_id == c4d.ID_BASEOBJECT_POSITION:
                            if did.GetDepth() >= 2:
                                pos_axes.add(did[1].id)
                        elif first_id == c4d.ID_BASEOBJECT_ROTATION:
                            if did.GetDepth() >= 2:
                                rot_axes.add(did[1].id)
                    except Exception:
                        continue

                if len(pos_axes) > 1 or len(rot_axes) > 1:
                    offenders.append(o)

                # Early exit
                if len(offenders) > 50:
                    safe_print(f"Too many keyframe issues ({len(offenders)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking keyframes: {e}")

    check_cache.set(doc, "keys", offenders)
    return offenders

# ---------------- camera shift (optimized) ----------------
RS_CAMERA_ID = 1057516

def _camera_shift_values(o):
    """Get camera shift values"""
    if not o:
        return 0.0, 0.0
    try:
        x = float(o[c4d.CAMERAOBJECT_FILM_OFFSET_X] or 0.0)
        y = float(o[c4d.CAMERAOBJECT_FILM_OFFSET_Y] or 0.0)
        return x, y
    except Exception:
        return 0.0, 0.0

def check_camera_shift(doc):
    """Check for cameras with non-zero shift"""
    cached = check_cache.get(doc, "cam")
    if cached is not None:
        return cached

    bad = []
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "cam", bad)
        return bad

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                # Quick type check
                obj_type = o.GetType()
                if obj_type != c4d.Ocamera and obj_type != RS_CAMERA_ID:
                    continue

                x, y = _camera_shift_values(o)
                if abs(x) > 1e-6 or abs(y) > 1e-6:
                    bad.append(o)

                # Early exit
                if len(bad) > 20:
                    safe_print(f"Too many camera shift issues ({len(bad)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking camera shift: {e}")

    check_cache.set(doc, "cam", bad)
    return bad

# ---------------- render preset conflicts (optimized) ----------------
def check_render_conflicts(doc):
    """Check for render setting conflicts - accepts pre_render, pre-render, Pre-Render etc."""
    cached = check_cache.get(doc, "rdc")
    if cached is not None:
        return cached

    allowed = set(PRESETS)
    name_counts = defaultdict(int)
    extras = 0

    try:
        rd = doc.GetFirstRenderData()
        count = 0
        max_check = 100  # Limit iterations

        while rd and count < max_check:
            try:
                # Normalize the name (lowercase, replace hyphens/spaces with underscores)
                name = normalize_preset_name(rd.GetName() or "")
                if name in allowed:
                    name_counts[name] += 1
                else:
                    extras += 1
            except Exception:
                pass

            rd = rd.GetNext()
            count += 1

        dups = sum(max(0, c - 1) for c in name_counts.values())
        result = extras + dups

    except Exception as e:
        safe_print(f"Error checking render conflicts: {e}")
        result = 0

    check_cache.set(doc, "rdc", result)
    return result

def _is_absolute_path(filepath):
    """Check if a file path is absolute (not relative)"""
    if not filepath:
        return False
    if len(filepath) > 2:
        if filepath[1] == ':' or filepath.startswith('\\\\'):
            return True
    if filepath.startswith('/'):
        return True
    return False

# ---------------- unused materials ----------------
def check_unused_materials(doc):
    """Check for materials not assigned to any object via any tag type"""
    cached = check_cache.get(doc, "unused_mats")
    if cached is not None:
        return cached

    unused = []
    try:
        materials = doc.GetMaterials()
        if not materials:
            check_cache.set(doc, "unused_mats", unused)
            return unused

        # Collect all materials referenced by ANY tag on ANY object
        used_mats = set()
        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                for tag in obj.GetTags():
                    # Check texture tags (standard material assignment)
                    if tag.GetType() == c4d.Ttexture:
                        mat = tag[c4d.TEXTURETAG_MATERIAL]
                        if mat:
                            used_mats.add(mat.GetName())
                    # Check any tag that might link a material
                    try:
                        bc = tag.GetDataInstance()
                        if bc:
                            for desc_id, _ in bc:
                                link = bc.GetLink(desc_id, doc)
                                if link and link.IsInstanceOf(c4d.Mbase):
                                    used_mats.add(link.GetName())
                    except Exception:
                        pass

        # Also check materials referenced by other materials (multi/blend materials)
        for mat in materials:
            try:
                shader = mat.GetFirstShader()
                while shader:
                    try:
                        bc = shader.GetDataInstance()
                        if bc:
                            for desc_id, _ in bc:
                                link = bc.GetLink(desc_id, doc)
                                if link and link.IsInstanceOf(c4d.Mbase):
                                    used_mats.add(link.GetName())
                    except Exception:
                        pass
                    shader = shader.GetNext()
            except Exception:
                pass

        for mat in materials:
            if mat.GetName() not in used_mats:
                unused.append(mat)

    except Exception as e:
        safe_print(f"Error checking unused materials: {e}")

    check_cache.set(doc, "unused_mats", unused)
    return unused

# ---------------- default naming ----------------
# Common default object names that indicate unorganized scenes
_DEFAULT_NAMES = {
    "null", "cube", "sphere", "cylinder", "cone", "plane", "disc", "torus",
    "capsule", "oil tank", "platonic", "pyramid", "gem", "tube", "landscape",
    "figure", "spline", "circle", "rectangle", "n-side", "arc", "helix",
    "sweep", "extrude", "lathe", "loft", "boole", "symmetry", "instance",
    "cloner", "fracture", "voronoi fracture", "matrix", "mograph",
    "camera", "light", "floor", "sky", "environment", "physical sky",
}

def check_default_names(doc):
    """Check for objects with default/generic names (Cube, Null, Sphere.1, etc.)"""
    cached = check_cache.get(doc, "names")
    if cached is not None:
        return cached

    offenders = []
    first = doc.GetFirstObject()
    if not first:
        check_cache.set(doc, "names", offenders)
        return offenders

    try:
        for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not obj:
                continue
            name = (obj.GetName() or "").strip()
            if not name:
                offenders.append(obj)
                continue

            # Strip trailing ".N" suffix (e.g., "Cube.1", "Null.23")
            base = name.rsplit(".", 1)[0].strip().lower() if "." in name else name.lower()

            if base in _DEFAULT_NAMES:
                offenders.append(obj)

            if len(offenders) > 50:
                break

    except Exception as e:
        safe_print(f"Error checking default names: {e}")

    check_cache.set(doc, "names", offenders)
    return offenders

# ---------------- output path validation ----------------
def check_output_paths(doc):
    """Check render output paths are configured with proper tokens"""
    cached = check_cache.get(doc, "output")
    if cached is not None:
        return cached

    issues = []
    try:
        rd = doc.GetFirstRenderData()
        count = 0
        while rd and count < 100:
            name = rd.GetName() or "unnamed"
            path = rd[c4d.RDATA_PATH] or ""

            if not path.strip():
                issues.append({"preset": name, "issue": "empty output path"})
            elif "$prj" not in path and "$take" not in path:
                issues.append({"preset": name, "issue": f"no tokens in path: {path}"})

            # Check multi-pass path if enabled
            try:
                if rd[c4d.RDATA_MULTIPASS_SAVEIMAGE]:
                    mp_path = rd[c4d.RDATA_MULTIPASS_FILENAME] or ""
                    if not mp_path.strip():
                        issues.append({"preset": name, "issue": "empty multi-pass path"})
            except Exception:
                pass

            rd = rd.GetNext()
            count += 1

    except Exception as e:
        safe_print(f"Error checking output paths: {e}")

    check_cache.set(doc, "output", issues)
    return issues

# ---------------- unified texture check ----------------
RS_NODESPACE = "com.redshift3d.redshift4c4d.class.nodespace"

def check_textures_unified(doc):
    """Unified check: scans classic shaders, RS nodes, and alembics for absolute paths and missing files"""
    cached = check_cache.get(doc, "textures")
    if cached is not None:
        return cached

    issues = []
    seen_paths = set()
    doc_path = doc.GetDocumentPath() or ""

    def resolve(filepath):
        if not filepath:
            return None
        filepath = str(filepath).strip()
        if not filepath:
            return None
        if _is_absolute_path(filepath):
            return filepath
        if doc_path:
            return os.path.join(doc_path, filepath)
        return None

    def add_issue(source, filepath):
        """Check a file path and add issue if absolute or missing"""
        if not filepath or filepath in seen_paths:
            return
        seen_paths.add(filepath)

        if _is_absolute_path(filepath):
            issues.append({"source": source, "path": filepath, "issue": "absolute"})
        else:
            resolved = resolve(filepath)
            if resolved and not os.path.exists(resolved):
                issues.append({"source": source, "path": filepath, "issue": "missing", "resolved": resolved})

    try:
        materials = doc.GetMaterials() or []

        for mat in materials:
            if not mat:
                continue
            mat_name = mat.GetName()

            # --- Classic shaders ---
            shader = mat.GetFirstShader()
            while shader:
                if shader.GetType() == c4d.Xbitmap:
                    try:
                        fp = shader[c4d.BITMAPSHADER_FILENAME]
                        if fp:
                            add_issue(f"Shader in '{mat_name}'", str(fp))
                    except Exception:
                        pass
                shader = shader.GetNext()

            # --- BaseContainer file params ---
            try:
                bc = mat.GetDataInstance()
                if bc:
                    for desc_id, _ in bc:
                        try:
                            fp = bc.GetFilename(desc_id)
                            if fp and str(fp).strip():
                                add_issue(f"Material '{mat_name}'", str(fp))
                        except Exception:
                            pass
            except Exception:
                pass

            # --- RS Node graph ---
            if MAXON_AVAILABLE:
                try:
                    nodeMat = mat.GetNodeMaterialReference()
                    if nodeMat and nodeMat.HasSpace(RS_NODESPACE):
                        graph = nodeMat.GetGraph(RS_NODESPACE)
                        if graph:
                            root = graph.GetViewRoot()

                            def check_port_value(port):
                                try:
                                    val = None
                                    try:
                                        val = port.GetPortValue()
                                    except Exception:
                                        try:
                                            val = port.GetDefaultValue()
                                        except Exception:
                                            return None
                                    if val is None:
                                        return None
                                    filepath = ""
                                    try:
                                        if hasattr(val, 'GetSystemPath'):
                                            filepath = str(val.GetSystemPath())
                                    except Exception:
                                        pass
                                    if not filepath:
                                        try:
                                            if hasattr(val, 'ToString'):
                                                filepath = str(val.ToString())
                                        except Exception:
                                            pass
                                    if not filepath:
                                        filepath = str(val)
                                    if (not filepath or filepath == "None" or len(filepath) < 4
                                            or not ("/" in filepath or "\\" in filepath)):
                                        return None
                                    if filepath.startswith("asset:") or filepath.startswith("preset:"):
                                        return None
                                    return filepath
                                except Exception:
                                    return None

                            def scan_ports(port):
                                if not port:
                                    return
                                fp = check_port_value(port)
                                if fp:
                                    add_issue(f"RS Node in '{mat_name}'", fp)
                                try:
                                    for child in port.GetChildren():
                                        scan_ports(child)
                                except Exception:
                                    pass

                            def scan_node(node, depth=0):
                                if not node or depth > 10:
                                    return
                                try:
                                    inputs = node.GetInputs()
                                    if inputs:
                                        for port in inputs.GetChildren():
                                            scan_ports(port)
                                    for child in node.GetChildren():
                                        scan_node(child, depth + 1)
                                except Exception:
                                    pass

                            scan_node(root)
                except Exception:
                    pass

            if len(issues) > 50:
                break

        # --- Alembic objects ---
        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                if obj.GetType() == 1028083:
                    try:
                        fp = obj[c4d.ALEMBIC_PATH]
                        if fp:
                            add_issue(f"Alembic '{obj.GetName()}'", str(fp))
                    except Exception:
                        pass
                if len(issues) > 50:
                    break

    except Exception as e:
        safe_print(f"Error in unified texture check: {e}")

    check_cache.set(doc, "textures", issues)
    return issues

# ---------------- scene complexity ----------------
def get_scene_stats(doc):
    """Get scene complexity statistics"""
    cached = check_cache.get(doc, "stats")
    if cached is not None:
        return cached

    stats = {"objects": 0, "polygons": 0, "materials": 0, "lights": 0}

    try:
        stats["materials"] = len(doc.GetMaterials() or [])

        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                stats["objects"] += 1
                try:
                    cache = obj.GetDeformCache() or obj.GetCache()
                    target = cache if cache else obj
                    if target.IsInstanceOf(c4d.Opolygon):
                        stats["polygons"] += target.GetPolygonCount()
                except Exception:
                    pass
                if _is_light_obj(obj):
                    stats["lights"] += 1

    except Exception as e:
        safe_print(f"Error getting scene stats: {e}")

    check_cache.set(doc, "stats", stats)
    return stats

# ---------------- RS AOV management ----------------
# AOV definitions: (const_candidates, bit_depth)
# bit_depth: 16 = half-float, 32 = full float
_AOV_DEFS = {
    "Diffuse Lighting":   (["REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING"], 16),
    "GI":                 (["REDSHIFT_AOV_TYPE_GI", "REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION", "REDSHIFT_AOV_TYPE_INDIRECT_DIFFUSE", "REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING_RAW"], 16),
    "Specular Lighting":  (["REDSHIFT_AOV_TYPE_SPECULAR_LIGHTING"], 16),
    "Reflections":        (["REDSHIFT_AOV_TYPE_REFLECTIONS"], 16),
    "Emission":           (["REDSHIFT_AOV_TYPE_EMISSION"], 16),
    "Depth":              (["REDSHIFT_AOV_TYPE_DEPTH", "REDSHIFT_AOV_TYPE_Z_DEPTH"], 32),
    "Motion Vectors":     (["REDSHIFT_AOV_TYPE_MOTION_VECTORS"], 32),
    "Cryptomatte":        (["REDSHIFT_AOV_TYPE_CRYPTOMATTE"], 32),
    "SSS":                (["REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER", "REDSHIFT_AOV_TYPE_SSS"], 16),
    "Refractions":        (["REDSHIFT_AOV_TYPE_REFRACTIONS"], 16),
    "Diffuse Filter":     (["REDSHIFT_AOV_TYPE_DIFFUSE_FILTER"], 16),
    "World Position":     (["REDSHIFT_AOV_TYPE_WORLD_POSITION"], 32),
    "Normals":            (["REDSHIFT_AOV_TYPE_NORMALS"], 16),
    "Ambient Occlusion":  (["REDSHIFT_AOV_TYPE_AMBIENT_OCCLUSION"], 16),
    "Volume Lighting":      (["REDSHIFT_AOV_TYPE_VOLUME_LIGHTING"], 16),
    "Volume Fog Tint":      (["REDSHIFT_AOV_TYPE_VOLUME_FOG_TINT"], 16),
    "Volume Fog Emission":  (["REDSHIFT_AOV_TYPE_VOLUME_FOG_EMISSION"], 16),
    "Shadows":              (["REDSHIFT_AOV_TYPE_SHADOWS"], 16),
    "Caustics":             (["REDSHIFT_AOV_TYPE_CAUSTICS"], 16),
    "Bump Normals":         (["REDSHIFT_AOV_TYPE_BUMP_NORMALS"], 16),
    "Reflection Filter":    (["REDSHIFT_AOV_TYPE_REFLECTION_FILTER", "REDSHIFT_AOV_TYPE_REFLECTIONS_FILTER", "REDSHIFT_AOV_TYPE_REFL_FILTER"], 16),
    "Diffuse Lighting Raw": (["REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING_RAW"], 16),
}

# Tier definitions — names must match _AOV_DEFS keys
# Tier 1: Beauty rebuild + essential utility
# Beauty = Diffuse + GI + Specular + Reflections + SSS + Refractions + Emission (+ Caustics if enabled)
AOV_TIER_ESSENTIALS = [
    "Diffuse Lighting", "GI", "Specular Lighting", "Reflections",
    "SSS", "Refractions", "Emission",
    "Depth", "Motion Vectors", "Cryptomatte",
]

# Tier 2: Full compositing control — relighting, volumes, raw passes
AOV_TIER_PRODUCTION = AOV_TIER_ESSENTIALS + [
    "Diffuse Filter", "World Position", "Normals", "Ambient Occlusion",
    "Volume Lighting", "Volume Fog Tint", "Volume Fog Emission",
    "Diffuse Lighting Raw", "Reflection Filter",
    "Shadows", "Bump Normals",
]

def _get_rs_videopost(doc):
    if not REDSHIFT_AVAILABLE:
        return None
    try:
        rd = doc.GetActiveRenderData()
        return redshift.FindAddVideoPost(rd, redshift.VPrsrenderer) if rd else None
    except Exception:
        return None

RS_CAUSTICS_ENGINE_ID = 9014  # "Caustics Engine" parameter in RS VideoPost

def _are_caustics_enabled(doc):
    """Check if caustics are enabled in RS render settings"""
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return False
    try:
        return bool(vprs[RS_CAUSTICS_ENGINE_ID])
    except Exception:
        return False

def _resolve_aov_type(name):
    """Resolve AOV name to c4d constant value"""
    aov_def = _AOV_DEFS.get(name)
    if not aov_def:
        return None
    candidates, _ = aov_def
    for const_name in candidates:
        val = getattr(c4d, const_name, None)
        if val is not None:
            return val
    return None

def get_rs_aovs(doc):
    """Get list of current RS AOVs"""
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return None

    aovs = []
    try:
        for aov in redshift.RendererGetAOVs(vprs):
            try:
                aovs.append({
                    "name": aov.GetParameter(c4d.REDSHIFT_AOV_NAME) or "",
                    "type": aov.GetParameter(c4d.REDSHIFT_AOV_TYPE),
                    "enabled": aov.GetParameter(c4d.REDSHIFT_AOV_ENABLED),
                })
            except Exception:
                pass
    except Exception as e:
        safe_print(f"Error reading RS AOVs: {e}")
    return aovs

def check_rs_aovs(doc, tier=None):
    """Check AOVs against a tier. tier=None uses Essentials."""
    tier_list = _build_tier_list(doc, tier or AOV_TIER_ESSENTIALS)
    result = {"available": REDSHIFT_AVAILABLE, "aovs": [], "missing": [], "tier": tier_list}

    aovs = get_rs_aovs(doc)
    if aovs is None:
        return result

    result["aovs"] = aovs
    active_names = {a["name"] for a in aovs if a.get("enabled", True)}
    result["missing"] = [name for name in tier_list if name not in active_names]
    return result

def _build_tier_list(doc, tier_list):
    """Build effective tier list, adding Caustics if enabled in render settings"""
    effective = list(tier_list)
    if "Caustics" not in effective and _are_caustics_enabled(doc):
        effective.append("Caustics")
        safe_print("  Caustics enabled in render settings - adding AOV")
    return effective

def force_aov_tier(doc, tier_list):
    """Add missing AOVs from a tier to RS render settings, with proper bit depth"""
    if not REDSHIFT_AVAILABLE:
        return 0, "Redshift module not available"

    vprs = _get_rs_videopost(doc)
    if not vprs:
        return 0, "Redshift VideoPost not found"

    tier_list = _build_tier_list(doc, tier_list)

    try:
        existing_aovs = redshift.RendererGetAOVs(vprs)
        existing_names = set()
        for aov in existing_aovs:
            try:
                existing_names.add(aov.GetParameter(c4d.REDSHIFT_AOV_NAME) or "")
            except Exception:
                pass

        added = 0
        new_aovs = list(existing_aovs)

        for name in tier_list:
            if name in existing_names:
                continue

            aov_type = _resolve_aov_type(name)
            if aov_type is None:
                safe_print(f"  Skipped AOV '{name}': constant not found")
                continue

            _, bit_depth = _AOV_DEFS[name]

            try:
                new_aov = redshift.RSAOV()
                new_aov.SetParameter(c4d.REDSHIFT_AOV_TYPE, aov_type)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_NAME, name)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_ENABLED, True)

                # Set bit depth: 0=8bit, 1=16bit half, 2=32bit float
                depth_val = 2 if bit_depth == 32 else 1
                try:
                    new_aov.SetParameter(c4d.REDSHIFT_AOV_BITS_PER_CHANNEL, depth_val)
                except Exception:
                    pass

                new_aovs.append(new_aov)
                added += 1
                safe_print(f"  Added AOV: {name} ({bit_depth}-bit)")
            except Exception as e:
                safe_print(f"  Failed: '{name}': {e}")

        if added > 0:
            redshift.RendererSetAOVs(vprs, new_aovs)
            check_cache.clear()
            c4d.EventAdd()

        return added, None

    except Exception as e:
        safe_print(f"Error forcing AOVs: {e}")
        return 0, f"Error: {e}"

# ---------------- auto-fix functions ----------------
def fix_lights(doc, lights_bad):
    """Move stray lights into a 'lights' group null"""
    if not lights_bad:
        return 0

    doc.StartUndo()

    # Find or create the lights group
    lights_group = None
    obj = doc.GetFirstObject()
    while obj:
        if obj.GetType() == c4d.Onull and obj.GetName().strip().lower() in {"light", "lights", "lighting"}:
            lights_group = obj
            break
        obj = obj.GetNext()

    if not lights_group:
        lights_group = c4d.BaseObject(c4d.Onull)
        lights_group.SetName("lights")
        doc.InsertObject(lights_group)
        doc.AddUndo(c4d.UNDOTYPE_NEW, lights_group)

    moved = 0
    for light in lights_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        light.Remove()
        light.InsertUnderLast(lights_group)
        moved += 1

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return moved

def fix_camera_shift(doc, cam_bad):
    """Reset camera shift to 0 on all flagged cameras"""
    if not cam_bad:
        return 0

    doc.StartUndo()
    fixed = 0
    for cam in cam_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, cam)
        try:
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
            fixed += 1
        except Exception:
            pass

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return fixed

def fix_unused_materials(doc, unused_mats):
    """Delete unused materials from the scene"""
    if not unused_mats:
        return 0

    doc.StartUndo()
    deleted = 0
    for mat in unused_mats:
        doc.AddUndo(c4d.UNDOTYPE_DELETE, mat)
        mat.Remove()
        deleted += 1

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return deleted

def export_qc_report(doc, results, artist_name):
    """Export QC report as JSON to a user-chosen location"""
    from datetime import datetime

    # Build report
    report = {
        "report": "YS Guardian QC Report",
        "version": PLUGIN_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene": doc.GetDocumentName() or "untitled",
        "path": doc.GetDocumentPath() or "",
        "artist": artist_name or "",
        "shot_id": "",
        "checks": {}
    }

    # Get shot ID
    try:
        td = doc.GetTakeData()
        if td:
            main_take = td.GetMainTake()
            if main_take:
                report["shot_id"] = main_take.GetName() or ""
    except Exception:
        pass

    # Populate checks
    for key, label, items in [
        ("lights", "Lights outside group", results.get("lights_bad", [])),
        ("visibility", "Visibility mismatches", results.get("vis_bad", [])),
        ("keyframes", "Multi-axis keyframes", results.get("keys_bad", [])),
        ("camera_shift", "Camera shift != 0", results.get("cam_bad", [])),
        ("unused_materials", "Unused materials", results.get("unused_mats_bad", [])),
        ("default_names", "Default/generic names", results.get("names_bad", [])),
    ]:
        obj_list = []
        for item in (items or []):
            try:
                obj_list.append(item.GetName() or "unnamed")
            except Exception:
                obj_list.append(str(item))
        report["checks"][key] = {
            "status": "PASS" if not obj_list else "FAIL",
            "count": len(obj_list),
            "label": label,
            "items": obj_list[:50],
        }

    # Unified textures check
    tex_bad = results.get("textures_bad", [])
    report["checks"]["textures"] = {
        "status": "PASS" if not tex_bad else "FAIL",
        "count": len(tex_bad),
        "label": "Texture issues (absolute paths + missing files)",
        "items": [f"[{t['issue'].upper()}] {t['source']}: {t['path']}" for t in tex_bad[:30]],
    }

    # Scene stats
    stats = results.get("scene_stats", {})
    if stats:
        report["scene_stats"] = stats

    # Info-only checks
    for key, label, count in [
        ("render_presets", "Non-standard presets", results.get("rdc_count", 0)),
        ("output_paths", "Output path issues", results.get("output_count", 0)),
    ]:
        report["checks"][key] = {
            "status": "PASS" if count == 0 else "FAIL",
            "count": count,
            "label": label,
        }

    if results.get("output_bad"):
        report["checks"]["output_paths"]["items"] = [
            f"[{i['preset']}] {i['issue']}" for i in results["output_bad"][:10]
        ]

    # Summary
    total = len(report["checks"])
    passed = sum(1 for c in report["checks"].values() if c["status"] == "PASS")
    report["summary"] = {
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "score": f"{passed}/{total}"
    }

    # Ask user where to save
    save_path = c4d.storage.SaveDialog(
        title="Save QC Report",
        force_suffix="json",
    )

    if not save_path:
        return None

    if not save_path.endswith(".json"):
        save_path += ".json"

    with open(save_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return save_path

# ---------------- UI StatusArea ----------------
# Pre-allocated colors to avoid GC pressure in DrawMsg
_COL_GREEN = c4d.Vector(0.3, 1, 0.3)
_COL_RED = c4d.Vector(1, 0.3, 0.3)
_COL_YELLOW = c4d.Vector(1, 1, 0.3)
_COL_GRAY = c4d.Vector(0.5, 0.5, 0.5)
_COL_BG = c4d.Vector(0.08, 0.08, 0.08)
_COL_BLACK = c4d.Vector(0, 0, 0)
_COL_BG_OK = c4d.Vector(0.15, 0.15, 0.15)
_COL_BG_WARN = c4d.Vector(0.25, 0.20, 0.10)
_COL_BG_FAIL = c4d.Vector(0.25, 0.10, 0.10)

# Check display config: (severity, ok_message, fail_template, name_key_for_first)
_CHECK_DISPLAY = {
    "lights":      ("FAIL", "All lights properly organized", "{n} lights outside lights group", None),
    "vis":         ("WARN", "Visibility settings consistent", "Visibility mismatch on '{first}'", "vis_names"),
    "keys":        ("WARN", "Keyframes properly configured", "Multi-axis keys on '{first}'", "keys_names"),
    "cam":         ("FAIL", "Camera shifts at 0%", "{n} camera(s) with non-zero shift", None),
    "rdc":         ("FAIL", "Render presets compliant", "{n} non-standard render preset(s)", None),
    "textures":    ("FAIL", "All assets OK", "{n} asset issue(s)", None),
    "unused_mats": ("WARN", "All materials assigned", "{n} unused material(s)", None),
    "names":       ("WARN", "All objects named", "Default name '{first}'", "names_list"),
    "output":      ("FAIL", "Output paths configured", "{n} output path issue(s)", None),
}

class StatusArea(gui.GeUserArea):
    def __init__(self):
        super().__init__()
        self.data = {}
        self.show = {k: True for k in _CHECK_DISPLAY}
        self.pad = 3
        self.rowh = 20
        self.font = c4d.FONT_MONOSPACED
        self.last_draw_time = 0
        self.min_draw_interval = 0.05

    def GetMinSize(self):
        rows = sum(1 for _, v in self.show.items() if v)
        return 400, max(1, rows) * (self.rowh + self.pad) + self.pad + 4

    def set_state(self, data, show):
        self.data = data or {}
        self.show = show or self.show

        # Throttle redraws
        now = time.time()
        if now - self.last_draw_time > self.min_draw_interval:
            self.Redraw()
            self.last_draw_time = now

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            x = self.pad
            y = self.pad

            for label, key in [("Lights","lights"), ("Visibility","vis"), ("Keyframes","keys"),
                               ("Cameras","cam"), ("Presets","rdc"), ("Assets","textures"),
                               ("Materials","unused_mats"), ("Naming","names"), ("Output","output")]:
                if not self.show.get(key, False):
                    continue

                val = int(self.data.get(key, 0))
                cfg = _CHECK_DISPLAY.get(key)
                if not cfg:
                    continue

                severity, ok_msg, fail_tpl, name_key = cfg

                if val > 0:
                    status = f"[{severity}]"
                    first = ""
                    if name_key:
                        names = self.data.get(name_key, [])
                        first = names[0] if names else "object"
                    message = fail_tpl.format(n=val, first=first)
                    if name_key and val > 1:
                        message += f" (+{val-1} more)"
                    text_col = _COL_RED if severity == "FAIL" else _COL_YELLOW
                    bg = _COL_BG_FAIL if severity == "FAIL" else _COL_BG_WARN
                else:
                    status = "[ OK ]"
                    message = ok_msg
                    text_col = _COL_GREEN
                    bg = _COL_BG_OK

                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(y), int(w - self.pad), int(y + self.rowh))

                text_y = int(y + (self.rowh - 12) // 2)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(status, int(x + 5), text_y)

                self.DrawSetTextCol(_COL_GRAY, _COL_BLACK)
                self.DrawText(f"{label.ljust(13)}:", int(x + 55), text_y)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(message, int(x + 175), text_y)

                y += self.rowh + self.pad

        except Exception as e:
            safe_print(f"Error in DrawMsg: {e}")

# ---------------- Snapshot Handler ----------------
# ---------------- Snapshot System (cross-platform) ----------------

def _get_stills_dir(doc, artist_name):
    """Get output directory: project_root/output/stills/Artist/YYMMDD/"""
    from datetime import datetime
    doc_path = doc.GetDocumentPath() or ""
    if doc_path:
        project_root = os.path.dirname(os.path.dirname(doc_path))
    else:
        project_root = os.path.join(os.path.expanduser("~"), "YS_Guardian_Output")

    output_dir = os.path.join(
        project_root, "output", "stills",
        artist_name or "Unknown",
        datetime.now().strftime("%y%m%d")
    )
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def _find_latest_exr():
    """Find the most recent EXR in the RS snapshot directory"""
    snap_dir = GlobalSettings.get_snapshot_dir()
    if not os.path.exists(snap_dir):
        return None, f"Snapshot directory not found:\n{snap_dir}\n\nConfigure it in Redshift RenderView > Preferences > Snapshots"

    exr_files = []
    for f in os.listdir(snap_dir):
        if f.lower().endswith('.exr'):
            full = os.path.join(snap_dir, f)
            exr_files.append((full, os.path.getmtime(full)))

    if not exr_files:
        return None, f"No EXR snapshots found in:\n{snap_dir}\n\nTake a snapshot in RS RenderView first."

    exr_files.sort(key=lambda x: x[1], reverse=True)
    return exr_files[0][0], None

def _find_system_python():
    """Find a system Python 3 with OpenEXR support (cross-platform)"""
    import subprocess

    candidates = []
    if sys.platform == "darwin":
        candidates = ["/usr/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3"]
    else:
        import glob
        candidates = ["python", "python3"]
        for pattern in [r"C:\Program Files\Python*\python.exe",
                        r"C:\Program Files (x86)\Python*\python.exe"]:
            candidates.extend(glob.glob(pattern))
        user_local = os.path.expanduser("~")
        for pattern in [os.path.join(user_local, r"AppData\Local\Programs\Python\Python*\python.exe")]:
            candidates.extend(glob.glob(pattern))

    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import OpenEXR, numpy, PIL; print('OK')"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and "OK" in result.stdout:
                safe_print(f"Found system Python with OpenEXR: {py}")
                return py
        except Exception:
            continue

    return None

_CACHED_PYTHON = None

def _convert_exr_to_png(exr_path, png_path):
    """Convert EXR to PNG via external Python with OpenEXR + ACES pipeline"""
    import subprocess

    global _CACHED_PYTHON
    if not _CACHED_PYTHON:
        _CACHED_PYTHON = _find_system_python()

    if not _CACHED_PYTHON:
        return False, ("System Python with OpenEXR not found.\n\n"
                       "Install dependencies:\n"
                       "  pip3 install OpenEXR numpy Pillow")

    # Use the existing external converter script
    converter = os.path.join(os.path.dirname(__file__), "exr_converter_external.py")
    if not os.path.exists(converter):
        return False, f"Converter script not found: {converter}"

    try:
        result = subprocess.run(
            [_CACHED_PYTHON, converter, exr_path, png_path, "aces"],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode == 0 and os.path.exists(png_path):
            safe_print(f"Conversion complete: {os.path.basename(png_path)}")
            return True, None
        else:
            error = result.stderr or result.stdout or "Unknown error"
            safe_print(f"Converter error: {error}")
            return False, f"Conversion failed:\n{error[:300]}"

    except subprocess.TimeoutExpired:
        return False, "Conversion timed out (>120s)"
    except Exception as e:
        return False, f"Error running converter: {e}"

def snapshot_save_still(doc, artist_name):
    """Main entry point: find latest EXR, convert with ACES, save to project"""
    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return

    # Find latest EXR
    exr_path, error = _find_latest_exr()
    if not exr_path:
        c4d.gui.MessageDialog(error)
        return

    # Build output path
    output_dir = _get_stills_dir(doc, artist_name)
    doc_name = doc.GetDocumentName() or "untitled"
    scene_name = os.path.splitext(doc_name)[0]
    png_path = os.path.join(output_dir, f"{scene_name}.png")

    safe_print(f"Converting {os.path.basename(exr_path)} -> {png_path}")

    # Convert
    success, error = _convert_exr_to_png(exr_path, png_path)
    if not success:
        c4d.gui.MessageDialog(f"Conversion failed:\n{error}")
        return

    # Show in Picture Viewer
    bmp = c4d.bitmaps.BaseBitmap()
    if bmp.InitWith(png_path)[0] == c4d.IMAGERESULT_OK:
        c4d.bitmaps.ShowBitmap(bmp)
        w, h = bmp.GetBw(), bmp.GetBh()
        c4d.gui.MessageDialog(f"Still saved!\n\nFile: {os.path.basename(png_path)}\nResolution: {w}x{h}\nFolder: {output_dir}")
    else:
        c4d.gui.MessageDialog(f"Still saved!\n\n{png_path}")

    safe_print(f"Still saved: {png_path}")

def snapshot_open_folder(doc, artist_name):
    """Open the artist's stills folder"""
    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return
    output_dir = _get_stills_dir(doc, artist_name)
    if os.path.exists(output_dir):
        open_in_explorer(output_dir)
    else:
        c4d.gui.MessageDialog(f"Folder not found:\n{output_dir}")

# ---------------- UI Widget IDs ----------------
class G:
    # Scene info
    SHOT = 1001
    ARTIST = 1003
    CANVAS = 1008

    # Per-check action buttons (1 click to select/info)
    BTN_SEL_LIGHTS = 1130
    BTN_SEL_VIS = 1131
    BTN_SEL_KEYS = 1132
    BTN_SEL_CAMS = 1133
    BTN_INFO_PRESET = 1134
    BTN_INFO_TEXTURES = 1135
    BTN_SEL_UNUSED_MATS = 1136
    BTN_SEL_NAMES = 1137
    BTN_INFO_OUTPUT = 1138

    # Auto-fix buttons
    BTN_FIX_LIGHTS = 1140
    BTN_FIX_CAMS = 1141
    BTN_FIX_UNUSED_MATS = 1142

    # Export
    BTN_EXPORT_QC = 1150

    # Render preset
    PRESET_DROPDOWN = 1002
    BTN_FORCE_RENDER = 1204
    BTN_FORCE_ALL = 1206

    # Quick Actions
    BTN_CREATE_HIERARCHY = 1126
    BTN_HIERARCHY_TO_LAYERS = 1101
    BTN_SOLO = 1103
    BTN_DROP_TO_FLOOR = 1122
    BTN_VIBRATE_NULL = 1120
    BTN_ABC_RETIME = 1020
    BTN_CAM_SIMPLE = 1123
    BTN_CAM_SHAKEL = 1124
    BTN_CAM_PATH = 1125

    # Output
    BTN_OPEN_FOLDER = 1010
    BTN_SNAPSHOT = 1009
    BTN_INFO_AOVS = 1155
    BTN_FORCE_ESSENTIALS = 1156
    BTN_FORCE_PRODUCTION = 1157
    BTN_SET_SNAPSHOT_DIR = 1160
    LABEL_SNAPSHOT_DIR = 1161
    BTN_GITHUB = 1306
    BTN_BUG_REPORT = 1307

class YSPanel(gui.GeDialog):
    def __init__(self):
        super().__init__()
        self._last_doc = None
        self._last_check_time = 0
        self.ua = None
        self._artist_name = ""
        self._dirty = False  # Set by CoreMessage, consumed by Timer

        # Store selection results
        self._lights_bad = []
        self._vis_bad = []
        self._keys_bad = []
        self._cam_bad = []
        self._textures_bad = []
        self._unused_mats_bad = []
        self._names_bad = []
        self._output_bad = []
        self._scene_stats = {}

        # Cycling indices for one-by-one selection
        self._unused_mats_idx = 0
        self._names_idx = 0

    def _update_snapshot_dir_label(self):
        snap_dir = GlobalSettings.get_snapshot_dir()
        # Shorten for display: show last 2 path components
        parts = snap_dir.replace("\\", "/").rstrip("/").split("/")
        short = "/".join(parts[-2:]) if len(parts) > 2 else snap_dir
        self.SetString(G.LABEL_SNAPSHOT_DIR, f"Snapshots: .../{short}")

    # ---- read scene -> UI
    def _sync_from_doc(self, doc):
        """Sync UI with document state"""
        if not doc:
            return

        try:
            td = None
            try:
                td = doc.GetTakeData()
            except Exception:
                try:
                    td = documents.GetTakeData(doc)
                except Exception:
                    pass

            shot = ""
            if td:
                main_take = td.GetMainTake()
                if main_take:
                    shot = main_take.GetName() or ""
            self.SetString(G.SHOT, shot)
        except Exception as e:
            safe_print(f"Error syncing shot name: {e}")

        try:
            ard = doc.GetActiveRenderData()
            if ard:
                name = (ard.GetName() or "").strip().lower()
                # Update the active preset based on current render data
                if name in PRESETS:
                    self._active_preset = name
                    self._update_preset_buttons()
        except Exception as e:
            safe_print(f"Error syncing render preset: {e}")

    # ---- write UI -> scene
    def _apply_shot(self, doc):
        if not doc:
            return

        try:
            name = self.GetString(G.SHOT)
            td = None

            try:
                td = doc.GetTakeData()
            except Exception:
                try:
                    td = documents.GetTakeData(doc)
                except Exception:
                    pass

            if td:
                main_take = td.GetMainTake()
                if main_take:
                    main_take.SetName(name)
                    c4d.EventAdd()
        except Exception as e:
            safe_print(f"Error applying shot name: {e}")

    def _apply_preset(self, doc, preset_name):
        """Apply preset - accepts pre_render, pre-render, Pre-Render, etc."""
        if not doc:
            return

        try:
            # Normalize the target preset name
            normalized_target = normalize_preset_name(preset_name)
            rd = doc.GetFirstRenderData()

            while rd:
                # Normalize the render data name for comparison
                normalized_rd = normalize_preset_name(rd.GetName() or "")
                if normalized_rd == normalized_target:
                    doc.SetActiveRenderData(rd)
                    check_cache.clear()  # Clear cache to update compliance check immediately
                    c4d.EventAdd()
                    self._active_preset = normalized_target
                    self._update_preset_buttons()
                    safe_print(f"Switched to render preset: {rd.GetName()} (normalized: {normalized_target})")
                    break
                rd = rd.GetNext()
        except Exception as e:
            safe_print(f"Error applying render preset: {e}")

    def _update_preset_buttons(self):
        """Update preset dropdown to show active preset"""
        # Map preset names to dropdown indices
        preset_to_index = {
            "previz": 0,
            "pre_render": 1,
            "render": 2,
            "stills": 3
        }

        normalized_preset = normalize_preset_name(self._active_preset)
        if normalized_preset in preset_to_index:
            self.SetInt32(G.PRESET_DROPDOWN, preset_to_index[normalized_preset])

    def _refresh(self):
        """Throttled refresh with performance optimization"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return

        # Check cooldown
        now = time.time()
        if now - self._last_check_time < CHECK_COOLDOWN:
            return
        self._last_check_time = now

        try:
            # Clear stale references before running checks
            check_cache.clear()

            # Run checks
            lights_bad = check_lights(doc)
            vis_bad = check_visibility_traps(doc)
            keys_bad = check_keys(doc)
            cam_bad = check_camera_shift(doc)
            rdc_bad = check_render_conflicts(doc)
            textures_bad = check_textures_unified(doc)
            unused_mats_bad = check_unused_materials(doc)
            names_bad = check_default_names(doc)
            output_bad = check_output_paths(doc)
            scene_stats = get_scene_stats(doc)

            # Count issues
            lights_count = len(lights_bad) if lights_bad else 0
            vis_count = len(vis_bad) if vis_bad else 0
            keys_count = len(keys_bad) if keys_bad else 0
            cam_count = len(cam_bad) if cam_bad else 0
            rdc_count = int(rdc_bad) if rdc_bad else 0
            textures_count = len(textures_bad) if textures_bad else 0
            unused_mats_count = len(unused_mats_bad) if unused_mats_bad else 0
            names_count = len(names_bad) if names_bad else 0
            output_count = len(output_bad) if output_bad else 0

            # Update StatusArea
            self.ua.set_state(
                dict(
                    lights=lights_count,
                    vis=vis_count,
                    vis_names=[_safe_name(o) for o in (vis_bad[:10] if vis_bad else [])],
                    keys=keys_count,
                    keys_names=[_safe_name(o) for o in (keys_bad[:10] if keys_bad else [])],
                    cam=cam_count,
                    rdc=rdc_count,
                    textures=textures_count,
                    unused_mats=unused_mats_count,
                    names=names_count,
                    names_list=[_safe_name(o) for o in (names_bad[:10] if names_bad else [])],
                    output=output_count,
                ),
                self.ua.show,
            )

            # Store results
            self._lights_bad = lights_bad
            self._vis_bad = vis_bad
            self._keys_bad = keys_bad
            self._cam_bad = cam_bad
            self._textures_bad = textures_bad
            self._scene_stats = scene_stats
            # Reset cycling indices when result count changes
            if len(unused_mats_bad) != len(self._unused_mats_bad):
                self._unused_mats_idx = 0
            if len(names_bad) != len(self._names_bad):
                self._names_idx = 0

            self._unused_mats_bad = unused_mats_bad
            self._names_bad = names_bad
            self._output_bad = output_bad

        except Exception as e:
            safe_print(f"Error during refresh: {e}")

    # ---- layout
    def CreateLayout(self):
        self.SetTitle(PLUGIN_NAME)

        # Main container
        self.GroupBegin(1, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(4, 4, 4, 4)

        # ── Scene Info ──
        self.GroupBegin(10, c4d.BFH_SCALEFIT, 4, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Shot ID", 0)
        self.AddEditText(G.SHOT, c4d.BFH_SCALEFIT, 80, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Artist  ", 0)
        self.AddEditText(G.ARTIST, c4d.BFH_SCALEFIT, 100, 0)
        self.GroupEnd()

        # ── Quality Checks ──
        self.AddSeparatorH(4)
        self.GroupBegin(39, c4d.BFH_SCALEFIT, 1, 0, "Quality Checks")
        self.GroupBorder(c4d.BORDER_WITH_TITLE_BOLD)
        self.GroupBorderSpace(4, 2, 4, 2)

        self.GroupBegin(40, c4d.BFH_SCALEFIT|c4d.BFV_TOP, 2, 0)
        self.GroupSpace(4, 0)

        # Left: terminal status display
        self.AddUserArea(G.CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 215)
        self.ua = StatusArea()
        self.AttachUserArea(self.ua, G.CANVAS)

        # Right: per-check Select + Fix buttons (2 columns, matched to StatusArea rows)
        self.GroupBegin(407, c4d.BFH_RIGHT|c4d.BFV_SCALEFIT, 2, 9)
        self.GroupBorderSpace(0, 3, 0, 3)
        self.GroupSpace(2, 3)
        # Row: LIGHTS
        self.AddButton(G.BTN_SEL_LIGHTS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_LIGHTS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        # Row: VISIBILITY
        self.AddButton(G.BTN_SEL_VIS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        # Row: KEYFRAMES
        self.AddButton(G.BTN_SEL_KEYS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        # Row: CAMERAS
        self.AddButton(G.BTN_SEL_CAMS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_CAMS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        # Row: PRESETS
        self.AddButton(G.BTN_INFO_PRESET, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        # Row: TEXTURES (unified)
        self.AddButton(G.BTN_INFO_TEXTURES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        # Row: UNUSED MATS
        self.AddButton(G.BTN_SEL_UNUSED_MATS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_UNUSED_MATS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        # Row: NAMES
        self.AddButton(G.BTN_SEL_NAMES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        # Row: OUTPUT
        self.AddButton(G.BTN_INFO_OUTPUT, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.GroupEnd()

        self.GroupEnd()
        self.GroupEnd()

        # ── Render Preset ──
        self.GroupBegin(19, c4d.BFH_SCALEFIT, 1, 0, "Render Preset")
        self.GroupBorder(c4d.BORDER_WITH_TITLE_BOLD)
        self.GroupBorderSpace(4, 2, 4, 2)
        self.GroupBegin(20, c4d.BFH_SCALEFIT, 3, 0)
        self.AddComboBox(G.PRESET_DROPDOWN, c4d.BFH_SCALEFIT, 100, 0)
        self.AddButton(G.BTN_FORCE_RENDER, c4d.BFH_SCALEFIT, 0, 0, "Force")
        self.AddButton(G.BTN_FORCE_ALL, c4d.BFH_SCALEFIT, 0, 0, "Force All")
        self.GroupEnd()
        self.GroupEnd()

        # ── RS AOVs ──
        self.GroupBegin(79, c4d.BFH_SCALEFIT, 1, 0, "Redshift AOVs")
        self.GroupBorder(c4d.BORDER_WITH_TITLE_BOLD)
        self.GroupBorderSpace(4, 2, 4, 2)
        self.GroupBegin(80, c4d.BFH_SCALEFIT, 3, 0)
        self.AddButton(G.BTN_INFO_AOVS, c4d.BFH_SCALEFIT, 0, 0, "Show AOVs")
        self.AddButton(G.BTN_FORCE_ESSENTIALS, c4d.BFH_SCALEFIT, 0, 0, "Essentials")
        self.AddButton(G.BTN_FORCE_PRODUCTION, c4d.BFH_SCALEFIT, 0, 0, "Production")
        self.GroupEnd()
        self.GroupEnd()

        # ── Quick Actions ──
        self.GroupBegin(49, c4d.BFH_SCALEFIT, 1, 0, "Quick Actions")
        self.GroupBorder(c4d.BORDER_WITH_TITLE_BOLD)
        self.GroupBorderSpace(4, 2, 4, 2)
        self.GroupBegin(50, c4d.BFH_SCALEFIT, 4, 0)
        self.AddButton(G.BTN_CREATE_HIERARCHY, c4d.BFH_SCALEFIT, 0, 0, "Hierarchy")
        self.AddButton(G.BTN_HIERARCHY_TO_LAYERS, c4d.BFH_SCALEFIT, 0, 0, "H -> Layers")
        self.AddButton(G.BTN_SOLO, c4d.BFH_SCALEFIT, 0, 0, "Solo Layers")
        self.AddButton(G.BTN_DROP_TO_FLOOR, c4d.BFH_SCALEFIT, 0, 0, "Drop to Floor")
        self.GroupEnd()
        self.GroupBegin(51, c4d.BFH_SCALEFIT, 4, 0)
        self.AddButton(G.BTN_VIBRATE_NULL, c4d.BFH_SCALEFIT, 0, 0, "Vibrate Null")
        self.AddButton(G.BTN_ABC_RETIME, c4d.BFH_SCALEFIT, 0, 0, "ABC Retime")
        self.AddButton(G.BTN_CAM_SIMPLE, c4d.BFH_SCALEFIT, 0, 0, "Cam Simple")
        self.AddButton(G.BTN_CAM_SHAKEL, c4d.BFH_SCALEFIT, 0, 0, "Cam Shakel")
        self.GroupEnd()
        self.GroupEnd()

        # ── Output ──
        self.GroupBegin(59, c4d.BFH_SCALEFIT, 1, 0, "Output")
        self.GroupBorder(c4d.BORDER_WITH_TITLE_BOLD)
        self.GroupBorderSpace(4, 2, 4, 2)

        # Snapshot dir display + set button
        self.GroupBegin(61, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(G.LABEL_SNAPSHOT_DIR, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddButton(G.BTN_SET_SNAPSHOT_DIR, c4d.BFH_RIGHT, 30, 0, "...")
        self.GroupEnd()

        # Action buttons
        self.GroupBegin(60, c4d.BFH_SCALEFIT, 3, 0)
        self.AddButton(G.BTN_OPEN_FOLDER, c4d.BFH_SCALEFIT, 0, 0, "Open Folder")
        self.AddButton(G.BTN_SNAPSHOT, c4d.BFH_SCALEFIT, 0, 0, "Save Still")
        self.AddButton(G.BTN_EXPORT_QC, c4d.BFH_SCALEFIT, 0, 0, "Export QC")
        self.GroupEnd()

        self.GroupEnd()

        # ── Footer ──
        self.GroupBegin(70, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_GITHUB, c4d.BFH_SCALEFIT, 0, 0, "GitHub")
        self.AddButton(G.BTN_BUG_REPORT, c4d.BFH_SCALEFIT, 0, 0, "Report Bug")
        self.GroupEnd()

        self.GroupEnd()  # Main container

        self.SetTimer(3000)
        return True

    def InitValues(self):
        # Initialize watcher states (all active by default - always enabled now)

        # Populate render preset dropdown
        self.AddChild(G.PRESET_DROPDOWN, 0, "Previz")
        self.AddChild(G.PRESET_DROPDOWN, 1, "Pre-Render")
        self.AddChild(G.PRESET_DROPDOWN, 2, "Render")
        self.AddChild(G.PRESET_DROPDOWN, 3, "Stills")

        # Load artist name from computer-level settings
        self._artist_name = GlobalSettings.load_artist_name()
        if self._artist_name:
            self.SetString(G.ARTIST, self._artist_name)

        # Initialize active preset
        self._active_preset = "previz"

        # Show snapshot directory
        self._update_snapshot_dir_label()

        doc = c4d.documents.GetActiveDocument()
        self._sync_from_doc(doc)
        self._refresh()
        self._last_doc = doc
        return True

    def Timer(self, msg):
        doc = c4d.documents.GetActiveDocument()

        # Document change detection
        if doc is not self._last_doc:
            check_cache.clear()
            self._sync_from_doc(doc)
            self._dirty = True
            self._last_doc = doc

        # Only refresh if dirty or cache expired
        if self._dirty:
            self._dirty = False
            self._refresh()
        else:
            self._refresh()  # Cache handles skip if still valid

    def CoreMessage(self, id, msg):
        if id == c4d.EVMSG_CHANGE:
            self._dirty = True  # Don't clear cache or refresh here - let Timer handle it
            return True

        if id == 431000159:  # EVMSG_TAKECHANGED
            doc = c4d.documents.GetActiveDocument()
            if doc:
                self._sync_from_doc(doc)
            self._dirty = True
            return True

        return gui.GeDialog.CoreMessage(self, id, msg)

    def Command(self, cid, msg):
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return True

        if cid == G.SHOT:
            self._apply_shot(doc)

        # Handle preset dropdown selection
        elif cid == G.PRESET_DROPDOWN:
            selected_index = self.GetInt32(G.PRESET_DROPDOWN)
            index_to_preset = {0: "previz", 1: "pre_render", 2: "render", 3: "stills"}
            if selected_index in index_to_preset:
                self._apply_preset(doc, index_to_preset[selected_index])

        # Handle Force button (applies template settings to current preset)
        elif cid == G.BTN_FORCE_RENDER:
            self._force_render_settings(doc)

        # Handle Force All button (applies template to all 4 presets + deletes others)
        elif cid == G.BTN_FORCE_ALL:
            self._force_all_presets(doc)

        elif cid == G.ARTIST:
            # Artist name changed - save to global settings
            new_artist_name = self.GetString(G.ARTIST).strip()
            if new_artist_name != self._artist_name:
                self._artist_name = new_artist_name
                GlobalSettings.save_artist_name(self._artist_name)

        elif cid == G.BTN_SNAPSHOT:
            self._take_renderview_snapshot()

        elif cid == G.BTN_INFO_AOVS:
            result = check_rs_aovs(doc, AOV_TIER_PRODUCTION)
            if not result["available"]:
                c4d.gui.MessageDialog("Redshift module not available.\n\nMake sure Redshift is installed and active.")
            elif not result["aovs"]:
                c4d.gui.MessageDialog("No AOVs configured.\n\nUse 'Essentials' or 'Production' to add passes.")
            else:
                msg = f"REDSHIFT AOVs: {len(result['aovs'])}\n\n"
                msg += "ACTIVE:\n"
                for aov in result["aovs"]:
                    status = "ON" if aov.get("enabled") else "OFF"
                    msg += f"  [{status}] {aov['name']}\n"

                # Check against both tiers
                ess = check_rs_aovs(doc, AOV_TIER_ESSENTIALS)
                prod = check_rs_aovs(doc, AOV_TIER_PRODUCTION)

                if ess["missing"]:
                    msg += f"\nMISSING ESSENTIALS ({len(ess['missing'])}):\n"
                    for n in ess["missing"]:
                        msg += f"  ! {n}\n"

                prod_only = [n for n in prod["missing"] if n not in ess["missing"]]
                if prod_only:
                    msg += f"\nMISSING PRODUCTION ({len(prod_only)}):\n"
                    for n in prod_only:
                        msg += f"  - {n}\n"

                if not prod["missing"]:
                    msg += "\nAll Production AOVs present."
                elif not ess["missing"]:
                    msg += "\nAll Essentials AOVs present."

                c4d.gui.MessageDialog(msg)

        elif cid == G.BTN_FORCE_ESSENTIALS:
            self._force_aov_tier(doc, AOV_TIER_ESSENTIALS, "Essentials")

        elif cid == G.BTN_FORCE_PRODUCTION:
            self._force_aov_tier(doc, AOV_TIER_PRODUCTION, "Production")

        elif cid == G.BTN_SET_SNAPSHOT_DIR:
            new_dir = c4d.storage.LoadDialog(title="Select RS Snapshot Folder", flags=c4d.FILESELECT_DIRECTORY)
            if new_dir:
                GlobalSettings.set_snapshot_dir(new_dir)
                self._update_snapshot_dir_label()
                safe_print(f"Snapshot directory set to: {new_dir}")

        elif cid == G.BTN_OPEN_FOLDER:
            self._open_artist_folder()

        elif cid == G.BTN_ABC_RETIME:
            self._apply_abc_retime_tag()

        elif cid == G.BTN_VIBRATE_NULL:
            self._create_vibrate_null(doc)

        elif cid == G.BTN_CAM_SIMPLE:
            self._merge_camera_file(doc, "cam_simple.c4d")

        elif cid == G.BTN_CAM_SHAKEL:
            self._merge_camera_file(doc, "cam_w_shakel.c4d")

        elif cid == G.BTN_CAM_PATH:
            self._merge_camera_file(doc, "cam_path.c4d")

        elif cid == G.BTN_CREATE_HIERARCHY:
            self._create_hierarchy(doc)

        elif cid == G.BTN_DROP_TO_FLOOR:
            self._drop_to_floor(doc)

        elif cid == G.BTN_HIERARCHY_TO_LAYERS:
            self._hierarchy_to_layers(doc)

        elif cid == G.BTN_SOLO:
            self._solo_layers(doc)

        elif cid == G.BTN_GITHUB:
            # Open GitHub repository
            github_url = "https://github.com/jmcodex93/ys-guardian"
            webbrowser.open(github_url)
            safe_print(f"Opening GitHub repository: {github_url}")

        elif cid == G.BTN_BUG_REPORT:
            # Open GitHub issues page for bug reports
            bug_url = "https://github.com/jmcodex93/ys-guardian/issues/new"
            webbrowser.open(bug_url)
            safe_print(f"Opening bug report page: {bug_url}")

        # Per-check Select buttons (1 click to select problematic objects)
        elif cid == G.BTN_SEL_LIGHTS:
            if self._lights_bad:
                _select_objects(doc, self._lights_bad)
                safe_print(f"Selected {len(self._lights_bad)} lights outside group")
            else:
                safe_print("No light issues found")

        elif cid == G.BTN_SEL_VIS:
            if self._vis_bad:
                _select_objects(doc, self._vis_bad)
                safe_print(f"Selected {len(self._vis_bad)} objects with visibility mismatch")
            else:
                safe_print("No visibility issues found")

        elif cid == G.BTN_SEL_KEYS:
            if self._keys_bad:
                _select_objects(doc, self._keys_bad)
                safe_print(f"Selected {len(self._keys_bad)} objects with multi-axis keyframes")
            else:
                safe_print("No keyframe issues found")

        elif cid == G.BTN_SEL_CAMS:
            if self._cam_bad:
                _select_objects(doc, self._cam_bad)
                safe_print(f"Selected {len(self._cam_bad)} cameras with non-zero shift")
            else:
                safe_print("No camera shift issues found")

        elif cid == G.BTN_INFO_PRESET:
            info_msg = "RENDER PRESETS:\n\n"
            info_msg += "Standard presets: previz, pre_render, render, stills\n\n"
            rd = doc.GetFirstRenderData()
            while rd:
                name = rd.GetName()
                normalized = normalize_preset_name(name)
                status = "OK" if normalized in set(PRESETS) else "NON-STANDARD"
                info_msg += f"  [{status}] {name}\n"
                rd = rd.GetNext()
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_TEXTURES:
            if self._textures_bad:
                absolute = [t for t in self._textures_bad if t["issue"] == "absolute"]
                missing = [t for t in self._textures_bad if t["issue"] == "missing"]
                info_msg = f"ASSET ISSUES: {len(self._textures_bad)}\n\n"
                if absolute:
                    info_msg += f"ABSOLUTE PATHS ({len(absolute)}):\n"
                    for i, t in enumerate(absolute[:10], 1):
                        info_msg += f"  {i}. {t['source']}\n     {t['path']}\n"
                    info_msg += "\n"
                if missing:
                    info_msg += f"MISSING FILES ({len(missing)}):\n"
                    for i, t in enumerate(missing[:10], 1):
                        info_msg += f"  {i}. {t['source']}\n     {t['path']}\n"
                    info_msg += "\n"
                info_msg += "Fix: Project > Save Project with Assets"
            else:
                info_msg = "All assets OK. No absolute paths or missing files."
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_SEL_UNUSED_MATS:
            if self._unused_mats_bad:
                # Cycle through unused materials one by one
                if self._unused_mats_idx >= len(self._unused_mats_bad):
                    self._unused_mats_idx = 0

                mat = self._unused_mats_bad[self._unused_mats_idx]
                # Deselect all materials first
                for m in doc.GetMaterials():
                    m.DelBit(c4d.BIT_ACTIVE)
                # Select this one
                mat.SetBit(c4d.BIT_ACTIVE)
                c4d.EventAdd()

                safe_print(f"Unused material [{self._unused_mats_idx + 1}/{len(self._unused_mats_bad)}]: '{mat.GetName()}'")
                self._unused_mats_idx += 1
            else:
                safe_print("No unused materials found")

        elif cid == G.BTN_SEL_NAMES:
            if self._names_bad:
                # Cycle through default-named objects one by one
                if self._names_idx >= len(self._names_bad):
                    self._names_idx = 0

                obj = self._names_bad[self._names_idx]
                _select_objects(doc, [obj])

                safe_print(f"Default name [{self._names_idx + 1}/{len(self._names_bad)}]: '{obj.GetName()}'")
                self._names_idx += 1
            else:
                safe_print("No naming issues found")

        elif cid == G.BTN_INFO_OUTPUT:
            if hasattr(self, '_output_bad') and self._output_bad:
                info_msg = f"OUTPUT PATH ISSUES: {len(self._output_bad)}\n\n"
                for i, issue in enumerate(self._output_bad[:10], 1):
                    info_msg += f"{i}. [{issue['preset']}] {issue['issue']}\n"
                info_msg += "\nUse $prj and $take tokens in output paths."
            else:
                info_msg = "All output paths are properly configured."
            c4d.gui.MessageDialog(info_msg)

        # ── Auto-fix handlers ──
        elif cid == G.BTN_FIX_LIGHTS:
            if self._lights_bad:
                count = fix_lights(doc, self._lights_bad)
                safe_print(f"Moved {count} lights into 'lights' group")
                c4d.gui.MessageDialog(f"Moved {count} light(s) into 'lights' group.\n\nUndo available (Ctrl+Z).")
            else:
                safe_print("No light issues to fix")

        elif cid == G.BTN_FIX_CAMS:
            if self._cam_bad:
                count = fix_camera_shift(doc, self._cam_bad)
                safe_print(f"Reset shift on {count} cameras")
                c4d.gui.MessageDialog(f"Reset shift to 0 on {count} camera(s).\n\nUndo available (Ctrl+Z).")
            else:
                safe_print("No camera shift issues to fix")

        elif cid == G.BTN_FIX_UNUSED_MATS:
            if self._unused_mats_bad:
                count = len(self._unused_mats_bad)
                if c4d.gui.QuestionDialog(f"Delete {count} unused material(s)?\n\nThis can be undone (Ctrl+Z)."):
                    deleted = fix_unused_materials(doc, self._unused_mats_bad)
                    safe_print(f"Deleted {deleted} unused materials")
                    self._unused_mats_idx = 0
            else:
                safe_print("No unused materials to delete")

        # ── Export QC Report ──
        elif cid == G.BTN_EXPORT_QC:
            results = {
                "lights_bad": self._lights_bad,
                "vis_bad": self._vis_bad,
                "keys_bad": self._keys_bad,
                "cam_bad": self._cam_bad,
                "rdc_count": int(check_render_conflicts(doc) or 0),
                "textures_bad": self._textures_bad,
                "unused_mats_bad": self._unused_mats_bad,
                "names_bad": self._names_bad,
                "output_bad": self._output_bad,
                "output_count": len(self._output_bad) if self._output_bad else 0,
                "scene_stats": self._scene_stats,
            }
            save_path = export_qc_report(doc, results, self._artist_name)
            if save_path:
                safe_print(f"QC report saved to: {save_path}")
                c4d.gui.MessageDialog(f"QC Report saved!\n\n{save_path}")

        return True

    def _force_aov_tier(self, doc, tier_list, tier_name):
        if not REDSHIFT_AVAILABLE:
            c4d.gui.MessageDialog("Redshift module not available.")
            return
        result = check_rs_aovs(doc, tier_list)
        if not result["missing"]:
            c4d.gui.MessageDialog(f"All {tier_name} AOVs already configured.")
            return
        missing_list = "\n".join(f"  - {n}" for n in result["missing"])
        if c4d.gui.QuestionDialog(f"Add {len(result['missing'])} {tier_name} AOVs?\n\n{missing_list}"):
            added, error = force_aov_tier(doc, tier_list)
            if error:
                c4d.gui.MessageDialog(f"Error: {error}")
            else:
                safe_print(f"Added {added} {tier_name} AOVs")
                c4d.gui.MessageDialog(f"Added {added} {tier_name} AOV(s).\n\n32-bit float set for: Depth, Motion Vectors, World Position")

    def _open_artist_folder(self):
        """Open the artist's output folder"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document!")
            return

        snapshot_open_folder(doc, self._artist_name)

    def _create_vibrate_null(self, doc):
        self._merge_c4d_file(doc, "VibrateNull.c4d")

    def _create_hierarchy(self, doc):
        self._merge_c4d_file(doc, "nulls.c4d")

    def _merge_camera_file(self, doc, filename):
        self._merge_c4d_file(doc, filename)

    def _merge_c4d_file(self, doc, filename):
        """Merge camera setup from C4D file"""
        if not doc:
            return

        try:
            # Get path to the C4D file (in the same plugin directory)
            plugin_dir = os.path.dirname(__file__)
            c4d_file = os.path.join(plugin_dir, "c4d", filename)

            # Check if file exists
            if not os.path.exists(c4d_file):
                safe_print(f"{filename} not found at: {c4d_file}")
                c4d.gui.MessageDialog(f"{filename} file not found in c4d folder")
                return

            # Merge the C4D file into the current document
            merge_doc = c4d.documents.MergeDocument(doc, c4d_file, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)

            if merge_doc:
                c4d.EventAdd()
                camera_name = filename.replace(".c4d", "").replace("cam_", "").replace("_", " ").title()
                safe_print(f"Merged {camera_name} camera setup from {filename}")
            else:
                safe_print(f"Failed to merge {filename}")

        except Exception as e:
            safe_print(f"Error merging camera file {filename}: {e}")
            c4d.gui.MessageDialog(f"Error loading camera setup: {e}")

    def _load_template_render_data(self, preset_name):
        """Load render data from template C4D file for the specified preset"""
        try:
            # Get path to the template C4D file (in plugin's c4d folder)
            plugin_dir = os.path.dirname(__file__)
            template_path = os.path.join(plugin_dir, "c4d", "new.c4d")

            # Check if template file exists
            if not os.path.exists(template_path):
                safe_print(f"Template file not found: {template_path}")
                return None

            # Load the template document
            template_doc = c4d.documents.LoadDocument(template_path, c4d.SCENEFILTER_NONE)
            if not template_doc:
                safe_print(f"Failed to load template document: {template_path}")
                return None

            # Find the render data matching the preset name
            template_rd = template_doc.GetFirstRenderData()
            normalized_target = normalize_preset_name(preset_name)

            while template_rd:
                template_name = normalize_preset_name(template_rd.GetName() or "")
                if template_name == normalized_target:
                    # Clone the render data
                    cloned_rd = template_rd.GetClone(c4d.COPYFLAGS_NONE)
                    c4d.documents.KillDocument(template_doc)  # Clean up template doc
                    return cloned_rd
                template_rd = template_rd.GetNext()

            c4d.documents.KillDocument(template_doc)  # Clean up template doc
            safe_print(f"Preset '{preset_name}' not found in template file")
            return None

        except Exception as e:
            safe_print(f"Error loading template render data: {e}")
            return None

    def _force_render_settings(self, doc):
        """Force apply render settings from template file to active preset"""
        if not doc:
            return

        template_doc = None
        try:
            # Get the active preset name
            preset_name = self._active_preset

            # Load the template document
            plugin_dir = os.path.dirname(__file__)
            template_path = os.path.join(plugin_dir, "c4d", "new.c4d")

            if not os.path.exists(template_path):
                c4d.gui.MessageDialog(f"Template file not found!\n\n"
                                     f"Expected at:\n{template_path}")
                return

            template_doc = c4d.documents.LoadDocument(template_path, c4d.SCENEFILTER_NONE)
            if not template_doc:
                c4d.gui.MessageDialog(f"Failed to load template file!\n\n{template_path}")
                return

            # Find the matching preset in the template
            template_rd = template_doc.GetFirstRenderData()
            normalized_target = normalize_preset_name(preset_name)
            source_rd = None

            while template_rd:
                template_name = normalize_preset_name(template_rd.GetName() or "")
                if template_name == normalized_target:
                    source_rd = template_rd
                    break
                template_rd = template_rd.GetNext()

            if not source_rd:
                c4d.gui.MessageDialog(f"Preset '{preset_name}' not found in template file!\n\n"
                                     f"Template should contain: Previz, Pre-Render, Render, Stills")
                return

            # Find or create render data with this name in the current document
            rd = doc.GetFirstRenderData()
            target_rd = None

            # Search for existing preset (using normalized comparison)
            while rd:
                if normalize_preset_name(rd.GetName() or "") == normalize_preset_name(preset_name):
                    target_rd = rd
                    break
                rd = rd.GetNext()

            if not target_rd:
                # Create new render data if not found
                target_rd = c4d.documents.RenderData()
                target_rd.SetName(preset_name)
                doc.InsertRenderData(target_rd)
                safe_print(f"Created new render preset: {preset_name}")

            # Copy all settings from template to target (while template doc is still alive)
            source_rd.CopyTo(target_rd, c4d.COPYFLAGS_NONE)

            # Set as active
            doc.SetActiveRenderData(target_rd)
            check_cache.clear()  # Clear cache to update compliance check immediately
            c4d.EventAdd()

            safe_print(f"Applied template settings for '{preset_name}' preset")
            c4d.gui.MessageDialog(f"Applied template settings for '{preset_name}' preset\n\n"
                                 f"Resolution: {target_rd[c4d.RDATA_XRES]}x{target_rd[c4d.RDATA_YRES]}\n"
                                 f"Frame Rate: {target_rd[c4d.RDATA_FRAMERATE]} fps\n"
                                 f"Output Path: {target_rd[c4d.RDATA_PATH]}")

        except Exception as e:
            safe_print(f"Error forcing render settings: {e}")
            c4d.gui.MessageDialog(f"Error applying template settings: {e}")
        finally:
            # Clean up template document
            if template_doc:
                c4d.documents.KillDocument(template_doc)

    def _force_all_presets(self, doc):
        """Force all 4 render presets from template file and delete others"""
        if not doc:
            return

        try:
            # Define the 4 standard presets
            standard_presets = ["previz", "pre_render", "render", "stills"]

            # Delete all existing render data first
            rd = doc.GetFirstRenderData()
            deleted_count = 0
            while rd:
                next_rd = rd.GetNext()
                rd.Remove()
                deleted_count += 1
                rd = next_rd

            safe_print(f"Deleted {deleted_count} existing render presets")

            # Load and insert all 4 standard presets from template
            inserted_count = 0
            first_rd = None

            for preset_name in standard_presets:
                # Load template render data for this preset
                template_rd = self._load_template_render_data(preset_name)
                if template_rd:
                    # Ensure proper name
                    template_rd.SetName(preset_name)
                    # Insert into document
                    doc.InsertRenderData(template_rd)
                    inserted_count += 1
                    if first_rd is None:
                        first_rd = template_rd
                    safe_print(f"Inserted '{preset_name}' preset from template")
                else:
                    safe_print(f"Warning: Could not load '{preset_name}' from template")

            # Set the first preset (previz) as active
            if first_rd:
                doc.SetActiveRenderData(first_rd)
                self._active_preset = "previz"
                self._update_preset_buttons()

            check_cache.clear()  # Clear cache to update compliance check immediately
            c4d.EventAdd()

            if inserted_count > 0:
                c4d.gui.MessageDialog(f"Force All Presets Complete!\n\n"
                                     f"Deleted {deleted_count} old presets\n"
                                     f"Inserted {inserted_count} standard presets from template:\n"
                                     f"• Previz\n"
                                     f"• Pre-Render\n"
                                     f"• Render\n"
                                     f"• Stills\n\n"
                                     f"Active preset: Previz")
            else:
                plugin_dir = os.path.dirname(__file__)
                template_path = os.path.join(plugin_dir, "c4d", "new.c4d")
                c4d.gui.MessageDialog(f"Failed to load presets from template file.\n\n"
                                     f"Make sure the template file exists at:\n{template_path}")

        except Exception as e:
            safe_print(f"Error forcing all presets: {e}")
            c4d.gui.MessageDialog(f"Error forcing all presets: {e}")

    def _hierarchy_to_layers(self, doc):
        """Link main project nulls and their children to layers with matching names"""
        if not doc:
            return

        safe_print("Starting Hierarchy to Layers sync...")

        # Check for objects outside nulls first
        root_objects = []
        orphan_objects = []

        obj = doc.GetFirstObject()
        while obj:
            # Only consider top-level objects
            if obj.GetUp() is None:
                if obj.GetType() == c4d.Onull:
                    root_objects.append(obj)
                else:
                    # Check if it's a camera or light (they might be allowed outside)
                    obj_type = obj.GetType()
                    if obj_type not in [c4d.Ocamera, c4d.Olight]:
                        orphan_objects.append(obj)
            obj = obj.GetNext()

        # If there are orphan objects, show error
        if orphan_objects:
            orphan_names = [obj.GetName() for obj in orphan_objects[:5]]  # Show first 5
            more = f" and {len(orphan_objects)-5} more" if len(orphan_objects) > 5 else ""

            msg = f"Found {len(orphan_objects)} object(s) outside of null groups:\n"
            msg += "\n".join(orphan_names) + more
            msg += "\n\nPlease organize all objects into null groups first."
            c4d.gui.MessageDialog(msg)
            safe_print(f"Aborted: {len(orphan_objects)} objects found outside null groups")
            return

        # No orphans, proceed with layer sync
        if not root_objects:
            c4d.gui.MessageDialog("No null groups found in the scene.")
            return

        # Start undo
        doc.StartUndo()

        # Get or create layer root
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            safe_print("Error: Could not get layer root")
            doc.EndUndo()
            return

        created_layers = 0
        updated_layers = 0

        for null in root_objects:
            null_name = null.GetName()

            # Find or create layer with matching name (returns layer and is_new flag)
            layer, is_new = self._find_or_create_layer(doc, layer_root, null_name)

            if layer:
                # Assign null and all children to this layer
                self._assign_to_layer_recursive(doc, null, layer)

                if is_new:
                    created_layers += 1
                    safe_print(f"Created new layer '{null_name}' and synced objects")
                else:
                    updated_layers += 1
                    safe_print(f"Updated existing layer '{null_name}' with objects")

        doc.EndUndo()
        c4d.EventAdd()

        # Just report to console, no popup
        safe_print(f"Hierarchy→Layers complete: {created_layers} new, {updated_layers} updated layers, {len(root_objects)} nulls synced")

    def _find_or_create_layer(self, doc, layer_root, name):
        """Find existing layer by name or create new one. Returns (layer, is_new)"""
        # First, search for existing layer
        layer = layer_root.GetDown()
        while layer:
            if layer.GetName() == name:
                return layer, False  # Found existing
            layer = layer.GetNext()

        # Create new layer
        new_layer = c4d.documents.LayerObject()
        new_layer.SetName(name)
        new_layer.InsertUnder(layer_root)

        # Generate unique random color based on layer name hash
        # This ensures same name always gets same color (consistent)
        import hashlib

        # Create hash from name
        name_hash = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)

        # Generate pleasant, distinct colors using golden ratio
        # This creates visually distinct colors that are evenly distributed
        golden_ratio = 0.618033988749895
        hue = (name_hash * golden_ratio) % 1.0

        # Convert HSV to RGB (S=0.6, V=0.95 for pleasant, bright colors)
        saturation = 0.6
        value = 0.95

        def hsv_to_rgb(h, s, v):
            """Convert HSV to RGB"""
            h_i = int(h * 6)
            f = h * 6 - h_i
            p = v * (1 - s)
            q = v * (1 - f * s)
            t = v * (1 - (1 - f) * s)

            if h_i == 0:
                r, g, b = v, t, p
            elif h_i == 1:
                r, g, b = q, v, p
            elif h_i == 2:
                r, g, b = p, v, t
            elif h_i == 3:
                r, g, b = p, q, v
            elif h_i == 4:
                r, g, b = t, p, v
            else:
                r, g, b = v, p, q

            return c4d.Vector(r, g, b)

        unique_color = hsv_to_rgb(hue, saturation, value)
        new_layer[c4d.ID_LAYER_COLOR] = unique_color

        doc.AddUndo(c4d.UNDOTYPE_NEW, new_layer)
        return new_layer, True  # Return new layer and flag

    def _solo_layers(self, doc):
        """Solo selected layers - disable all other layers and their objects"""
        if not doc:
            return

        # Check if any layers are currently disabled (solo is active)
        # If so, restore all layers
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            safe_print("Error: Could not get layer root")
            return

        # Check if we're in solo mode
        def check_solo_mode(layer):
            """Check if any layer is disabled (indicating solo mode)"""
            while layer:
                if not layer[c4d.ID_LAYER_VIEW]:
                    return True
                child = layer.GetDown()
                if child and check_solo_mode(child):
                    return True
                layer = layer.GetNext()
            return False

        first_layer = layer_root.GetDown()
        if first_layer and check_solo_mode(first_layer):
            # We're in solo mode, restore all
            self._unsolo_layers(doc)
            return

        # Get all selected layers
        selected_layers = []

        def collect_selected_layers(layer):
            """Recursively collect selected layers"""
            while layer:
                if layer.GetBit(c4d.BIT_ACTIVE):
                    selected_layers.append(layer)
                # Check children
                child = layer.GetDown()
                if child:
                    collect_selected_layers(child)
                layer = layer.GetNext()

        # Start from first layer
        first_layer = layer_root.GetDown()
        if not first_layer:
            c4d.gui.MessageDialog("No layers found in the scene.\nCreate layers first using Hierarchy→Layers.")
            return

        collect_selected_layers(first_layer)

        if not selected_layers:
            c4d.gui.MessageDialog("Please select one or more layers to solo.")
            return

        safe_print(f"Solo mode: Isolating {len(selected_layers)} layer(s)")

        # Start undo
        doc.StartUndo()

        # Track what we're doing
        layers_disabled = 0
        layers_soloed = 0
        objects_affected = 0

        # First pass: Process all layers
        def process_layer(layer, is_soloed):
            """Process a layer and return count of affected objects"""
            nonlocal layers_disabled, layers_soloed

            doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

            if is_soloed:
                # Enable this layer
                layer[c4d.ID_LAYER_VIEW] = True
                layer[c4d.ID_LAYER_RENDER] = True
                layer[c4d.ID_LAYER_MANAGER] = True
                layer[c4d.ID_LAYER_GENERATORS] = True
                layer[c4d.ID_LAYER_DEFORMERS] = True
                layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = True
                layer[c4d.ID_LAYER_LOCKED] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = True
                layers_soloed += 1
                safe_print(f"  Enabled layer: {layer.GetName()}")
            else:
                # Disable this layer completely
                layer[c4d.ID_LAYER_VIEW] = False
                layer[c4d.ID_LAYER_RENDER] = False
                layer[c4d.ID_LAYER_MANAGER] = False
                layer[c4d.ID_LAYER_GENERATORS] = False
                layer[c4d.ID_LAYER_DEFORMERS] = False
                layer[c4d.ID_LAYER_EXPRESSIONS] = False  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = False
                layers_disabled += 1

        # Process all layers
        def process_all_layers(layer):
            while layer:
                is_selected = layer in selected_layers
                process_layer(layer, is_selected)

                # Process children
                child = layer.GetDown()
                if child:
                    process_all_layers(child)

                layer = layer.GetNext()

        process_all_layers(first_layer)

        # Second pass: Handle objects without layers (disable them too)
        def disable_unassigned_objects(obj):
            """Disable objects not assigned to any layer"""
            nonlocal objects_affected

            while obj:
                # Check if object has no layer assignment
                if not obj.GetLayerObject(doc):
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                    # Disable the object
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 1  # Hide in editor
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 1  # Hide in render

                    # Disable generators and deformers
                    obj.SetDeformMode(False)

                    # If it's a generator, try to disable it
                    if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                        obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = False

                    objects_affected += 1

                # Process children
                child = obj.GetDown()
                if child:
                    disable_unassigned_objects(child)

                obj = obj.GetNext()

        # Disable unassigned objects
        first_object = doc.GetFirstObject()
        if first_object:
            disable_unassigned_objects(first_object)

        doc.EndUndo()
        c4d.EventAdd()

        # Report to console
        safe_print(f"Solo Layers complete: {layers_soloed} soloed, {layers_disabled} disabled, {objects_affected} unassigned objects hidden")

    def _unsolo_layers(self, doc):
        """Restore all layers to their default visible state"""
        if not doc:
            return

        safe_print("Restoring all layers...")

        # Get layer root
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            return

        doc.StartUndo()

        layers_restored = 0

        def restore_layer(layer):
            """Restore a layer to default visible state"""
            nonlocal layers_restored

            while layer:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

                # Enable everything
                layer[c4d.ID_LAYER_VIEW] = True
                layer[c4d.ID_LAYER_RENDER] = True
                layer[c4d.ID_LAYER_MANAGER] = True
                layer[c4d.ID_LAYER_GENERATORS] = True
                layer[c4d.ID_LAYER_DEFORMERS] = True
                layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = True
                layer[c4d.ID_LAYER_LOCKED] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = True

                layers_restored += 1

                # Process children
                child = layer.GetDown()
                if child:
                    restore_layer(child)

                layer = layer.GetNext()

        # Restore all layers
        first_layer = layer_root.GetDown()
        if first_layer:
            restore_layer(first_layer)

        # Restore objects without layers
        def restore_unassigned_objects(obj):
            while obj:
                if not obj.GetLayerObject(doc):
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 2  # Show
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 2  # Show
                    obj.SetDeformMode(True)
                    if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                        obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = True

                child = obj.GetDown()
                if child:
                    restore_unassigned_objects(child)

                obj = obj.GetNext()

        first_object = doc.GetFirstObject()
        if first_object:
            restore_unassigned_objects(first_object)

        doc.EndUndo()
        c4d.EventAdd()

        safe_print(f"Restored {layers_restored} layers to visible state")

    def _assign_to_layer_recursive(self, doc, obj, layer):
        """Assign object and all its children to a layer"""
        if not obj or not layer:
            return

        # Add undo for the object
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

        # Assign to layer
        obj.SetLayerObject(layer)

        # Process all children recursively
        child = obj.GetDown()
        while child:
            self._assign_to_layer_recursive(doc, child, layer)
            child = child.GetNext()

    def _drop_to_floor(self, doc):
        """Drop selected objects to floor (Y=0 plane) - handles rotation and hierarchy correctly"""
        if not doc:
            return

        # Get selected objects
        selected = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_SELECTIONORDER)
        if not selected:
            safe_print("Please select one or more objects to drop to floor")
            return

        # Start undo
        doc.StartUndo()

        dropped_count = 0

        for obj in selected:
            # Get object's global matrix
            mg = obj.GetMg()

            # Get cache (the actual geometry for display/render)
            cache = obj.GetCache()
            if cache is None:
                cache = obj.GetDeformCache()

            # If we have a cache, use it to get the accurate global bounding box
            if cache:
                # Initialize with first point
                min_y = None

                # Recursively process cache and all children
                def process_cache(cache_obj, parent_mg):
                    """Recursively get all points from cache hierarchy"""
                    nonlocal min_y

                    if not cache_obj:
                        return

                    # Get cache's local matrix
                    cache_mg = cache_obj.GetMl()
                    # Combine with parent matrix to get global position
                    global_mg = parent_mg * cache_mg

                    # Get points if this is a PointObject
                    if cache_obj.CheckType(c4d.Opoint):
                        points = cache_obj.GetAllPoints()
                        if points:
                            for point in points:
                                # Transform point to global space
                                global_point = global_mg * point
                                if min_y is None or global_point.y < min_y:
                                    min_y = global_point.y

                    # Process children
                    child = cache_obj.GetDown()
                    if child:
                        process_cache(child, global_mg)

                    # Process siblings
                    next_obj = cache_obj.GetNext()
                    if next_obj:
                        process_cache(next_obj, parent_mg)

                # Process cache hierarchy
                process_cache(cache, mg)

                # If we didn't find any points, fall back to bounding box method
                if min_y is None:
                    # Use bounding box as fallback
                    mp = obj.GetMp()
                    rad = obj.GetRad()

                    if rad.GetLength() == 0:
                        rad = c4d.Vector(50, 50, 50)

                    # Calculate all 8 corners
                    corners = [
                        c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                    ]

                    min_y = float('inf')
                    for corner in corners:
                        world_corner = mg * corner
                        if world_corner.y < min_y:
                            min_y = world_corner.y
            else:
                # No cache - use bounding box method
                mp = obj.GetMp()
                rad = obj.GetRad()

                if rad.GetLength() == 0:
                    rad = c4d.Vector(50, 50, 50)

                # Calculate all 8 corners
                corners = [
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                ]

                min_y = float('inf')
                for corner in corners:
                    world_corner = mg * corner
                    if world_corner.y < min_y:
                        min_y = world_corner.y

            # Calculate how much to move the object
            if min_y is not None and abs(min_y) > 0.001:  # Small threshold to avoid tiny movements
                move_distance = -min_y

                # Record undo for position change
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                # Move the object in global space
                current_pos = obj.GetAbsPos()
                new_pos = c4d.Vector(current_pos.x, current_pos.y + move_distance, current_pos.z)
                obj.SetAbsPos(new_pos)

                dropped_count += 1
                safe_print(f"Dropped '{obj.GetName()}' by {move_distance:.2f} units")

        # End undo
        doc.EndUndo()

        # Update the scene
        c4d.EventAdd()

        # Show result message in console only (no popup for smooth workflow)
        if dropped_count == 1:
            safe_print(f"Dropped 1 object to floor")
        elif dropped_count > 1:
            safe_print(f"Dropped {dropped_count} objects to floor")
        else:
            safe_print("No objects needed dropping - already on floor")

    def _take_renderview_snapshot(self):
        """Take a snapshot from RenderView"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document!")
            return

        if not self._artist_name:
            c4d.gui.MessageDialog("Please set your artist name first!")
            return

        snapshot_save_still(doc, self._artist_name)

    def _apply_abc_retime_tag(self):
        """Apply ABC Retime tag to selected object(s)"""
        doc = documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document")
            return

        selection = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN)
        if not selection:
            c4d.gui.MessageDialog("Please select an object first\n\n(Works with Alembic, Point Cache, Mograph Cache, or X-Particles Cache objects)")
            return

        # ABC Retime plugin ID
        ABC_RETIME_TAG_ID = 1058910

        applied_count = 0
        skipped_count = 0
        failed_count = 0

        for obj in selection:
            # Check if tag already exists
            existing_tag = obj.GetTag(ABC_RETIME_TAG_ID)
            if existing_tag:
                safe_print(f"ABC Retime tag already exists on {obj.GetName()}")
                skipped_count += 1
                continue

            # Apply the tag
            tag = obj.MakeTag(ABC_RETIME_TAG_ID)
            if tag:
                applied_count += 1
                safe_print(f"ABC Retime tag applied to {obj.GetName()}")
            else:
                failed_count += 1
                safe_print(f"Failed to apply ABC Retime tag to {obj.GetName()}")

        # Update the scene
        if applied_count > 0:
            c4d.EventAdd()

        # Show error message only if failed
        if applied_count == 0 and skipped_count == 0:
            c4d.gui.MessageDialog("ABC Retime tag could not be applied\n\nPossible reasons:\n- ABC Retime plugin not installed\n- Invalid object type\n\nManual access: Right-click Tags → Extensions → Alembic Retime")

    def DestroyWindow(self):
        """Clean up when panel closes"""
        pass  # No cleanup needed anymore

def _select_objects(doc, objs):
    """Select objects in the scene"""
    if not doc or not objs:
        return

    first = doc.GetFirstObject()
    if first:
        for o in _iter_objs(first):
            o.DelBit(c4d.BIT_ACTIVE)

    for o in objs:
        try:
            if o:
                o.SetBit(c4d.BIT_ACTIVE)
        except Exception:
            pass

    c4d.EventAdd()

# -------------- registration --------------
class YSPanelCmd(plugins.CommandData):
    dlg = None

    def Execute(self, doc):
        if self.dlg is None:
            self.dlg = YSPanel()
            safe_print(f"{PLUGIN_NAME} initialized")
        # Pass plugin ID as second argument for layout persistence
        return self.dlg.Open(dlgtype=c4d.DLG_TYPE_ASYNC, pluginid=PLUGIN_ID,
                            defaultw=420, defaulth=360)

    def RestoreLayout(self, sec_ref):
        """Required for layout persistence - called when C4D restores layouts"""
        if self.dlg is None:
            self.dlg = YSPanel()
        # Restore the dialog with the plugin ID
        return self.dlg.Restore(pluginid=PLUGIN_ID, secret=sec_ref)

def Register():
    # Load plugin icon (PNG format for best Cinema 4D compatibility)
    icon = c4d.bitmaps.BaseBitmap()
    icon_path = os.path.join(os.path.dirname(__file__), "icons", "ys-logo-alpha-32.png")

    if os.path.exists(icon_path):
        result = icon.InitWith(icon_path)
        if result[0] == c4d.IMAGERESULT_OK:
            # Validate icon properties
            width = icon.GetBw()
            height = icon.GetBh()
            depth = icon.GetBt()

            if width == 32 and height == 32:
                safe_print(f"Plugin icon loaded: {icon_path} ({width}x{height}, {depth}-bit)")
            else:
                safe_print(f"Warning: Icon loaded but dimensions are {width}x{height}, expected 32x32")
        else:
            safe_print(f"Warning: Failed to load icon from {icon_path}")
            icon = None  # Use no icon instead of empty bitmap
    else:
        safe_print(f"Warning: Icon not found at {icon_path}")
        icon = None  # Use no icon instead of empty bitmap

    ok = plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        icon=icon,
        help="Open YS Guardian Panel",
        dat=YSPanelCmd()
    )
    if ok:
        safe_print(f"{PLUGIN_NAME} registered successfully")
    else:
        safe_print("Failed to register Guardian panel")
    return ok

if __name__ == "__main__":
    # Print setup info using safe_print to avoid None returns in console
    safe_print("\n" + "="*50)
    safe_print(f"{PLUGIN_NAME}")
    safe_print(f"  Snapshot dir: {GlobalSettings.get_snapshot_dir()}")
    safe_print(f"  9 Quality Checks | ACES tone mapping")
    safe_print("="*50 + "\n")

    Register()