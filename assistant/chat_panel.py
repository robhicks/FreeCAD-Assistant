# SPDX-License-Identifier: LGPL-2.1-or-later

import html
import re

import FreeCAD
from PySide import QtCore, QtGui, QtWidgets


class AssistantDockWidget(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("AI Assistant", parent)
        self.setObjectName("AssistantPanel")
        self.setWidget(ChatWidget(self))


class ChatWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []  # [{"role": "user"|"assistant", "content": str}]
        self._code_blocks = []  # extracted code blocks from responses
        self._exec_results = {}  # {block_index: (success, stdout, stderr)}
        self._worker = None
        self._orchestrator = None
        self._current_plan = None
        self._plan_preamble = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Message display
        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)
        layout.addWidget(self._browser, 1)

        # Status label
        self._status = QtWidgets.QLabel("")
        self._status.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._status)

        # Input area
        input_layout = QtWidgets.QHBoxLayout()
        input_layout.setSpacing(4)

        self._input = ChatInput(self)
        self._input.setPlaceholderText("Describe what you want to create...")
        self._input.setMinimumHeight(120)
        self._input.send_requested.connect(self._on_send)
        input_layout.addWidget(self._input, 1)

        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setSpacing(2)

        self._send_btn = QtWidgets.QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(self._send_btn)

        self._undo_btn = QtWidgets.QPushButton("Undo")
        self._undo_btn.clicked.connect(self._on_undo)
        btn_layout.addWidget(self._undo_btn)

        self._clear_btn = QtWidgets.QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self._clear_btn)

        btn_layout.addStretch()
        input_layout.addLayout(btn_layout)
        layout.addLayout(input_layout)

    def _get_orchestrator(self):
        """Lazy-init orchestrator and connect signals."""
        if self._orchestrator is None:
            from assistant.orchestrator import Orchestrator

            self._orchestrator = Orchestrator(parent=self)
            self._orchestrator.status_changed.connect(self._on_status_changed)
            self._orchestrator.plan_received.connect(self._on_plan_received)
            self._orchestrator.direct_response.connect(self._on_direct_response)
            self._orchestrator.step_completed.connect(self._on_step_completed)
            self._orchestrator.retry_started.connect(self._on_retry_started)
            self._orchestrator.all_done.connect(self._on_all_done)
            self._orchestrator.error_occurred.connect(self._on_error)
        return self._orchestrator

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        orch = self._get_orchestrator()
        if orch.state != "idle":
            return

        self._input.clear()
        self._history.append({"role": "user", "content": text})
        self._render_messages()
        self._send_btn.setEnabled(False)

        orch.submit(text, self._history)

    def _on_status_changed(self, text):
        self._status.setText(text)

    def _on_direct_response(self, text):
        self._send_btn.setEnabled(True)
        self._history.append({"role": "assistant", "content": text})

        start_idx = len(self._code_blocks)
        self._render_messages()

        # Auto-execute if enabled
        prefs = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Assistant")
        if prefs.GetBool("AutoExecute", False):
            for idx in range(start_idx, len(self._code_blocks)):
                self._execute_code(idx)
                # Auto-retry on failure
                if idx in self._exec_results:
                    success, _stdout, stderr = self._exec_results[idx]
                    if not success and idx < len(self._code_blocks):
                        self._get_orchestrator().retry_direct(
                            self._code_blocks[idx], stderr
                        )
                        break  # orchestrator takes over

    def _on_plan_received(self, plan, preamble):
        self._send_btn.setEnabled(True)
        self._current_plan = plan
        self._plan_preamble = preamble
        self._render_messages()

        # Auto-execute plan if enabled
        prefs = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Assistant")
        if prefs.GetBool("AutoExecute", False):
            self._get_orchestrator().execute_plan()

    def _on_step_completed(self, index, success, stdout, stderr):
        if self._current_plan and index < len(self._current_plan.steps):
            step = self._current_plan.steps[index]
            step.result = (success, stdout, stderr)
        self._render_messages()

    def _on_retry_started(self, step_index, attempt):
        self._render_messages()

    def _on_all_done(self):
        self._send_btn.setEnabled(True)
        self._status.setText("")

        # Add summary to history
        if self._current_plan:
            done = sum(1 for s in self._current_plan.steps if s.status == "done")
            total = len(self._current_plan.steps)
            self._history.append({
                "role": "assistant",
                "content": f"Plan completed: {done}/{total} steps succeeded.",
            })
        self._render_messages()

    def _on_error(self, msg):
        self._status.setText("")
        self._send_btn.setEnabled(True)
        self._history.append(
            {"role": "assistant", "content": f"**Error:** {msg}"}
        )
        self._render_messages()

    def _on_undo(self):
        doc = FreeCAD.ActiveDocument
        if not doc:
            self._status.setText("No active document.")
            return
        if not doc.HasPendingTransaction and doc.UndoCount > 0:
            doc.undo()
            doc.recompute()
            self._status.setText("Undo successful.")
        else:
            self._status.setText("Nothing to undo.")

    def _on_clear(self):
        self._history.clear()
        self._code_blocks.clear()
        self._exec_results.clear()
        self._current_plan = None
        self._plan_preamble = ""
        self._browser.clear()
        self._status.setText("")
        if self._orchestrator:
            self._orchestrator.cancel()

    def _on_anchor_clicked(self, url):
        url_str = url.toString()
        if ":" not in url_str:
            return
        scheme, _, index_str = url_str.partition(":")
        try:
            index = int(index_str)
        except (ValueError, TypeError):
            return

        if scheme == "execute":
            self._execute_code(index)
        elif scheme == "copy":
            self._copy_code(index)
        elif scheme == "plan-execute":
            self._get_orchestrator().execute_plan()
        elif scheme == "plan-cancel":
            self._get_orchestrator().cancel()
            self._current_plan = None
            self._render_messages()

    def _execute_code(self, index):
        if index < 0 or index >= len(self._code_blocks):
            return

        code = self._code_blocks[index]
        from assistant.executor import CodeExecutor

        executor = CodeExecutor()
        success, stdout, stderr = executor.execute(code)
        self._exec_results[index] = (success, stdout, stderr)
        self._render_messages()

    def _copy_code(self, index):
        if index < 0 or index >= len(self._code_blocks):
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self._code_blocks[index])
        self._status.setText("Code copied to clipboard.")

    def _render_messages(self):
        self._code_blocks.clear()
        parts = []
        parts.append(
            "<html><head><style>"
            "body { font-family: sans-serif; font-size: 13px; }"
            ".user { background: #dbeafe; padding: 8px; margin: 4px 0; "
            "border-radius: 8px; }"
            ".assistant { background: #f3f4f6; padding: 8px; margin: 4px 0; "
            "border-radius: 8px; }"
            ".error { background: #ffebee; padding: 8px; margin: 4px 0; "
            "border-radius: 8px; }"
            "pre { background: #1e1e1e; color: #d4d4d4; padding: 8px; "
            "border-radius: 4px; font-size: 12px; white-space: pre-wrap; "
            "word-wrap: break-word; }"
            ".actions { margin: 2px 0 8px 0; }"
            ".actions a { color: #1976d2; text-decoration: none; "
            "margin-right: 12px; font-size: 12px; }"
            ".step-pending { color: #757575; }"
            ".step-running { color: #1565c0; font-weight: bold; }"
            ".step-done { color: #2e7d32; }"
            ".step-failed { color: #c62828; }"
            ".retry-badge { background: #fff3e0; color: #e65100; "
            "padding: 1px 6px; border-radius: 8px; font-size: 11px; "
            "margin-left: 6px; }"
            ".plan-box { background: #e3f2fd; padding: 10px; margin: 4px 0; "
            "border-radius: 8px; border-left: 4px solid #1565c0; }"
            ".plan-actions { margin-top: 8px; }"
            ".plan-actions a { color: #1565c0; text-decoration: none; "
            "font-weight: bold; margin-right: 16px; font-size: 13px; }"
            "</style></head><body>"
        )

        for msg in self._history:
            if msg["role"] == "user":
                parts.append(
                    f'<div class="user"><b>You:</b><br/>'
                    f"{html.escape(msg['content'])}</div>"
                )
            else:
                content = msg["content"]
                is_error = content.startswith("**Error:**")
                css_class = "error" if is_error else "assistant"
                rendered = self._render_assistant_content(content)
                parts.append(
                    f'<div class="{css_class}"><b>Assistant:</b><br/>'
                    f"{rendered}</div>"
                )

        # Render current plan if active
        if self._current_plan:
            parts.append(self._render_plan())

        parts.append("</body></html>")
        self._browser.setHtml("".join(parts))
        self._scroll_to_bottom()

    def _render_plan(self):
        """Render plan steps with status indicators."""
        plan = self._current_plan
        lines = ['<div class="plan-box">']

        if self._plan_preamble:
            escaped = html.escape(self._plan_preamble)
            escaped = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped)
            escaped = escaped.replace("\n", "<br/>")
            lines.append(f"<b>Assistant:</b><br/>{escaped}<br/><br/>")

        lines.append("<b>Execution Plan:</b><br/>")
        for step in plan.steps:
            icon = {
                "pending": "&#9711;",   # circle
                "running": "&#9654;",   # play
                "done": "&#10004;",     # check
                "failed": "&#10008;",   # cross
            }.get(step.status, "&#9711;")

            css = f"step-{step.status}"
            retry_html = ""
            if step.retries > 0:
                retry_html = f'<span class="retry-badge">retry {step.retries}</span>'

            lines.append(
                f'<div class="{css}">'
                f"{icon} Step {step.number}: {html.escape(step.description)}"
                f"{retry_html}</div>"
            )

            # Show step execution result
            if step.result:
                success, stdout, stderr = step.result
                if stdout:
                    lines.append(
                        '<div style="background:#e8f5e9; padding:4px 8px; '
                        'margin:2px 0 2px 20px; border-radius:4px; '
                        'font-family:monospace; font-size:11px;">'
                        f"{html.escape(stdout)}</div>"
                    )
                if stderr and not success:
                    lines.append(
                        '<div style="background:#ffebee; padding:4px 8px; '
                        'margin:2px 0 2px 20px; border-radius:4px; '
                        'font-family:monospace; font-size:11px;">'
                        f"{html.escape(stderr)}</div>"
                    )

        # Plan action buttons
        orch = self._get_orchestrator()
        if orch.state == "showing_plan":
            lines.append(
                '<div class="plan-actions">'
                '<a href="plan-execute:0">[Execute Plan]</a>'
                '<a href="plan-cancel:0">[Cancel]</a>'
                "</div>"
            )

        lines.append("</div>")
        return "".join(lines)

    def _render_assistant_content(self, text):
        prefs = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/Assistant"
        )
        show_code = prefs.GetBool("ShowCode", True)
        segments = re.split(r"(```(?:python)?\n.*?```)", text, flags=re.DOTALL)
        result = []
        for segment in segments:
            m = re.match(r"```(?:python)?\n(.*?)```", segment, re.DOTALL)
            if m:
                code = m.group(1).rstrip("\n")
                idx = len(self._code_blocks)
                self._code_blocks.append(code)
                if show_code:
                    result.append(f"<pre>{html.escape(code)}</pre>")
                    result.append(
                        '<div class="actions">'
                        f'<a href="execute:{idx}">[Execute]</a>'
                        f'<a href="copy:{idx}">[Copy]</a>'
                        "</div>"
                    )
                else:
                    result.append(
                        '<div class="actions">'
                        f'<a href="execute:{idx}">[Execute Code]</a>'
                        "</div>"
                    )
                # Show execution result if available
                if idx in self._exec_results:
                    success, stdout, stderr = self._exec_results[idx]
                    if stdout:
                        result.append(
                            '<div style="background:#e8f5e9; padding:6px; '
                            'margin:2px 0; border-radius:4px; '
                            'font-family:monospace; font-size:12px;">'
                            f"{html.escape(stdout)}</div>"
                        )
                    if stderr:
                        color = "#e8f5e9" if success else "#ffebee"
                        result.append(
                            f'<div style="background:{color}; padding:6px; '
                            'margin:2px 0; border-radius:4px; '
                            'font-family:monospace; font-size:12px;">'
                            f"{html.escape(stderr)}</div>"
                        )
                    if success and not stdout and not stderr:
                        result.append(
                            '<div style="background:#e8f5e9; padding:6px; '
                            'margin:2px 0; border-radius:4px; '
                            'color:#2e7d32;">Executed successfully.</div>'
                        )
            else:
                # Simple markdown-ish rendering
                escaped = html.escape(segment)
                escaped = re.sub(
                    r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped
                )
                escaped = escaped.replace("\n", "<br/>")
                result.append(escaped)
        return "".join(result)

    def _scroll_to_bottom(self):
        sb = self._browser.verticalScrollBar()
        sb.setValue(sb.maximum())


class ChatInput(QtWidgets.QPlainTextEdit):
    """Text input that sends on Enter and inserts newline on Shift+Enter."""

    send_requested = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
                return
        super().keyPressEvent(event)
