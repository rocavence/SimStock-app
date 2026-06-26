"""台股模擬交易 — 桌面選單列 App。

選單列一顆圖示 → 開出可自由調整大小的懸浮視窗（WKWebView）顯示 web app；
後端 uvicorn 在背景執行緒內建啟動。第一次開啟有引導設定（port + 存檔位置），
之後可在選單調整、並可註冊「登入時自動啟動」（預設關）。

開發執行：  desktop/.venv/bin/python desktop/app.py
冒煙測試：  TWSTOCK_SMOKE=1 desktop/.venv/bin/python desktop/app.py   # 只測後端、不開 GUI
打包：      desktop/build.sh  → 產出 desktop/dist/TWStockSim.app
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---- 路徑：凍結時用 _MEIPASS；開發時把專案根目錄加進 sys.path 以 import backend ----
if getattr(sys, "frozen", False):
    BASE = Path(sys._MEIPASS)
    MENUBAR_ICON = str(BASE / "menubar-icon.png")
    SAMPLE_SAVE = str(BASE / "sample-save.json")
    APP_PATH = str(Path(sys.executable).resolve().parents[2])  # …/TWStockSim.app
else:
    BASE = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(BASE))
    MENUBAR_ICON = str(Path(__file__).resolve().parent / "menubar-icon.png")
    SAMPLE_SAVE = str(Path(__file__).resolve().parent / "sample-save.json")
    APP_PATH = "/Applications/TWStockSim.app"

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "twstock-sim"
CONFIG_FILE = APP_SUPPORT / "config.json"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.rocavence.twstocksim.plist"
DEFAULT_PORT = 8888


def load_config() -> dict:
    cfg = {"port": DEFAULT_PORT, "save_dir": None, "onboarded": False}
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


CONFIG = load_config()
FIRST_RUN = not bool(CONFIG.get("onboarded"))


def get_port() -> int:
    return int(CONFIG.get("port") or DEFAULT_PORT)


def apply_save_env() -> None:
    """把存檔位置反映到環境變數（必須在 import backend 前設好）。"""
    if CONFIG.get("save_dir"):
        os.environ["TWSTOCK_SAVE_DIR"] = str(CONFIG["save_dir"])
    else:
        os.environ.pop("TWSTOCK_SAVE_DIR", None)


apply_save_env()


def port_alive(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.25)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def start_backend(port: int) -> None:
    """在背景執行緒啟動 uvicorn。固定 asyncio+h11，避免凍結時缺 uvloop/httptools。"""
    import uvicorn

    conf = uvicorn.Config("backend.main:app", host="127.0.0.1", port=port,
                          loop="asyncio", http="h11", log_level="warning")
    server = uvicorn.Server(conf)
    threading.Thread(target=server.run, daemon=True, name="uvicorn").start()


def wait_for_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_alive(port):
            return True
        time.sleep(0.2)
    return False


# ---- 登入時自動啟動（LaunchAgent，放 ~/Library/LaunchAgents 即會在下次登入自動載入）----
def login_item_enabled() -> bool:
    return LAUNCH_AGENT.exists()


def set_login_item(on: bool) -> None:
    if on:
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '  <key>Label</key><string>com.rocavence.twstocksim</string>\n'
            '  <key>ProgramArguments</key>\n'
            f'  <array><string>/usr/bin/open</string><string>-a</string><string>{APP_PATH}</string></array>\n'
            '  <key>RunAtLoad</key><true/>\n'
            '</dict></plist>\n',
            encoding="utf-8",
        )
        # 僅寫檔即可在下次登入生效；不立刻 load 以免現在又開一個實例。
    else:
        try:
            LAUNCH_AGENT.unlink()
        except FileNotFoundError:
            pass
        subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT)],
                       capture_output=True)


# ---------------------------------------------------------------- 冒煙測試（無 GUI）
if os.environ.get("TWSTOCK_SMOKE"):
    start_backend(get_port())
    ok = wait_for_port(get_port())
    print(f"[smoke] backend on {get_port()}: {'OK' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- GUI
import rumps
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSFloatingWindowLevel, NSMakeRect,
    NSNormalWindowLevel, NSOpenPanel, NSViewHeightSizable, NSViewWidthSizable,
    NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration

WINDOW_STYLE = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                | NSWindowStyleMaskResizable | NSWindowStyleMaskMiniaturizable)


class _WindowAutoHide(NSObject):
    """視窗失去焦點（使用者點了別處）就隱藏，而非關閉。"""

    def windowDidResignKey_(self, note):
        note.object().orderOut_(None)


class TwstockApp(rumps.App):
    def __init__(self):
        if os.path.exists(MENUBAR_ICON):
            super().__init__("台股", icon=MENUBAR_ICON, template=True, quit_button=None)
        else:
            super().__init__("台股", title="台股", quit_button=None)
        self._window = None
        self._web = None
        self._floating = True
        self._win_delegate = _WindowAutoHide.alloc().init()

        self.open_item = rumps.MenuItem("開啟視窗", callback=self.open_window)
        self.port_item = rumps.MenuItem(self._port_title(), callback=self.set_port)
        self.save_item = rumps.MenuItem(self._save_title(), callback=self.set_save_dir)
        self.float_item = rumps.MenuItem("視窗置頂（懸浮）", callback=self.toggle_floating)
        self.float_item.state = 1 if self._floating else 0
        self.login_item = rumps.MenuItem("登入時自動啟動", callback=self.toggle_login)
        self.login_item.state = 1 if login_item_enabled() else 0
        self.menu = [
            self.open_item,
            None,
            self.port_item,
            self.save_item,
            self.float_item,
            self.login_item,
            None,
            rumps.MenuItem("重新啟動", callback=self.relaunch),
            rumps.MenuItem("結束", callback=rumps.quit_application),
        ]

        # 第一次開啟：等 run loop 起來後跑引導設定。
        if FIRST_RUN:
            self._onboard_timer = rumps.Timer(self._run_onboarding, 0.4)
            self._onboard_timer.start()

    # ---- 選單標題 ----
    def _port_title(self) -> str:
        return f"Port：{get_port()}"

    def _save_title(self) -> str:
        sd = CONFIG.get("save_dir")
        return f"存檔位置：{sd}" if sd else "存檔位置：預設（Dropbox／文件）"

    def _refresh_titles(self):
        self.port_item.title = self._port_title()
        self.save_item.title = self._save_title()

    def _activate(self):
        NSApp.activateIgnoringOtherApps_(True)

    # ---- 第一次開啟的引導 ----
    def _run_onboarding(self, sender):
        sender.stop()
        self._activate()
        rumps.alert(
            "歡迎使用 台股模擬交易",
            "這個 App 會在你的電腦「本機」跑一個小型網頁伺服器來顯示操作介面。\n\n"
            "接下來用兩步完成設定：\n① 選擇連線埠（Port）\n② 選擇存檔位置",
            ok="開始設定",
        )

        # ① Port
        w = rumps.Window(
            "Port（埠號）是本機伺服器在你電腦上的「門牌號碼」，App 透過它連到介面。\n\n"
            "預設 8888，通常直接用即可；只有當 8888 被其他程式占用、或你想換號時才需要改。\n\n"
            "請輸入 1024–65535：",
            "設定 Port", default_text=str(get_port()),
            ok="下一步", cancel="用預設 8888", dimensions=(160, 22))
        resp = w.run()
        if resp.clicked == 1 and resp.text.strip().isdigit() and 1024 <= int(resp.text.strip()) <= 65535:
            CONFIG["port"] = int(resp.text.strip())
        else:
            CONFIG["port"] = DEFAULT_PORT

        # ② 存檔位置
        if rumps.alert(
            "存檔位置",
            "模擬資料要存到哪裡？\n\n預設會放 Dropbox/Apps（找不到則放「文件」），方便跨機同步。\n"
            "你也可以自己指定一個資料夾。",
            ok="選擇資料夾…", cancel="用預設",
        ) == 1:
            path = self._choose_folder()
            if path:
                CONFIG["save_dir"] = path

        # ③ 範例資料（可選）
        import_sample = os.path.exists(SAMPLE_SAVE) and rumps.alert(
            "範例資料",
            "要不要匯入一份現成的範例投資組合（持股／交易紀錄／自選股），方便直接看效果？\n\n"
            "之後可在介面按「重置」清空，從零開始。",
            ok="匯入範例", cancel="從空白開始",
        ) == 1

        CONFIG["onboarded"] = True
        save_config(CONFIG)
        apply_save_env()
        if import_sample:
            self._import_sample()
        self._refresh_titles()
        start_backend(get_port())

        rumps.alert(
            "設定完成！",
            "點右上角選單列的圖示 →「開啟視窗」即可開始。\n\n"
            "日後可隨時在選單修改 Port、存檔位置，或開啟「登入時自動啟動」。",
            ok="好",
        )

    def _import_sample(self):
        """把打包的範例存檔灌入 DB，並存到使用者選的位置（不改資料來源指標）。"""
        try:
            import backend.db as db
            db.init_db()
            db.load_snapshot(SAMPLE_SAVE)
            try:
                db.save_snapshot()
            except OSError:
                pass  # 存檔位置不可寫也無妨，資料已在 DB
        except Exception as e:  # noqa: BLE001
            rumps.alert("範例匯入失敗", str(e))

    def _choose_folder(self):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setPrompt_("選擇")
        panel.setMessage_("選擇存檔資料夾（save.json 會放在這裡）")
        return panel.URLs()[0].path() if panel.runModal() == 1 else None

    # ---- 視窗 ----
    def open_window(self, _):
        if not port_alive(get_port()):
            rumps.alert("後端尚未就緒", "請稍候幾秒後再開啟視窗。")
            return
        if self._window is not None:
            self._window.makeKeyAndOrderFront_(None)
            self._activate()
            return
        rect = NSMakeRect(0, 0, 1180, 800)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, WINDOW_STYLE, NSBackingStoreBuffered, False)
        win.setTitle_("台股模擬交易")
        win.setReleasedWhenClosed_(False)
        win.setDelegate_(self._win_delegate)  # 失焦自動隱藏
        win.setMinSize_((720, 480))
        win.setLevel_(NSFloatingWindowLevel if self._floating else NSNormalWindowLevel)

        conf = WKWebViewConfiguration.alloc().init()
        web = WKWebView.alloc().initWithFrame_configuration_(rect, conf)
        web.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        win.setContentView_(web)
        web.loadRequest_(NSURLRequest.requestWithURL_(
            NSURL.URLWithString_(f"http://127.0.0.1:{get_port()}/")))

        win.center()
        win.makeKeyAndOrderFront_(None)
        self._activate()
        self._window, self._web = win, web

    def toggle_floating(self, sender):
        self._floating = not self._floating
        sender.state = 1 if self._floating else 0
        if self._window is not None:
            self._window.setLevel_(
                NSFloatingWindowLevel if self._floating else NSNormalWindowLevel)

    def toggle_login(self, sender):
        on = not login_item_enabled()
        set_login_item(on)
        sender.state = 1 if on else 0

    # ---- 設定 ----
    def set_port(self, _):
        w = rumps.Window("輸入埠號（1024–65535），重新啟動後生效：", "設定 Port",
                         default_text=str(get_port()), ok="儲存", cancel="取消",
                         dimensions=(160, 22))
        resp = w.run()
        if resp.clicked != 1:
            return
        txt = resp.text.strip()
        if not (txt.isdigit() and 1024 <= int(txt) <= 65535):
            rumps.alert("埠號無效", "請輸入 1024–65535 之間的數字。")
            return
        CONFIG["port"] = int(txt)
        save_config(CONFIG)
        self._refresh_titles()
        self._ask_relaunch(f"Port 已改為 {txt}")

    def set_save_dir(self, _):
        path = self._choose_folder()
        if not path:
            return
        CONFIG["save_dir"] = path
        save_config(CONFIG)
        self._refresh_titles()
        self._ask_relaunch(f"存檔位置已設為：\n{path}")

    def _ask_relaunch(self, msg: str):
        if rumps.alert("已儲存", f"{msg}\n\n需重新啟動 App 才會生效。要現在重新啟動嗎？",
                       ok="重新啟動", cancel="稍後"):
            self.relaunch(None)

    def relaunch(self, _):
        os.execv(sys.executable, [sys.executable])


def main():
    if not FIRST_RUN:
        start_backend(get_port())
    TwstockApp().run()


if __name__ == "__main__":
    main()
