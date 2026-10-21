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
from utils import (MODE_LABELS, STATUS_LABELS, export_csv, format_date, format_size as _format_size,
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
        self.geometry("820x640")
        self.minsize(720, 570)
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
        self.window.geometry("1200x760")
        self.window.minsize(850, 480)
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
        self.root = root
        self.settings = settings
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
        width = min(1440, max(1100, root.winfo_screenwidth() - 80))
        height = min(980, max(760, root.winfo_screenheight() - 80))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1100, 760)
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
                        foreground=INK, borderwidth=0, rowheight=38)
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
        sidebar = tk.Frame(self.root, bg=NAV, width=212)
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

    def filter_changed(self):
        display = self.filter_display_var.get()
        for key in ("Visi skirtumai", "Nauji šaltinyje", "Pakeisti", "Tik kopijoje",
                    "Vienodi", "Konfliktai", "Skaitymo problemos", "Pažymėti", "Visi elementai"):
            if T(key) == display and self.filter_var.get() != key:
                self.filter_var.set(key)
                break

    def build_workspace(self):
        self.workspace_controls = []
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
            label(cell, title, size=9, color=MUTED, bold=True).pack(anchor="w", pady=(0, 7))
            field = tk.Frame(cell, bg=WHITE)
            field.pack(fill="x")
            entry = ttk.Entry(field, textvariable=variable, font=(FONT, 10))
            entry.pack(side="left", fill="x", expand=True)
            browse = button(field, "…", lambda var=variable: self.browse_root(var))
            browse.pack(side="left", padx=(6, 0))
            self.workspace_controls.extend([entry, browse])
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
        self.scan_button = button(bottom, "Tikrinti skirtumus", self.start_scan, primary=True)
        self.scan_button.pack(side="right")
        self.workspace_controls.append(self.scan_button)
        self.full_scan_button = button(bottom, "Pilna patikra", lambda: self.start_scan(full=True))
        self.full_scan_button.pack(side="right", padx=(0, 8))
        self.workspace_controls.append(self.full_scan_button)
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
        for index, (key, title, color, filter_text) in enumerate([
            ("source_only", "NAUJI ŠALTINYJE", TEAL, "Nauji šaltinyje"),
            ("modified", "PAKEISTI", AMBER, "Pakeisti"),
            ("destination_only", "TIK KOPIJOJE", STATUS_BLUE, "Tik kopijoje"),
            ("identical", "VIENODI", MUTED, "Vienodi"),
        ]):
            stats.columnconfigure(index, weight=1, uniform="stats")
            stat_card = card(stats)
            stat_card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0 if index == 3 else 6))
            value = label(stat_card, "—", size=24, bold=True, color=color)
            value.pack(anchor="w", padx=15, pady=(10, 0))
            caption = label(stat_card, title, size=8, color=MUTED, bold=True)
            caption.pack(anchor="w", padx=15, pady=(0, 12))
            for widget in (stat_card, value, caption):
                widget.bind("<Button-1>", lambda event, val=filter_text: self.filter_var.set(val))
                widget.configure(cursor="hand2")
            self.stat_values[key] = value
            self.stat_captions[key] = caption
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
        definitions = [("check", "✓", 36, "center"), ("relative", "FAILAS / APLANKAS", 295, "w"),
                       ("status", "BŪSENA", 145, "w"), ("source", "ŠALTINIS", 113, "e"),
                       ("destination", "KOPIJA", 113, "e"), ("action", "PAŽYMĖJUS", 170, "w")]
        for key, title, width, anchor in definitions:
            self.tree.heading(key, text=T(title), anchor=anchor,
                              command=lambda col=key: self.select_visible() if col == "check" else self.sort_rows(col))
            minimum = {"check": 36, "relative": 210, "status": 95, "source": 72, "destination": 72, "action": 100}[key]
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
        compact = self.root.winfo_height() < 880
        if self.page in MODE_LABELS and self.tree.winfo_exists() and self.tree.winfo_height() > 1:
            # Use the actual table allocation as well as the window height (DPI,
            # translated text and footer wrapping all affect the available space).
            heading = tkfont.Font(family=FONT, size=9, weight="bold").metrics("linespace") + 24
            target = heading + 5 * 38
            threshold = target + (120 if self.compact else 0)
            compact = compact or self.tree.winfo_height() < threshold
        if compact != self.compact:
            self.compact = compact
            self.apply_density()

    def apply_density(self):
        """Keep the file table usable on laptop screens with limited height."""
        workspace = self.page in MODE_LABELS
        self.main.pack_configure(pady=12 if self.compact or workspace else 24)
        self.header.pack_configure(pady=(0, 10 if workspace else 18))
        self.heading_label.configure(font=(FONT, 21 if self.compact else 25, "bold"))
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
        self.poll_id = self.root.after(75, self.poll_events)

    def show_errors(self, errors):
        dialog = tk.Toplevel(self.root)
        dialog.title(T("Patikrinkite šias problemas"))
        dialog.geometry("800x390")
        dialog.minsize(600, 320)
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
                    T(MODE_LABELS.get(report["mode"], report["mode"])), report["completed"], report["failed"],
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
        controls.pack(fill="x", pady=(16, 0))
        button(controls, "Atverti operacijos versijas", self.open_history_archive, primary=True).pack(side="left")
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
        content = [f"{T('Šaltinis: ')}{report['source']}", f"{T('Kopija: ')}{report['destination']}",
                   f"{T('Versijų aplankas: ')}{report.get('archive') or T('Šiai operacijai versijų nebuvo')}", "",
                   T(f"Atlikta: {report['completed']} | Klaidų: {report['failed']} | Praleista: {report['skipped']} | Sustabdyta: {report['cancelled']}"), ""]
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
        self.persist_settings()
        self.root.after_cancel(self.poll_id)
        if self.density_id is not None:
            self.root.after_cancel(self.density_id)
            self.density_id = None
        self.root.destroy()
