# SPDX-License-Identifier: LGPL-2.1-or-later

import os

import FreeCADGui


class AssistantChatCommand:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                os.path.dirname(__file__), "resources", "icons", "Assistant.svg"
            ),
            "MenuText": "AI Assistant",
            "ToolTip": "Open the AI Assistant chat panel",
        }

    def Activated(self):
        from PySide import QtCore, QtWidgets

        mw = FreeCADGui.getMainWindow()
        dock = mw.findChild(QtWidgets.QDockWidget, "AssistantPanel")
        if dock:
            dock.setVisible(not dock.isVisible())
        else:
            from assistant.chat_panel import AssistantDockWidget

            dock = AssistantDockWidget(mw)
            mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    def IsActive(self):
        return True
