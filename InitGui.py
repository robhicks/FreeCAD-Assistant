# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD
import FreeCADGui


class AIAssistantWorkbench(FreeCADGui.Workbench):
    import os as _os
    MenuText = "AI Assistant"
    ToolTip = "AI Assistant for FreeCAD"
    Icon = _os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "AIAssistant", "assistant", "resources", "icons", "Assistant.svg")

    def Initialize(self):
        from assistant import command

        FreeCADGui.addCommand("Assistant_Chat", command.AssistantChatCommand())
        self.appendMenu("AI Assistant", ["Assistant_Chat"])
        self.appendToolbar("AI Assistant", ["Assistant_Chat"])

    def Activated(self):
        from PySide import QtCore
        QtCore.QTimer.singleShot(100, lambda: FreeCADGui.runCommand("Assistant_Chat"))

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(AIAssistantWorkbench)

from assistant.preferences import DlgSettingsAssistant

FreeCADGui.addPreferencePage(DlgSettingsAssistant, "AI Assistant")
