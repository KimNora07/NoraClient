"""Nora Studio native Windows shell (PySide6 + embedded Qt WebEngine)."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


def show_message(message):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(message), "Nora Studio", 0x10)
    else:
        print(message, file=sys.stderr)


def config():
    executable_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    user_data_root = Path(os.environ.get("LOCALAPPDATA", str(executable_dir))) / "NoraStudio"
    user_data_root.mkdir(parents=True, exist_ok=True)
    path = user_data_root / "config.json"
    legacy_path = executable_dir / "NoraStudio.config.json"
    template = {
        "port": 8765,
        "adminToken": "",
        "unityRepo": "",
        "model": "qwen3:8b",
        "codexEnabled": False,
        "autoRunApprovedTasks": False,
        "releaseRepo": "KimNora07/NoraClient",
    }
    if not path.exists():
        if legacy_path.exists():
            path.write_bytes(legacy_path.read_bytes())
        else:
            path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    if settings.get("releaseRepo") in (None, "", "KimNora07/NoraStudio"):
        settings["releaseRepo"] = "KimNora07/NoraClient"
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    port = int(settings.get("port", 8765))
    if not 1024 <= port <= 65535:
        raise ValueError("포트는 1024~65535 사이여야 합니다.")
    data_dir = user_data_root / "data"
    os.environ["NORA_DATA"] = str(data_dir)
    os.environ["NORA_TOKEN"] = str(settings.get("adminToken") or "")
    os.environ["NORA_REPO"] = str(settings.get("unityRepo") or "")
    os.environ["NORA_MODEL"] = str(settings.get("model") or "qwen3:8b")
    os.environ["NORA_CODEX_ENABLED"] = "1" if settings.get("codexEnabled") is True else "0"
    os.environ["NORA_AUTO_RUN"] = "1" if settings.get("autoRunApprovedTasks") is True else "0"
    os.environ["NORA_RELEASE_REPO"] = str(settings.get("releaseRepo") or "")
    return port


def create_icon():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, 62, 62), radius=17, fill="#7466D9")
    draw.rounded_rectangle((6, 6, 58, 58), radius=14, outline="#AFA4FF", width=2)
    try:
        font = ImageFont.truetype("arialbd.ttf", 35)
    except OSError:
        font = ImageFont.load_default()
    draw.text((32, 31), "N", anchor="mm", font=font, fill="#FFFFFF")
    return img


def port_is_nora(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as response:
            data = json.load(response)
        return data.get("role") in ("guest", "admin") and "codex_enabled" in data
    except Exception:
        return False


def run_desktop_window(url, server=None):
    """Keep the local dashboard in a standalone Qt window with tray controls."""
    from PySide6.QtCore import QUrl, QTimer
    from PySide6.QtGui import QAction, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon
    from PySide6.QtWebEngineWidgets import QWebEngineView

    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Nora Studio")
    application.setQuitOnLastWindowClosed(False)

    image = create_icon()
    icon_bytes = __import__("io").BytesIO()
    image.save(icon_bytes, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(icon_bytes.getvalue(), "PNG")
    icon = QIcon(pixmap)
    application.setWindowIcon(icon)

    class StudioWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Nora Studio")
            self.setWindowIcon(icon)
            self.resize(1380, 850)
            self.setMinimumSize(900, 600)
            self.web = QWebEngineView(self)
            self.web.setUrl(QUrl(url))
            self.setCentralWidget(self.web)

        def closeEvent(self, event):
            if tray.isVisible():
                self.hide()
                event.ignore()
            else:
                event.accept()

    window = StudioWindow()
    tray = QSystemTrayIcon(icon, application)
    tray.setToolTip("Nora Studio — 실행 중")
    menu = QMenu()
    show_action = QAction("대시보드 열기", menu)
    show_action.triggered.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
    menu.addAction(show_action)
    quit_action = QAction("Nora Studio 종료", menu)

    def quit_studio():
        if server is not None:
            server.should_exit = True
        tray.hide()
        window.close()
        application.quit()

    quit_action.triggered.connect(quit_studio)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: show_action.trigger() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()
    else:
        # Without a tray, closing the only window must also stop the server.
        application.setQuitOnLastWindowClosed(True)
        application.aboutToQuit.connect(lambda: setattr(server, "should_exit", True) if server is not None else None)

    from studio import updater
    update_timer = QTimer(window)
    def check_install_request():
        requested = updater.consume_install_request()
        if not requested:
            return
        if not getattr(sys, "frozen", False):
            show_message("업데이트 설치에는 실제 설치된 Nora Studio.exe 실행이 필요합니다.")
            return
        try:
            script = updater.make_helper(Path(requested).parent)
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(script), "-ParentProcessId", str(os.getpid()),
                              "-InstallerPath", requested, "-AppPath", sys.executable],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            show_message(f"업데이트 설치 프로그램을 시작하지 못했습니다: {exc}")
            return
        quit_studio()
    update_timer.timeout.connect(check_install_request)
    update_timer.start(1000)
    window.show()
    return application.exec()


def main():
    if sys.platform != "win32":
        print("This desktop entrypoint targets Windows.")
        return 1
    try:
        port = config()
        url = f"http://127.0.0.1:{port}"
        if port_is_nora(port):
            return run_desktop_window(url)

        import uvicorn
        from studio.app import app

        # Avoid Uvicorn's dynamically resolved logging formatter in frozen builds.
        # PyInstaller cannot always discover the default logging formatter class.
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                              log_config=None, log_level="warning",
                                              access_log=False))
        thread = threading.Thread(target=server.run, daemon=True, name="nora-api")
        thread.start()
        for _ in range(100):
            if port_is_nora(port):
                break
            if not thread.is_alive():
                raise RuntimeError("서버 시작에 실패했습니다. 포트가 사용 중인지 확인하세요.")
            time.sleep(0.2)
        else:
            raise TimeoutError("서버가 20초 내에 응답하지 않았습니다.")

        run_desktop_window(url, server)
        thread.join(timeout=5)
        return 0
    except Exception as exc:
        show_message(f"Nora Studio 실행 실패:\n{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
