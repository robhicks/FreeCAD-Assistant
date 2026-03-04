# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD
from PySide import QtCore

from assistant.plan_parser import parse_response, extract_code_block


# States
IDLE = "idle"
WAITING_FOR_LLM = "waiting_for_llm"
SHOWING_PLAN = "showing_plan"
EXECUTING_STEP = "executing_step"
WAITING_FOR_STEP_CODE = "waiting_for_step_code"
RETRYING = "retrying"


class Orchestrator(QtCore.QObject):
    """State machine managing plan execution, auto-retry, and LLM interaction."""

    status_changed = QtCore.Signal(str)
    plan_received = QtCore.Signal(object, str)  # (Plan, preamble)
    direct_response = QtCore.Signal(str)
    step_completed = QtCore.Signal(int, bool, str, str)  # index, success, stdout, stderr
    retry_started = QtCore.Signal(int, int)  # step_index, attempt
    all_done = QtCore.Signal()
    error_occurred = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = IDLE
        self._plan = None
        self._current_step = 0
        self._history = []
        self._user_text = ""
        self._worker = None
        self._max_retries = 3
        self._pending_code = None
        self._pending_error = None

    @property
    def state(self):
        return self._state

    def submit(self, user_text, history):
        """Entry point: submit a user request. Replaces direct LLMWorker usage."""
        if self._state != IDLE:
            return

        self._user_text = user_text
        self._history = list(history)
        self._plan = None
        self._current_step = 0

        # Load max retries from prefs
        prefs = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/Assistant"
        )
        self._max_retries = prefs.GetInt("MaxRetries", 3)

        self._state = WAITING_FOR_LLM
        self.status_changed.emit("Thinking...")
        self._call_llm(self._history, self._build_system_prompt())

    def execute_plan(self):
        """Start executing the current plan step by step."""
        if self._state != SHOWING_PLAN or not self._plan:
            return
        self._current_step = 0
        self._execute_next_step()

    def cancel(self):
        """Cancel current operation and return to idle."""
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
        self._state = IDLE
        self.status_changed.emit("")

    def _build_system_prompt(self, step_info=None, retry_info=None):
        """Build system prompt with RAG context and plan/retry instructions."""
        from assistant.system_prompt import (
            build_system_prompt,
            build_document_context,
            build_rag_context,
            build_step_prompt,
            build_retry_prompt,
        )

        if retry_info:
            return build_retry_prompt(
                retry_info["code"],
                retry_info["error"],
                retry_info.get("step_info", ""),
            )

        base = build_system_prompt()

        # Add RAG context for the relevant query
        query = self._user_text
        if step_info:
            query = step_info["description"]
        rag_section = build_rag_context(query)

        doc_context = build_document_context()

        parts = [base]
        if rag_section:
            parts.append(rag_section)
        parts.append(doc_context)

        if step_info:
            parts.append(build_step_prompt(
                step_info["number"],
                step_info["description"],
                step_info["total"],
            ))

        return "\n\n".join(parts)

    def _call_llm(self, messages, system_prompt):
        """Fire an LLM request on a worker thread."""
        from assistant.llm_client import LLMClient
        from assistant.llm_worker import LLMWorker

        try:
            client = LLMClient.from_preferences()
        except ValueError as e:
            self._state = IDLE
            self.error_occurred.emit(str(e))
            return

        self._worker = LLMWorker(client, messages, system_prompt, parent=self)
        self._worker.response_ready.connect(self._on_llm_response)
        self._worker.error_occurred.connect(self._on_llm_error)
        self._worker.start()

    def _on_llm_response(self, text):
        if self._state == WAITING_FOR_LLM:
            self._handle_initial_response(text)
        elif self._state == WAITING_FOR_STEP_CODE:
            self._handle_step_code(text)
        elif self._state == RETRYING:
            self._handle_retry_response(text)

    def _on_llm_error(self, msg):
        self._state = IDLE
        self.status_changed.emit("")
        self.error_occurred.emit(msg)

    def _handle_initial_response(self, text):
        """Handle the first LLM response: plan or direct."""
        plan, preamble = parse_response(text)

        if plan:
            self._plan = plan
            self._state = SHOWING_PLAN
            self.status_changed.emit("")
            self.plan_received.emit(plan, preamble)
        else:
            # Direct response — check for auto-execute + retry
            self._state = IDLE
            self.status_changed.emit("")
            self.direct_response.emit(text)

            # Try auto-retry for direct responses
            prefs = FreeCAD.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/Assistant"
            )
            if prefs.GetBool("AutoExecute", False):
                code = extract_code_block(text)
                if code:
                    self._try_direct_auto_retry(code, text)

    def _try_direct_auto_retry(self, code, response_text):
        """Execute code from a direct response and auto-retry on failure."""
        from assistant.executor import CodeExecutor

        executor = CodeExecutor()
        success, stdout, stderr = executor.execute(code)

        if success or self._max_retries <= 0:
            return

        # Failed — attempt retry
        self._pending_code = code
        self._pending_error = stderr
        self._state = RETRYING
        self._plan = None
        self._current_step = 0
        self._do_retry(code, stderr, attempt=1, step_index=-1)

    def _execute_next_step(self):
        """Request code for the next plan step."""
        if not self._plan or self._current_step >= len(self._plan.steps):
            self._state = IDLE
            self.status_changed.emit("")
            self.all_done.emit()
            return

        step = self._plan.steps[self._current_step]
        step.status = "running"

        self._state = WAITING_FOR_STEP_CODE
        self.status_changed.emit(
            f"Step {step.number}/{len(self._plan.steps)}: Generating code..."
        )

        step_info = {
            "number": step.number,
            "description": step.description,
            "total": len(self._plan.steps),
        }

        # Build messages for this step
        messages = list(self._history)
        messages.append({
            "role": "user",
            "content": f"Implement step {step.number}: {step.description}",
        })

        system = self._build_system_prompt(step_info=step_info)
        self._call_llm(messages, system)

    def _handle_step_code(self, text):
        """Handle LLM response for a plan step: extract code and execute."""
        from assistant.executor import CodeExecutor

        step = self._plan.steps[self._current_step]
        code = extract_code_block(text)

        if not code:
            step.status = "failed"
            step.result = (False, "", "No code block found in response")
            self.step_completed.emit(self._current_step, False, "", "No code block in response")
            self._advance_step()
            return

        step.code = code
        self.status_changed.emit(
            f"Step {step.number}/{len(self._plan.steps)}: Executing..."
        )

        executor = CodeExecutor()
        success, stdout, stderr = executor.execute(
            code, description=f"Step {step.number}: {step.description}"
        )

        if success:
            step.status = "done"
            step.result = (True, stdout, stderr)
            self.step_completed.emit(self._current_step, True, stdout, stderr)
            self._advance_step()
        else:
            # Try retry
            if step.retries < self._max_retries:
                step.retries += 1
                self._state = RETRYING
                self.retry_started.emit(self._current_step, step.retries)
                self._do_retry(code, stderr, step.retries, self._current_step)
            else:
                step.status = "failed"
                step.result = (False, stdout, stderr)
                self.step_completed.emit(self._current_step, False, stdout, stderr)
                self._advance_step()

    def _do_retry(self, code, error, attempt, step_index):
        """Send a retry request to the LLM with error context."""
        step_info_str = ""
        if step_index >= 0 and self._plan:
            step = self._plan.steps[step_index]
            step_info_str = f"Step {step.number}: {step.description}"

        self.status_changed.emit(
            f"Retry {attempt}/{self._max_retries}: Fixing code..."
        )

        system = self._build_system_prompt(
            retry_info={"code": code, "error": error, "step_info": step_info_str}
        )

        messages = list(self._history)
        messages.append({
            "role": "user",
            "content": f"The code failed with error: {error}\nPlease fix it.",
        })

        self._call_llm(messages, system)

    def _handle_retry_response(self, text):
        """Handle LLM response for a retry attempt."""
        from assistant.executor import CodeExecutor

        code = extract_code_block(text)
        if not code:
            # Retry produced no code — treat as failure
            if self._plan and 0 <= self._current_step < len(self._plan.steps):
                step = self._plan.steps[self._current_step]
                step.status = "failed"
                step.result = (False, "", "Retry produced no code")
                self.step_completed.emit(self._current_step, False, "", "Retry produced no code")
                self._advance_step()
            else:
                self._state = IDLE
                self.status_changed.emit("")
                self.direct_response.emit(text)
            return

        executor = CodeExecutor()
        success, stdout, stderr = executor.execute(code)

        if self._plan and 0 <= self._current_step < len(self._plan.steps):
            step = self._plan.steps[self._current_step]
            step.code = code

            if success:
                step.status = "done"
                step.result = (True, stdout, stderr)
                self.step_completed.emit(self._current_step, True, stdout, stderr)
                self._advance_step()
            elif step.retries < self._max_retries:
                step.retries += 1
                self.retry_started.emit(self._current_step, step.retries)
                self._do_retry(code, stderr, step.retries, self._current_step)
            else:
                step.status = "failed"
                step.result = (False, stdout, stderr)
                self.step_completed.emit(self._current_step, False, stdout, stderr)
                self._advance_step()
        else:
            # Direct mode retry
            if success:
                self._state = IDLE
                self.status_changed.emit("")
                self.direct_response.emit(text)
            else:
                self._state = IDLE
                self.status_changed.emit("")
                self.direct_response.emit(text)

    def _advance_step(self):
        """Move to the next plan step."""
        self._current_step += 1
        self._state = EXECUTING_STEP
        self._execute_next_step()
