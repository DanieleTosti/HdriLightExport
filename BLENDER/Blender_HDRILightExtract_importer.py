"""
Blender HDRI Light Rig Importer  v1.0
Author: Daniele Tosti - 2026-03

Converts Nuke's HDRI Light Export metadata (embedded in EXR files)
into a Blender lighting rig using native Blender lights.

Features:
    - World Environment Texture for HDRI dome
    - Native AREA lights for extracted rectangular light sources
    - Native SUN lights for distant/sun sources
    - Per-light LightGroup metadata from Nuke -> _LGT<n> naming
    - Exposure_compensation global control with per-light drivers
    - Enable_z_translate toggle + ZTranslate_lights offset (driven)
    - Track To constraints targeting rig center
    - Y-up to Z-up coordinate conversion
    - Name sanitization (dashes replaced with underscores)

Usage:
    import importlib, sys
    sys.path.append(r"path/to/script/folder")
    import Blender_HDRILightExtract_importer
    importlib.reload(Blender_HDRILightExtract_importer)
    Blender_HDRILightExtract_importer.build_light_rig(r"C:\\path\\to\\hdri.exr")

Author: DanieleT - 202106 (Blender port: 2026-03)
"""

import bpy
import math
import os
import struct
import time
import traceback


# ---------------------------------------------------------------------------
# Logging helper -- visible in Blender's Info editor AND system console
# ---------------------------------------------------------------------------

_LOG_LINES = []


def _log(msg, level="INFO"):
    """Print *msg* to stdout and append to the in-memory log.

    After the rig is built the full log is also stored as a custom property
    on the rig collection so it survives even if the system console is closed.
    """
    print("[HDRI Importer] {}".format(msg))
    _LOG_LINES.append(msg)
    # bpy.context.window_manager can be None in background mode.
    try:
        bpy.context.workspace.status_text_set(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# EXR metadata parser (stdlib only -- no OpenEXR / OpenImageIO dependency)
# ---------------------------------------------------------------------------

def _read_null_terminated_string(f):
    """Read bytes from file handle *f* until a null terminator, return str."""
    chars = []
    while True:
        b = f.read(1)
        if not b or b == b"\x00":
            break
        chars.append(b)
    return b"".join(chars).decode("utf-8", errors="replace")


def read_exr_metadata(filepath):
    """
    Read all header attributes from an OpenEXR file.

    Only uses the ``struct`` module (Python stdlib).  Handles ``string``,
    ``int``, ``float`` and ``double`` attribute types.  Other types are
    silently skipped.

    Args:
        filepath: Absolute path to the EXR file.

    Returns:
        dict of ``{attribute_name: attribute_value}``.
    """
    metadata = {}

    with open(filepath, "rb") as f:
        magic = struct.unpack("<I", f.read(4))[0]
        if magic != 20000630:
            raise ValueError("Not a valid OpenEXR file: {}".format(filepath))

        # Version (4 bytes) -- skip, we only need header attributes.
        f.read(4)

        while True:
            name = _read_null_terminated_string(f)
            if not name:
                break

            attr_type = _read_null_terminated_string(f)
            size = struct.unpack("<I", f.read(4))[0]
            raw = f.read(size)

            if attr_type == "string" and size > 0:
                # Standard OpenEXR: 4-byte length prefix + character data.
                # Some writers (including certain Nuke versions) omit the
                # length prefix and store the raw string directly.  We detect
                # the format by checking whether the first 4 bytes, read as
                # a little-endian int, equal (size - 4).
                if size >= 4:
                    candidate_len = struct.unpack("<i", raw[:4])[0]
                    if candidate_len == size - 4 and candidate_len >= 0:
                        metadata[name] = raw[4:4 + candidate_len].decode(
                            "utf-8", errors="replace"
                        )
                    else:
                        metadata[name] = raw.decode(
                            "utf-8", errors="replace"
                        ).rstrip("\x00")
                else:
                    metadata[name] = raw.decode(
                        "utf-8", errors="replace"
                    ).rstrip("\x00")
            elif attr_type == "int" and size == 4:
                metadata[name] = struct.unpack("<i", raw)[0]
            elif attr_type == "float" and size == 4:
                metadata[name] = struct.unpack("<f", raw)[0]
            elif attr_type == "double" and size == 8:
                metadata[name] = struct.unpack("<d", raw)[0]

    return metadata


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _yup_to_zup(x, y, z):
    """Convert a position from Y-up (Nuke/Gaffer/USD) to Z-up (Blender)."""
    return (x, -z, y)


# ---------------------------------------------------------------------------
# Driver helpers
# ---------------------------------------------------------------------------

def _add_energy_driver(light_obj, rig_empty, base_exposure):
    """
    Drive ``light_obj.data.energy`` with::

        energy = 2 ** (base_exposure + Exposure_compensation)

    where *Exposure_compensation* is a custom property on *rig_empty*.

    When the light uses a shader node tree (``use_nodes=True``) the Emission
    node's Strength input is driven as well so the two stay in sync.
    """
    expr = "2 ** ({} + exp_comp)".format(base_exposure)

    # Drive the RNA energy property.
    fcurve = light_obj.data.driver_add("energy")
    drv = fcurve.driver
    drv.type = "SCRIPTED"
    var = drv.variables.new()
    var.name = "exp_comp"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = rig_empty
    var.targets[0].data_path = '["Exposure_compensation"]'
    drv.expression = expr

    # Also drive the Emission node Strength when the light has a node tree,
    # because Blender may not propagate the RNA property into the node.
    if light_obj.data.use_nodes and light_obj.data.node_tree:
        emission = None
        for node in light_obj.data.node_tree.nodes:
            if node.type == "EMISSION":
                emission = node
                break
        if emission is not None:
            fc2 = emission.inputs["Strength"].driver_add("default_value")
            drv2 = fc2.driver
            drv2.type = "SCRIPTED"
            var2 = drv2.variables.new()
            var2.name = "exp_comp"
            var2.type = "SINGLE_PROP"
            var2.targets[0].id_type = "OBJECT"
            var2.targets[0].id = rig_empty
            var2.targets[0].data_path = '["Exposure_compensation"]'
            drv2.expression = expr


def _add_z_translate_driver(light_obj, rig_empty, direction):
    """
    Drive ``light_obj.delta_location`` along the light's radial direction
    (from the aim target toward the light) so the offset moves the light
    closer to or further from the centre, not just straight up.

    *direction* is a unit vector ``(dx, dy, dz)`` pointing from the aim
    target to the light.  Each axis is driven independently::

        delta_location[i] = ZTranslate_lights * dir[i]  if enabled else 0

    Args:
        light_obj: The light object.
        rig_empty: The rig controller empty with custom properties.
        direction: Normalised ``(dx, dy, dz)`` radial direction.
    """
    for axis_idx in range(3):
        d = direction[axis_idx]
        if abs(d) < 1e-9:
            continue
        fcurve = light_obj.driver_add("delta_location", axis_idx)
        drv = fcurve.driver
        drv.type = "SCRIPTED"

        var_enable = drv.variables.new()
        var_enable.name = "enabled"
        var_enable.type = "SINGLE_PROP"
        var_enable.targets[0].id_type = "OBJECT"
        var_enable.targets[0].id = rig_empty
        var_enable.targets[0].data_path = '["Enable_z_translate"]'

        var_offset = drv.variables.new()
        var_offset.name = "z_val"
        var_offset.type = "SINGLE_PROP"
        var_offset.targets[0].id_type = "OBJECT"
        var_offset.targets[0].id = rig_empty
        var_offset.targets[0].data_path = '["ZTranslate_lights"]'

        drv.expression = "(z_val * {}) if enabled else 0".format(d)


# ---------------------------------------------------------------------------
# World HDRI setup
# ---------------------------------------------------------------------------

def _setup_world_hdri(hdri_path, env_name):
    """
    Create a Blender World with an Environment Texture node pointing at
    the HDRI, plus a Mapping node whose Z rotation is driven by the
    ``HDRI_rotation`` custom property on the rig empty so the user can
    align the HDRI with the light rig interactively.

    Returns:
        Tuple of ``(world, mapping_node)`` so the caller can wire a driver
        on the Mapping node's Z rotation.
    """
    world = bpy.data.worlds.new("World_" + env_name)
    bpy.context.scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()

    output_node = tree.nodes.new("ShaderNodeOutputWorld")
    output_node.location = (600, 300)

    bg_node = tree.nodes.new("ShaderNodeBackground")
    bg_node.location = (300, 300)

    env_tex = tree.nodes.new("ShaderNodeTexEnvironment")
    env_tex.location = (-200, 300)
    env_tex.image = bpy.data.images.load(hdri_path, check_existing=True)

    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.location = (-500, 300)

    texcoord = tree.nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-700, 300)

    tree.links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], env_tex.inputs["Vector"])
    tree.links.new(env_tex.outputs["Color"], bg_node.inputs["Color"])
    tree.links.new(bg_node.outputs["Background"], output_node.inputs["Surface"])

    return world, mapping


# ---------------------------------------------------------------------------
# Light texture setup (Cycles shader nodes on AREA lights)
# ---------------------------------------------------------------------------

def _setup_light_texture(light_data, texture_path):
    """Wire an Image Texture into *light_data*'s node tree.

    Blender AREA lights support a full shader node tree when ``use_nodes``
    is enabled.  The default tree contains an *Emission* node connected to
    *Light Output*.  We insert an Image Texture feeding into the Emission
    colour so the light projects the extracted crop texture.

    The Image Texture's Vector input is left **unconnected** so that Cycles
    uses its built-in light-surface UV parameterisation (0-1 across the
    rectangle).  Connecting any explicit coordinate chain overrides that
    and usually breaks the mapping.

    **Important**: light textures are only visible in Cycles Rendered
    viewport mode (Z > Rendered) or an actual F12 render.  They do NOT
    appear in Solid, Wireframe, or Material Preview (EEVEE) modes.
    """
    light_data.use_nodes = True
    tree = light_data.node_tree

    emission = tree.nodes.get("Emission")
    if emission is None:
        for node in tree.nodes:
            if node.type == "EMISSION":
                emission = node
                break
    if emission is None:
        _log("  Warning: no Emission node found in light node tree")
        return

    # Load and validate image.
    img = bpy.data.images.load(texture_path, check_existing=True)
    if img.size[0] == 0 or img.size[1] == 0:
        _log("  Warning: image loaded but has 0x0 dimensions -- "
             "file may be corrupt: {}".format(texture_path))
        return
    # Color space name varies by Blender colour management config (sRGB
    # default uses "Linear", ACES/AgX uses "Linear Rec.709", etc.).
    for candidate in ("Linear", "Linear Rec.709", "scene_linear", "Non-Color"):
        try:
            img.colorspace_settings.name = candidate
            break
        except TypeError:
            continue
    _log("  Image loaded: {}x{} colorspace={}".format(
        img.size[0], img.size[1], img.colorspace_settings.name))

    # Image Texture node -- NO Vector input connected.  Cycles maps
    # the texture across the area light surface automatically.
    tex_node = tree.nodes.new("ShaderNodeTexImage")
    tex_node.location = (emission.location.x - 300, emission.location.y)
    tex_node.image = img

    tree.links.new(tex_node.outputs["Color"], emission.inputs["Color"])

    _log("  Texture attached: {}".format(os.path.basename(texture_path)))


# ---------------------------------------------------------------------------
# Internal: move an object into a specific collection (and out of others)
# ---------------------------------------------------------------------------

def _move_to_collection(obj, target_collection):
    """Unlink *obj* from every collection it belongs to, then link it into
    *target_collection*."""
    for col in list(obj.users_collection):
        col.objects.unlink(obj)
    target_collection.objects.link(obj)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_light_rig(hdri_path):
    """
    Build a Blender lighting rig from a Nuke HDRI Light Extract EXR.

    Reads embedded metadata from the EXR and creates:

    * World Environment Texture (dome / HDRI)
    * AREA lights for extracted rectangular light sources
    * SUN lights for distant / sun sources
    * Track To constraints aiming lights at the rig centre
    * Drivers for Exposure_compensation, Enable_z_translate, ZTranslate_lights

    Args:
        hdri_path: Absolute path to the HDRI EXR file with Nuke metadata.

    Returns:
        The ``bpy.types.Collection`` containing the rig.

    Usage::

        import Blender_HDRILightExtract_importer
        Blender_HDRILightExtract_importer.build_light_rig(
            r"C:\\path\\to\\hdri.exr"
        )
    """
    _LOG_LINES.clear()

    if not os.path.isfile(hdri_path):
        raise FileNotFoundError("HDRI file not found: {}".format(hdri_path))

    # ------------------------------------------------------------------
    # 1. Read & normalise EXR metadata
    # ------------------------------------------------------------------
    all_metadata = read_exr_metadata(hdri_path)
    _log("EXR metadata: {} attributes read from {}".format(
        len(all_metadata), os.path.basename(hdri_path)))

    # Gaffer prefixes keys with "nuke/" -- raw EXR files usually don't.
    # Build a normalised dict that works either way.
    normalised = {}
    for key, val in all_metadata.items():
        norm = key[5:] if key.startswith("nuke/") else key
        normalised[norm] = val

    # Dump all HDRI_CROP keys for diagnostics.
    crop_keys = sorted(k for k in normalised if "HDRI_CROP" in k)
    _log("HDRI_CROP keys found ({}):".format(len(crop_keys)))
    for ck in crop_keys:
        _log("  {} = {}".format(ck, repr(normalised[ck])))

    env_light_name = ""
    for key, val in normalised.items():
        if key == "HDRI_CROP_Name" and isinstance(val, str):
            env_light_name = val
            break

    lights_list = {}  # { "LGT1": { "HDRI_CROP_LGT1_Name": "...", ... }, ... }
    for key, val in normalised.items():
        if "HDRI_CROP_LGT" not in key:
            continue
        parts = key.split("_")
        light_id = None
        for i, part in enumerate(parts):
            if "LGT" in part and i > 0:
                light_id = part
                break
        if light_id is None:
            continue
        if light_id not in lights_list:
            lights_list[light_id] = {}
        lights_list[light_id][key] = str(val) if not isinstance(val, str) else val

    _log("env_light_name = {}".format(repr(env_light_name)))
    _log("lights_list IDs = {}".format(list(lights_list.keys())))

    if not lights_list or not env_light_name:
        raise RuntimeError(
            "No HDRI Light Extract metadata found in {}".format(hdri_path)
        )

    env_light_name = env_light_name.replace("-", "_")
    date_stamp = time.strftime("%Y%m%d%H%M%S")
    hdri_base_dir = os.path.dirname(hdri_path)

    # ------------------------------------------------------------------
    # 2. Collection & rig controller
    # ------------------------------------------------------------------
    rig_col_name = "HDRI_RIG__{}__{}".format(env_light_name, date_stamp)
    rig_col = bpy.data.collections.new(rig_col_name)
    bpy.context.scene.collection.children.link(rig_col)

    # Rig controller empty -- custom properties live here.
    # Using bpy.data.objects.new() instead of bpy.ops to avoid viewport
    # context dependency.
    rig_empty = bpy.data.objects.new("HDRIRig_" + env_light_name, None)
    rig_empty.empty_display_type = "PLAIN_AXES"
    rig_empty.empty_display_size = 0.5
    rig_col.objects.link(rig_empty)

    rig_empty["Exposure_compensation"] = 0.0
    ui = rig_empty.id_properties_ui("Exposure_compensation")
    ui.update(
        min=-10.0, max=10.0, soft_min=-5.0, soft_max=5.0,
        description="Global exposure offset added to every light",
    )

    rig_empty["Enable_z_translate"] = 0
    ui = rig_empty.id_properties_ui("Enable_z_translate")
    ui.update(min=0, max=1, description="Toggle Z-axis offset for all lights")

    rig_empty["ZTranslate_lights"] = 0.0
    ui = rig_empty.id_properties_ui("ZTranslate_lights")
    ui.update(
        min=-100.0, max=100.0, soft_min=-20.0, soft_max=20.0,
        description="Z offset applied to all lights when enabled",
    )

    rig_empty["HDRI_rotation"] = 180.0
    ui = rig_empty.id_properties_ui("HDRI_rotation")
    ui.update(
        min=-360.0, max=360.0, soft_min=-180.0, soft_max=180.0,
        description="Horizontal rotation of the HDRI environment (degrees)",
    )

    # Aim-target empty at the origin.
    aim_target = bpy.data.objects.new("AimTarget_" + env_light_name, None)
    aim_target.empty_display_type = "SPHERE"
    aim_target.empty_display_size = 0.2
    aim_target.parent = rig_empty
    rig_col.objects.link(aim_target)

    # ------------------------------------------------------------------
    # 3. World HDRI (environment light)
    # ------------------------------------------------------------------
    world, hdri_mapping = _setup_world_hdri(hdri_path, env_light_name)

    # Drive the Mapping node's Z rotation from the HDRI_rotation property
    # (user value is in degrees, Mapping node expects radians).
    fc = hdri_mapping.inputs["Rotation"].driver_add("default_value", 2)
    drv = fc.driver
    drv.type = "SCRIPTED"
    var = drv.variables.new()
    var.name = "deg"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = rig_empty
    var.targets[0].data_path = '["HDRI_rotation"]'
    drv.expression = "radians(deg)"

    # ------------------------------------------------------------------
    # 4. Area / Sun lights
    # ------------------------------------------------------------------
    AREA_SCALE_FACTOR = 2.0  # matches the Gaffer AERig_group 2x scale

    light_objects = []
    light_group_counter = 2

    for light_id in lights_list:
        prefix = "HDRI_CROP_{}_".format(light_id)
        ld = lights_list[light_id]

        # -- Parse per-light metadata --------------------------------
        _log("--- Parsing light '{}' (prefix='{}') ---".format(light_id, prefix))
        _log("  Available keys: {}".format(list(ld.keys())))
        try:
            light_name = ld[prefix + "Name"].replace("-", "_")
            extract_mode = ld[prefix + "ExtractModeType"]
            light_ev = float(ld[prefix + "EV"])
            # Scale and Pos3D are stored as string representations of tuples.
            light_scale = eval(ld[prefix + "Scale"])   # noqa: S307
            light_width = float(light_scale[0])
            light_height = float(light_scale[1])
            light_pos = eval(ld[prefix + "Pos3D"])     # noqa: S307
            light_texture = ld.get(prefix + "OutputPath", "")

            try:
                is_sun = float(ld[prefix + "IsSun"])
            except (KeyError, ValueError):
                is_sun = 0.0

            try:
                light_group = ld[prefix + "LightGroup"]
            except KeyError:
                light_group = ""

        except Exception as exc:
            _log("ERROR: skipping light {} -- {}\n{}".format(
                light_id, exc, traceback.format_exc()))
            continue

        base_exposure = light_ev / 4.0
        energy = 2.0 ** base_exposure

        # Resolve texture path (stored as custom property for reference).
        resolved_tex = ""
        if light_texture:
            tex_fn = os.path.basename(
                light_texture.replace("//", "/").replace("\\", "/")
            )
            resolved_tex = os.path.join(hdri_base_dir, tex_fn).replace("\\", "/")
            _log("  Texture: {} -> {}".format(light_texture, resolved_tex))

        lg_val = light_group if light_group else str(light_group_counter)
        full_name = "{}_LGT{}".format(light_name, lg_val)

        # Y-up -> Z-up, then apply the 2x area-group scale.
        bx, by, bz = _yup_to_zup(light_pos[0], light_pos[1], light_pos[2])
        bx *= AREA_SCALE_FACTOR
        by *= AREA_SCALE_FACTOR
        bz *= AREA_SCALE_FACTOR

        # -- Create light data & object ------------------------------
        if is_sun == 0.0:
            light_data = bpy.data.lights.new(name=full_name, type="AREA")
            light_data.shape = "RECTANGLE"
            scale_div = 25.0 if extract_mode == "corner_pin" else 15.0
            light_data.size = light_width / scale_div
            light_data.size_y = light_height / scale_div
        else:
            light_data = bpy.data.lights.new(name=full_name, type="SUN")

        light_data.energy = energy

        # Attach texture via shader nodes (Cycles only; EEVEE ignores these).
        if resolved_tex and os.path.isfile(resolved_tex) and is_sun == 0.0:
            _setup_light_texture(light_data, resolved_tex)
        elif resolved_tex and is_sun == 0.0:
            _log("  Texture file not found on disk: {}".format(resolved_tex))

        light_obj = bpy.data.objects.new(full_name, light_data)
        light_obj.location = (bx, by, bz)
        rig_col.objects.link(light_obj)

        # Parent to rig empty (preserve world transform).
        light_obj.parent = rig_empty
        light_obj.matrix_parent_inverse = rig_empty.matrix_world.inverted()

        # Make the light surface visible to camera rays so the textured
        # rectangle shows up in Cycles renders (not just its light effect).
        light_obj.visible_camera = True
        light_obj.show_name = True

        # Cycles Light Group -- create the group on the view layer if it
        # doesn't exist yet, then assign this light to it.
        vl = bpy.context.view_layer
        lg_name = "lightGroup{}".format(lg_val)
        existing = {lg.name for lg in vl.lightgroups}
        if lg_name not in existing:
            vl.lightgroups.add(name=lg_name)
        light_obj.lightgroup = lg_name

        # Pipeline metadata as custom properties.
        light_obj["lightgroup"] = lg_val
        light_obj["base_exposure"] = base_exposure
        if resolved_tex:
            light_obj["texture_path"] = resolved_tex

        # Track To constraint -> aim at centre of rig.
        track = light_obj.constraints.new("TRACK_TO")
        track.target = aim_target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"

        # Compute radial direction (from aim target to light) for Z-translate.
        length = math.sqrt(bx * bx + by * by + bz * bz)
        if length > 1e-9:
            radial_dir = (bx / length, by / length, bz / length)
        else:
            radial_dir = (0.0, 0.0, 1.0)

        # Drivers.
        _add_energy_driver(light_obj, rig_empty, base_exposure)
        _add_z_translate_driver(light_obj, rig_empty, radial_dir)

        light_objects.append(light_obj)
        light_group_counter += 1

    # ------------------------------------------------------------------
    # 5. Finish
    # ------------------------------------------------------------------
    try:
        bpy.ops.object.select_all(action="DESELECT")
        rig_empty.select_set(True)
        bpy.context.view_layer.objects.active = rig_empty
    except RuntimeError:
        pass

    summary = "HDRI Light Rig created: {} with {} lights (Blender native)".format(
        rig_col_name, len(light_objects),
    )
    _log(summary)
    _log("NOTE: Light textures are only visible in Cycles Rendered viewport "
         "mode (Viewport Shading > Rendered with Render Engine = Cycles) "
         "or in an actual F12 render.  They will NOT appear in Solid, "
         "Wireframe, or Material Preview modes.")

    # Persist the full build log on the collection for post-mortem inspection.
    rig_col["_build_log"] = "\n".join(_LOG_LINES)

    # Show a popup so the result is impossible to miss, even without the
    # system console open.
    def _draw_popup(self, context):
        self.layout.label(text=summary)
        if not light_objects:
            self.layout.label(
                text="No lights created -- check _build_log on the collection",
                icon="ERROR",
            )
        else:
            self.layout.label(
                text="Light textures visible in Cycles Rendered mode or F12 only",
                icon="INFO",
            )

    try:
        bpy.context.window_manager.popup_menu(
            _draw_popup, title="HDRI Importer", icon="LIGHT"
        )
    except Exception:
        pass

    return rig_col
