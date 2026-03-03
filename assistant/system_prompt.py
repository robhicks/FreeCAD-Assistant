# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD


def build_system_prompt():
    return """\
You are a FreeCAD Python code assistant. You generate executable Python code \
for FreeCAD based on the user's natural language request.

RULES:
- Output ONLY executable Python code inside a single ```python fenced block.
- You may include a brief explanation outside the code block.
- Do NOT include import statements — FreeCAD, FreeCADGui, Part, PartDesign, \
Sketcher, Draft, Mesh, and doc (active document) are pre-loaded.
- Use the variable `doc` for the active document.
- All dimensions are in millimeters unless the user specifies otherwise.

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

Working with selection:
  sel = FreeCADGui.Selection.getSelection()
  sel_ex = FreeCADGui.Selection.getSelectionEx()  # with sub-elements
"""


def build_document_context():
    doc = FreeCAD.ActiveDocument
    if not doc:
        return "No active document. A new document will be created if needed."

    lines = [f"Active document: {doc.Name}"]

    objects = doc.Objects
    if objects:
        lines.append(f"Objects ({len(objects)}):")
        for obj in objects[:20]:
            type_name = obj.TypeId.split("::")[-1] if "::" in obj.TypeId else obj.TypeId
            lines.append(f"  - {obj.Label} ({type_name})")
        if len(objects) > 20:
            lines.append(f"  ... and {len(objects) - 20} more")
    else:
        lines.append("Document is empty.")

    try:
        sel = FreeCADGui.Selection.getSelection()
        if sel:
            sel_labels = [obj.Label for obj in sel[:5]]
            lines.append(f"Selected: {', '.join(sel_labels)}")
    except Exception:
        pass

    return "\n".join(lines)
