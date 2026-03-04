# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD
from PySide import QtWidgets

PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/Assistant"


class DlgSettingsAssistant(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.loadSettings()

    def _setup_ui(self):
        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Provider
        self._provider = QtWidgets.QComboBox()
        self._provider.addItems(["anthropic", "openai", "gemini", "custom"])
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        layout.addRow("Provider:", self._provider)

        # API Key
        self._api_key = QtWidgets.QLineEdit()
        self._api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addRow("API Key:", self._api_key)

        # Warning
        warning = QtWidgets.QLabel(
            "<i>Note: API key is stored as plaintext in FreeCAD configuration.</i>"
        )
        warning.setStyleSheet("color: #b71c1c; font-size: 11px;")
        warning.setWordWrap(True)
        layout.addRow("", warning)

        # Base URL
        self._base_url = QtWidgets.QLineEdit()
        self._base_url.setPlaceholderText("Leave empty for default")
        layout.addRow("Base URL:", self._base_url)

        # Model
        self._model = QtWidgets.QLineEdit()
        self._model.setPlaceholderText("Leave empty for default")
        layout.addRow("Model:", self._model)

        # Auto-execute
        self._auto_execute = QtWidgets.QCheckBox(
            "Automatically execute generated code"
        )
        layout.addRow("", self._auto_execute)

        # Show code
        self._show_code = QtWidgets.QCheckBox(
            "Show generated code in chat"
        )
        self._show_code.setChecked(True)
        layout.addRow("", self._show_code)

        # Max retries
        self._max_retries = QtWidgets.QSpinBox()
        self._max_retries.setMinimum(0)
        self._max_retries.setMaximum(10)
        self._max_retries.setValue(3)
        self._max_retries.setToolTip(
            "Maximum number of auto-retry attempts when generated code fails"
        )
        layout.addRow("Max retries:", self._max_retries)

    def _on_provider_changed(self, index):
        provider = self._provider.currentText()
        placeholders = {
            "anthropic": ("https://api.anthropic.com", "claude-sonnet-4-20250514"),
            "openai": ("https://api.openai.com", "gpt-4o"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
            "custom": ("http://localhost:11434", ""),
        }
        url_ph, model_ph = placeholders.get(provider, ("", ""))
        self._base_url.setPlaceholderText(url_ph or "Leave empty for default")
        self._model.setPlaceholderText(model_ph or "Leave empty for default")

    def saveSettings(self):
        prefs = FreeCAD.ParamGet(PREFS_PATH)
        prefs.SetString("Provider", self._provider.currentText())
        prefs.SetString("ApiKey", self._api_key.text())
        prefs.SetString("BaseUrl", self._base_url.text())
        prefs.SetString("Model", self._model.text())
        prefs.SetBool("AutoExecute", self._auto_execute.isChecked())
        prefs.SetBool("ShowCode", self._show_code.isChecked())
        prefs.SetInt("MaxRetries", self._max_retries.value())

    def loadSettings(self):
        prefs = FreeCAD.ParamGet(PREFS_PATH)
        provider = prefs.GetString("Provider", "anthropic")
        idx = self._provider.findText(provider)
        if idx >= 0:
            self._provider.setCurrentIndex(idx)
        self._api_key.setText(prefs.GetString("ApiKey", ""))
        self._base_url.setText(prefs.GetString("BaseUrl", ""))
        self._model.setText(prefs.GetString("Model", ""))
        self._auto_execute.setChecked(prefs.GetBool("AutoExecute", False))
        self._show_code.setChecked(prefs.GetBool("ShowCode", True))
        self._max_retries.setValue(prefs.GetInt("MaxRetries", 3))
        self._on_provider_changed(self._provider.currentIndex())
