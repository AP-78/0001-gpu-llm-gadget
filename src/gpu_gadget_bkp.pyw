#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Desktop Gadget fuer NVIDIA RTX 3060 (und andere NVIDIA GPUs).
Zeigt permanent auf dem Desktop an:
  - GPU-Auslastung (%)
  - VRAM belegt / gesamt (MB + Balken)
  - Temperatur (Grad C)

Bedienung:
  - Mit linker Maustaste ziehen  -> Fenster verschieben
  - Rechtsklick                  -> Menue (Kompakt/Detail, Immer-oben, Beenden)
  - Doppelklick                  -> zwischen Kompakt- und Detailansicht wechseln
Die Fensterposition wird in gpu_gadget_config.json gespeichert.
"""

import json
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont

def _app_dir():
    # PyInstaller-EXE: Ordner der .exe (nicht der fluechtige Temp-Extraktionsordner).
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(_app_dir(), "gpu_gadget_config.json")

REFRESH_MS = 1000          # Aktualisierung im Millisekunden-Takt
GPU_INDEX = 0              # welche GPU (0 = erste)

# Farbschema (dunkles, dezentes Overlay)
BG      = "#0d0f14"
FG      = "#e6e6e6"
MUTED   = "#8a8f99"
ACCENT  = "#76b900"        # NVIDIA-Gruen
WARN    = "#ffb000"
HOT     = "#ff4d4d"
BAR_BG  = "#22262e"

# nvidia-smi finden (PATH oder Standard-Installationspfad)
def find_nvidia_smi():
    from shutil import which
    p = which("nvidia-smi")
    if p:
        return p
    candidates = [
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "nvidia-smi"  # letzter Versuch

NVIDIA_SMI = find_nvidia_smi()

# CREATE_NO_WINDOW damit kein Konsolenfenster aufblitzt
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def query_gpu():
    """Liefert dict mit den GPU-Werten oder None bei Fehler."""
    query = ("name,utilization.gpu,memory.used,memory.total,"
             "temperature.gpu,power.draw,fan.speed,clocks.gr")
    try:
        out = subprocess.run(
            [NVIDIA_SMI, f"--id={GPU_INDEX}",
             f"--query-gpu={query}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]

        def num(x):
            try:
                return float(x)
            except ValueError:
                return None

        return {
            "name":  parts[0],
            "util":  num(parts[1]),
            "vram":  num(parts[2]),
            "vramtot": num(parts[3]),
            "temp":  num(parts[4]),
            "power": num(parts[5]) if len(parts) > 5 else None,
            "fan":   num(parts[6]) if len(parts) > 6 else None,
            "clock": num(parts[7]) if len(parts) > 7 else None,
        }
    except Exception:
        return None


def query_llm():
    """Fragt Ollama ab, welches Modell aktuell im (GPU-)Speicher liegt.
    Liefert dict {name, size_vram, on_gpu} des groessten geladenen Modells
    oder None wenn nichts geladen / Ollama nicht erreichbar ist."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps",
                                    timeout=1.5) as r:
            data = _json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    models = data.get("models") or []
    if not models:
        return None
    # groesstes Modell (nach VRAM) waehlen, falls mehrere geladen sind
    m = max(models, key=lambda x: x.get("size_vram", 0) or 0)
    total = m.get("size", 0) or 0
    vram = m.get("size_vram", 0) or 0
    on_gpu = vram > 0
    # Anteil der auf GPU liegt (Ollama kann teilweise auf CPU auslagern)
    gpu_frac = (vram / total) if total else 0
    # Restzeit bis zum Entladen (expires_at) in Sekunden berechnen
    ttl = None
    exp = m.get("expires_at")
    if exp:
        try:
            from datetime import datetime, timezone
            # ISO-Format, evtl. mit Nanosekunden -> auf 6 Stellen kuerzen
            s = exp.strip()
            if "." in s:
                head, _, tail = s.partition(".")
                # Zeitzonen-Suffix abtrennen
                tz = ""
                for i, ch in enumerate(tail):
                    if ch in "+-Zz":
                        tz = tail[i:]
                        tail = tail[:i]
                        break
                tail = (tail + "000000")[:6]
                s = f"{head}.{tail}{tz}"
            s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ttl = (dt - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            ttl = None
    return {
        "name": m.get("name", "?"),
        "size_vram": vram,
        "gpu_frac": gpu_frac,
        "on_gpu": on_gpu,
        "ttl": ttl,
    }


def unload_llm(model):
    """Entlaedt das angegebene Ollama-Modell sofort aus dem Speicher
    (keep_alive=0). Liefert True bei Erfolg."""
    import json as _json
    import urllib.request
    if not model:
        return False
    try:
        body = _json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body, headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return True
    except Exception:
        return False


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


class GpuGadget:
    def __init__(self):
        self.cfg = load_config()
        self.detailed = self.cfg.get("detailed", True)
        self.always_on_top = self.cfg.get("always_on_top", True)

        self.root = tk.Tk()
        self.root.title("GPU Gadget")
        self.root.overrideredirect(True)          # randlos
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", self.always_on_top)
        try:
            self.root.attributes("-alpha", 0.92)  # leicht transparent
        except Exception:
            pass

        # Fonts
        self.f_title = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self.f_big   = tkfont.Font(family="Consolas", size=15, weight="bold")
        self.f_lbl   = tkfont.Font(family="Segoe UI", size=8)
        self.f_val   = tkfont.Font(family="Consolas", size=10, weight="bold")

        self._drag = {"x": 0, "y": 0}
        self.current_model = None      # aktuell geladenes LLM (fuer Unload)
        self._unload_pending = False   # laeuft gerade ein Unload?
        self._build_ui()
        self._bind_events()
        self._restore_position()
        self.update_loop()

    # ---------- UI ----------
    def _build_ui(self):
        pad = 10
        self.frame = tk.Frame(self.root, bg=BG, padx=pad, pady=pad,
                              highlightthickness=1,
                              highlightbackground="#2a2f3a")
        self.frame.pack(fill="both", expand=True)

        self.lbl_name = tk.Label(self.frame, text="NVIDIA GPU", bg=BG,
                                 fg=ACCENT, font=self.f_title, anchor="w")
        self.lbl_name.pack(fill="x")

        # Auslastung (grosse Zahl)
        row_util = tk.Frame(self.frame, bg=BG)
        row_util.pack(fill="x", pady=(4, 0))
        tk.Label(row_util, text="Load", bg=BG, fg=MUTED,
                 font=self.f_lbl).pack(side="left")
        self.lbl_util = tk.Label(row_util, text="--%", bg=BG, fg=FG,
                                 font=self.f_big)
        self.lbl_util.pack(side="right")
        self.bar_util = self._make_bar()

        # VRAM
        row_vram = tk.Frame(self.frame, bg=BG)
        row_vram.pack(fill="x", pady=(6, 0))
        tk.Label(row_vram, text="VRAM", bg=BG, fg=MUTED,
                 font=self.f_lbl).pack(side="left")
        self.lbl_vram = tk.Label(row_vram, text="-- / -- MB", bg=BG, fg=FG,
                                 font=self.f_val)
        self.lbl_vram.pack(side="right")
        self.bar_vram = self._make_bar()

        # LLM-Anzeige (welches Modell liegt gerade im GPU-VRAM) - unter VRAM
        row_llm = tk.Frame(self.frame, bg=BG)
        row_llm.pack(fill="x", pady=(6, 0))
        tk.Label(row_llm, text="LLM", bg=BG, fg=MUTED,
                 font=self.f_lbl).pack(side="left")
        self.lbl_llm = tk.Label(row_llm, text="--", bg=BG, fg=FG,
                                font=self.f_val, anchor="e")
        self.lbl_llm.pack(side="right")

        # Entlade-Timer (Countdown bis Ollama das Modell aus dem VRAM wirft)
        row_ttl = tk.Frame(self.frame, bg=BG)
        row_ttl.pack(fill="x", pady=(2, 0))
        tk.Label(row_ttl, text="Unload in", bg=BG, fg=MUTED,
                 font=self.f_lbl).pack(side="left")
        self.lbl_ttl = tk.Label(row_ttl, text="--", bg=BG, fg=MUTED,
                                font=self.f_val, anchor="e")
        self.lbl_ttl.pack(side="right")
        self.row_ttl = row_ttl

        # Unload-Button (LLM sofort aus dem VRAM werfen)
        self.btn_unload = tk.Button(
            self.frame, text="Unload LLM", command=self._unload_now,
            bg="#2a2f3a", fg=FG, activebackground=HOT,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=self.f_lbl, cursor="hand2", state="disabled",
            disabledforeground=MUTED, padx=6, pady=3)
        self.btn_unload.pack(fill="x", pady=(5, 0))

        # Temperatur
        row_temp = tk.Frame(self.frame, bg=BG)
        row_temp.pack(fill="x", pady=(6, 0))
        tk.Label(row_temp, text="Temp", bg=BG, fg=MUTED,
                 font=self.f_lbl).pack(side="left")
        self.lbl_temp = tk.Label(row_temp, text="--C", bg=BG, fg=FG,
                                 font=self.f_val)
        self.lbl_temp.pack(side="right")
        self.bar_temp = self._make_bar()

        # Detail-Zeile (Power / Takt / Luefter)
        self.detail_frame = tk.Frame(self.frame, bg=BG)
        self.lbl_detail = tk.Label(self.detail_frame, text="", bg=BG,
                                   fg=MUTED, font=self.f_lbl, justify="left",
                                   anchor="w")
        self.lbl_detail.pack(fill="x")

        self._apply_view()

    def _make_bar(self, height=6):
        c = tk.Canvas(self.frame, height=height, bg=BAR_BG,
                      highlightthickness=0, bd=0)
        c.pack(fill="x", pady=(2, 0))
        c._rect = c.create_rectangle(0, 0, 0, height, fill=ACCENT, width=0)
        return c

    def _set_bar(self, canvas, frac, color):
        frac = max(0.0, min(1.0, frac))
        w = canvas.winfo_width() or 160
        h = int(canvas["height"])
        canvas.coords(canvas._rect, 0, 0, int(w * frac), h)
        canvas.itemconfig(canvas._rect, fill=color)

    def _apply_view(self):
        if self.detailed:
            self.detail_frame.pack(fill="x", pady=(6, 0))
        else:
            self.detail_frame.pack_forget()
        self.root.update_idletasks()

    # ---------- Events ----------
    def _bind_events(self):
        for w in (self.root, self.frame, self.lbl_name):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Double-Button-1>", self._toggle_view)
            w.bind("<Button-3>", self._show_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Toggle view", command=self._toggle_view)
        # Invertierte Logik: Haken gesetzt = darf ueberlagert werden,
        # Haken weg = permanent im Vordergrund.
        self.overlay_var = tk.BooleanVar(value=not self.always_on_top)
        self.menu.add_checkbutton(label="Allow overlap",
                                  variable=self.overlay_var,
                                  command=self._toggle_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self._quit)

    def _start_drag(self, e):
        self._drag["x"] = e.x_root - self.root.winfo_x()
        self._drag["y"] = e.y_root - self.root.winfo_y()

    def _on_drag(self, e):
        x = e.x_root - self._drag["x"]
        y = e.y_root - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e):
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        save_config(self.cfg)

    def _toggle_view(self, e=None):
        self.detailed = not self.detailed
        self.cfg["detailed"] = self.detailed
        save_config(self.cfg)
        self._apply_view()

    def _toggle_topmost(self):
        # overlay_var True  -> Ueberlagern erlaubt -> NICHT topmost
        # overlay_var False -> permanent im Vordergrund -> topmost
        self.always_on_top = not self.overlay_var.get()
        self.root.attributes("-topmost", self.always_on_top)
        self.cfg["always_on_top"] = self.always_on_top
        save_config(self.cfg)

    def _show_menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _quit(self):
        save_config(self.cfg)
        self.root.destroy()

    def _unload_now(self):
        """Entlaedt das aktuell geladene Modell sofort (im Hintergrund-Thread,
        damit die UI nicht blockiert)."""
        model = self.current_model
        if not model or self._unload_pending:
            return
        import threading
        self._unload_pending = True
        self.btn_unload.config(text="unloading\u2026", state="disabled")

        def worker():
            ok = unload_llm(model)
            # UI-Update zurueck in den Tk-Thread schieben
            self.root.after(0, lambda: self._unload_done(ok))

        threading.Thread(target=worker, daemon=True).start()

    def _unload_done(self, ok):
        self._unload_pending = False
        if not ok:
            self.btn_unload.config(text="Failed \u2013 retry?", state="normal")
        # bei Erfolg setzt update_loop den Button automatisch zurueck

    def _restore_position(self):
        self.root.update_idletasks()
        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            sw = self.root.winfo_screenwidth()
            x, y = sw - 220, 40      # oben rechts
        self.root.geometry(f"+{int(x)}+{int(y)}")

    # ---------- Update ----------
    @staticmethod
    def _temp_color(t):
        if t is None:
            return FG
        if t >= 83:
            return HOT
        if t >= 70:
            return WARN
        return ACCENT

    @staticmethod
    def _fmt_ttl(sec):
        sec = int(round(sec))
        if sec >= 3600:
            h, rem = divmod(sec, 3600)
            mm = rem // 60
            return f"{h}h {mm:02d}m"
        mm, ss = divmod(sec, 60)
        return f"{mm}:{ss:02d}"

    @staticmethod
    def _util_color(u):
        if u is None:
            return FG
        if u >= 90:
            return WARN
        return ACCENT

    def update_loop(self):
        d = query_gpu()
        if d is None:
            self.lbl_name.config(text="nvidia-smi not found", fg=HOT)
            self.lbl_util.config(text="--")
        else:
            self.lbl_name.config(text=d["name"] or "NVIDIA GPU", fg=ACCENT)

            util = d["util"]
            if util is not None:
                self.lbl_util.config(text=f"{util:.0f}%",
                                     fg=self._util_color(util))
                self._set_bar(self.bar_util, util / 100.0,
                              self._util_color(util))

            vram, vramtot = d["vram"], d["vramtot"]
            if vram is not None and vramtot:
                self.lbl_vram.config(
                    text=f"{vram:.0f} / {vramtot:.0f} MB "
                         f"({vram/vramtot*100:.0f}%)")
                frac = vram / vramtot
                col = WARN if frac >= 0.9 else ACCENT
                self._set_bar(self.bar_vram, frac, col)

            # LLM-Modell (Ollama)
            llm = query_llm()
            if llm is None:
                self.lbl_llm.config(text="no model", fg=MUTED)
                self.lbl_ttl.config(text="--", fg=MUTED)
                self.current_model = None
                if not self._unload_pending:
                    self.btn_unload.config(text="Unload LLM",
                                           state="disabled")
            else:
                self.current_model = llm["name"]
                if not self._unload_pending:
                    self.btn_unload.config(text="Unload LLM", state="normal")
                gb = llm["size_vram"] / (1024 ** 3)
                name = llm["name"]
                if len(name) > 22:
                    name = name[:21] + "\u2026"
                if llm["gpu_frac"] >= 0.99:
                    txt = f"{name}  {gb:.1f}G"
                    col = ACCENT
                else:
                    # teilweise auf CPU ausgelagert
                    txt = f"{name}  {gb:.1f}G ({llm['gpu_frac']*100:.0f}% GPU)"
                    col = WARN
                self.lbl_llm.config(text=txt, fg=col)

                # Entlade-Timer
                ttl = llm.get("ttl")
                if ttl is None:
                    self.lbl_ttl.config(text="?", fg=MUTED)
                elif ttl > 3.15e7:      # > ~1 Jahr = "keep_alive=-1" (dauerhaft)
                    self.lbl_ttl.config(text="never (pinned)", fg=ACCENT)
                elif ttl <= 0:
                    self.lbl_ttl.config(text="now", fg=HOT)
                else:
                    self.lbl_ttl.config(text=self._fmt_ttl(ttl),
                                        fg=(HOT if ttl < 30 else
                                            WARN if ttl < 60 else FG))

            temp = d["temp"]
            if temp is not None:
                self.lbl_temp.config(text=f"{temp:.0f} C",
                                     fg=self._temp_color(temp))
                self._set_bar(self.bar_temp, temp / 100.0,
                              self._temp_color(temp))

            if self.detailed:
                bits = []
                if d["power"] is not None:
                    bits.append(f"Power  {d['power']:.0f} W")
                if d["clock"] is not None:
                    bits.append(f"Clock  {d['clock']:.0f} MHz")
                if d["fan"] is not None:
                    bits.append(f"Fan    {d['fan']:.0f} %")
                self.lbl_detail.config(text="\n".join(bits))

        self.root.after(REFRESH_MS, self.update_loop)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Optionaler Startverzoegerung, z.B. beim Autostart: --delay 15
    delay = 0
    if "--delay" in sys.argv:
        try:
            delay = float(sys.argv[sys.argv.index("--delay") + 1])
        except (IndexError, ValueError):
            delay = 0
    if delay > 0:
        import time
        time.sleep(delay)
    try:
        GpuGadget().run()
    except KeyboardInterrupt:
        sys.exit(0)
