# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD


def build_system_prompt():
    return """\
You are a FreeCAD Python code assistant. You generate executable Python code \
for FreeCAD based on the user's natural language request.

RULES:
- Do NOT include import statements — FreeCAD, FreeCADGui, Part, PartDesign, \
Sketcher, Draft, Mesh, Arch, and doc (active document) are pre-loaded.
- Use the variable `doc` for the active document.
- All dimensions are in millimeters unless the user specifies otherwise.

EXECUTION MODES:
- Simple requests: respond with explanation and a single ```python code block.
- Complex multi-step requests: output a plan in this format, then STOP (no code):

<<<PLAN>>>
STEP 1: Description of what this step does
STEP 2: Description of what this step does
STEP 3: Description of what this step does
<<<END_PLAN>>>

When implementing a plan step:
- Output exactly ONE ```python code block
- Reference objects from previous steps by their document names
- Each step should be self-contained and executable independently

When fixing code after an error:
- Read the error message carefully
- Output a complete corrected ```python code block
- Do not repeat the same mistake

COMMON PATTERNS:

Part primitives:
  box = doc.addObject("Part::Box", "Box")
  box.Length, box.Width, box.Height = 10, 20, 30

  cyl = doc.addObject("Part::Cylinder", "Cylinder")
  cyl.Radius, cyl.Height = 5, 20

  sphere = doc.addObject("Part::Sphere", "Sphere")
  sphere.Radius = 10

Boolean operations:
  cut = doc.addObject("Part::Cut", "Cut")
  cut.Base = obj1
  cut.Tool = obj2

  fuse = doc.addObject("Part::Fuse", "Fuse")
  fuse.Base = obj1
  fuse.Tool = obj2

  common = doc.addObject("Part::Common", "Common")
  common.Base = obj1
  common.Tool = obj2

Fillet / Chamfer (Part):
  fillet = doc.addObject("Part::Fillet", "Fillet")
  fillet.Base = obj
  fillet.Shape = obj.Shape.makeFillet(2, obj.Shape.Edges)

Placement:
  obj.Placement = FreeCAD.Placement(
      FreeCAD.Vector(x, y, z),
      FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle_deg)
  )

PartDesign workflow:
  body = doc.addObject("PartDesign::Body", "Body")
  sketch = body.newObject("Sketcher::SketchObject", "Sketch")
  sketch.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
  sketch.MapMode = "FlatFace"
  # Add geometry to sketch...
  sketch.addGeometry(Part.LineSegment(
      FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(10, 0, 0)))
  # Pad
  pad = body.newObject("PartDesign::Pad", "Pad")
  pad.Profile = sketch
  pad.Length = 10

Draft objects:
  import Draft
  wire = Draft.make_wire([FreeCAD.Vector(0,0,0), FreeCAD.Vector(10,10,0)])
  circle = Draft.make_circle(5)

Arch/BIM objects:
  wall = Arch.makeWall(length=1000, width=200, height=3000)
  structure = Arch.makeStructure(length=500, width=500, height=3000)
  window = Arch.makeWindowPreset("Open 1-pane", width=1200, height=1500,
      h1=100, h2=100, h3=100, w1=200, w2=100, o1=0, o2=100,
      placement=FreeCAD.Placement(FreeCAD.Vector(0, 0, 800),
      FreeCAD.Rotation()))

Working with selection:
  sel = FreeCADGui.Selection.getSelection()
  sel_ex = FreeCADGui.Selection.getSelectionEx()  # with sub-elements
"""


_PROPERTY_MAP = {
    "Part::Box": ["Length", "Width", "Height"],
    "Part::Cylinder": ["Radius", "Height"],
    "Part::Sphere": ["Radius"],
    "Part::Cone": ["Radius1", "Radius2", "Height"],
    "Part::Torus": ["Radius1", "Radius2"],
    "PartDesign::Pad": ["Length"],
    "PartDesign::Pocket": ["Length"],
    "PartDesign::Fillet": ["Radius"],
    "PartDesign::Chamfer": ["Size"],
    "Arch::Wall": ["Length", "Width", "Height"],
}

_OBJECT_LIMIT = 30


def _get_object_summary(obj):
    """Return a one-line summary with key properties and placement."""
    parts = []

    # Dimension / shape properties
    props = _PROPERTY_MAP.get(obj.TypeId, [])
    for prop in props:
        val = getattr(obj, prop, None)
        if val is not None:
            # Round floats for readability
            if isinstance(val, float):
                val = round(val, 2)
            parts.append(f"{prop}={val}")

    # Placement (skip if at origin)
    try:
        base = obj.Placement.Base
        if base.x != 0 or base.y != 0 or base.z != 0:
            parts.append(
                f"Pos=({round(base.x, 2)}, {round(base.y, 2)}, {round(base.z, 2)})"
            )
    except AttributeError:
        pass

    suffix = f" [{', '.join(parts)}]" if parts else ""
    return f"{obj.Label} ({obj.TypeId}){suffix}"


def _get_parent_label(obj):
    """Return the label of the object's parent group/body, or None."""
    for parent in obj.InListRecursive:
        if parent.TypeId in (
            "PartDesign::Body",
            "App::Part",
            "App::DocumentObjectGroup",
        ):
            return parent.Label
    return None


def build_document_context():
    doc = FreeCAD.ActiveDocument
    if not doc:
        return "No active document. A new document will be created if needed."

    lines = [f"Active document: {doc.Name}"]

    objects = doc.Objects
    if not objects:
        lines.append("Document is empty.")
        return "\n".join(lines)

    lines.append(f"Objects ({len(objects)}):")
    for obj in objects[:_OBJECT_LIMIT]:
        summary = _get_object_summary(obj)
        parent = _get_parent_label(obj)
        indent = "    " if parent else "  "
        prefix = f"[in {parent}] " if parent else ""
        lines.append(f"{indent}- {prefix}{summary}")

    if len(objects) > _OBJECT_LIMIT:
        lines.append(
            f"  ... and {len(objects) - _OBJECT_LIMIT} more objects (not shown)"
        )

    # Sub-element selection (faces, edges, etc.)
    try:
        import FreeCADGui

        sel_ex = FreeCADGui.Selection.getSelectionEx()
        if sel_ex:
            sel_parts = []
            for s in sel_ex[:10]:
                if s.SubElementNames:
                    subs = list(s.SubElementNames[:10])
                    if len(s.SubElementNames) > 10:
                        subs.append("...")
                    sel_parts.append(f"{s.Object.Label} [{', '.join(subs)}]")
                else:
                    sel_parts.append(s.Object.Label)
            lines.append(f"Selected: {'; '.join(sel_parts)}")
    except Exception:
        pass

    return "\n".join(lines)


def build_rag_context(query):
    """Retrieve relevant API chunks and format as a system prompt section."""
    try:
        from assistant.rag.retriever import get_retriever

        retriever = get_retriever()
        retriever.ensure_indexed()
        chunks = retriever.retrieve(query, top_k=5)
    except Exception:
        return ""

    if not chunks:
        return ""

    lines = ["RELEVANT API REFERENCE:"]
    for chunk in chunks:
        lines.append(f"\n--- {chunk['id']} ---")
        lines.append(chunk["text"])

    return "\n".join(lines)


def build_step_prompt(step_number, description, total_steps):
    """Build a system prompt section for implementing a specific plan step."""
    return (
        f"You are implementing step {step_number} of {total_steps} in a plan.\n"
        f"Step description: {description}\n\n"
        "Output exactly ONE ```python code block that implements this step.\n"
        "Reference objects from previous steps by their document names.\n"
        "The code must be self-contained and executable."
    )


def build_retry_prompt(code, error, step_info=""):
    """Build a system prompt for retrying failed code."""
    parts = [
        build_system_prompt(),
        build_document_context(),
        "\nCODE THAT FAILED:\n```python\n" + code + "\n```",
        "\nERROR:\n" + error,
        "\nPlease analyze the error and provide a corrected ```python code block.",
        "Fix the root cause, do not just suppress the error.",
    ]
    if step_info:
        parts.insert(2, f"\nContext: {step_info}")
    return "\n".join(parts)
