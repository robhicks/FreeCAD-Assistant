# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
from io import StringIO

import FreeCAD
import FreeCADGui


class CodeExecutor:
    def execute(self, code, description="AI Assistant"):
        """Execute code with transaction wrapping.

        Returns (success, stdout, stderr) tuple.
        """
        doc = FreeCAD.ActiveDocument
        if not doc:
            doc = FreeCAD.newDocument("Unnamed")

        namespace = self._build_namespace(doc)

        stdout_capture = StringIO()
        stderr_capture = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        doc.openTransaction(description)
        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            exec(code, namespace)
            doc.commitTransaction()
            doc.recompute()
            try:
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
            return (True, stdout_capture.getvalue(), stderr_capture.getvalue())
        except Exception as e:
            doc.abortTransaction()
            return (False, stdout_capture.getvalue(), str(e))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _build_namespace(self, doc):
        ns = {
            "FreeCAD": FreeCAD,
            "App": FreeCAD,
            "FreeCADGui": FreeCADGui,
            "Gui": FreeCADGui,
            "doc": doc,
        }
        # Load common modules into namespace
        for mod_name in ("Part", "PartDesign", "Sketcher", "Draft", "Mesh"):
            try:
                ns[mod_name] = __import__(mod_name)
            except ImportError:
                pass
        return ns
