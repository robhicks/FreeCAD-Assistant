# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCADGui

from assistant import command

FreeCADGui.addCommand("Assistant_Chat", command.AssistantChatCommand())

from assistant.preferences import DlgSettingsAssistant

FreeCADGui.addPreferencePage(DlgSettingsAssistant, "Assistant")
