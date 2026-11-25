"""Codex app-server stdio JSON-RPC bridge for one approved worktree task.

The bridge never accepts agent-generated approval prompts: command approval is
disabled at thread start and unsolicited server requests are denied.
"""

import json
import queue
import subprocess
import threading
import time


class AppServerError(RuntimeError):
    pass


class AppServerSession:
    def __init__(self, executable, cwd, on_event=None):
        self.on_event = on_event or (lambda _message: None)
        self.proc = subprocess.Popen(
            list(executable) + ["app-server"], cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._messages = queue.Queue()
        self._seq = 0
        self.thread_id = None
        self.turn_id = None
        self._stop = threading.Event()
        self._stderr_tail = ""
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _send(self, message):
        with self._write_lock:
            if self.proc.poll() is not None:
                raise AppServerError(f"Codex App Server exited: {self.proc.returncode} {self._stderr_tail[-500:]}")
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def _read_stdout(self):
        try:
            for line in self.proc.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    with self._pending_lock:
                        waiter = self._pending.pop(message["id"], None)
                    if waiter:
                        waiter.put(message)
                elif "id" in message and "method" in message:
                    # No autonomous escalation; the owner must authorize work
                    # through Nora Studio, not through an invisible RPC dialog.
                    try:
                        self._send({"id": message["id"], "error": {
                            "code": -32600, "message": "Nora Studio does not grant interactive approvals"}})
                    except (OSError, AppServerError):
                        pass
                else:
                    self._messages.put(message)
        finally:
            self._messages.put({"method": "_server/exited"})

    def _read_stderr(self):
        for line in self.proc.stderr:
            self._stderr_tail = (self._stderr_tail + line)[-4000:]

    def request(self, method, params=None, timeout=20):
        reply = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._seq += 1
            request_id = self._seq
            self._pending[request_id] = reply
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            try:
                message = reply.get(timeout=timeout)
            except queue.Empty as exc:
                raise AppServerError(f"Codex App Server did not respond to {method}") from exc
            if "error" in message:
                raise AppServerError(f"{method}: {message['error']}")
            return message.get("result", {})
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def start(self, prompt, cwd):
        self.request("initialize", {"clientInfo": {
            "name": "nora_studio", "title": "Nora Studio", "version": "0.4.0"}})
        self._send({"method": "initialized", "params": {}})
        result = self.request("thread/start", {
            "cwd": str(cwd), "approvalPolicy": "never", "sandbox": "workspace-write",
            "serviceName": "nora_studio"})
        self.thread_id = result["thread"]["id"]
        result = self.request("turn/start", {"threadId": self.thread_id,
            "input": [{"type": "text", "text": prompt}]})
        self.turn_id = result["turn"]["id"]
        return self.thread_id, self.turn_id

    def interrupt(self):
        self._stop.set()
        if self.thread_id and self.turn_id and self.proc.poll() is None:
            try:
                self.request("turn/interrupt", {"threadId": self.thread_id,
                    "turnId": self.turn_id}, timeout=5)
            except (AppServerError, OSError):
                pass

    def wait(self, timeout, stop_requested=None):
        started = time.monotonic()
        interrupt_sent = None
        while True:
            if time.monotonic() - started >= timeout:
                self.interrupt()
                raise subprocess.TimeoutExpired("codex app-server", timeout)
            if (self._stop.is_set() or (stop_requested and stop_requested())) and interrupt_sent is None:
                self.interrupt()
                interrupt_sent = time.monotonic()
            if interrupt_sent is not None and time.monotonic() - interrupt_sent > 8:
                return "interrupted"
            try:
                event = self._messages.get(timeout=0.3)
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise AppServerError(f"Codex App Server exited unexpectedly: {self._stderr_tail[-700:]}")
                continue
            method = event.get("method")
            if method == "_server/exited":
                raise AppServerError(f"Codex App Server exited: {self._stderr_tail[-700:]}")
            params = event.get("params") or {}
            if method == "turn/completed" and params.get("turn", {}).get("id") == self.turn_id:
                status = params["turn"].get("status", "failed")
                self.on_event(event)
                return status
            self.on_event(event)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
