# SPDX-License-Identifier: LGPL-2.1-or-later

from PySide import QtCore


class LLMWorker(QtCore.QThread):
    response_ready = QtCore.Signal(str)
    error_occurred = QtCore.Signal(str)

    def __init__(self, client, messages, system_prompt, parent=None):
        super().__init__(parent)
        self.client = client
        self.messages = messages
        self.system_prompt = system_prompt

    def run(self):
        try:
            text = self.client.send_message(self.messages, self.system_prompt)
            self.response_ready.emit(text)
        except Exception as e:
            self.error_occurred.emit(str(e))
