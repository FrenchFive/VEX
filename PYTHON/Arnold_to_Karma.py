"""
Arnold -> Karma MaterialX Material Builder converter (non-destructive).

Usage
-----
1. Select one or more `arnold_materialbuilder` nodes.
2. Run this script from the Python Source Editor.
3. Read the report at the end of the run.

Workflow
--------
For each material:
  1. Create the Karma builder (via voptoolutils or template clone)
  2. Find/create the three terminal nodes: standard_surface, displacement, properties
  3. Wire them into the suboutput IN THIS ORDER: surface, displacement, properties
  4. Rename slot 2's parmname to 'displacement' and label to 'Displacement'
  5. Build the Arnold graph inside, replacing the placeholder surface with
     the converted Arnold standard_surface chain
"""

import hou
import inspect
import traceback

try:
    import voptoolutils
except ImportError:
    voptoolutils = None


DEBUG   = True
VERBOSE = True

TEMPLATE_KARMA_PATH = None
TEMPLATE_NAME_HINTS = ("karma_template", "karmamaterial_template", "mtlx_template")


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
        "input":    "inx",
        "input_Y":  "iny",
        "input_Z":  "inz",
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

    "arnold::clamp": {"input": "in", "low": "low", "high": "high",
                      "min": "low", "max": "high"},
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

SURFACE_NAME_MARKERS      = ("surface", "shader", "surf")
DISPLACEMENT_NAME_MARKERS = ("displacement", "displace", "disp")


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

class MaterialReport(object):
    def __init__(self, name):
        self.name = name
        self.crashed = False
        self.crash_reason = None
        self.builder_method = None
        self.terminal_info = None
        self.properties_connected = False
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
        if self.builder_method:
            print("  Builder:  {}".format(self.builder_method))
        if self.terminal_info:
            print("  Terminal: {}".format(self.terminal_info))
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
        print("  Outputs:     surface={}   displacement={}   properties={}".format(
            self.surface_connected, self.displacement_connected,
            self.properties_connected))

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

    methods = set(r.builder_method for r in reports if r.builder_method)
    if methods:
        print("  Builder method(s): {}".format(", ".join(sorted(methods))))

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

    broken_surf = [r.name for r in reports
                   if not r.crashed and not r.surface_connected]
    if broken_surf:
        print("")
        print("  Materials with NO surface output connected:")
        for name in broken_surf:
            print("    - {}".format(name))

    not_disp = [r.name for r in reports
                if not r.crashed and not r.displacement_connected]
    if not_disp:
        print("")
        print("  Materials with NO displacement output connected:")
        for name in not_disp:
            print("    - {}".format(name))

    no_props = [r.name for r in reports
                if not r.crashed and not r.properties_connected]
    if no_props:
        print("")
        print("  Materials with NO properties output connected:")
        for name in no_props:
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


def _classify_terminal_input(input_name):
    nl = input_name.lower()
    if any(m in nl for m in DISPLACEMENT_NAME_MARKERS):
        return "displacement"
    if any(m in nl for m in SURFACE_NAME_MARKERS):
        return "surface"
    return None


# ----------------------------------------------------------------------------
# Karma Material Builder creation
# ----------------------------------------------------------------------------

def _find_template_node(wrapper_parent):
    if TEMPLATE_KARMA_PATH:
        node = hou.node(TEMPLATE_KARMA_PATH)
        if node is not None:
            return node

    search = wrapper_parent
    while search is not None:
        for child in search.children():
            if child.name() in TEMPLATE_NAME_HINTS:
                return child
            for hint in TEMPLATE_NAME_HINTS:
                if hint in child.name():
                    return child
        search = search.parent()
    return None


def _copy_template(template, destination, name):
    copied = hou.copyNodesTo([template], destination)
    if not copied:
        raise RuntimeError("hou.copyNodesTo returned nothing")
    clone = copied[0]
    try:
        clone.setName(name, unique_name=True)
    except Exception:
        pass
    return clone


def _build_karma_material_builder_from_template(wrapper, template, name):
    clone = _copy_template(template, wrapper, name)
    return clone, "template_clone({})".format(template.path())


def _inspect_voptoolutils_signature():
    if voptoolutils is None or not hasattr(voptoolutils, "_setupMtlXBuilderSubnet"):
        return None
    try:
        sig = inspect.signature(voptoolutils._setupMtlXBuilderSubnet)
        params = list(sig.parameters.keys())
        print("voptoolutils._setupMtlXBuilderSubnet signature: ({})".format(
            ", ".join(params)))
        return params
    except Exception as err:
        print("[WARN] could not inspect voptoolutils signature: {}".format(err))
        return None


def _build_karma_material_builder_via_voptoolutils(wrapper, name):
    if voptoolutils is None:
        return None, None

    mask = getattr(voptoolutils, "KARMAMTLX_TAB_MASK", None)
    if mask is None:
        return None, None

    if hasattr(voptoolutils, "_setupMtlXBuilderSubnet"):
        params = _inspect_voptoolutils_signature() or []
        subnet = wrapper.createNode("subnet", name)

        candidate_values = {
            "subnet_node":      subnet,
            "destination_node": wrapper,
            "name":             name,
            "subnet_name":      name,
            "ref_node_name":    "karmamaterial",
            "mask":             mask,
            "tab_mask":         mask,
            "folder_label":     "Karma Material Builder",
            "render_context":   "kma",
            "node_graph":       "kma",
            "node_graph_prefix": "kma",
            "prefix":           "kma",
        }
        kwargs = {p: candidate_values[p] for p in params if p in candidate_values}

        try:
            voptoolutils._setupMtlXBuilderSubnet(**kwargs)
            return subnet, "voptoolutils._setupMtlXBuilderSubnet(kwargs={})".format(
                sorted(kwargs.keys()))
        except Exception as err:
            print("[WARN] _setupMtlXBuilderSubnet with kwargs failed: {}".format(err))

        for args in (
            (subnet, name, "karmamaterial", mask, "Karma Material Builder", "kma"),
            (wrapper, subnet, name, "karmamaterial", mask, "Karma Material Builder", "kma"),
            (subnet, name, mask, "Karma Material Builder", "kma"),
        ):
            try:
                voptoolutils._setupMtlXBuilderSubnet(*args)
                return subnet, "voptoolutils._setupMtlXBuilderSubnet(*args, n={})".format(
                    len(args))
            except Exception as err:
                print("[WARN] _setupMtlXBuilderSubnet positional({}) failed: {}".format(
                    len(args), err))

        try:
            subnet.destroy()
        except Exception:
            pass

    if hasattr(voptoolutils, "createMaskedMtlXSubnet"):
        kwargs_tab = {"destination_node": wrapper, "autoplace": False}
        try:
            result = voptoolutils.createMaskedMtlXSubnet(
                kwargs_tab, "karmamaterial", mask,
                "Karma Material Builder", "kma",
            )
            if result is not None:
                try:
                    result.setName(name, unique_name=True)
                except Exception:
                    pass
                return result, "voptoolutils.createMaskedMtlXSubnet"
        except Exception as err:
            print("[WARN] createMaskedMtlXSubnet failed: {}".format(err))

    return None, None


def _build_karma_material_builder(wrapper, name, template):
    if template is not None:
        try:
            return _build_karma_material_builder_from_template(wrapper, template, name)
        except Exception as err:
            print("[WARN] Template clone failed: {}".format(err))
            traceback.print_exc()

    vop_result, vop_method = _build_karma_material_builder_via_voptoolutils(
        wrapper, name)
    if vop_result is not None:
        return vop_result, vop_method

    print("[WARN] Falling back to bare subnet for '{}'".format(name))
    subnet = wrapper.createNode("subnet", name)
    for child in list(subnet.children()):
        try:
            child.destroy()
        except Exception:
            pass
    return subnet, "bare_subnet"


def _dump_suboutput(terminal, label=""):
    if terminal is None or not DEBUG:
        return
    try:
        print("  [suboutput dump {}]".format(label))
        numparms = terminal.parm("numparms")
        count = numparms.eval() if numparms is not None else 0
        print("    numparms = {}".format(count))
        for i in range(1, max(count + 1, 5)):
            np = terminal.parm("parmname{}".format(i))
            lp = terminal.parm("parmlabel{}".format(i))
            tp = terminal.parm("parmtype{}".format(i))
            if np is None and lp is None and tp is None:
                try:
                    inp = terminal.input(i - 1)
                except Exception:
                    inp = None
                if inp is not None:
                    print("    slot {} (idx {}): (no parms) <- {}".format(
                        i, i - 1, inp.name()))
                continue
            name = np.eval() if np is not None else "?"
            lbl = lp.eval() if lp is not None else "?"
            tpv = tp.eval() if tp is not None else "?"
            try:
                input_node = terminal.input(i - 1)
                src = input_node.name() if input_node else None
            except Exception:
                src = None
            print("    slot {} (idx {}): name='{}' label='{}' type='{}'  <-  {}".format(
                i, i - 1, name, lbl, tpv, src))
    except Exception as err:
        print("  [suboutput dump failed: {}]".format(err))


def _find_subnet_output_terminal(karma):
    for child in karma.children():
        if child.type().name() == "suboutput":
            return child
    for child in karma.children():
        if child.type().name() == "collect":
            return child
    return None


def _find_builder_internals(karma):
    placeholder_surface = None
    placeholder_disp = None
    props_node = None

    for child in karma.children():
        tname = child.type().name().lower()
        if tname == "mtlxstandard_surface" and placeholder_surface is None:
            placeholder_surface = child
        elif tname == "mtlxdisplacement" and placeholder_disp is None:
            placeholder_disp = child
        elif props_node is None and ("materialproperties" in tname
                                     or "material_properties" in tname
                                     or tname.startswith("kma_materialproperties")
                                     or tname.endswith("materialproperties")):
            props_node = child

    terminal = _find_subnet_output_terminal(karma)

    return {
        "placeholder_surface": placeholder_surface,
        "placeholder_disp":    placeholder_disp,
        "props_node":          props_node,
        "terminal":            terminal,
    }


def _build_wrapper(parent, anchor_node):
    wrapper = parent.createNode("subnet", "mtlx_materials")
    for child in list(wrapper.children()):
        try:
            child.destroy()
        except Exception:
            pass
    wrapper.setPosition(anchor_node.position() + hou.Vector2(4.0, 0.0))
    return wrapper


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
# Core conversion
# ----------------------------------------------------------------------------

def convert_material(arnold_builder, wrapper, template):
    report = MaterialReport(arnold_builder.name())

    karma, method = _build_karma_material_builder(
        wrapper, arnold_builder.name(), template)
    report.builder_method = method

    arnold_terminal = _find_output_terminal(arnold_builder)

    internals = _find_builder_internals(karma)
    terminal         = internals["terminal"]
    placeholder_surf = internals["placeholder_surface"]
    placeholder_disp = internals["placeholder_disp"]
    props_node       = internals["props_node"]

    _dump_suboutput(terminal, "right after clone")

    # ========================================================================
    # STEP A: FORCEFULLY RESET THE SUBOUTPUT
    # Disconnect everything from the terminal and clear all existing parmnames.
    # We're going to wire it fresh in a known order.
    # ========================================================================
    if terminal is not None:
        # Disconnect everything
        try:
            num_inputs = len(terminal.inputs())
            for i in range(num_inputs):
                try:
                    terminal.setInput(i, None)
                except Exception:
                    pass
        except Exception:
            pass

        # Reset numparms to 0 so we can rebuild from scratch
        try:
            numparms = terminal.parm("numparms")
            if numparms is not None:
                numparms.set(0)
        except Exception:
            pass

    _dump_suboutput(terminal, "after reset")

    # ========================================================================
    # STEP B: Ensure the three terminal nodes exist.
    # If the placeholders are missing (odd template), create them.
    # ========================================================================
    if placeholder_surf is None:
        try:
            placeholder_surf = karma.createNode("mtlxstandard_surface", "mtlxstandard_surface")
        except Exception as err:
            print("[WARN] Could not create mtlxstandard_surface: {}".format(err))

    if placeholder_disp is None:
        try:
            placeholder_disp = karma.createNode("mtlxdisplacement", "mtlxdisplacement")
        except Exception as err:
            print("[WARN] Could not create mtlxdisplacement: {}".format(err))

    # props_node could legitimately be absent in some template variants;
    # that's fine, we just skip wiring that slot.

    # ========================================================================
    # STEP C: Wire them in to the suboutput IN ORDER.
    #   slot 0 (1st) = surface placeholder
    #   slot 1 (2nd) = displacement placeholder
    #   slot 2 (3rd) = properties node
    #
    # Then set numparms = 3 and populate each slot's parmname/label/type.
    # ========================================================================

    if terminal is not None:
        # Wire surface FIRST
        if placeholder_surf is not None:
            try:
                terminal.setInput(0, placeholder_surf, 0)
            except Exception as err:
                print("[WARN] wire surface to slot 0 failed: {}".format(err))

        # Wire displacement SECOND
        if placeholder_disp is not None:
            try:
                terminal.setInput(1, placeholder_disp, 0)
            except Exception as err:
                print("[WARN] wire displacement to slot 1 failed: {}".format(err))

        # Wire properties THIRD
        if props_node is not None:
            try:
                terminal.setInput(2, props_node, 0)
                report.properties_connected = True
            except Exception as err:
                print("[WARN] wire properties to slot 2 failed: {}".format(err))

        # Now set numparms and configure each slot's metadata.
        slot_count = 3 if props_node is not None else 2
        try:
            numparms = terminal.parm("numparms")
            if numparms is not None:
                numparms.set(slot_count)
        except Exception as err:
            print("[WARN] could not set numparms={}: {}".format(slot_count, err))

        # Slot 1 (surface)
        try:
            np = terminal.parm("parmname1")
            lp = terminal.parm("parmlabel1")
            tp = terminal.parm("parmtype1")
            if np is not None: np.set("surface")
            if lp is not None: lp.set("Surface")
            if tp is not None:
                try: tp.set("surface")
                except Exception: pass
        except Exception:
            pass

        # Slot 2 (displacement) -- renamed from default 'out1' to 'displacement'
        try:
            np = terminal.parm("parmname2")
            lp = terminal.parm("parmlabel2")
            tp = terminal.parm("parmtype2")
            if np is not None: np.set("displacement")
            if lp is not None: lp.set("Displacement")
            if tp is not None:
                try: tp.set("displacement")
                except Exception: pass
        except Exception:
            pass

        # Slot 3 (properties)
        if props_node is not None:
            try:
                np = terminal.parm("parmname3")
                lp = terminal.parm("parmlabel3")
                tp = terminal.parm("parmtype3")
                if np is not None: np.set("properties")
                if lp is not None: lp.set("Properties")
                if tp is not None:
                    try: tp.set("struct")
                    except Exception: pass
            except Exception:
                pass

    _dump_suboutput(terminal, "after fresh wiring + rename")

    # Record that displacement is pre-wired via placeholder.
    # Pass 3 will set this to True specifically if Arnold has displacement.
    # If Arnold doesn't, the placeholder stays and we'll mark it at the end.

    # Known slot indices -- we've enforced them.
    surf_idx  = 0
    disp_idx  = 1
    props_idx = 2 if props_node is not None else -1

    term_parts = []
    if terminal is not None:
        try:
            term_name = terminal.type().name()
        except Exception:
            term_name = "?"
        try:
            names = terminal.inputNames()
        except Exception:
            names = []
        term_parts.append("terminal={}".format(term_name))
        for classification, idx in (("surf", surf_idx),
                                    ("disp", disp_idx),
                                    ("props", props_idx)):
            if 0 <= idx < len(names):
                term_parts.append("{}[{}]={}".format(classification, idx, names[idx]))
            else:
                term_parts.append("{}=(none)".format(classification))
    else:
        term_parts.append("terminal=(not found)")
    report.terminal_info = ", ".join(term_parts)

    # ========================================================================
    # STEP D: Destroy the surface placeholder. Pass 3 will wire the converted
    # standard_surface into slot 0 in its place.
    # ========================================================================
    if placeholder_surf is not None:
        try:
            placeholder_surf.destroy()
        except Exception:
            pass

    # The displacement node stays. If Arnold has displacement, Pass 1 will
    # adopt it (reuse the same node, rename it).
    displacement_node = placeholder_disp

    _copy_node_metadata(arnold_builder, karma)

    node_map = {}

    # --- Pass 1: create MaterialX equivalents of Arnold nodes ---
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

            if a_type == "arnold::displacement" and displacement_node is not None:
                new_node = displacement_node
                try:
                    new_node.setName(a_node.name(), unique_name=True)
                except Exception:
                    pass
                report.counts["nodes_via_map"] += 1
            else:
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

    # --- Pass 2: rebuild shader graph connections ---
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

    # --- Pass 3: wire converted surface/displacement into the terminal ---
    if arnold_terminal is not None and terminal is not None:
        try:
            term_conns = arnold_terminal.inputConnections()
        except Exception:
            term_conns = []
        try:
            arnold_input_names = arnold_terminal.inputNames()
        except Exception:
            arnold_input_names = []

        if DEBUG:
            print("  [pass 3] Arnold terminal has {} connections".format(len(term_conns)))

        for conn in term_conns:
            a_src = conn.inputNode()
            if a_src not in node_map:
                continue
            try:
                input_name = arnold_input_names[conn.inputIndex()]
            except Exception:
                input_name = ""
            classification = _classify_terminal_input(input_name)
            is_disp = classification == "displacement"

            idx = disp_idx if is_disp else surf_idx

            src_node = node_map[a_src]
            try:
                out_count = len(src_node.outputNames())
            except Exception:
                out_count = 1
            out_idx = conn.outputIndex()
            if out_idx >= out_count:
                out_idx = 0
            try:
                terminal.setInput(idx, src_node, out_idx)
                if is_disp:
                    report.displacement_connected = True
                else:
                    report.surface_connected = True
                if DEBUG:
                    print("    [pass 3] WIRED {} (arnold '{}') to terminal[{}]".format(
                        src_node.name(), input_name, idx))
            except Exception as err:
                report.wire_issues.append(
                    (a_src.name(),
                     "OUTPUT({}) arnold_input={}".format(
                        "disp" if is_disp else "surf", input_name),
                     str(err))
                )

    # If no Arnold displacement, the placeholder still sits in slot 1.
    if not report.displacement_connected and displacement_node is not None \
            and terminal is not None:
        try:
            if terminal.input(disp_idx) is displacement_node:
                report.displacement_connected = True
        except Exception:
            pass

    _dump_suboutput(terminal, "final")

    return karma, report


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

    template = _find_template_node(builders[0].parent())
    if template is not None:
        print("Using template Karma Material Builder: {}".format(template.path()))
    else:
        print("No template found. Using voptoolutils.")
        _inspect_voptoolutils_signature()

    reports = []
    wrapper = None
    try:
        with hou.undos.group("Arnold -> MaterialX"):
            wrapper = _build_wrapper(builders[0].parent(), builders[0])
            for builder in builders:
                try:
                    _, report = convert_material(builder, wrapper, template)
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


# FIVE
