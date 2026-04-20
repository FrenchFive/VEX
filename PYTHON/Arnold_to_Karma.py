"""
Arnold -> Karma MaterialX Material Builder converter (non-destructive).

Usage
-----
1. Select one or more `arnold_materialbuilder` nodes (typically in /mat).
2. Run this script from the Python Source Editor or a shelf tool.
3. Read the report at the end of the run.
"""

import hou
import traceback


# ----------------------------------------------------------------------------
# Debug toggles
# ----------------------------------------------------------------------------

DEBUG   = True
VERBOSE = True


# ----------------------------------------------------------------------------
# Mapping tables
# ----------------------------------------------------------------------------

ARNOLD_BUILDER_TYPES = {"arnold_materialbuilder", "arnold::materialbuilder"}
ARNOLD_OUTPUT_TYPES = {"arnold_material", "arnold::material"}

NODE_TYPE_MAP = {
    "arnold::standard_surface": "mtlxstandard_surface",
    "arnold::standard_hair":    "mtlxstandard_surface",
    "arnold::flat":             "mtlxconstant",

    "arnold::image":            "mtlximage",
    "arnold::checkerboard":     "mtlxchecker",
    "arnold::noise":            "mtlxfractal3d",
    "arnold::cell_noise":       "mtlxcellnoise3d",
    "arnold::triplanar":        "mtlxtriplanarprojection",

    "arnold::user_data_float":  "mtlxconstant",
    "arnold::user_data_int":    "mtlxconstant",
    "arnold::user_data_rgb":    "mtlxconstant",
    "arnold::user_data_rgba":   "mtlxconstant",

    "arnold::range":            "mtlxrange",
    "arnold::mix_rgba":         "mtlxmix",
    "arnold::mix_shader":       "mtlxmix",
    "arnold::mix_float":        "mtlxmix",
    "arnold::layer_rgba":       "mtlxmix",
    "arnold::layer_float":      "mtlxmix",
    "arnold::color_correct":    "mtlxhsvadjust",
    "arnold::length":           "mtlxmagnitude",

    "arnold::bump2d":           "mtlxbump",
    "arnold::bump3d":           "mtlxbump",
    "arnold::normal_map":       "mtlxnormalmap",
    "arnold::displacement":     "mtlxdisplacement",

    "arnold::uv_transform":     "mtlxplace2d",

    "arnold::ramp_rgb":         "mtlxramplr",
    "arnold::ramp_float":       "mtlxramplr",
}

INPUT_RENAME = {
    "arnold::image":         {"uvcoords": "texcoord"},
    "arnold::bump2d":        {"bump_map": "height", "normal": "normal"},
    "arnold::bump3d":        {"bump_map": "height", "normal": "normal"},
    "arnold::normal_map":    {"input": "in"},
    "arnold::color_correct": {"input": "in"},
    "arnold::displacement":  {"displacement": "displacement"},

    "arnold::triplanar": {
        "input":   "inx",
        "input_Y": "iny",
        "input_Z": "inz",
        "position": "position",
        "normal":   "normal",
    },

    "arnold::range": {
        "input":      "in",
        "input_min":  "inlow",
        "input_max":  "inhigh",
        "output_min": "outlow",
        "output_max": "outhigh",
    },

    "arnold::mix_rgba":    {"input1": "bg", "input2": "fg", "mix": "mix"},
    "arnold::mix_shader":  {"input1": "bg", "input2": "fg", "mix": "mix"},
    "arnold::mix_float":   {"input1": "bg", "input2": "fg", "mix": "mix"},
    "arnold::layer_rgba":  {"input1": "bg", "input2": "fg"},
    "arnold::layer_float": {"input1": "bg", "input2": "fg"},

    "arnold::multiply": {"input1": "in1", "input2": "in2"},
    "arnold::add":      {"input1": "in1", "input2": "in2"},
    "arnold::subtract": {"input1": "in1", "input2": "in2"},
    "arnold::divide":   {"input1": "in1", "input2": "in2"},
    "arnold::min":      {"input1": "in1", "input2": "in2"},
    "arnold::max":      {"input1": "in1", "input2": "in2"},
    "arnold::cross":    {"input1": "in1", "input2": "in2"},
    "arnold::dot":      {"input1": "in1", "input2": "in2"},
    "arnold::power":    {"base": "in1", "exponent": "in2"},

    "arnold::abs":       {"input": "in"},
    "arnold::sign":      {"input": "in"},
    "arnold::sqrt":      {"input": "in"},
    "arnold::exp":       {"input": "in"},
    "arnold::log":       {"input": "in"},
    "arnold::normalize": {"input": "in"},
    "arnold::length":    {"input": "in"},
    "arnold::luminance": {"input": "in"},

    "arnold::clamp": {"input": "in", "min": "low", "max": "high"},
}

PARM_RENAME = {
    "arnold::image": {
        "filename":               "file",
        "color_space":            "filecolorspace",
        "uvset":                  "uvindex",
        "swrap":                  "uaddressmode",
        "twrap":                  "vaddressmode",
        "filter":                 "filtertype",
        "missing_texture_color":  "default",
    },
    "arnold::range": {
        "smoothstep": "doclamp",
    },
    "arnold::bump2d": {
        "bump_height": "scale",
    },
    "arnold::normal_map": {
        "strength": "scale",
    },
    "arnold::triplanar": {
        # scale / offset / blend tend to match 1:1 on mtlxtriplanarprojection
        # when they exist; cell_* and rotate are arnold-specific and are
        # expected to be dropped.
    },
}

SIGNATURE_SIZE = {
    "float":   1,
    "integer": 1,
    "boolean": 1,
    "string":  1,
    "vector2": 2,
    "color3":  3, "vector3": 3,
    "color4":  4, "vector4": 4,
}


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

class MaterialReport(object):
    def __init__(self, name):
        self.name = name
        self.crashed = False
        self.crash_reason = None
        self.counts = {
            "nodes_seen":          0,
            "nodes_created":       0,
            "nodes_via_map":       0,
            "nodes_via_guess":     0,
            "nodes_via_special":   0,
            "parms_seen":          0,
            "parms_copied":        0,
            "parms_no_target":     0,
            "parms_failed":        0,
            "conns_attempted":     0,
            "conns_made":          0,
            "conns_input_missing": 0,
            "conns_wire_failed":   0,
        }
        self.unmapped = []
        self.create_failed = []
        self.parm_issues = []
        self.rename_target_missing = []
        self.input_missing = []
        self.wire_issues = []
        self.surface_connected = False
        self.displacement_connected = False

    def _pct(self, a, b):
        return "n/a" if b <= 0 else "{:.0f}%".format(100.0 * a / b)

    def print_summary(self):
        c = self.counts
        print("")
        print("=" * 64)
        print("  Material: {}".format(self.name))
        if self.crashed:
            print("  *** CRASHED: {} ***".format(self.crash_reason))
        print("-" * 64)
        print("  Nodes:       {:>4} / {:<4} created  ({})".format(
            c["nodes_created"], c["nodes_seen"],
            self._pct(c["nodes_created"], c["nodes_seen"])))
        print("               via map: {}   via guess: {}   via special: {}".format(
            c["nodes_via_map"], c["nodes_via_guess"], c["nodes_via_special"]))
        print("               unmapped: {}   create-failed: {}".format(
            len(self.unmapped), len(self.create_failed)))
        print("  Parms:       {:>4} / {:<4} copied   ({})".format(
            c["parms_copied"], c["parms_seen"],
            self._pct(c["parms_copied"], c["parms_seen"])))
        print("               no-target: {}   failed: {}".format(
            c["parms_no_target"], c["parms_failed"]))
        print("  Connections: {:>4} / {:<4} wired    ({})".format(
            c["conns_made"], c["conns_attempted"],
            self._pct(c["conns_made"], c["conns_attempted"])))
        print("               input-missing: {}   wire-failed: {}".format(
            c["conns_input_missing"], c["conns_wire_failed"]))
        print("  Outputs:     surface={}   displacement={}".format(
            self.surface_connected, self.displacement_connected))

        if self.unmapped:
            print("")
            print("  Unmapped nodes:")
            for n, t in self.unmapped:
                print("    - {} ({})".format(n, t))

        if self.create_failed:
            print("")
            print("  Create failures:")
            for n, t, err in self.create_failed:
                print("    - {} ({}): {}".format(n, t, err))

        if self.rename_target_missing:
            print("")
            print("  Rename targets missing (check PARM_RENAME):")
            for a_type, a_parm, m_parm in self.rename_target_missing:
                print("    - {}.{} -> mtlx parm '{}' does not exist".format(
                    a_type, a_parm, m_parm))

        if self.input_missing:
            print("")
            print("  Input connectors not found (check INPUT_RENAME):")
            for m_type, name, src in self.input_missing:
                print("    - {} has no input '{}' (source: {})".format(
                    m_type, name, src))

        if DEBUG and self.parm_issues:
            print("")
            print("  Parm copy failures (first 25):")
            for a_type, parm, reason in self.parm_issues[:25]:
                print("    - {}.{}: {}".format(a_type, parm, reason))
            if len(self.parm_issues) > 25:
                print("    ... and {} more".format(len(self.parm_issues) - 25))

        if self.wire_issues:
            print("")
            print("  Wire failures:")
            for src, dst, reason in self.wire_issues:
                print("    - {} -> {}: {}".format(src, dst, reason))

        print("=" * 64)


def _print_overall_summary(reports, wrapper_path):
    print("")
    print("#" * 64)
    print("#  OVERALL SUMMARY  --  {} material(s) into {}".format(
        len(reports), wrapper_path))
    print("#" * 64)

    totals = {}
    for r in reports:
        for k, v in r.counts.items():
            totals[k] = totals.get(k, 0) + v
    order = ("nodes_seen", "nodes_created",
             "parms_seen", "parms_copied", "parms_failed",
             "conns_attempted", "conns_made", "conns_wire_failed")
    for key in order:
        print("  {:<22}: {}".format(key, totals.get(key, 0)))

    unmapped_types = {}
    for r in reports:
        for _, t in r.unmapped:
            unmapped_types[t] = unmapped_types.get(t, 0) + 1
    if unmapped_types:
        print("")
        print("  Unmapped arnold:: types (add to NODE_TYPE_MAP):")
        for t, count in sorted(unmapped_types.items(), key=lambda x: -x[1]):
            print("    {:<40} x {}".format(t, count))

    missing_inputs = {}
    for r in reports:
        for m_type, name, _ in r.input_missing:
            key = (m_type, name)
            missing_inputs[key] = missing_inputs.get(key, 0) + 1
    if missing_inputs:
        print("")
        print("  Missing input connectors (add to INPUT_RENAME):")
        for (m_type, name), count in sorted(missing_inputs.items(), key=lambda x: -x[1]):
            print("    {}.{:<20} x {}".format(m_type, name, count))

    crashed = [r.name for r in reports if r.crashed]
    if crashed:
        print("")
        print("  CRASHED materials:")
        for name in crashed:
            print("    - {}".format(name))

    broken = [r.name for r in reports
              if not r.crashed and not r.surface_connected]
    if broken:
        print("")
        print("  Materials with NO surface output connected:")
        for name in broken:
            print("    - {}".format(name))

    print("#" * 64)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

_VOP_TYPES_CACHE = None


def _get_vop_types():
    global _VOP_TYPES_CACHE
    if _VOP_TYPES_CACHE is None:
        _VOP_TYPES_CACHE = set(hou.vopNodeTypeCategory().nodeTypes().keys())
    return _VOP_TYPES_CACHE


def _guess_mtlx_type(arnold_type):
    if not arnold_type.startswith("arnold::"):
        return None
    candidate = "mtlx" + arnold_type.split("::", 1)[1]
    return candidate if candidate in _get_vop_types() else None


def _resolve_mtlx_type(arnold_type):
    """Resolve an arnold:: type to an mtlx VOP type.

    Explicit NODE_TYPE_MAP wins, but only if the target actually exists as
    a VOP type in this Houdini build. Otherwise fall back to _guess_mtlx_type.
    Returns (type_name, via) where via is 'map' / 'guess' / None.
    """
    vop_types = _get_vop_types()
    mapped = NODE_TYPE_MAP.get(arnold_type)
    if mapped is not None and mapped in vop_types:
        return mapped, "map"
    guessed = _guess_mtlx_type(arnold_type)
    if guessed is not None:
        return guessed, "guess"
    return None, None


def _is_string_parm(parm):
    try:
        return parm.parmTemplate().type() == hou.parmTemplateType.String
    except Exception:
        return False


def _translate_name(arnold_type, name, prefer_parm=False):
    if prefer_parm:
        primary   = PARM_RENAME.get(arnold_type, {})
        secondary = INPUT_RENAME.get(arnold_type, {})
    else:
        primary   = INPUT_RENAME.get(arnold_type, {})
        secondary = PARM_RENAME.get(arnold_type, {})
    if name in primary:
        return primary[name], True
    if name in secondary:
        return secondary[name], True
    return name, False


def _copy_parms(src, dst, report):
    src_type = src.type().name()
    for parm in src.parms():
        report.counts["parms_seen"] += 1
        parm_name = parm.name()
        target_name, was_renamed = _translate_name(src_type, parm_name, prefer_parm=True)
        target = dst.parm(target_name)

        if target is None:
            report.counts["parms_no_target"] += 1
            if was_renamed:
                report.rename_target_missing.append((src_type, parm_name, target_name))
            continue

        try:
            if _is_string_parm(parm):
                target.set(parm.unexpandedString())
            else:
                target.set(parm.eval())
            report.counts["parms_copied"] += 1
        except Exception as err:
            report.counts["parms_failed"] += 1
            report.parm_issues.append(
                (src_type, "{} -> {}".format(parm_name, target_name), str(err))
            )


def _copy_node_metadata(src, dst):
    try:
        dst.setPosition(src.position())
    except Exception:
        pass
    try:
        dst.setColor(src.color())
    except Exception:
        pass
    try:
        comment = src.comment()
        if comment:
            dst.setComment(comment)
            try:
                dst.setGenericFlag(hou.nodeFlag.DisplayComment, True)
            except Exception:
                pass
    except Exception:
        pass
    try:
        if src.isGenericFlagSet(hou.nodeFlag.Bypass):
            dst.setGenericFlag(hou.nodeFlag.Bypass, True)
    except Exception:
        pass


def _resolve_input_index(node, input_name):
    try:
        return node.inputIndex(input_name)
    except Exception:
        try:
            names = node.inputNames()
            return names.index(input_name) if input_name in names else -1
        except Exception:
            return -1


def _find_output_terminal(arnold_builder):
    for child in arnold_builder.children():
        if child.type().name() in ARNOLD_OUTPUT_TYPES:
            return child
    return None


# ----------------------------------------------------------------------------
# Special creators
# ----------------------------------------------------------------------------

def _fit_value_to_size(value, target_size):
    if not isinstance(value, (tuple, list)):
        value = (value,)
    value = tuple(value)
    if target_size <= 0:
        return value
    if len(value) < target_size:
        pad = value[-1] if value else 0
        value = value + (pad,) * (target_size - len(value))
    elif len(value) > target_size:
        value = value[:target_size]
    return value


def _set_constant_value(mtlx_const, signature, value):
    try:
        sp = mtlx_const.parm("signature")
        if sp is not None:
            sp.set(signature)
    except Exception:
        pass

    expected = SIGNATURE_SIZE.get(signature, 0)
    try:
        candidates = [pt for pt in mtlx_const.parmTuples()
                      if pt.name().startswith("value")]
    except Exception:
        candidates = []
    candidates.sort(key=lambda pt: 0 if len(pt) == expected else 1)

    for pt in candidates:
        fitted = _fit_value_to_size(value, len(pt))
        try:
            pt.set(fitted)
            return True
        except Exception:
            continue

    try:
        p = mtlx_const.parm("value")
        if p is not None:
            scalar = value[0] if isinstance(value, (tuple, list)) else value
            p.set(scalar)
            return True
    except Exception:
        pass

    return False


def _create_user_data_constant(a_node, karma, signature):
    new_node = karma.createNode("mtlxconstant", a_node.name())
    value = None
    default_tup = a_node.parmTuple("default")
    if default_tup is not None:
        try:
            value = default_tup.eval()
        except Exception:
            value = None
    if value is None:
        default_parm = a_node.parm("default")
        if default_parm is not None:
            try:
                value = default_parm.eval()
            except Exception:
                value = None
    if value is not None:
        _set_constant_value(new_node, signature, value)
    return new_node


SPECIAL_CREATORS = {
    "arnold::user_data_float": lambda n, k: _create_user_data_constant(n, k, "float"),
    "arnold::user_data_int":   lambda n, k: _create_user_data_constant(n, k, "integer"),
    "arnold::user_data_rgb":   lambda n, k: _create_user_data_constant(n, k, "color3"),
    "arnold::user_data_rgba":  lambda n, k: _create_user_data_constant(n, k, "color4"),
}


# ----------------------------------------------------------------------------
# Shell / wrapper construction
# ----------------------------------------------------------------------------

def _build_mtlx_shell(parent, name):
    karma = parent.createNode("subnet", name)
    for child in karma.children():
        child.destroy()

    surf = karma.createNode("subnetconnector", "surface_output")
    surf.parm("connectorkind").set("output")
    surf.parm("parmname").set("surface")
    surf.parm("parmlabel").set("Surface")
    surf.parm("parmtype").set("surface")

    disp = karma.createNode("subnetconnector", "displacement_output")
    disp.parm("connectorkind").set("output")
    disp.parm("parmname").set("displacement")
    disp.parm("parmlabel").set("Displacement")
    disp.parm("parmtype").set("displacement")

    return karma, surf, disp


def _build_wrapper(parent, anchor_node):
    wrapper = parent.createNode("subnet", "mtlx_materials")
    for child in wrapper.children():
        child.destroy()
    wrapper.setPosition(anchor_node.position() + hou.Vector2(4.0, 0.0))
    return wrapper


# ----------------------------------------------------------------------------
# Core conversion
# ----------------------------------------------------------------------------

def convert_material(arnold_builder, wrapper):
    report = MaterialReport(arnold_builder.name())
    karma, surf_out, disp_out = _build_mtlx_shell(wrapper, arnold_builder.name())

    _copy_node_metadata(arnold_builder, karma)

    node_map = {}

    # --- Pass 1: create MaterialX equivalents ---
    for a_node in arnold_builder.children():
        a_type = a_node.type().name()

        if a_type in ARNOLD_OUTPUT_TYPES:
            continue

        report.counts["nodes_seen"] += 1

        new_node = None

        if a_type in SPECIAL_CREATORS:
            try:
                new_node = SPECIAL_CREATORS[a_type](a_node, karma)
                report.counts["nodes_via_special"] += 1
            except Exception as err:
                report.create_failed.append((a_node.name(), a_type, str(err)))
                continue
        else:
            mtlx_type, via = _resolve_mtlx_type(a_type)
            if mtlx_type is None:
                if a_type.startswith("arnold"):
                    report.unmapped.append((a_node.name(), a_type))
                continue
            try:
                new_node = karma.createNode(mtlx_type, a_node.name())
                if via == "map":
                    report.counts["nodes_via_map"] += 1
                else:
                    report.counts["nodes_via_guess"] += 1
            except Exception as err:
                report.create_failed.append((a_node.name(), a_type, str(err)))
                continue

        if new_node is None:
            continue

        _copy_node_metadata(a_node, new_node)
        node_map[a_node] = new_node
        report.counts["nodes_created"] += 1

        if a_type not in SPECIAL_CREATORS:
            _copy_parms(a_node, new_node, report)

    # --- Pass 2: rebuild connections ---
    for a_node, new_node in node_map.items():
        a_type = a_node.type().name()
        try:
            input_conns = a_node.inputConnections()
        except Exception:
            continue
        for conn in input_conns:
            a_src = conn.inputNode()
            if a_src not in node_map:
                continue
            report.counts["conns_attempted"] += 1

            try:
                a_input_name = a_node.inputNames()[conn.inputIndex()]
            except Exception:
                report.counts["conns_input_missing"] += 1
                continue

            mtlx_input_name, _ = _translate_name(a_type, a_input_name, prefer_parm=False)
            dst_idx = _resolve_input_index(new_node, mtlx_input_name)
            if dst_idx < 0:
                report.counts["conns_input_missing"] += 1
                report.input_missing.append(
                    (new_node.type().name(), mtlx_input_name, a_src.name())
                )
                continue

            src_node = node_map[a_src]
            try:
                out_count = len(src_node.outputNames())
            except Exception:
                out_count = 1
            out_idx = conn.outputIndex()
            if out_idx >= out_count:
                out_idx = 0

            try:
                new_node.setInput(dst_idx, src_node, out_idx)
                report.counts["conns_made"] += 1
            except Exception as err:
                report.counts["conns_wire_failed"] += 1
                report.wire_issues.append((a_src.name(), a_node.name(), str(err)))

    # --- Pass 3: output terminal ---
    terminal = _find_output_terminal(arnold_builder)
    if terminal is not None:
        try:
            term_conns = terminal.inputConnections()
        except Exception:
            term_conns = []
        for conn in term_conns:
            a_src = conn.inputNode()
            if a_src not in node_map:
                continue
            try:
                input_name = terminal.inputNames()[conn.inputIndex()].lower()
            except Exception:
                input_name = ""
            is_disp = "disp" in input_name
            target = disp_out if is_disp else surf_out
            src_node = node_map[a_src]
            try:
                out_count = len(src_node.outputNames())
            except Exception:
                out_count = 1
            out_idx = conn.outputIndex()
            if out_idx >= out_count:
                out_idx = 0
            try:
                target.setInput(0, src_node, out_idx)
                if is_disp:
                    report.displacement_connected = True
                else:
                    report.surface_connected = True
            except Exception as err:
                report.wire_issues.append(
                    (a_src.name(),
                     "OUTPUT({})".format("disp" if is_disp else "surf"),
                     str(err))
                )

    return karma, report


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def run():
    selected = hou.selectedNodes()
    builders = [n for n in selected if n.type().name() in ARNOLD_BUILDER_TYPES]

    if not builders:
        hou.ui.displayMessage(
            "Select one or more Arnold Material Builders first.",
            severity=hou.severityType.Warning,
        )
        return

    print("")
    print("Starting Arnold -> MaterialX conversion ({} builder(s))".format(len(builders)))
    print("DEBUG={}  VERBOSE={}".format(DEBUG, VERBOSE))

    reports = []
    wrapper = None
    try:
        with hou.undos.group("Arnold -> MaterialX"):
            wrapper = _build_wrapper(builders[0].parent(), builders[0])
            for builder in builders:
                try:
                    _, report = convert_material(builder, wrapper)
                    reports.append(report)
                except Exception as err:
                    crashed = MaterialReport(builder.name())
                    crashed.crashed = True
                    crashed.crash_reason = str(err)
                    reports.append(crashed)
                    print("")
                    print("[ERROR] '{}' crashed: {}".format(builder.name(), err))
                    traceback.print_exc()

                if VERBOSE:
                    reports[-1].print_summary()

            try:
                wrapper.layoutChildren()
            except Exception:
                pass
    except Exception as err:
        print("")
        print("[FATAL] Converter aborted: {}".format(err))
        traceback.print_exc()

    _print_overall_summary(
        reports,
        wrapper.path() if wrapper is not None else "<no wrapper created>"
    )


run()


# FIVE -- this revision:
#
# - arnold::triplanar is now explicitly mapped to mtlxtriplanarprojection
#   with input renames (input -> inx, input_Y -> iny, input_Z -> inz).
#   That's why range1's `in` was dangling: its upstream triplanar was
#   unmapped, so a_src wasn't in node_map and pass 2 quietly skipped the
#   wire. With triplanar present, the range connection rebuilds.
#
# - _resolve_mtlx_type() replaces the old "explicit map OR guess" branch.
#   It now also validates that the explicit map target actually exists as
#   a VOP type in this Houdini build -- if not, it falls through to the
#   guess. So if mtlxtriplanarprojection isn't the right name on your
#   hfs20.5.278 build, the guess ('mtlxtriplanar') gets a shot before we
#   give up entirely, and you'll see which path was used in the report's
#   "via map: X   via guess: Y" line.
#
# - If triplanar still doesn't land (neither name exists), the report
#   will flag it as unmapped AND the "Missing input connectors" aggregate
#   will show the dangling range input, which tells us what to do next.
#   Paste the summary and I'll patch the name.
