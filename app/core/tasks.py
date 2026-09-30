"""生成任务的原子状态管理，避免并发竞态。"""
from __future__ import annotations

import threading
import time


class GenerateManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {
            "running": False,
            "started_at": 0.0,
            "finished_at": 0.0,
            "ok": None,
            "stdout": "",
            "stderr": "",
            "error": "",
            "trigger": "",
        }

    def try_begin(self, trigger: str) -> bool:
        with self._lock:
            if self._state["running"]:
                return False
            self._state.update(
                running=True,
                started_at=time.time(),
                finished_at=0.0,
                ok=None,
                stdout="",
                stderr="",
                error="",
                trigger=trigger,
            )
            return True

    def append_log(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._state["stdout"] = (self._state["stdout"] + text)[-32000:]

    def append_err(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._state["stderr"] = (self._state["stderr"] + text)[-16000:]

    def finish(self, ok: bool, error: str = "") -> None:
        with self._lock:
            self._state.update(
                running=False,
                finished_at=time.time(),
                ok=ok,
                error=error,
            )

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])


gen_manager = GenerateManager()