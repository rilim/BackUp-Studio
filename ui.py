"""Native desktop interface. All Tk calls stay on the main thread."""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

from config import APP_NAME, APP_VERSION, Settings, save_settings, state_directory
from i18n import translate
from path_utils import display_path, display_text, display_data
from file_icons import FileIcons
from file_ops import (BackupError, Cancelled, action_label, compare, eligible, execute,
                      recommended, versions_root, SYSTEM_EXCLUSIONS)
from retention import (CONTENT_LABELS, archive_root, find_unique_files, list_archive_runs, plan_for_settings,
                       prune, rules_enabled)
from utils import (HISTORY_LABELS, MODE_LABELS, STATUS_LABELS, export_csv, format_date, format_size as _format_size,
                   normalize_exclusion, open_folder)

BG = "#F3F6F8"
WHITE = "#FFFFFF"
INK = "#182F39"
MUTED = "#6B7F88"
LINE = "#DDE5E9"
TEAL = "#117D71"
TEAL_LIGHT = "#E8F5F1"
NAV = "#132E35"
NAV_ACTIVE = "#29464E"
AMBER = "#9C6821"
RED = "#AF4146"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
ON_ACCENT = "#FFFFFF"
NAV_TEXT = "#FFFFFF"
ENTRY_BG = WHITE
HEADING_BG = "#F6F8FA"
SELECT_BG = "#E8F2F5"
HOVER_BG = "#EDF2F5"
DETAIL_BG = "#F7F9FA"
STATUS_BLUE = "#566992"
BUTTON_HOVER = "#0C695F"
DISABLED_BG = "#E7ECEF"
DISABLED_FG = "#586870"
DISABLED_BORDER = "#BCC8CE"
_language = "lt"
# Screen scale: 1.0 at 100 % Windows scaling (96 DPI), 1.25 at 125 %, 1.5 at 150 % ...
# Fonts are given in points and scale by themselves; pixel sizes go through S().
SCALE = 1.0


def detect_scale(root):
    try:
        return max(1.0, min(3.0, float(root.winfo_fpixels("1i")) / 96.0))
    except (tk.TclError, ValueError):
        return 1.0


def S(value):
    """A design size in pixels (at 100 %) converted for the current screen scale."""
    return int(round(value * SCALE))


def fit_window(window, width, height, min_width, min_height):
    """Size a window by design pixels, scaled, but never larger than the screen."""
    screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    min_w, min_h = min(S(min_width), screen_w - S(40)), min(S(min_height), screen_h - S(90))
    w = max(min_w, min(S(width), screen_w - S(60)))
    h = max(min_h, min(S(height), screen_h - S(90)))
    window.geometry(f"{w}x{h}")
    window.minsize(min_w, min_h)
    return w, h


def T(value):
    return display_text(translate(value, _language))


def format_size(size):
    rendered = _format_size(size)
    return rendered.replace(",", ".") if _language == "en" else rendered


def set_appearance(language, theme):
    global _language, BG, WHITE, INK, MUTED, LINE, TEAL, TEAL_LIGHT, NAV, NAV_ACTIVE
    global AMBER, RED, ON_ACCENT, NAV_TEXT, ENTRY_BG, HEADING_BG, SELECT_BG, HOVER_BG
    global DETAIL_BG, STATUS_BLUE, BUTTON_HOVER
    global DISABLED_BG, DISABLED_FG, DISABLED_BORDER
    _language = language
    if theme == "dark":
        BG, WHITE, INK, MUTED, LINE = "#111F26", "#1B2B33", "#E8F2F4", "#A8BFC7", "#38505B"
        TEAL, TEAL_LIGHT, NAV, NAV_ACTIVE = "#5AD4C1", "#21443F", "#0C171D", "#29434D"
        AMBER, RED = "#F4C075", "#FA9398"
        ON_ACCENT, NAV_TEXT = "#09251F", "#E8F2F4"
        ENTRY_BG, HEADING_BG, SELECT_BG, HOVER_BG = "#233740", "#263A44", "#31565A", "#30454F"
        DETAIL_BG, STATUS_BLUE, BUTTON_HOVER = "#21343D", "#A6C2F4", "#74E2D0"
        DISABLED_BG, DISABLED_FG, DISABLED_BORDER = "#2A3B45", "#B4C2CA", "#50636E"
    else:
        BG, WHITE, INK, MUTED, LINE = "#F3F6F8", "#FFFFFF", "#182F39", "#6B7F88", "#DDE5E9"
        TEAL, TEAL_LIGHT, NAV, NAV_ACTIVE = "#117D71", "#E8F5F1", "#132E35", "#29464E"
        AMBER, RED = "#9C6821", "#AF4146"
        ON_ACCENT, NAV_TEXT = "#FFFFFF", "#FFFFFF"
        ENTRY_BG, HEADING_BG, SELECT_BG, HOVER_BG = WHITE, "#F6F8FA", "#E8F2F5", "#EDF2F5"
        DETAIL_BG, STATUS_BLUE, BUTTON_HOVER = "#F7F9FA", "#566992", "#0C695F"
        DISABLED_BG, DISABLED_FG, DISABLED_BORDER = "#E7ECEF", "#586870", "#BCC8CE"


class UiTextVar(tk.StringVar):
    """Translate messages when they are presented, without changing file paths or filter keys."""
    def set(self, value):
        super().set(T(value))


class PathTextVar(tk.StringVar):
    """Keep path entries readable, including paths pasted into the Tk widget."""
    def __init__(self, *args, **kwargs):
        if "value" in kwargs:
            kwargs["value"] = display_path(kwargs["value"])
        super().__init__(*args, **kwargs)
        self.trace_add("write", self._display_path)

    def _display_path(self, *args):
        value = self.get()
        cleaned = display_path(value)
        if cleaned != value:
            self.set(cleaned)


def label(parent, text="", size=10, color=None, bold=False, bg=None, **kwargs):
    return tk.Label(parent, text=T(text), bg=bg or parent.cget("bg"), fg=color or INK,
                    font=(FONT, size, "bold" if bold else "normal"), **kwargs)


class ThemedButton(tk.Button):
    """Classic Tk has no disabled background option; keep both states explicit."""
    _style_keys = ("background", "foreground", "activebackground", "activeforeground",
                   "cursor", "highlightbackground", "highlightcolor")

    def __init__(self, parent, preserve_disabled_colors=False, **kwargs):
        super().__init__(parent, **kwargs)
        self._preserve_disabled_colors = preserve_disabled_colors
        self._enabled_style = {key: self.cget(key) for key in self._style_keys}
        self._disabled_style = dict(background=DISABLED_BG, foreground=DISABLED_FG,
                                    activebackground=DISABLED_BG, activeforeground=DISABLED_FG,
                                    disabledforeground=DISABLED_FG, cursor="arrow",
                                    highlightbackground=DISABLED_BORDER, highlightcolor=DISABLED_BORDER)
        self._refresh_style()

    def _refresh_style(self):
        style = self._disabled_style if str(self.cget("state")) == "disabled" else self._enabled_style
        if self._preserve_disabled_colors and str(self.cget("state")) == "disabled":
            style = {**self._enabled_style, "disabledforeground": self._enabled_style["foreground"], "cursor": "arrow"}
        super().configure(**style)

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, str) or (cnf is None and not kwargs):
            return super().configure(cnf, **kwargs)
        options = dict(cnf or {})
        options.update(kwargs)
        result = super().configure(**options)
        for key, value in options.items():
            key = {"bg": "background", "fg": "foreground"}.get(key, key)
            if key in self._style_keys:
                self._enabled_style[key] = value
        self._refresh_style()
        return result

    config = configure


def button(parent, text, command, primary=False, danger=False, **kwargs):
    color = RED if danger else TEAL
    return ThemedButton(parent, text=T(text), command=command, bg=color if primary else WHITE,
                     fg=ON_ACCENT if primary else INK, activebackground=BUTTON_HOVER if primary else HOVER_BG,
                     activeforeground=ON_ACCENT if primary else INK, disabledforeground=DISABLED_FG,
                     relief="flat", bd=0, highlightthickness=1, cursor="hand2",
                     highlightbackground=color if primary else WHITE, highlightcolor=TEAL,
                     padx=15, pady=9, font=(FONT, 10, "bold"), **kwargs)


def card(parent, **kwargs):
    return tk.Frame(parent, bg=WHITE, highlightbackground=LINE, highlightthickness=1, **kwargs)


class SlimProgress(tk.Canvas):
    """A thin progress indicator with consistent sizing across Tk themes."""
    def __init__(self, parent):
        super().__init__(parent, height=5, bg=LINE, highlightthickness=0, bd=0)
        self.mode = "determinate"
        self.value = 0
        self.offset = 0
        self.timer = None
        self.bind("<Configure>", lambda event: self.draw())

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {})
        options.update(kwargs)
        self.mode = options.pop("mode", getattr(self, "mode", "determinate"))
        self.value = options.pop("value", getattr(self, "value", 0))
        if options:
            super().configure(**options)
        if hasattr(self, "offset"):
            self.draw()

    config = configure

    def draw(self):
        self.delete("all")
        width = self.winfo_width()
        if self.mode == "indeterminate":
            left = self.offset * width
            right = min(width, left + width * .24)
        else:
            left, right = 0, width * min(100, max(0, self.value)) / 100
        self.create_rectangle(left, 0, right, self.winfo_height(), fill=TEAL, outline="")

    def start(self, interval=14):
        self.stop()
        self.offset = (self.offset + .025) % 1
        self.draw()
        self.timer = self.after(max(30, interval), lambda: self.start(interval))

    def stop(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def destroy(self):
        self.stop()
        super().destroy()


class ExclusionsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title(T("Nekopijuojami aplankai"))
        fit_window(self, 820, 640, 720, 570)
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()
        self.values = list(app.settings.exclusions)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        title = tk.Frame(self, bg=BG)
        title.grid(row=0, column=0, sticky="ew", padx=26, pady=(24, 14))
        label(title, "Ką norite praleisti?", size=20, bold=True).pack(anchor="w")
        label(title, "Šie aplankai ir visas jų turinys bus praleisti abiejose pusėse.", color=MUTED).pack(anchor="w", pady=(7, 0))
        note = label(self, "Išimtys galioja palyginimui, kopijavimui, atkūrimui ir valymui.", color=TEAL, bg=TEAL_LIGHT,
                     anchor="w", padx=15, pady=12)
        note.grid(row=1, column=0, sticky="ew", padx=26, pady=(0, 12))
        panel = card(self)
        panel.grid(row=2, column=0, sticky="nsew", padx=26)
        label(panel, "APLANKAI ŠALTINIO VIDUJE", size=9, color=MUTED, bold=True).pack(anchor="w", padx=14, pady=12)
        search = tk.Frame(panel, bg=WHITE)
        search.pack(fill="x", padx=14, pady=(0, 10))
        label(search, "Ieškoti išimčių").pack(side="left", padx=(0, 10))
        self.search_value = tk.StringVar()
        ttk.Entry(search, textvariable=self.search_value).pack(side="left", fill="x", expand=True)
        listing = tk.Frame(panel, bg=WHITE)
        listing.pack(fill="both", expand=True, padx=14)
        listing.rowconfigure(0, weight=1)
        listing.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(listing, font=(FONT, 11), bg=WHITE, fg=INK, bd=0, highlightthickness=0,
                                  selectbackground=TEAL_LIGHT, selectforeground=TEAL, activestyle="none", selectmode="extended")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(listing, orient="vertical", command=self.listbox.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(listing, orient="horizontal", command=self.listbox.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.listbox.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.count_label = label(panel, size=9, color=MUTED, anchor="w")
        self.count_label.pack(fill="x", padx=14, pady=8)
        if os.name == "nt":
            label(panel, T("Automatiškai praleidžiama: ") + ", ".join(SYSTEM_EXCLUSIONS),
                  size=9, color=MUTED, anchor="w").pack(fill="x", padx=14, pady=(0, 8))
        self.search_value.trace_add("write", lambda *args: self.refresh())
        self.listbox.bind("<<ListboxSelect>>", lambda event: self.update_count())
        self.refresh()
        editor = tk.Frame(self, bg=BG)
        editor.grid(row=3, column=0, sticky="ew", padx=26, pady=12)
        self.entry_value = PathTextVar()
        entry = ttk.Entry(editor, textvariable=self.entry_value, font=(FONT, 10))
        entry.pack(side="left", fill="x", expand=True, ipady=7)
        entry.bind("<Return>", lambda event: self.add_typed())
        button(editor, "Pridėti kelią", self.add_typed).pack(side="left", padx=(8, 0))
        tools = tk.Frame(self, bg=BG)
        tools.grid(row=4, column=0, sticky="ew", padx=26)
        button(tools, "+ Pasirinkti aplanką…", self.browse).pack(side="left")
        button(tools, "Pašalinti pažymėtus", self.remove).pack(side="left", padx=8)
        label(self, "Pavyzdys: Dokumentai/Laikina. Galima įklijuoti ir pilną šaltinio poaplankio kelią.",
              size=9, color=MUTED, anchor="w").grid(row=5, column=0, sticky="ew", padx=26, pady=(10, 4))
        footer = tk.Frame(self, bg=BG)
        footer.grid(row=6, column=0, sticky="ew", padx=26, pady=(10, 24))
        button(footer, "Taikyti išimtis", self.apply, primary=True).pack(side="right")
        button(footer, "Atšaukti", self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda event: self.destroy())

    def refresh(self):
        selected = {self.visible_values[i] for i in self.listbox.curselection()}
        query = self.search_value.get().casefold()
        self.visible_values = [item for item in self.values if query in item.casefold()]
        self.listbox.delete(0, "end")
        for index, item in enumerate(self.visible_values):
            self.listbox.insert("end", display_path(item))
            if item in selected:
                self.listbox.selection_set(index)
        self.update_count()

    def update_count(self):
        self.count_label.configure(text=T(f"Išimčių: {len(self.values)}  ·  Rodoma: {len(self.visible_values)}"
                                         f"  ·  Pažymėta: {len(self.listbox.curselection())}"))

    def add(self, text):
        try:
            item = normalize_exclusion(text, self.app.source_var.get())
            if item not in self.values:
                self.values.append(item)
                self.values.sort(key=str.casefold)
                self.refresh()
            self.entry_value.set("")
        except ValueError as error:
            messagebox.showerror(T("Netinkama išimtis"), T(str(error)), parent=self)

    def add_typed(self):
        self.add(self.entry_value.get())

    def browse(self):
        root = Path(self.app.source_var.get()).expanduser()
        if not root.is_dir():
            messagebox.showinfo(T("Pasirinkite šaltinį"), T("Pirmiausia pagrindiniame lange pasirinkite esantį šaltinio aplanką.\nKelio išimtį taip pat galite įvesti ranka."), parent=self)
            return
        chosen = filedialog.askdirectory(title=T("Pasirinkite nekopijuojamą šaltinio poaplankį"), initialdir=root, parent=self)
        if chosen:
            self.add(chosen)

    def remove(self):
        selected = {self.visible_values[index] for index in self.listbox.curselection()}
        self.values = [item for item in self.values if item not in selected]
        self.refresh()

    def apply(self):
        self.app.settings.exclusions = self.values
        self.app.invalidate("Išimtys pakeistos. Patikrinkite skirtumus iš naujo.")
        self.app.persist_settings()
        self.app.refresh_exclusion_label()
        self.destroy()


class PruneDialog(tk.Toplevel):
    """Review and delete old version-archive runs. Nothing is removed without a click."""
    MAX_LISTED_FILES = 2000

    def __init__(self, app, root_path, prompt=False):
        super().__init__(app.root)
        self.app = app
        self.archive = root_path
        self.settings = app.current_settings()
        self.prompt = prompt
        self.plan = []
        self.items = {}
        self.warnings = []
        self.unique = None  # run id -> [(relative, size)] once checked; None while unknown
        self.found = {}  # (run id, relative) -> where an identical copy was found
        self.checking = False
        self.selected_run = None
        self.auto_selected = None  # Row chosen by the dialog itself; a user's own choice is never overridden.
        self.result_text = ""  # Outcome of the last deletion, kept visible while the list refreshes.
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.close_requested = False
        self.withdraw()
        self.title(T("Senų versijų valymas"))
        fit_window(self, 1240, 980, 860, 600)
        self.configure(bg=BG)
        self.transient(app.root)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(20, 8))
        self.heading = label(header, "Versijų archyvas viršija nustatytas ribas" if prompt else "Senų versijų valymas",
                             size=19, bold=True)
        self.heading.pack(anchor="w")
        label(header, T("Archyvas: ") + display_path(root_path), color=MUTED, anchor="w",
              justify="left", wraplength=1100).pack(anchor="w", pady=(6, 0))
        label(header, self.rules_text(), color=MUTED, anchor="w").pack(anchor="w", pady=(2, 0))
        note = label(self, "Trinamos tik visos operacijos, kurias sukūrė ši programa. Naujausia ir nebaigtos operacijos "
                     "niekada netrinamos. Kiti archyvo aplankai neliečiami. Pažymėkite operaciją, kad pamatytumėte jos turinį.",
                     color=TEAL, bg=TEAL_LIGHT, anchor="w", justify="left", padx=15, pady=9, wraplength=1100)
        note.grid(row=1, column=0, sticky="ew", padx=26, pady=(0, 8))

        panel = card(self)
        panel.grid(row=2, column=0, sticky="nsew", padx=26)
        panel.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)
        columns = (("date", "PRADĖTA", S(140)), ("mode", "VEIKSMAS", S(160)), ("folder", "APLANKAS", S(230)),
                   ("files", "FAILŲ", S(70)), ("size", "DYDIS", S(90)), ("plan", "PLANAS", S(380)))
        self.tree = ttk.Treeview(panel, columns=[key for key, _, _ in columns], show="headings", selectmode="browse")
        for key, title, width in columns:
            self.tree.heading(key, text=T(title), anchor="w")
            self.tree.column(key, width=width, anchor="e" if key in ("files", "size") else "w",
                             stretch=key == "plan")
        self.tree.tag_configure("delete", foreground=RED)
        self.tree.tag_configure("protected", foreground=MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.show_selected())

        details = card(self)
        details.grid(row=3, column=0, sticky="nsew", padx=26, pady=(8, 0))
        details.rowconfigure(2, weight=1)
        details.columnconfigure(0, weight=1)
        title_row = tk.Frame(details, bg=WHITE)
        title_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 0))
        self.detail_title = label(title_row, "OPERACIJOS TURINYS", size=9, color=MUTED, bold=True, anchor="w")
        self.detail_title.pack(side="left")
        self.open_button = button(title_row, "Atverti aplanką", self.open_selected)
        self.open_button.configure(pady=4, padx=8, font=(FONT, 9), state="disabled")
        self.open_button.pack(side="right")
        self.detail_info = label(details, "Pažymėkite operaciją viršutinėje lentelėje.", size=9, color=MUTED,
                                 anchor="w", justify="left", wraplength=1100)
        self.detail_info.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 6))
        self.files = ttk.Treeview(details, columns=("path", "size", "where"), show="headings", selectmode="browse")
        for key, title, width in (("path", "FAILAS", S(520)), ("size", "DYDIS", S(90)), ("where", "KUR DAR YRA?", S(420))):
            self.files.heading(key, text=T(title), anchor="w")
            # Fixed widths (widened to the longest path) + a horizontal scrollbar: long paths are never cut off.
            self.files.column(key, width=width, minwidth=S(60), anchor="e" if key == "size" else "w", stretch=False)
        self.files.tag_configure("unique", foreground=RED)
        self.files.tag_configure("elsewhere", foreground=MUTED)
        self.files.grid(row=2, column=0, sticky="nsew", padx=(14, 0))
        file_scroll = ttk.Scrollbar(details, orient="vertical", command=self.files.yview)
        file_scroll.grid(row=2, column=1, sticky="ns", padx=(0, 14))
        file_xscroll = ttk.Scrollbar(details, orient="horizontal", command=self.files.xview)
        file_xscroll.grid(row=3, column=0, sticky="ew", padx=(14, 0))
        self.files.configure(yscrollcommand=file_scroll.set, xscrollcommand=file_xscroll.set)
        self.files.bind("<<TreeviewSelect>>", lambda event: self.show_file_detail())
        self.file_rows = {}
        self.file_detail = label(details, "Pažymėkite failą, kad pamatytumėte visą jo kelią.", size=9, color=MUTED,
                                 anchor="w", justify="left", wraplength=S(1100))
        self.file_detail.grid(row=4, column=0, columnspan=2, sticky="ew", padx=14, pady=(6, 10))

        self.summary = label(self, "Skaičiuojamas archyvo dydis…", bold=True, anchor="w")
        self.summary.grid(row=4, column=0, sticky="ew", padx=26, pady=(10, 0))
        self.warning = label(self, "", color=AMBER, anchor="w", justify="left", wraplength=1100)
        self.warning.grid(row=5, column=0, sticky="ew", padx=26, pady=(4, 0))
        footer = tk.Frame(self, bg=BG)
        footer.grid(row=6, column=0, sticky="ew", padx=26, pady=(10, 20))
        self.status = label(footer, "", size=9, color=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.delete_button = button(footer, "Ištrinti", self.confirm_delete, primary=True, danger=True)
        self.delete_button.configure(state="disabled")
        self.delete_button.pack(side="right")
        self.close_button = button(footer, "Ne dabar" if prompt else "Uždaryti", self.request_close)
        self.close_button.pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.request_close)
        self.bind("<Escape>", lambda event: self.request_close())
        if not prompt:
            self.reveal()
        self.start_listing()
        self.poll_id = self.after(100, self.poll)

    def rules_text(self):
        parts = []
        if self.settings.keep_runs:
            parts.append(T("visada paliekamos paskutinės ") + str(self.settings.keep_runs))
        if self.settings.keep_days:
            parts.append(T("ne senesnės nei ") + f"{self.settings.keep_days} " + T("d."))
        if self.settings.max_versions_gb:
            parts.append(T("iki ") + f"{self.settings.max_versions_gb} GB")
        if not parts:
            return T("Taisyklės nenustatytos – nieko nesiūloma trinti. Nustatykite jas skiltyje „Nustatymai“.")
        return T("Taisyklės: ") + " · ".join(parts)

    def reveal(self):
        self.prompt = False
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()

    def set_status(self, text=""):
        self.status.configure(text="  ·  ".join(part for part in (self.result_text, text) if part))

    def doomed(self):
        return [item for item in self.plan if item.action == "delete"]

    def start_listing(self):
        self.delete_button.configure(state="disabled")
        self.summary.configure(text=T("Skaičiuojamas archyvo dydis…"), fg=INK)
        self.unique = None
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        settings = self.settings

        def job():
            try:
                runs, warnings = list_archive_runs(self.archive, cancel)
                plan = plan_for_settings(settings, runs)
                self.events.put(("plan", (plan, warnings)))
                cleanup_runs = [item.run for item in plan if item.action == "delete" and item.run.mode == "cleanup"]
                if cleanup_runs:
                    roots = [value for value in (settings.source, settings.destination) if value.strip()]
                    try:
                        found = {}
                        result = find_unique_files(cleanup_runs, roots, cancel,
                                                   lambda done, total: self.events.put(("progress", (done, total))), found)
                        self.events.put(("unique", (result, found)))
                    except Cancelled:
                        raise
                    except Exception as error:
                        self.events.put(("unique_failed", str(error)))
            except Cancelled:
                self.events.put(("cancelled", None))
            except Exception as error:
                self.events.put(("error", str(error)))
        self.worker = threading.Thread(target=job, name="archive-inspection", daemon=True)
        self.worker.start()

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def poll(self):
        progress = None
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "plan":
                if not self.show_plan(*value):
                    return
            elif kind == "progress":
                progress = value
            elif kind == "unique":
                self.show_unique(*value)
            elif kind == "unique_failed":
                self.checking = False
                self.unique = None
                self.set_status(T("Nepavyko patikrinti, ar failai yra kitur: ") + T(value))
                self.update_warning()
                self.update_delete_button()
            elif kind == "pruned":
                self.show_result(value)
            elif kind == "error":
                if self.prompt:
                    self.destroy_dialog()
                    return
                self.summary.configure(text=T("Archyvo patikrinti nepavyko."), fg=RED)
                self.set_status(T(value))
            elif kind == "cancelled":
                self.set_status(T("Veiksmas sustabdytas."))
        if progress and self.checking:
            self.set_status(T("Tikrinama, ar valymo archyvų failai yra kitur… ") + f"{progress[0]}/{progress[1]}")
        if self.close_requested and not self.busy():
            self.destroy_dialog()
            return
        self.poll_id = self.after(100, self.poll)

    def plan_text(self, item):
        if item.action == "keep":
            return T("Liks")
        if item.action == "protected":
            return T("Saugoma") + " – " + T(item.reason)
        text = T("Bus ištrinta") + " – " + T(item.reason)
        unique = (self.unique or {}).get(item.run.id)
        if unique:
            text += T(f"  ·  tik archyve: {len(unique)}")
        return text

    def show_plan(self, plan, warnings):
        """Returns False when the (hidden) prompt closed itself because nothing needs cleaning."""
        self.plan = plan
        doomed = self.doomed()
        if self.prompt:
            if not doomed:
                self.destroy_dialog()
                return False
            self.reveal()
        self.checking = any(item.run.mode == "cleanup" for item in doomed)
        self.tree.delete(*self.tree.get_children())
        self.items = {}
        first_doomed = None
        for item in plan:
            run = item.run
            row = self.tree.insert("", "end", tags=(item.action,), values=(
                run.started.strftime("%Y-%m-%d %H:%M"), T(HISTORY_LABELS.get(run.mode, run.mode)), run.id,
                run.files, format_size(run.size), self.plan_text(item)))
            self.items[row] = item
            if item.action == "delete" and first_doomed is None:
                first_doomed = row
        total = sum(item.run.size for item in plan)
        freed = sum(item.run.size for item in doomed)
        files = sum(item.run.files for item in doomed)
        if not plan:
            self.summary.configure(text=T("Versijų archyve operacijų nėra."), fg=INK)
        elif doomed:
            self.summary.configure(fg=RED, text=T(f"Bus ištrinta operacijų: {len(doomed)} · failų: {files} · ")
                                   + format_size(freed) + T("  (archyve iš viso: ") + format_size(total) + ")")
        else:
            self.summary.configure(fg=TEAL, text=T(f"Archyvas atitinka taisykles. Operacijų: {len(plan)} · ")
                                   + format_size(total))
        self.warnings = warnings
        self.set_status(T("Tikrinama, ar valymo archyvų failai yra kitur…") if self.checking else
                        T(f"Nepažįstami elementai palikti: {len(warnings)}") if warnings else "")
        self.update_warning()
        self.update_delete_button()
        target = first_doomed or (self.tree.get_children()[0] if self.tree.get_children() else None)
        if target:
            self.select_row(target)
        return True

    def select_row(self, row):
        self.auto_selected = row
        self.tree.selection_set(row)
        self.tree.see(row)
        self.show_selected()

    def show_unique(self, result, found=None):
        self.unique = result
        self.found = found or {}
        self.checking = False
        self.set_status(T(f"Nepažįstami elementai palikti: {len(self.warnings)}") if self.warnings else "")
        for row, item in self.items.items():
            self.tree.set(row, "plan", self.plan_text(item))
        self.update_warning()
        self.update_delete_button()
        riskiest = max(self.items, key=lambda row: len(result.get(self.items[row].run.id, [])), default=None)
        selection = self.tree.selection()
        if (riskiest and result.get(self.items[riskiest].run.id)
                and (not selection or selection[0] == self.auto_selected)):
            self.select_row(riskiest)  # Show the run whose deletion would lose the most files.
        else:
            self.show_selected()

    def update_warning(self):
        cleanup_runs = [item.run for item in self.doomed() if item.run.mode == "cleanup"]
        if not cleanup_runs:
            self.warning.configure(text="")
        elif self.checking:
            self.warning.configure(fg=AMBER, text=T(f"⚠ Kopijos valymo archyvų tarp trinamų: {len(cleanup_runs)}. ")
                                   + T("Tikrinama, ar jų failai dar yra šaltinyje arba kopijoje…"))
        elif self.unique is None:
            self.warning.configure(fg=AMBER, text=T(f"⚠ Kopijos valymo archyvų tarp trinamų: {len(cleanup_runs)}. ")
                                   + T("Šie failai jau pašalinti iš šaltinio ir kopijos – archyvas yra paskutinė jų kopija."))
        else:
            unique = [entry for run in cleanup_runs for entry in self.unique.get(run.id, [])]
            if unique:
                self.warning.configure(fg=RED, text=T(f"⚠ Failų, kurių daugiau niekur nėra: {len(unique)} (")
                                       + format_size(sum(size for _, size in unique))
                                       + T("). Ištrynus šias operacijas jie bus prarasti. Pažymėkite operaciją, kad pamatytumėte, kurie."))
            else:
                self.warning.configure(fg=TEAL, text=T("Visi trinamų valymo archyvų failai dar yra šaltinyje arba kopijoje."))

    def update_delete_button(self):
        doomed = self.doomed()
        self.delete_button.configure(text=T(f"Ištrinti operacijų: {len(doomed)}"),
                                     state="normal" if doomed and not self.checking else "disabled")

    def show_selected(self):
        selection = self.tree.selection()
        item = self.items.get(selection[0]) if selection else None
        if not item:
            return
        run = item.run
        self.selected_run = run
        self.open_button.configure(state="normal")
        self.detail_title.configure(text=T("OPERACIJOS TURINYS: ") + run.id)
        kinds = sorted({relative.split("/", 1)[0] for relative, _ in run.entries})
        when = run.started.strftime("%Y-%m-%d %H:%M:%S")
        if run.finished:
            when += "–" + run.finished.strftime("%H:%M:%S" if run.finished.date() == run.started.date() else "%Y-%m-%d %H:%M:%S")
        lines = [display_path(run.path), T("Operacija vykdyta: ") + when + "  ·  "
                 + " · ".join(T(CONTENT_LABELS.get(kind, kind)) for kind in kinds)]
        unique_entries = (self.unique or {}).get(run.id)
        checked = unique_entries is not None
        unique_set = {relative for relative, _ in unique_entries} if checked else set()
        if checked:
            lines.append(T(f"Tik archyve: {len(unique_entries)} failų (") + format_size(sum(s for _, s in unique_entries))
                         + T(f") · yra ir kitur: {len(run.entries) - len(unique_entries)}"))
        elif run.mode == "cleanup" and item.action == "delete" and self.checking:
            lines.append(T("Tikrinama, ar failai yra kitur…"))
        if run.problem:
            lines.append(T(run.problem))
        self.detail_info.configure(text="\n".join(line for line in lines if line))
        self.files.delete(*self.files.get_children())
        self.file_rows = {}
        self.file_detail.configure(text=T("Pažymėkite failą, kad pamatytumėte visą jo kelią."))
        entries = sorted(run.entries, key=lambda entry: (entry[0] not in unique_set, entry[0].casefold()))
        measure = tkfont.Font(family=FONT, size=10).measure
        widest = {"path": S(520), "where": S(420)}
        for relative, size in entries[:self.MAX_LISTED_FILES]:
            shown = relative.split("/", 1)[1] if "/" in relative else relative
            if checked:
                if relative in unique_set:
                    tag, where = "unique", T("Tik archyve")
                else:
                    tag, where = "elsewhere", self.found.get((run.id, relative), T("Yra kitur"))
            else:
                tag, where = "", ""
            row = self.files.insert("", "end", tags=(tag,), values=(shown, format_size(size), where))
            self.file_rows[row] = (relative, where)
            widest["path"] = max(widest["path"], measure(shown) + S(24))
            widest["where"] = max(widest["where"], measure(where) + S(24))
        for key, width in widest.items():
            self.files.column(key, width=min(width, S(4000)))
        self.files.xview_moveto(0)
        if len(entries) > self.MAX_LISTED_FILES:
            self.files.insert("", "end", values=(T(f"… ir dar {len(entries) - self.MAX_LISTED_FILES} failų. Visą turinį matysite atvėrę aplanką."), "", ""))

    def show_file_detail(self):
        selection = self.files.selection()
        info = self.file_rows.get(selection[0]) if selection else None
        if not info or self.selected_run is None:
            return
        relative, where = info
        lines = [T("Archyve: ") + display_path(self.selected_run.path.joinpath(*relative.split("/")))]
        if where:
            lines.append(T("Kur dar yra: ") + where)
        self.file_detail.configure(text="\n".join(lines))

    def open_selected(self):
        if self.selected_run is not None:
            self.app.open_path(display_path(self.selected_run.path))

    def confirm_delete(self):
        doomed = self.doomed()
        if not doomed or self.busy():
            return
        if self.app.busy:
            messagebox.showinfo(T("Vyksta operacija"), T("Palaukite, kol baigsis vykdoma operacija."), parent=self)
            return
        freed = format_size(sum(item.run.size for item in doomed))
        message = T(f"Negrįžtamai ištrinti senų operacijų: {len(doomed)}?") + f"\n\n{freed}\n"
        unique = [entry for item in doomed for entry in (self.unique or {}).get(item.run.id, [])]
        if unique:
            message += "\n" + T(f"Dėmesio: failų, kurių daugiau niekur nėra: {len(unique)}.") + "\n"
        message += "\n" + T("Ištrintų versijų atkurti nebus galima.")
        if not messagebox.askyesno(T("Patvirtinkite trynimą"), message, icon="warning", parent=self):
            return
        self.delete_button.configure(state="disabled")
        self.close_button.configure(text=T("Stabdyti"))
        self.set_status(T("Trinama…"))
        self.cancel_event = threading.Event()
        cancel, plan, settings = self.cancel_event, list(self.plan), self.settings

        def job():
            try:
                report = prune(self.archive, plan, settings, cancel=cancel,
                               log_directory=self.app.data_directory / "logs")
                self.events.put(("pruned", report))
            except Exception as error:
                self.events.put(("error", str(error)))
        self.worker = threading.Thread(target=job, name="archive-prune", daemon=False)
        self.worker.start()

    def show_result(self, report):
        self.close_button.configure(text=T("Uždaryti"))
        failures = [f"{item['path']}: {item['message']}" for item in report["items"] if item["status"] == "failed"]
        self.result_text = T(f"Ištrinta: {report['completed']}  ·  Klaidų: {report['failed']}  ·  "
                             f"Sustabdyta: {report['cancelled']}. Išsamiau – veiksmų istorijoje.")
        self.set_status()
        if failures:
            self.app.show_errors(failures)
        if report.get("log_error"):
            messagebox.showwarning(T("Žurnalas"), T(report["log_error"]), parent=self)
        if not self.close_requested:
            self.start_listing()

    def request_close(self):
        if self.busy():
            self.cancel_event.set()
            self.close_requested = True
            self.set_status(T("Stabdoma…"))
            return
        self.destroy_dialog()

    def destroy_dialog(self):
        try:
            self.after_cancel(self.poll_id)
        except (tk.TclError, AttributeError):
            pass
        self.cancel_event.set()
        if getattr(self.app, "prune_window", None) is self:
            self.app.prune_window = None
        self.destroy()


def checkbox_hit(tree, event):
    """Only the checkbox part of the gutter toggles; the type icon selects."""
    if tree.identify_region(event.x, event.y) != "tree" or tree.identify_column(event.x) != "#0":
        return False
    row = tree.identify_row(event.y)
    bounds = tree.bbox(row, "#0") if row else ()
    return bool(bounds and 12 <= event.x - bounds[0] < 34)


class ColumnWidths:
    """Resize exactly one column, keeping the rest fixed and scrollable.

    Native Treeview drag redistributes widths among stretchable columns. Handle
    separators before those class bindings, leaving normal row/header clicks alone.
    """
    def __init__(self, tree, saved):
        self.tree, self.saved = tree, saved
        display = tuple(tree.cget("displaycolumns"))
        self.data_columns = tuple(tree.cget("columns")) if display == ("#all",) else display
        self.has_tree = "tree" in tuple(str(part) for part in tree.cget("show"))
        self.columns = (("#0",) if self.has_tree else ()) + self.data_columns
        self.manual = bool(saved)
        self.drag = None
        for key in self.columns:
            options = {"stretch": False}
            if key in saved:
                options["width"] = max(int(tree.column(key, "minwidth")), saved[key])
            tree.column(key, **options)
        # Dot-prefixed bind tags must name an existing Tk window. Use a class
        # tag with a non-dot prefix, while retaining the widget's unique name.
        self.tag = "BackUpColumnWidths:" + str(tree)
        tree.bindtags((self.tag, *tree.bindtags()))
        for sequence, handler in (("<Button-1>", self.press), ("<Double-Button-1>", self.press),
                                  ("<B1-Motion>", self.motion), ("<ButtonRelease-1>", self.release)):
            tree.bind_class(self.tag, sequence, handler)
        tree.bind("<Configure>", self.fit, add="+")
        tree.bind("<Destroy>", self.destroy, add="+")

    def fit(self, event):
        if self.manual or self.drag or event.width <= 1:
            return
        others = sum(int(self.tree.column(key, "width")) for key in self.columns if key != "relative")
        minimum = int(self.tree.column("relative", "minwidth"))
        self.tree.column("relative", width=max(minimum, event.width - others - 2))

    def press(self, event):
        if self.tree.identify_region(event.x, event.y) != "separator":
            return
        column = self.tree.identify_column(event.x)
        if not column.startswith("#") or not column[1:].isdigit():
            return
        index = int(column[1:]) - 1
        if column == "#0" and self.has_tree:
            return "break"  # Keep the checkbox/type-icon gutter fixed.
        if not 0 <= index < len(self.data_columns):
            return
        key = self.data_columns[index]
        self.drag = (key, event.x_root, int(self.tree.column(key, "width")))
        return "break"

    def motion(self, event):
        if self.drag is None:
            return
        key, start, original = self.drag
        minimum = int(self.tree.column(key, "minwidth"))
        width = max(minimum, original + event.x_root - start)
        if width != int(self.tree.column(key, "width")):
            self.manual = True
            self.tree.column(key, width=width)
            self.saved.update({column: int(self.tree.column(column, "width")) for column in self.columns})
        return "break"

    def release(self, event):
        if self.drag is not None:
            self.motion(event)
            self.drag = None
            return "break"

    def destroy(self, event):
        if event.widget is self.tree:
            for sequence in ("<Button-1>", "<Double-Button-1>", "<B1-Motion>", "<ButtonRelease-1>"):
                self.tree.unbind_class(self.tag, sequence)


class ExpandedList:
    """A second view of the current scan, never a separate selection or operation."""
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root, bg=WHITE)
        self.window.title(f"{T('Failų sąrašas')} • {T(MODE_LABELS[app.mode])}")
        fit_window(self.window, 1200, 760, 850, 480)
        self.window.protocol("WM_DELETE_WINDOW", app.close_expanded_list)
        toolbar = tk.Frame(self.window, bg=WHITE)
        toolbar.pack(fill="x", padx=14, pady=12)
        label(toolbar, "Paieška pagal kelią", size=9).pack(side="left", padx=(0, 8))
        self.search = ttk.Entry(toolbar, textvariable=app.search_var)
        self.search.pack(side="left", fill="x", expand=True)
        ttk.Combobox(toolbar, textvariable=app.filter_display_var,
                     values=app.filter_combo.cget("values"), state="readonly", width=20).pack(side="left", padx=8)
        actions = tk.Frame(self.window, bg=WHITE)
        actions.pack(fill="x", padx=14, pady=(0, 8))
        self.controls = []
        for title, command in (("Pažymėti rodomus", app.select_visible), ("Nuimti žymas", app.clear_selection),
                               ("Eksportuoti CSV", app.export_differences)):
            widget = button(actions, title, command)
            widget.pack(side="left", padx=(0, 8))
            self.controls.append(widget)
        button(actions, "Failo informacija", self.details).pack(side="right")
        bottom = tk.Frame(self.window, bg=WHITE)
        bottom.pack(side="bottom", fill="x", padx=14, pady=10)
        self.summary = label(bottom, anchor="w", size=9, color=MUTED)
        self.summary.pack(side="left", fill="x", expand=True)
        button(bottom, "Uždaryti", app.close_expanded_list).pack(side="right")
        holder = tk.Frame(self.window, bg=WHITE)
        holder.pack(fill="both", expand=True, padx=14)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(holder, columns=app.tree.cget("columns"),
                                 displaycolumns=app.tree.cget("displaycolumns"),
                                 show="tree headings", style="Files.Treeview", selectmode="browse")
        for key in ("#0", *app.tree.cget("columns")):
            self.tree.column(key, **{option: app.tree.column(key, option)
                                     for option in ("width", "minwidth", "stretch", "anchor")})
            self.tree.heading(key, text=app.tree.heading(key, "text"), anchor=app.tree.heading(key, "anchor"),
                              command=lambda col=key: app.select_visible() if col in ("#0", "check") else app.sort_rows(col))
        for tag in ("source_only", "modified", "destination_only", "identical", "conflict", "unreadable"):
            self.tree.tag_configure(tag, foreground=app.tree.tag_configure(tag, "foreground"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(holder, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind("<Button-1>", self.click)
        self.tree.bind("<space>", self.toggle)
        self.tree.bind("<Return>", self.details)
        self.tree.bind("<Double-1>", self.double_click)
        self.tree.bind("<<TreeviewSelect>>", self.focus_row)
        self.column_widths = ColumnWidths(self.tree, app.column_widths.setdefault("expanded", {}))
        self.window.bind("<Control-f>", self.focus_search)
        self.window.bind("<Escape>", lambda event: app.close_expanded_list())

    def focus_search(self, event=None):
        self.search.focus_set()
        self.search.selection_range(0, "end")
        return "break"

    def focus_row(self, event=None):
        item = self.tree.focus()
        if item in self.app.row_map:
            self.app.tree.focus(item)
            if self.app.tree.selection() != (item,):
                self.app.tree.selection_set(item)
            self.app.show_detail()

    def click(self, event):
        if checkbox_hit(self.tree, event):
            self.app.toggle_row(self.tree.identify_row(event.y))

    def toggle(self, event=None):
        self.app.toggle_row(self.tree.focus())
        return "break"

    def double_click(self, event):
        if not checkbox_hit(self.tree, event):
            self.app.toggle_row(self.tree.identify_row(event.y))
        return "break"

    def details(self, event=None):
        self.focus_row()
        if self.tree.focus() in self.app.row_map:
            self.app.detail_popup()
        return "break"

    def refresh(self):
        focused = self.tree.focus() or self.app.tree.focus()
        offset = self.tree.yview()[0] if self.tree.get_children() else 0
        horizontal_offset = self.tree.xview()[0]
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for item in self.app.tree.get_children():
            self.tree.insert("", "end", iid=item, values=self.app.tree.item(item, "values"),
                             image=self.app.tree.item(item, "image"),
                             tags=self.app.tree.item(item, "tags"))
        if focused in self.app.row_map:
            self.tree.focus(focused)
            self.tree.selection_set(focused)
        self.tree.yview_moveto(offset)
        self.tree.xview_moveto(horizontal_offset)
        self.summary.configure(text=self.app.table_count.cget("text") + "  |  " + self.app.selection_label.cget("text"))
        for control in self.controls:
            control.configure(state="disabled" if self.app.busy else "normal")


class BackupApp:
    def __init__(self, root, settings: Settings, data_directory=None, demo=False, startup_warning=""):
        global SCALE
        self.root = root
        self.settings = settings
        SCALE = detect_scale(root)
        self.row_height = S(38)
        set_appearance(settings.language, settings.theme)
        self.data_directory = Path(data_directory) if data_directory else state_directory()
        self.demo = demo
        self.comparison = None
        self.selected = set()
        self.visible_rows = []
        self.row_map = {}
        self.busy = False
        self.activity = None
        self.restart_available = False
        self.compact = False
        self.density_id = None
        self.mode = "sync"
        self.page = "sync"
        self.events = queue.Queue()
        self.progress_lock = threading.Lock()
        self.latest_progress = None
        self.cancel_event = threading.Event()
        self.worker = None
        self.prune_window = None
        self.retention_prompt_pending = False
        self.sort_column = "relative"
        self.sort_reverse = False
        self.column_widths = {}
        self.source_var = PathTextVar(value=settings.source)
        self.destination_var = PathTextVar(value=settings.destination)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="Visi skirtumai")  # Stable internal filter key.
        self.filter_display_var = tk.StringVar(value=T("Visi skirtumai"))
        self.status_var = UiTextVar(value=T("Pasirinkite aplankus ir patikrinkite skirtumus."))
        self.heading_var = UiTextVar()
        self.subtitle_var = UiTextVar()
        self.root.title(f"{APP_NAME}{T(' • Failų kopijos')}")
        fit_window(self.root, 1440, 980, 1100, 760)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", (FONT, 10))
        self.root.option_add("*Menu.background", WHITE)
        self.root.option_add("*Menu.foreground", INK)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.setup_styles()
        self.build_shell()
        self.show_page("sync")
        self.root.bind("<Configure>", self.window_resized, add="+")
        self.source_var.trace_add("write", lambda *args: self.invalidate("Šaltinis pakeistas. Patikrinkite skirtumus."))
        self.destination_var.trace_add("write", lambda *args: self.invalidate("Kopijos aplankas pakeistas. Patikrinkite skirtumus."))
        self.search_var.trace_add("write", lambda *args: self.render_rows())
        self.filter_var.trace_add("write", lambda *args: self.render_rows())
        self.filter_var.trace_add("write", lambda *args: self.refresh_filter_indicator())
        self.filter_var.trace_add("write", lambda *args: self.filter_display_var.set(T(self.filter_var.get())))
        self.filter_display_var.trace_add("write", lambda *args: self.filter_changed())
        self.overwrite_var.trace_add("write", lambda *args: self.restore_mode_changed())
        self.root.bind("<F5>", lambda event: self.start_scan() if self.page in MODE_LABELS and not self.busy else None)
        self.root.bind("<Control-f>", self.focus_search)
        self.poll_id = self.root.after(75, self.poll_events)
        if startup_warning:
            self.root.after(200, lambda: messagebox.showwarning(T("Nustatymai"), T(startup_warning), parent=root))

    def setup_styles(self):
        self.file_icons = FileIcons(self.root, self.settings.theme == "dark")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=INK, background=ENTRY_BG, insertcolor=INK, bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, padding=7)
        style.map("TEntry", bordercolor=[("focus", TEAL)])
        style.configure("TCombobox", fieldbackground=ENTRY_BG, background=ENTRY_BG, foreground=INK,
                        bordercolor=LINE, arrowcolor=MUTED, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", ENTRY_BG)], background=[("readonly", ENTRY_BG)],
                  foreground=[("readonly", INK)], selectbackground=[("readonly", ENTRY_BG)], selectforeground=[("readonly", INK)])
        self.root.option_add("*TCombobox*Listbox.background", ENTRY_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)
        style.configure("TSpinbox", fieldbackground=ENTRY_BG, foreground=INK, background=ENTRY_BG,
                        arrowsize=18, arrowcolor=INK, bordercolor=LINE, padding=6)
        style.map("TSpinbox", fieldbackground=[("readonly", ENTRY_BG)], foreground=[("readonly", INK)],
                  arrowcolor=[("disabled", DISABLED_FG), ("pressed", TEAL), ("active", TEAL)],
                  background=[("disabled", DISABLED_BG), ("active", HOVER_BG)])
        style.configure("Treeview", font=(FONT, 10), background=WHITE, fieldbackground=WHITE,
                        foreground=INK, borderwidth=0, rowheight=self.row_height)
        style.configure("Treeview.Heading", font=(FONT, 9, "bold"), background=HEADING_BG, foreground=MUTED,
                        relief="flat", padding=(10, 11))
        style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", INK)])
        style.map("Treeview.Heading", background=[("active", HOVER_BG)], foreground=[("active", INK)])
        # Flat rows: omit the native indentation/expand arrow, keep our image gutter.
        style.layout("Files.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"side": "left", "sticky": ""})]})])
        style.configure("Horizontal.TProgressbar", background=TEAL, troughcolor=LINE, borderwidth=0,
                        lightcolor=TEAL, darkcolor=TEAL, thickness=5)
        style.configure("TCheckbutton", background=BG, foreground=INK)
        style.configure("TRadiobutton", background=WHITE, foreground=INK)
        style.map("TRadiobutton", background=[("active", WHITE)], foreground=[("active", INK)])
        for orientation in ("Vertical", "Horizontal"):
            name = f"{orientation}.TScrollbar"
            style.configure(name, background=LINE, troughcolor=WHITE, bordercolor=LINE,
                            darkcolor=LINE, lightcolor=LINE, arrowcolor=MUTED, relief="flat", gripcount=0)
            style.map(name, background=[("active", HOVER_BG), ("pressed", SELECT_BG)],
                      arrowcolor=[("active", INK)])

    def build_shell(self):
        sidebar = tk.Frame(self.root, bg=NAV, width=S(212))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=NAV)
        brand.pack(fill="x", padx=23, pady=(31, 6))
        mark = tk.Canvas(brand, width=39, height=39, bg=NAV, highlightthickness=0)
        mark.pack(side="left", padx=(0, 10))
        mark.create_oval(1, 1, 38, 38, fill="#9AE0C8", outline="")
        mark.create_text(19, 19, text="B", font=(FONT, 21, "bold"), fill=NAV)
        label(brand, "BackUp", size=19, color=NAV_TEXT, bold=True).pack(side="left")
        label(sidebar, "S T U D I O", size=9, color="#86A5AE").pack(anchor="w", padx=69)
        label(sidebar, "DARBO SRITIS", size=8, color="#799AA4", bold=True).pack(anchor="w", padx=24, pady=(43, 12))
        self.nav_buttons = {}
        titles = [("sync", "Sinchronizavimas"), ("restore", "Atkūrimas"), ("cleanup", "Kopijos valymas")]
        for key, title in titles:
            self.nav_buttons[key] = self.nav_button(sidebar, title, key)
        tk.Frame(sidebar, bg=NAV_ACTIVE, height=1).pack(fill="x", padx=24, pady=22)
        for key, title in [("history", "Veiksmų istorija"), ("settings", "Nustatymai")]:
            self.nav_buttons[key] = self.nav_button(sidebar, title, key)
        bottom = tk.Frame(sidebar, bg=NAV)
        bottom.pack(side="bottom", fill="x", padx=24, pady=25)
        label(bottom, "●  Vietinė programa", size=9, color="#9AE0C8").pack(anchor="w")
        label(bottom, "Jūsų failai jūsų įrenginiuose.", size=8, color="#86A5AE").pack(anchor="w", pady=(6, 16))
        label(bottom, f"{T('VERSIJA')} {APP_VERSION}", size=8, color="#6F919C").pack(anchor="w")
        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(side="left", fill="both", expand=True, padx=28, pady=24)
        header = self.header = tk.Frame(self.main, bg=BG)
        header.pack(fill="x", pady=(0, 18))
        left = tk.Frame(header, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        self.heading_label = label(left, textvariable=self.heading_var, size=25, bold=True)
        self.heading_label.pack(anchor="w")
        self.subtitle_label = label(left, textvariable=self.subtitle_var, color=MUTED)
        self.subtitle_label.pack(anchor="w", pady=(5, 0))
        if self.demo:
            label(header, "  DEMONSTRACIJA  ", color=TEAL, bold=True, size=9, bg=TEAL_LIGHT, pady=8).pack(side="right")
        self.content = tk.Frame(self.main, bg=BG)
        self.content.pack(fill="both", expand=True)

    def nav_button(self, parent, title, key):
        widget = ThemedButton(parent, preserve_disabled_colors=True, text=T(title), command=lambda: self.show_page(key), bg=NAV, fg="#C4D5DB",
                           activebackground=NAV_ACTIVE, activeforeground=NAV_TEXT, disabledforeground=DISABLED_FG,
                           font=(FONT, 10), anchor="w", padx=17, pady=13, relief="flat", bd=0, highlightthickness=1,
                           highlightbackground=NAV, highlightcolor=TEAL, cursor="hand2")
        widget.pack(fill="x", padx=12, pady=3)
        return widget

    def show_page(self, page):
        if self.busy:
            return
        self.close_expanded_list()
        self.page = page
        for key, nav in self.nav_buttons.items():
            nav.configure(bg=NAV_ACTIVE if key == page else NAV, fg=NAV_TEXT if key == page else "#C4D5DB",
                          highlightbackground=NAV_ACTIVE if key == page else NAV)
        for child in self.content.winfo_children():
            child.destroy()
        if page in MODE_LABELS:
            if page != self.mode:
                self.mode = page
                self.comparison = None
                self.selected.clear()
                self.status_var.set("Pasirinkite aplankus ir patikrinkite skirtumus.")
            self.heading_var.set(MODE_LABELS[page])
            self.subtitle_var.set({"sync": "Atnaujinkite kopiją. Matykite ir pasirinkite kiekvieną pakeitimą.",
                                   "restore": "Susigrąžinkite failus iš kopijos į šaltinio aplanką.",
                                   "cleanup": "Peržiūrėkite, ko šaltinyje nebėra, ir sutvarkykite kopiją."}[page])
            self.build_workspace()
        elif page == "settings":
            self.heading_var.set("Nustatymai")
            self.subtitle_var.set("Kopijavimo greitis, failų versijos ir programos elgsena.")
            self.build_settings()
        else:
            self.heading_var.set("Veiksmų istorija")
            self.subtitle_var.set("Atliktos operacijos, rezultatai ir išsaugotos failų versijos.")
            self.build_history()
        self.apply_density()
        self.schedule_density()

    def toggle_stat_filter(self, value):
        """A statistic card filters the list; clicking the active card again shows all differences."""
        self.filter_var.set("Visi skirtumai" if self.filter_var.get() == value else value)

    def refresh_filter_indicator(self):
        if self.page not in MODE_LABELS or not hasattr(self, "show_all_button") or not self.show_all_button.winfo_exists():
            return
        current = self.filter_var.get()
        for stat_card, color, filter_text in getattr(self, "stat_cards", {}).values():
            if stat_card.winfo_exists():
                stat_card.configure(highlightbackground=color if current == filter_text else LINE)
        if current == "Visi skirtumai":
            self.show_all_button.pack_forget()
        elif not self.show_all_button.winfo_ismapped():
            self.show_all_button.pack(side="right", padx=(0, 8), after=self.filter_combo)

    def filter_changed(self):
        display = self.filter_display_var.get()
        for key in ("Visi skirtumai", "Nauji šaltinyje", "Pakeisti", "Tik kopijoje",
                    "Vienodi", "Konfliktai", "Skaitymo problemos", "Pažymėti", "Visi elementai"):
            if T(key) == display and self.filter_var.get() != key:
                self.filter_var.set(key)
                break

    def build_workspace(self):
        self.workspace_controls = []
        self.density_buttons = []
        self.density_titles = []
        panel = card(self.content)
        panel.pack(fill="x", pady=(0, 8))
        paths = tk.Frame(panel, bg=WHITE)
        paths.pack(fill="x", padx=18, pady=(8, 4))
        paths.columnconfigure(0, weight=1, uniform="paths")
        paths.columnconfigure(2, weight=1, uniform="paths")
        for index, title, variable in ((0, "ŠALTINIS  ·  jūsų failai", self.source_var),
                                       (2, "ATSARGINĖ KOPIJA", self.destination_var)):
            cell = tk.Frame(paths, bg=WHITE)
            cell.grid(row=0, column=index, sticky="ew")
            title_label = label(cell, title, size=9, color=MUTED, bold=True)
            title_label.pack(anchor="w", pady=(0, 7))
            self.density_titles.append(title_label)
            field = tk.Frame(cell, bg=WHITE)
            field.pack(fill="x")
            entry = ttk.Entry(field, textvariable=variable, font=(FONT, 10))
            entry.pack(side="left", fill="x", expand=True)
            browse = button(field, "…", lambda var=variable: self.browse_root(var))
            browse.pack(side="left", padx=(6, 0))
            self.workspace_controls.extend([entry, browse])
            self.density_buttons.append(browse)
        label(paths, "←" if self.mode == "restore" else "→", size=21, color=TEAL).grid(row=0, column=1, padx=14, pady=(20, 0))
        tk.Frame(panel, bg=LINE, height=1).pack(fill="x", padx=18, pady=(3, 4))
        bottom = tk.Frame(panel, bg=WHITE)
        bottom.pack(fill="x", padx=18, pady=(0, 2))
        self.exclusion_label = label(bottom, "", size=9, color=MUTED)
        self.exclusion_label.pack(side="left")
        self.refresh_exclusion_label()
        edit = button(bottom, "Tvarkyti išimtis", self.open_exclusions)
        edit.pack(side="left", padx=(12, 0))
        self.workspace_controls.append(edit)
        self.density_buttons.append(edit)
        self.scan_button = button(bottom, "Tikrinti skirtumus", self.start_scan, primary=True)
        self.scan_button.pack(side="right")
        self.workspace_controls.append(self.scan_button)
        self.full_scan_button = button(bottom, "Pilna patikra", lambda: self.start_scan(full=True))
        self.full_scan_button.pack(side="right", padx=(0, 8))
        self.workspace_controls.append(self.full_scan_button)
        self.density_buttons.extend([self.scan_button, self.full_scan_button])
        # Equal-height context row in every mode. Restore/cleanup no longer
        # take an extra panel's worth of vertical space away from the list.
        options = self.mode_options = tk.Frame(panel, bg=WHITE,
            height=max(32, tkfont.Font(family=FONT, size=10).metrics("linespace") + 12))
        options.pack(fill="x", padx=18, pady=(0, 4))
        options.pack_propagate(False)
        if self.mode == "restore":
            label(options, "Atkurti:", bold=True).pack(side="left")
            for text, value in (("Tik trūkstamus", False), ("Ir perrašyti esamus", True)):
                radio = ttk.Radiobutton(options, text=T(text), variable=self.overwrite_var, value=value)
                radio.pack(side="left", padx=9)
                self.workspace_controls.append(radio)
        else:
            text = ("Failai bus perkelti į versijų archyvą. Aplankai pašalinami tik kai lieka tušti."
                    if self.mode == "cleanup" else "Atnaujinkite kopiją. Matykite ir pasirinkite kiekvieną pakeitimą.")
            label(options, text, color=TEAL if self.mode == "cleanup" else MUTED,
                  anchor="w", size=9).pack(fill="both", expand=True)
        stats = tk.Frame(self.content, bg=BG)
        stats.pack(fill="x", pady=(0, 8))
        self.stat_values = {}
        self.stat_captions = {}
        self.stat_titles = {}
        self.stat_cards = {}
        for index, (key, title, color, filter_text) in enumerate([
            ("source_only", "NAUJI ŠALTINYJE", TEAL, "Nauji šaltinyje"),
            ("modified", "PAKEISTI", AMBER, "Pakeisti"),
            ("destination_only", "TIK KOPIJOJE", STATUS_BLUE, "Tik kopijoje"),
            ("identical", "VIENODI", MUTED, "Vienodi"),
        ]):
            stats.columnconfigure(index, weight=1, uniform="stats")
            stat_card = card(stats)
            stat_card.configure(highlightthickness=2)  # Constant width: only the colour marks the active filter.
            stat_card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0 if index == 3 else 6))
            value = label(stat_card, "—", size=24, bold=True, color=color)
            value.pack(anchor="w", padx=15, pady=(10, 0))
            caption = label(stat_card, title, size=8, color=MUTED, bold=True)
            caption.pack(anchor="w", padx=15, pady=(0, 12))
            for widget in (stat_card, value, caption):
                widget.bind("<Button-1>", lambda event, val=filter_text: self.toggle_stat_filter(val))
                widget.configure(cursor="hand2")
            self.stat_values[key] = value
            self.stat_captions[key] = caption
            self.stat_titles[key] = title
            self.stat_cards[key] = (stat_card, color, filter_text)
        # Pack the action footer first to preserve it when the window is resized.
        footer = card(self.content)
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        progress_strip = tk.Frame(footer, bg=LINE, height=5)
        progress_strip.pack(fill="x")
        progress_strip.pack_propagate(False)
        self.progressbar = SlimProgress(progress_strip)
        self.progressbar.pack(fill="both", expand=True)
        footer_top = tk.Frame(footer, bg=WHITE)
        footer_top.pack(fill="x", padx=16, pady=(12, 4))
        self.selection_label = label(footer_top, "Nieko nepažymėta", bold=True)
        self.selection_label.pack(side="left")
        self.execute_button = button(footer_top, "Kopijuoti pasirinktus", self.confirm_execute, primary=True)
        self.execute_button.pack(side="right")
        self.cancel_button = button(footer_top, "Stabdyti", self.cancel_work)
        self.cancel_button.pack(side="right", padx=(0, 8))
        self.density_buttons.extend([self.execute_button, self.cancel_button])
        self.cancel_button.configure(state="disabled")
        self.status_label = label(footer, textvariable=self.status_var, color=MUTED, size=9, anchor="w")
        self.status_label.pack(fill="x", padx=16, pady=(0, 12))
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(300, event.width - 10)))
        table_card = card(self.content)
        table_card.pack(fill="both", expand=True)
        tools = tk.Frame(table_card, bg=WHITE)
        tools.pack(fill="x", padx=14, pady=(8, 6))
        self.search_entry = ttk.Entry(tools, textvariable=self.search_var, font=(FONT, 10), width=25)
        self.search_entry.pack(side="left", fill="x", expand=True)
        label(tools, "Paieška pagal kelią", size=8, color=MUTED).pack(side="left", padx=(8, 14))
        self.filter_display_var.set(T(self.filter_var.get()))
        self.filter_combo = ttk.Combobox(tools, textvariable=self.filter_display_var, state="readonly", width=18,
                                        values=[T(key) for key in ("Visi skirtumai", "Nauji šaltinyje", "Pakeisti",
                                                              "Tik kopijoje", "Vienodi", "Konfliktai", "Skaitymo problemos", "Pažymėti", "Visi elementai")])
        self.filter_combo.pack(side="right")
        self.show_all_button = button(tools, "✕ Rodyti visus skirtumus", lambda: self.filter_var.set("Visi skirtumai"))
        self.show_all_button.configure(pady=3, padx=8, font=(FONT, 9))
        self.refresh_filter_indicator()
        selection_tools = tk.Frame(table_card, bg=WHITE)
        selection_tools.pack(fill="x", padx=14, pady=(0, 7))
        self.select_all_button = button(selection_tools, "Pažymėti rodomus", self.select_visible)
        self.select_all_button.configure(pady=5, padx=8, font=(FONT, 9))
        self.select_all_button.pack(side="left")
        self.clear_button = button(selection_tools, "Nuimti žymas", self.clear_selection)
        self.clear_button.configure(pady=5, padx=8, font=(FONT, 9))
        self.clear_button.pack(side="left", padx=5)
        self.export_button = button(selection_tools, "Eksportuoti CSV", self.export_differences)
        self.export_button.configure(pady=5, padx=8, font=(FONT, 9))
        self.export_button.pack(side="right")
        self.expand_button = button(selection_tools, "Išplėsti sąrašą", self.open_expanded_list)
        self.expand_button.configure(pady=5, padx=8, font=(FONT, 9))
        self.expand_button.pack(side="right", padx=8)
        self.workspace_controls.extend([self.select_all_button, self.clear_button, self.export_button])
        self.detail_var = UiTextVar(value=T("Pažymėkite eilutę – čia matysite failo informaciją ir veiksmo paaiškinimą."))
        self.detail_area = tk.Frame(table_card, bg=WHITE)
        self.detail_area.pack(side="bottom", fill="x", padx=14, pady=8)
        detail = tk.Text(self.detail_area, height=3, wrap="word", bg=WHITE, fg=MUTED,
                         font=(FONT, 9), relief="flat", borderwidth=0, highlightthickness=0)
        self.detail_label = detail
        detail.pack(side="left", fill="x", expand=True)
        detail_scroll = ttk.Scrollbar(self.detail_area, command=detail.yview)
        detail_scroll.pack(side="right", fill="y")
        detail.configure(yscrollcommand=detail_scroll.set)
        variable = self.detail_var
        def update_detail(*_):
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("1.0", variable.get())
            detail.configure(state="disabled")
            detail.yview_moveto(0)
        trace = variable.trace_add("write", update_detail)
        detail.bind("<Destroy>", lambda event: variable.trace_remove("write", trace))
        update_detail()
        self.table_count = label(table_card, "", size=8, color=MUTED, anchor="w")
        self.table_count.pack(side="bottom", fill="x", padx=14, pady=(6, 0))
        holder = tk.Frame(table_card, bg=WHITE)
        holder.pack(fill="both", expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(holder, columns=("check", "relative", "status", "source", "destination", "action"),
                                 displaycolumns=("relative", "status", "source", "destination", "action"),
                                 show="tree headings", style="Files.Treeview", selectmode="browse", height=6)
        self.tree.column("#0", width=72, minwidth=72, stretch=False)
        self.tree.heading("#0", text="✓", anchor="w", command=self.select_visible)
        definitions = [("check", "✓", 36, "center"), ("relative", "FAILAS / APLANKAS", S(295), "w"),
                       ("status", "BŪSENA", S(145), "w"), ("source", "ŠALTINIS", S(113), "e"),
                       ("destination", "KOPIJA", S(113), "e"), ("action", "PAŽYMĖJUS", S(170), "w")]
        for key, title, width, anchor in definitions:
            self.tree.heading(key, text=T(title), anchor=anchor,
                              command=lambda col=key: self.select_visible() if col == "check" else self.sort_rows(col))
            minimum = {"check": 36, "relative": S(210), "status": S(95), "source": S(72), "destination": S(72),
                       "action": S(100)}[key]
            self.tree.column(key, width=width, minwidth=minimum, anchor=anchor, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("source_only", foreground=TEAL)
        self.tree.tag_configure("modified", foreground=AMBER)
        self.tree.tag_configure("destination_only", foreground=STATUS_BLUE)
        self.tree.tag_configure("identical", foreground=MUTED)
        self.tree.tag_configure("conflict", foreground=RED)
        self.tree.tag_configure("unreadable", foreground=RED)
        self.tree.bind("<Button-1>", self.tree_click)
        self.tree.bind("<Double-1>", self.tree_double_click)
        self.tree.bind("<space>", self.tree_space)
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        self.tree.bind("<Button-3>", self.context_menu)
        self.tree.bind("<Return>", self.detail_popup)
        self.main_column_widths = ColumnWidths(self.tree, self.column_widths.setdefault("main", {}))
        self.tree.bind("<Configure>", lambda event: self.schedule_density(), add="+")
        self.refresh_stats()
        self.render_rows()

    def window_resized(self, event):
        if event.widget is self.root:
            self.schedule_density()

    def schedule_density(self):
        if self.density_id is None:
            self.density_id = self.root.after_idle(self.check_density)

    def check_density(self):
        self.density_id = None
        compact = self.root.winfo_height() < S(880)
        if self.page in MODE_LABELS and self.tree.winfo_exists() and self.tree.winfo_height() > 1:
            # Use the actual table allocation as well as the window height (DPI,
            # translated text and footer wrapping all affect the available space).
            heading = tkfont.Font(family=FONT, size=9, weight="bold").metrics("linespace") + 24
            target = heading + 5 * getattr(self, "row_height", S(38))
            threshold = target + (S(120) if self.compact else 0)
            compact = compact or self.tree.winfo_height() < threshold
        if compact != self.compact:
            self.compact = compact
            self.apply_density()

    def apply_density(self):
        """Keep the file table usable on laptop screens with limited height."""
        workspace = self.page in MODE_LABELS
        self.main.pack_configure(pady=6 if self.compact else 12 if workspace else 24)
        self.header.pack_configure(pady=(0, 6 if self.compact else 10 if workspace else 18))
        self.heading_label.configure(font=(FONT, 18 if self.compact else 25, "bold"))
        # Compact mode: slimmer buttons and labels so the file list keeps at least five rows.
        for widget in getattr(self, "density_buttons", ()):
            if widget.winfo_exists():
                widget.configure(pady=4 if self.compact else 9)
        for widget in getattr(self, "density_titles", ()):
            if widget.winfo_exists():
                widget.pack_configure(pady=(0, 3 if self.compact else 7))
        if self.compact or workspace:
            self.subtitle_label.pack_forget()
        else:
            self.subtitle_label.pack(anchor="w", pady=(5, 0))
        if self.page not in MODE_LABELS:
            return
        for key, value in self.stat_values.items():
            caption = self.stat_captions[key]
            value.pack_forget()
            caption.pack_forget()
            value.configure(font=(FONT, 17 if self.compact else 20, "bold"))
            value.pack(side="left", padx=(10, 6), pady=6 if self.compact else 8)
            caption.pack(side="left", padx=(0, 8))
        self.detail_label.configure(height=2 if self.compact else 3)
        self.detail_area.pack_configure(pady=3 if self.compact else 8)
        if self.compact:
            self.table_count.pack_forget()
        elif not self.table_count.winfo_manager():
            self.table_count.pack(side="bottom", fill="x", padx=14, pady=(6, 0), before=self.detail_area)

    def detail_popup(self, event=None):
        row = self.row_map.get(self.tree.focus())
        if row:
            def details(info):
                return f"{format_size(info.size)}\n{format_date(info.mtime_ns)}" if info else T("Nėra")
            messagebox.showinfo(T("Failo informacija"),
                f"{row.relative}\n\n{T('Šaltinis: ')}\n{details(row.source)}\n\n{T('Kopija: ')}\n{details(row.destination)}"
                f"\n\n{T('Pažymėjus: ')}{T(action_label(row, self.mode, self.overwrite_var.get()))}"
                f"\n{T(row.problem)}", parent=self.root)
        return "break"

    def current_settings(self):
        return replace(self.settings, source=self.source_var.get().strip(), destination=self.destination_var.get().strip(),
                       exclusions=list(self.settings.exclusions))

    def persist_settings(self):
        self.settings = self.current_settings()
        try:
            save_settings(self.settings, self.data_directory)
            return True
        except (OSError, ValueError) as error:
            messagebox.showerror(T("Nustatymai neišsaugoti"), T(str(error)), parent=self.root)
            return False

    def browse_root(self, variable):
        current = Path(variable.get()).expanduser()
        chosen = filedialog.askdirectory(title=T("Pasirinkite aplanką"), mustexist=variable is self.source_var and self.mode != "restore",
                                         initialdir=current if current.is_dir() else Path.home(), parent=self.root)
        if chosen:
            variable.set(chosen)

    def open_prune(self, prompt=False):
        if self.busy:
            return
        if self.prune_window is not None and self.prune_window.winfo_exists():
            if not prompt:
                self.prune_window.reveal()
            return
        try:
            root = archive_root(self.current_settings())
        except (BackupError, ValueError, OSError) as error:
            if not prompt:
                messagebox.showerror(T("Versijų archyvas"), T(str(error)), parent=self.root)
            return
        if root is None:
            if not prompt:
                messagebox.showinfo(T("Versijų archyvas"), T("Pasirinkus visą diską, nustatymuose nurodykite atskirą versijų aplanką už abiejų darbo diskų."), parent=self.root)
            return
        self.prune_window = PruneDialog(self, root, prompt=prompt)

    def open_exclusions(self):
        if not self.busy:
            self.exclusion_window = ExclusionsDialog(self)

    def refresh_exclusion_label(self):
        if self.page in MODE_LABELS and hasattr(self, "exclusion_label"):
            self.exclusion_label.configure(text=T(f"Nekopijuojami aplankai: {len(self.settings.exclusions)}"))

    def invalidate(self, message="Patikrinkite skirtumus iš naujo."):
        self.comparison = None
        self.selected.clear()
        self.status_var.set(message)
        if self.page in MODE_LABELS:
            self.refresh_stats()
            self.render_rows()

    def refresh_stats(self):
        if self.page not in MODE_LABELS:
            return
        for key, widget in self.stat_values.items():
            count = sum(row.status == key and row.kind == "file" for row in self.comparison.rows) if self.comparison else None
            widget.configure(text=str(count) if count is not None else "—")
            # The large number counts files; folders (e.g. empty ones left for cleanup) are shown beside the title.
            folders = sum(row.status == key and row.kind == "directory" for row in self.comparison.rows) if self.comparison else 0
            caption = T(self.stat_titles[key]) + (f"  ·  {T('APLANKŲ')}: {folders}" if folders else "")
            self.stat_captions[key].configure(text=caption)

    def render_rows(self):
        if self.page not in MODE_LABELS or not hasattr(self, "tree") or not self.tree.winfo_exists():
            return
        focused = self.tree.focus()
        offset = self.tree.yview()[0] if self.tree.get_children() else 0
        horizontal_offset = self.tree.xview()[0]
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.row_map = {}
        self.visible_rows = []
        if self.comparison:
            chosen_filter = self.filter_var.get()
            query = self.search_var.get().strip().casefold()
            wanted = {"Nauji šaltinyje": "source_only", "Pakeisti": "modified", "Tik kopijoje": "destination_only",
                      "Vienodi": "identical", "Konfliktai": "conflict", "Skaitymo problemos": "unreadable"}.get(chosen_filter)
            for row in self.comparison.rows:
                if query and query not in row.relative.casefold():
                    continue
                if wanted and row.status != wanted:
                    continue
                if chosen_filter == "Visi skirtumai" and row.status == "identical":
                    continue
                if chosen_filter == "Pažymėti" and row.relative not in self.selected:
                    continue
                if row.kind == "directory" and row.status == "identical":
                    continue
                self.visible_rows.append(row)
            def sort_key(row):
                if self.sort_column == "status":
                    return T(STATUS_LABELS[row.status])
                if self.sort_column in ("source", "destination"):
                    value = getattr(row, self.sort_column)
                    return value.size if value else -1
                if self.sort_column == "action":
                    return T(action_label(row, self.mode, self.overwrite_var.get()))
                return row.relative.casefold()
            self.visible_rows.sort(key=sort_key, reverse=self.sort_reverse)
            for index, row in enumerate(self.visible_rows):
                possible = eligible(row, self.mode, self.overwrite_var.get()) and not self.comparison.blocked
                mark = "☑" if row.relative in self.selected else "☐" if possible else "—"
                name = row.relative + (" /" if row.kind == "directory" else "")
                def size(info):
                    return T("Aplankas") if info and info.kind == "directory" else format_size(info.size if info else None)
                item_id = row.relative
                self.row_map[item_id] = row
                status_text = T(STATUS_LABELS[row.status])
                if row.status == "modified" and row.destination.mtime_ns > row.source.mtime_ns:
                    status_text = T("Kopija naujesnė")
                self.tree.insert("", "end", iid=item_id,
                                 image=self.file_icons.get(row.relative, row.kind, mark),
                                 values=(mark, name, status_text, size(row.source), size(row.destination),
                                         T(action_label(row, self.mode, self.overwrite_var.get()))), tags=(row.status,))
            if focused in self.row_map:
                self.tree.focus(focused)
                self.tree.selection_set(focused)
            self.tree.yview_moveto(offset)
            self.tree.xview_moveto(horizontal_offset)
        self.table_count.configure(text=T(f"Rodoma: {len(self.visible_rows)}  ·  Pažymėta: {len(self.selected)}  ·  Dydžiai nurodyti failams"))
        self.refresh_selection()
        expanded = getattr(self, "expanded_list", None)
        if expanded:
            expanded.refresh()

    def sort_rows(self, column):
        self.sort_reverse = not self.sort_reverse if self.sort_column == column else False
        self.sort_column = column
        self.render_rows()

    def close_expanded_list(self):
        expanded = getattr(self, "expanded_list", None)
        self.expanded_list = None
        if expanded:
            expanded.window.destroy()

    def open_expanded_list(self):
        if getattr(self, "expanded_list", None):
            self.expanded_list.window.lift()
            self.expanded_list.window.focus_set()
        else:
            self.expanded_list = ExpandedList(self)
            self.expanded_list.refresh()

    def toggle_row(self, item):
        if self.busy or not self.comparison or self.comparison.blocked:
            return
        row = self.row_map.get(item)
        if not row or not eligible(row, self.mode, self.overwrite_var.get()):
            return
        targets = [row]
        if row.kind == "directory":
            targets += [child for child in self.comparison.rows if child.relative.startswith(row.relative + "/")
                        and eligible(child, self.mode, self.overwrite_var.get())]
        remove = row.relative in self.selected
        for target in targets:
            if remove:
                self.selected.discard(target.relative)
            else:
                self.selected.add(target.relative)
        self.render_rows()

    def tree_click(self, event):
        if checkbox_hit(self.tree, event):
            self.toggle_row(self.tree.identify_row(event.y))

    def tree_double_click(self, event):
        if not checkbox_hit(self.tree, event):
            self.toggle_row(self.tree.identify_row(event.y))
        return "break"

    def tree_space(self, event):
        self.toggle_row(self.tree.focus())
        return "break"

    def select_visible(self):
        if not self.busy and self.comparison and not self.comparison.blocked:
            self.selected.update(row.relative for row in self.visible_rows if eligible(row, self.mode, self.overwrite_var.get()))
            self.render_rows()

    def clear_selection(self):
        if not self.busy:
            self.selected.clear()
            self.render_rows()

    def restore_mode_changed(self):
        if self.comparison and self.mode == "restore" and not self.busy:
            self.selected = {row.relative for row in self.comparison.rows if recommended(row, self.mode, self.overwrite_var.get())}
            self.render_rows()

    def selected_rows(self):
        return [row for row in self.comparison.rows if row.relative in self.selected] if self.comparison else []

    def refresh_selection(self):
        rows = self.selected_rows()
        total = sum((row.destination if self.mode in ("restore", "cleanup") else row.source).size for row in rows)
        overwrite_count = sum(row.status == "modified" for row in rows)
        self.selection_label.configure(text=T(f"Pasirinkta: {len(rows)}  ·  {format_size(total)}" +
                                       (f"  ·  Perrašoma: {overwrite_count}" if overwrite_count else "")))
        title = {"sync": "Kopijuoti pasirinktus", "restore": "Atkurti pasirinktus", "cleanup": "Archyvuoti pasirinktus"}[self.mode]
        self.execute_button.configure(text=f"{T(title)} ({len(rows)})", state="normal" if rows and not self.busy and not self.comparison.blocked else "disabled")

    def show_detail(self, event=None):
        row = self.row_map.get(self.tree.focus())
        if not row:
            self.detail_var.set("Pažymėkite eilutę – čia matysite failo informaciją ir veiksmo paaiškinimą.")
            return
        def info(value):
            return f"{format_size(value.size)} · {format_date(value.mtime_ns)}" if value else T("nėra")
        explanation = T(action_label(row, self.mode, self.overwrite_var.get()))
        if row.problem:
            explanation += " · " + T(row.problem)
        if row.status == "conflict":
            explanation = T("Vienoje pusėje failas, kitoje aplankas. Sutvarkykite konfliktą ir tikrinkite iš naujo.")
        elif row.status == "modified" and row.destination.mtime_ns > row.source.mtime_ns:
            explanation += T(". Kopija naujesnė – prieš perrašydami patikrinkite, kurios versijos reikia.")
        self.detail_var.set(f"{row.relative}\nŠaltinis: {info(row.source)}  |  Kopija: {info(row.destination)}  ·  {explanation}")

    def context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.focus(item)
        self.tree.selection_set(item)
        menu = tk.Menu(self.root, tearoff=0)
        for text, root in (("Atverti šaltinio aplanką", self.comparison.source), ("Atverti kopijos aplanką", self.comparison.destination)):
            target = root / item
            target = target if target.is_dir() else target.parent
            menu.add_command(label=T(text), command=lambda path=target: self.open_path(path))
        menu.add_separator()
        menu.add_command(label=T("Failo informacija"), command=self.detail_popup)
        menu.add_command(label=T("Pažymėti / nuimti žymą"), command=lambda: self.toggle_row(item))
        menu.tk_popup(event.x_root, event.y_root)

    def focus_search(self, event=None):
        if self.page in MODE_LABELS:
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, "end")
        return "break"

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.workspace_controls:
            widget.configure(state="disabled" if busy else "normal")
        for widget in self.nav_buttons.values():
            widget.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy or self.restart_available else "disabled")
        self.cancel_button.configure(
            text=T("Tikrinti iš naujo" if not busy and self.restart_available else
                   "Nutraukti tikrinimą" if busy and self.activity == "scan" else "Stabdyti"),
            command=self.start_scan if not busy and self.restart_available else self.cancel_work)
        self.refresh_selection()
        if getattr(self, "expanded_list", None):
            self.expanded_list.refresh()

    def receive_progress(self, data):
        # Coalesce progress; do not enqueue one Tk event per file or megabyte.
        with self.progress_lock:
            self.latest_progress = data

    def start_scan(self, completion_message="", full=False):
        if self.busy or self.page not in MODE_LABELS:
            return
        if not self.persist_settings():
            return
        settings = self.current_settings()
        mode = self.mode
        self.comparison = None
        self.selected.clear()
        self.refresh_stats()
        self.render_rows()
        self.cancel_event = threading.Event()
        self.activity = "scan"
        self.restart_available = False
        self.scan_completion_message = completion_message
        self.progressbar.configure(mode="indeterminate")
        self.progressbar.start(14)
        self.status_label.configure(fg=MUTED)
        self.status_var.set("Skaitomi aplankai ir tikrinamas failų turinys…" if full else
                            "Greita patikra: skaitomi aplankai ir pasikeitę failai…")
        self.set_busy(True)

        def job():
            try:
                result = compare(settings, mode=mode, cancel=self.cancel_event, notify=self.receive_progress,
                                 cache_file=self.data_directory / "hash_cache.sqlite3", use_cache=not full)
                self.events.put(("comparison", result))
            except Cancelled:
                self.events.put(("cancelled", "Palyginimas sustabdytas. Failai nepakeisti."))
            except Exception as error:
                self.events.put(("error", str(error)))
        self.worker = threading.Thread(target=job, name="backup-comparison", daemon=False)
        self.worker.start()

    def confirm_execute(self):
        if self.busy or not self.comparison or not self.selected:
            return
        rows = self.selected_rows()
        settings = self.current_settings()
        files = sum(row.kind == "file" for row in rows)
        folders = len(rows) - files
        overwrite = sum(row.status == "modified" for row in rows)
        target = self.comparison.source if self.mode == "restore" else self.comparison.destination
        description = f"Veiksmas: {T(MODE_LABELS[self.mode])}\nPaskirtis: {target}\n\nFailų: {files}\nAplankų: {folders}\nPerrašomų failų: {overwrite}\n"
        if (self.mode == "cleanup" and files) or settings.keep_versions and overwrite:
            try:
                archive = versions_root(settings, self.comparison)
            except (BackupError, ValueError) as error:
                messagebox.showerror(T("Versijų archyvas"), T(str(error)), parent=self.root)
                return
            description += f"\nIšsaugomų versijų aplankas:\n{archive}\n"
        elif overwrite:
            description += f"\n{T('Ankstesnės perrašomų failų versijos nebus išsaugotos.')}\n"
        if self.mode == "cleanup":
            description += f"\n{T('Failai bus perkelti į archyvą. Netušti aplankai bus palikti.')}\n"
        description += "\nVykdyti lentelėje pažymėtus veiksmus?"
        if not messagebox.askyesno(T("Patvirtinkite pasirinktus veiksmus"), T(description), parent=self.root):
            return
        self.start_execute()

    def start_execute(self):
        """Called after the concrete selection has been reviewed and confirmed."""
        if self.busy or not self.comparison or not self.selected:
            return
        comparison = self.comparison
        selection = set(self.selected)
        settings = self.current_settings()
        overwrite = self.overwrite_var.get()
        self.cancel_event = threading.Event()
        self.activity = "execute"
        self.restart_available = False
        self.progressbar.configure(mode="determinate", value=0)
        self.status_var.set("Ruošiami pasirinkti veiksmai…")
        self.status_label.configure(fg=MUTED)
        self.set_busy(True)

        def job():
            try:
                result = execute(comparison, selection, settings, overwrite=overwrite, cancel=self.cancel_event,
                                 notify=self.receive_progress, log_directory=self.data_directory / "logs")
                self.events.put(("completed", result))
            except Cancelled:
                self.events.put(("cancelled", "Veiksmas sustabdytas. Patikrinkite skirtumus iš naujo."))
            except Exception as error:
                self.events.put(("error", str(error)))
        self.worker = threading.Thread(target=job, name="backup-execution", daemon=False)
        self.worker.start()

    def cancel_work(self):
        self.cancel_event.set()
        self.status_var.set("Stabdomas tikrinimas…" if self.activity == "scan" else
                            "Stabdoma… Baigtos operacijos išliks, nebaigti laikini failai bus pašalinti.")
        self.cancel_button.configure(state="disabled")

    def poll_events(self):
        with self.progress_lock:
            progress, self.latest_progress = self.latest_progress, None
        if progress and self.page in MODE_LABELS and self.busy and not self.cancel_event.is_set():
            phase = progress["phase"]
            if phase == "scan":
                self.status_var.set(f"Skaitomi aplankai… Rasta: {progress['found']}  ·  {progress['path']}")
            elif phase == "hash":
                self.progressbar.stop()
                self.progressbar.configure(mode="determinate", value=100 * progress["done"] / max(1, progress["total"]))
                self.status_var.set(f"Tikrinamas turinys: {progress['done']}/{progress['total']}  ·  "
                                    f"Iš indekso: {progress.get('reused', 0)}  ·  {progress['path']}")
            else:
                ratio = progress["bytes"] / progress["total_bytes"] if progress["total_bytes"] else progress["done"] / max(1, progress["total"])
                self.progressbar.configure(value=min(99, ratio * 100))
                speed = progress["bytes"] / max(0.1, progress["elapsed"])
                remaining = max(0, progress["total_bytes"] - progress["bytes"]) / speed if speed else 0
                eta = f"~{int(remaining // 60)} min {int(remaining % 60)} s" if speed and remaining else "tikrinama"
                self.status_var.set(f"Atlikta: {progress['done']}/{progress['total']}  ·  {format_size(progress['bytes'])}  ·  {format_size(int(speed))}/s  ·  Liko: {eta}")
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            self.progressbar.stop()
            self.progressbar.configure(mode="determinate", value=100 if kind in ("comparison", "completed") else 0)
            self.activity = None
            self.restart_available = kind == "cancelled"
            self.set_busy(False)
            if kind == "comparison":
                self.comparison = value
                self.selected = ({row.relative for row in value.rows if recommended(row, self.mode, self.overwrite_var.get())}
                                 if not value.blocked else set())
                self.refresh_stats()
                self.render_rows()
                if value.errors:
                    self.status_label.configure(fg=RED)
                    available = sum(eligible(row, self.mode, self.overwrite_var.get()) for row in value.rows)
                    protected = sum(row.status == "unreadable" for row in value.rows)
                    self.status_var.set((self.scan_completion_message + "  " if self.scan_completion_message else "") +
                        f"Skaitymo klaidų: {len(value.errors)}" +
                        (". Veiksmai užblokuoti; sutvarkykite klaidas arba pridėkite išimtis." if value.blocked else
                         f"  ·  Galimi veiksmai: {available}  ·  Apsaugoti įrašai: {protected}"))
                    self.show_errors(value.errors)
                else:
                    conflicts = sum(row.status == "conflict" for row in value.rows)
                    message = self.scan_completion_message or "Skirtumai nustatyti. Pasirinkite failus; veiksmas rodomas paskutiniame stulpelyje."
                    message += f" Iš indekso: {value.reused_hashes}; perskaityta: {value.verified_hashes}."
                    if conflicts:
                        message += f" Tipo konfliktų: {conflicts}; šie elementai praleidžiami."
                    if value.cache_warning:
                        message += " " + value.cache_warning
                    self.status_var.set(message)
                    self.status_label.configure(fg=AMBER if value.cache_warning else TEAL)
            elif kind == "completed":
                self.last_report = value
                self.retention_prompt_pending = self.settings.prune_prompt and rules_enabled(self.settings)
                summary = (f"Atlikta: {value['completed']}  ·  Klaidų: {value['failed']}  ·  Praleista: {value['skipped']}"
                           f"  ·  Dėl skaitymo klaidų: {value.get('scan_skipped', 0)}"
                           f"  ·  Sustabdyta: {value['cancelled']}. Išsamiau – veiksmų istorijoje.")
                self.status_var.set(summary)
                self.invalidate(summary)
                if value.get("log_error"):
                    messagebox.showwarning(T("Žurnalas"), T(value["log_error"]), parent=self.root)
                if value["failed"]:
                    self.show_errors([f"{item['path']}: {item['message']}" for item in value["items"] if item["status"] == "failed"])
                self.start_scan(completion_message=summary)
            else:
                self.invalidate(value)
                self.status_label.configure(fg=RED if kind == "error" else MUTED)
                if kind == "error":
                    messagebox.showerror(T("Veiksmas neatliktas"), T(value), parent=self.root)
        if self.retention_prompt_pending and not self.busy:
            # Offer (never perform) archive cleanup after the follow-up scan has finished.
            self.retention_prompt_pending = False
            self.open_prune(prompt=True)
        self.poll_id = self.root.after(75, self.poll_events)

    def show_errors(self, errors):
        dialog = tk.Toplevel(self.root)
        dialog.title(T("Patikrinkite šias problemas"))
        fit_window(dialog, 800, 390, 600, 320)
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        label(dialog, "Problemos, kurioms reikia dėmesio", size=17, bold=True).pack(anchor="w", padx=22, pady=20)
        footer = tk.Frame(dialog, bg=BG)
        footer.pack(side="bottom", fill="x", padx=22, pady=16)
        label(footer, f"Klaidų: {len(errors)}", color=MUTED).pack(side="left")
        content = "\n\n".join(T(error) for error in errors)
        def copy_errors():
            dialog.clipboard_clear()
            dialog.clipboard_append(content)
            copy_button.configure(text=T("Nukopijuota"))
        button(footer, "Uždaryti", dialog.destroy, primary=True).pack(side="right")
        copy_button = button(footer, "Kopijuoti klaidas", copy_errors)
        copy_button.pack(side="right", padx=10)
        panel = tk.Frame(dialog, bg=BG)
        panel.pack(fill="both", expand=True, padx=22)
        scrollbar = ttk.Scrollbar(panel, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        text = tk.Text(panel, font=(FONT, 10), bg=WHITE, fg=INK, bd=0, wrap="word", padx=12, pady=12,
                       yscrollcommand=scrollbar.set)
        text.pack(fill="both", expand=True)
        scrollbar.configure(command=text.yview)
        text.insert("1.0", content)
        text.configure(state="disabled")
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        return dialog

    def export_differences(self):
        if not self.comparison:
            messagebox.showinfo(T("Pirmiausia palyginkite"), T("Paspauskite „Tikrinti skirtumus“."), parent=self.root)
            return
        path = filedialog.asksaveasfilename(title=T("Eksportuoti šiuo metu rodomą sąrašą"), parent=self.root,
                                           defaultextension=".csv", filetypes=[(T("CSV lentelė"), "*.csv")],
                                           initialfile=f"{'Differences' if self.settings.language == 'en' else 'Skirtumai'}_{datetime.now():%Y%m%d_%H%M%S}.csv")
        if not path:
            return
        try:
            rows = []
            for row in self.visible_rows:
                rows.append([row.relative in self.selected, row.relative, row.kind, T(STATUS_LABELS[row.status]),
                             row.source.size if row.source else None, row.destination.size if row.destination else None,
                             format_date(row.source.mtime_ns if row.source else None),
                             format_date(row.destination.mtime_ns if row.destination else None),
                             T(action_label(row, self.mode, self.overwrite_var.get()))])
            export_csv(path, [T(value) for value in ("Pažymėtas", "Santykinis kelias", "Tipas", "Būsena", "Šaltinio dydis B", "Kopijos dydis B",
                              "Šaltinio data", "Kopijos data", "Veiksmas pažymėjus")], rows)
            self.status_var.set(f"Eksportuota eilučių: {len(rows)}  ·  {path}")
        except OSError as error:
            messagebox.showerror(T("Eksportas nepavyko"), T(str(error)), parent=self.root)

    def open_path(self, path):
        try:
            open_folder(path)
        except (OSError, ValueError) as error:
            messagebox.showerror(T("Aplankas nepasiekiamas"), T(str(error)), parent=self.root)

    def build_settings(self):
        footer = tk.Frame(self.content, bg=BG)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        actions = tk.Frame(footer, bg=BG)
        actions.pack(fill="x")
        self.settings_save_button = button(actions, "Išsaugoti nustatymus", self.save_preferences, primary=True)
        self.settings_save_button.pack(side="left")
        button(actions, "Atverti programos duomenis", lambda: self.open_path(self.data_directory)).pack(side="left", padx=10)
        label(footer, "Nustatymai išlieka uždarius programą. Aplankus ir kopijavimo išimtis keiskite darbo lange.",
              size=9, color=MUTED, anchor="w").pack(fill="x", pady=(10, 0))

        scroll_area = tk.Frame(self.content, bg=BG)
        scroll_area.pack(fill="both", expand=True)
        self.settings_canvas = tk.Canvas(scroll_area, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=self.settings_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.settings_canvas.pack(side="left", fill="both", expand=True)
        self.settings_canvas.configure(yscrollcommand=scrollbar.set)
        panel = card(self.settings_canvas)
        panel_window = self.settings_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda event: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda event: self.settings_canvas.itemconfigure(panel_window, width=event.width))
        body = tk.Frame(panel, bg=WHITE)
        body.pack(fill="x", padx=24, pady=23)
        label(body, "Failų versijos", size=17, bold=True).pack(anchor="w")
        self.keep_versions_var = tk.BooleanVar(value=self.settings.keep_versions)
        check = tk.Checkbutton(body, text=T("Išsaugoti esamus failus prieš perrašant"), variable=self.keep_versions_var,
                               bg=WHITE, fg=INK, activebackground=WHITE, activeforeground=INK,
                               selectcolor=WHITE, font=(FONT, 11), anchor="w", highlightthickness=0)
        check.pack(anchor="w", pady=(12, 5))
        label(body, "Galioja kopijavimui ir atkūrimui. Valymo metu failai visada archyvuojami.", color=MUTED, size=9).pack(anchor="w", padx=3)
        label(body, "VERSIJŲ APLANKAS", size=9, color=MUTED, bold=True).pack(anchor="w", pady=(22, 7))
        folder_line = tk.Frame(body, bg=WHITE)
        folder_line.pack(fill="x")
        self.versions_var = PathTextVar(value=self.settings.versions_directory)
        ttk.Entry(folder_line, textvariable=self.versions_var, font=(FONT, 10)).pack(side="left", fill="x", expand=True)
        def choose():
            path = filedialog.askdirectory(title=T("Atskiras versijų aplankas"), mustexist=False, parent=self.root)
            if path:
                self.versions_var.set(path)
        button(folder_line, "Pasirinkti…", choose).pack(side="left", padx=(10, 0))
        label(body, "Tuščia reikšmė: aplankas šalia kopijos, pvz., Copy.versions. Archyvas turi būti už abiejų darbo aplankų.",
              color=MUTED, size=9, wraplength=760, justify="left").pack(anchor="w", pady=(8, 0))
        label(body, "SENŲ VERSIJŲ SAUGOJIMAS", size=9, color=MUTED, bold=True).pack(anchor="w", pady=(22, 7))
        retention = tk.Frame(body, bg=WHITE)
        retention.pack(fill="x")
        self.keep_runs_var = tk.StringVar(value=str(self.settings.keep_runs))
        self.keep_days_var = tk.StringVar(value=str(self.settings.keep_days))
        self.max_versions_var = tk.StringVar(value=str(self.settings.max_versions_gb))
        for index, (title, variable, maximum, unit) in enumerate((
            ("Visada palikti paskutines operacijas", self.keep_runs_var, 1000, ""),
            ("Laikyti ne senesnes nei", self.keep_days_var, 3650, "d."),
            ("Didžiausias archyvo dydis", self.max_versions_var, 10000, "GB"),
        )):
            label(retention, title, bold=True).grid(row=index, column=0, sticky="w", pady=6)
            ttk.Spinbox(retention, from_=0, to=maximum, textvariable=variable, width=6).grid(row=index, column=1, padx=(20, 6))
            label(retention, unit).grid(row=index, column=2, sticky="w")
            label(retention, "0 = neribota", color=MUTED, size=9).grid(row=index, column=3, sticky="w", padx=(14, 0))
        self.prune_prompt_var = tk.BooleanVar(value=self.settings.prune_prompt)
        tk.Checkbutton(body, text=T("Pasiūlyti išvalyti po operacijos"), variable=self.prune_prompt_var,
                       bg=WHITE, fg=INK, activebackground=WHITE, activeforeground=INK,
                       selectcolor=WHITE, font=(FONT, 11), anchor="w", highlightthickness=0).pack(anchor="w", pady=(12, 5))
        label(body, "Paskutinės nurodyto skaičiaus operacijos niekada netrinamos. Senesnės trinamos, jei viršija "
              "dienų arba dydžio ribą; jei šių ribų nenustatėte – trinamos visos senesnės. "
              "Programa niekada netrina versijų pati: jei archyvas viršija ribas, po operacijos parodoma peržiūra – "
              "trinama tik jums patvirtinus. Rankiniu būdu: Veiksmų istorija → „Tvarkyti versijas…“. "
              "Nebaigtos operacijos niekada netrinamos.",
              color=MUTED, size=9, wraplength=760, justify="left").pack(anchor="w", padx=3)
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=24)
        label(body, "Kopijavimo elgsena", size=17, bold=True).pack(anchor="w", pady=(0, 14))
        grid = tk.Frame(body, bg=WHITE)
        grid.pack(fill="x")
        self.workers_var = tk.StringVar(value=str(self.settings.workers))
        self.retries_var = tk.StringVar(value=str(self.settings.retries))
        for index, title, variable, maximum, hint in [
            (0, "Lygiagrečios užduotys", self.workers_var, 16, "Pradžiai rekomenduojama 4. Lėtam HDD galite rinktis 1–2."),
            (1, "Bandymų skaičius", self.retries_var, 5, "Laikinai nepavykusi operacija pakartojama su trumpa pauze."),
        ]:
            label(grid, title, bold=True).grid(row=index, column=0, sticky="w", pady=10)
            ttk.Spinbox(grid, from_=1, to=maximum, textvariable=variable, width=5).grid(row=index, column=1, padx=20)
            label(grid, hint, color=MUTED, size=9, wraplength=450, justify="left").grid(row=index, column=2, sticky="w")
        label(body, "Greita patikra naudoja ankstesnes sumas nepakitusiems failams. Pilna patikra skaito visus failus. Kopijos turinys tikrinamas po kiekvieno kopijavimo.",
              color=TEAL, bg=TEAL_LIGHT, padx=14, pady=12, size=9).pack(fill="x", pady=(20, 0))
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", pady=18)
        label(body, "Kalba ir išvaizda", size=17, bold=True).pack(anchor="w", pady=(0, 12))
        appearance = tk.Frame(body, bg=WHITE)
        appearance.pack(fill="x")
        self.language_var = tk.StringVar(value=self.settings.language)
        self.theme_var = tk.StringVar(value=self.settings.theme)
        for column, (title, variable, values) in enumerate((
            ("Kalba", self.language_var, (("lt", "Lietuvių"), ("en", "English"))),
            ("Aplinka", self.theme_var, (("light", "Šviesi"), ("dark", "Tamsi"))),
        )):
            group = tk.Frame(appearance, bg=WHITE)
            group.grid(row=0, column=column, sticky="w", padx=(0, 30))
            label(group, title, bold=True).pack(anchor="w", pady=(0, 7))
            for value, caption in values:
                radio = tk.Radiobutton(group, text=T(caption), variable=variable, value=value,
                               bg=WHITE, fg=INK, activebackground=WHITE, activeforeground=INK,
                               selectcolor=WHITE, highlightthickness=0, font=(FONT, 10))
                radio.pack(anchor="w", pady=2)
                if value == "dark":
                    self.settings_dark_radio = radio
        label(body, "Pakeitimai pritaikomi išsaugojus nustatymus.", color=MUTED, size=9).pack(anchor="w", pady=(10, 0))
        def wheel(event):
            direction = -1 if event.delta > 0 or getattr(event, "num", None) == 4 else 1
            self.settings_canvas.yview_scroll(direction, "units")
        def bind_wheel(widget):
            if not isinstance(widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
                widget.bind("<MouseWheel>", wheel, add="+")
                widget.bind("<Button-4>", wheel, add="+")
                widget.bind("<Button-5>", wheel, add="+")
            for child in widget.winfo_children():
                bind_wheel(child)
        bind_wheel(panel)
        bind_wheel(self.settings_canvas)

    def save_preferences(self):
        try:
            updated = replace(self.current_settings(), workers=int(self.workers_var.get()), retries=int(self.retries_var.get()),
                              keep_versions=self.keep_versions_var.get(), versions_directory=self.versions_var.get().strip(),
                              keep_runs=int(self.keep_runs_var.get() or 0), keep_days=int(self.keep_days_var.get() or 0),
                              max_versions_gb=int(self.max_versions_var.get() or 0), prune_prompt=self.prune_prompt_var.get(),
                              language=self.language_var.get(), theme=self.theme_var.get()).validate()
            save_settings(updated, self.data_directory)
            appearance_changed = (updated.language, updated.theme) != (self.settings.language, self.settings.theme)
            self.settings = updated
            if appearance_changed:
                self.apply_appearance()
            messagebox.showinfo(T("Išsaugota"), T("Nustatymai išsaugoti."), parent=self.root)
        except (ValueError, OSError) as error:
            messagebox.showerror(T("Patikrinkite nustatymus"), T(str(error)), parent=self.root)

    def apply_appearance(self):
        """Rebuild widgets on the Tk thread, preserving comparison and selection."""
        self.close_expanded_list()
        page = self.page
        set_appearance(self.settings.language, self.settings.theme)
        self.root.title(f"{APP_NAME}{T(' • Failų kopijos')}")
        self.root.configure(bg=BG)
        for widget in self.root.winfo_children():
            widget.destroy()
        self.setup_styles()
        self.build_shell()
        self.status_var.set("Turinys patikrintas. Pasirinkite failus; veiksmas rodomas paskutiniame stulpelyje."
                            if self.comparison else "Pasirinkite aplankus ir patikrinkite skirtumus.")
        if self.comparison and self.comparison.errors:
            self.status_var.set(f"Skaitymo klaidų: {len(self.comparison.errors)}" +
                                (". Veiksmai užblokuoti; sutvarkykite klaidas arba pridėkite išimtis."
                                 if self.comparison.blocked else "; šie elementai praleidžiami."))
        self.show_page(page)

    def build_history(self):
        self.history_reports = {}
        panel = card(self.content)
        panel.pack(fill="both", expand=True)
        toolbar = tk.Frame(panel, bg=WHITE)
        toolbar.pack(fill="x", padx=16, pady=14)
        label(toolbar, "OPERACIJŲ ŽURNALAS", size=9, color=MUTED, bold=True).pack(side="left")
        button(toolbar, "Atnaujinti", lambda: self.show_page("history")).pack(side="right")
        self.history_tree = ttk.Treeview(panel, columns=("date", "mode", "success", "errors", "state"), show="headings", height=7)
        for key, title, width in [("date", "LAIKAS", 170), ("mode", "VEIKSMAS", 180), ("success", "ATLIKTA", 90),
                                  ("errors", "KLAIDOS", 90), ("state", "REZULTATAS", 140)]:
            self.history_tree.heading(key, text=T(title), anchor="w")
            self.history_tree.column(key, width=width, anchor="w")
        self.history_tree.pack(fill="x", padx=16)
        self.history_tree.bind("<<TreeviewSelect>>", self.show_history_details)
        logs = self.data_directory / "logs"
        warnings = []
        for file in sorted(logs.glob("*.json"), reverse=True):
            try:
                report = json.loads(file.read_text(encoding="utf-8"))
                item = self.history_tree.insert("", "end", values=(report["started"].replace("T", " "),
                    T(HISTORY_LABELS.get(report["mode"], report["mode"])), report["completed"], report["failed"],
                    T({"completed": "Baigta", "completed_with_skips": "Baigta su praleidimais", "errors": "Yra klaidų", "cancelled": "Sustabdyta", "running": "Nebaigta / vykdoma"}.get(report["state"], report["state"]))))
                self.history_reports[item] = (report, file)
            except (OSError, ValueError, KeyError, TypeError) as error:
                warnings.append(f"{file.name}: {error}")
        self.history_detail = tk.Text(panel, font=(FONT, 10), bg=DETAIL_BG, fg=INK, insertbackground=INK,
                                      wrap="word", relief="flat", bd=0, padx=14, pady=14)
        self.history_detail.pack(fill="both", expand=True, padx=16, pady=16)
        empty_text = "Pasirinkite operaciją, kad pamatytumėte failus, rezultatą ir versijų aplanką." if self.history_reports else "Čia matysite atliktus kopijavimus, atkūrimus ir valymus.\n\nPirmiausia darbo lange patikrinkite skirtumus ir atlikite pasirinktus veiksmus."
        if warnings:
            empty_text += "\n\nNeperskaityti žurnalai:\n" + "\n".join(warnings)
        self.history_detail.insert("1.0", T(empty_text))
        self.history_detail.configure(state="disabled")
        controls = tk.Frame(self.content, bg=BG)
        # Reserve the button row first: on scaled displays the detail text would otherwise push it out of view.
        controls.pack(side="bottom", fill="x", pady=(16, 0), before=panel)
        button(controls, "Atverti operacijos versijas", self.open_history_archive, primary=True).pack(side="left")
        button(controls, "Tvarkyti versijas…", lambda: self.open_prune()).pack(side="left", padx=(10, 0))
        button(controls, "Eksportuoti žurnalą", self.export_history).pack(side="left", padx=10)
        button(controls, "Žurnalų aplankas", lambda: self.open_path(logs)).pack(side="left")

    def history_selection(self):
        selection = self.history_tree.selection()
        return self.history_reports.get(selection[0]) if selection else None

    def show_history_details(self, event=None):
        selected = self.history_selection()
        if not selected:
            return
        report, file = selected
        if report.get("mode") == "prune":
            content = [f"{T('Versijų aplankas: ')}{report.get('archive', '')}", ""]
        else:
            content = [f"{T('Šaltinis: ')}{report['source']}", f"{T('Kopija: ')}{report['destination']}",
                       f"{T('Versijų aplankas: ')}{report.get('archive') or T('Šiai operacijai versijų nebuvo')}", ""]
        content += [T(f"Atlikta: {report['completed']} | Klaidų: {report['failed']} | Praleista: {report['skipped']} | Sustabdyta: {report['cancelled']}"), ""]
        states = {"completed": "ATLIKTA", "failed": "KLAIDA", "skipped": "PRALEISTA", "cancelled": "SUSTABDYTA"}
        for item in report.get("items", []):
            content.append(f"{T(states.get(item['status'], item['status']))}  {item['path']}" + (f"\n    {T(item['message'])}" if item.get("message") else ""))
        if report.get("scan_skipped"):
            content.extend(["", T(f"Dėl skaitymo klaidų: {report['scan_skipped']}")])
            for item in report.get("scan_skipped_items", []):
                content.append(f"{T('Skaitymo klaida – praleisti')}  {item['path']}\n    {T(item['message'])}")
        self.history_detail.configure(state="normal")
        self.history_detail.delete("1.0", "end")
        self.history_detail.insert("1.0", display_text("\n".join(content)))
        self.history_detail.configure(state="disabled")

    def open_history_archive(self):
        selected = self.history_selection()
        if not selected:
            messagebox.showinfo(T("Pasirinkite operaciją"), T("Pažymėkite operaciją istorijos lentelėje."), parent=self.root)
        elif selected[0].get("archive"):
            self.open_path(selected[0]["archive"])
        else:
            messagebox.showinfo(T("Versijų nėra"), T("Šioje operacijoje nebuvo archyvuotų arba perrašytų failų su versijų išsaugojimu."), parent=self.root)

    def export_history(self):
        selected = self.history_selection()
        if not selected:
            messagebox.showinfo(T("Pasirinkite operaciją"), T("Pažymėkite operaciją istorijos lentelėje."), parent=self.root)
            return
        report, original = selected
        path = filedialog.asksaveasfilename(parent=self.root, title=T("Eksportuoti operacijos žurnalą"), defaultextension=".json",
                                           filetypes=[(T("JSON žurnalas"), "*.json")], initialfile=original.name)
        if path:
            try:
                Path(path).write_text(json.dumps(display_data(report), ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as error:
                messagebox.showerror(T("Eksportas nepavyko"), T(str(error)), parent=self.root)

    def close(self):
        if self.busy:
            if messagebox.askyesno(T("Vyksta operacija"), T("Sustabdyti vykdomą operaciją?\nLangas liks atidarytas, kol bus saugiai baigta stabdyti."), parent=self.root):
                self.cancel_work()
            return
        if self.prune_window is not None and self.prune_window.winfo_exists():
            if self.prune_window.busy():
                self.prune_window.reveal()
                self.prune_window.request_close()
                return
            self.prune_window.destroy_dialog()
        self.persist_settings()
        self.root.after_cancel(self.poll_id)
        if self.density_id is not None:
            self.root.after_cancel(self.density_id)
            self.density_id = None
        self.root.destroy()
