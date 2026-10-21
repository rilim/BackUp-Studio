"""Small built-in file icons; no shell calls, file reads or extra dependencies."""
from pathlib import PureWindowsPath
import tkinter as tk


EXTENSIONS = {
    "pdf": "pdf",
    "word": "doc docx docm odt rtf pages",
    "sheet": "xls xlsx xlsm xlsb ods csv tsv numbers",
    "slides": "ppt pptx pptm odp key",
    "text": "txt md markdown log rst ini cfg conf",
    "image": "jpg jpeg png gif bmp webp tiff tif svg ico heic heif raw",
    "audio": "mp3 wav flac aac ogg opus m4a wma aiff",
    "video": "mp4 mkv avi mov wmv webm m4v mpg mpeg ts",
    "archive": "zip rar 7z tar gz bz2 xz tgz zst cab iso",
    "code": "py pyw js ts jsx tsx html htm css scss json xml yaml yml c cpp h hpp cs java rs go sh ps1 bat cmd sql",
    "app": "exe msi msix dll com app apk",
}
SUFFIX_TYPES = {suffix: category for category, suffixes in EXTENSIONS.items()
                for suffix in suffixes.split()}
COLORS = {"folder": "#C48A23", "file": "#647985", "pdf": "#C54D52",
          "word": "#3975BA", "sheet": "#318563", "slides": "#BF6837",
          "text": "#647985", "image": "#31879C", "audio": "#8563B7",
          "video": "#9D5A9B", "archive": "#A67B35", "code": "#42868B", "app": "#637AB0"}


def file_type(name, kind="file"):
    if kind == "directory":
        return "folder"
    if kind != "file":
        return "file"  # An unreadable object's type must not be guessed.
    return SUFFIX_TYPES.get(PureWindowsPath(name).suffix.lstrip(".").casefold(), "file")


def icon_pixels(category, mark, dark=False):
    """48×22 transparent pixels: checkbox, gap, type icon. Pure and testable."""
    pixels = [[None] * 48 for _ in range(22)]
    def rect(x0, y0, x1, y1, color):
        for y in range(y0, y1):
            for x in range(x0, x1):
                pixels[y][x] = color
    def line(points, color):
        for x, y in points:
            rect(x, y, x + 1, y + 1, color)
    border = "#B4C2CA" if dark else "#586870"
    accent = "#5AD4C1" if dark else "#117D71"
    if mark == "—":
        rect(3, 10, 13, 12, border)
    else:
        rect(1, 3, 16, 4, border)
        rect(1, 17, 16, 18, border)
        rect(1, 3, 2, 18, border)
        rect(15, 3, 16, 18, border)
        if mark == "☑":
            line([(4, 10), (5, 11), (6, 12), (7, 13), (8, 12), (9, 11),
                  (10, 10), (11, 9), (12, 8), (13, 7)], accent)
            line([(4, 11), (5, 12), (6, 13), (7, 14), (8, 13), (9, 12),
                  (10, 11), (11, 10), (12, 9), (13, 8)], accent)
    color = COLORS.get(category, COLORS["file"])
    white = "#FFFFFF"
    if category == "folder":
        rect(25, 5, 33, 8, color)
        rect(25, 8, 46, 19, color)
        rect(26, 9, 45, 11, "#E7B85E")
        return pixels
    rect(28, 2, 40, 20, color)
    rect(40, 6, 45, 20, color)
    for i in range(4):
        rect(40, 2 + i, 41 + i, 3 + i, "#CAD7DF")
    if category in ("file", "text"):
        for y in (9, 12, 15):
            rect(31, y, 41 if y != 15 else 38, y + 1, white)
    elif category == "sheet":
        for y in (8, 12, 16):
            rect(31, y, 42, y + 1, white)
        for x in (31, 36, 41):
            rect(x, 8, x + 1, 17, white)
    elif category in ("video", "slides"):
        for i in range(5):
            rect(33, 8 + i, 34 + i, 9 + i, white)
        for i in range(4):
            rect(33, 13 + i, 37 - i, 14 + i, white)
    elif category == "image":
        rect(38, 7, 41, 10, white)
        for i in range(5):
            rect(31, 15 - i, 32 + i, 16 - i, white)
            rect(35, 16 - i, 42 - i, 17 - i, white)
    elif category == "audio":
        rect(34, 8, 36, 16, white)
        rect(35, 7, 41, 9, white)
        rect(39, 8, 41, 15, white)
        rect(31, 14, 36, 17, white)
        rect(37, 13, 41, 16, white)
    elif category == "archive":
        for y in range(6, 16, 2):
            rect(35 + (y // 2) % 2, y, 37 + (y // 2) % 2, y + 2, white)
        rect(35, 16, 39, 18, white)
    elif category == "code":
        line([(33, 9), (32, 10), (31, 11), (32, 12), (33, 13),
              (39, 9), (40, 10), (41, 11), (40, 12), (39, 13),
              (37, 8), (37, 9), (36, 10), (36, 11), (35, 12), (35, 13), (35, 14)], white)
    elif category == "app":
        for x in (31, 37):
            for y in (8, 14):
                rect(x, y, x + 4, y + 4, white)
    else:
        glyph = {"pdf": ("1110", "1001", "1110", "1000", "1000"),
                 "word": ("10001", "10001", "10101", "10101", "01010")}[category]
        for y, row in enumerate(glyph):
            for x, bit in enumerate(row):
                if bit == "1":
                    rect(31 + x * 2, 8 + y * 2, 33 + x * 2, 10 + y * 2, white)
    return pixels


class FileIcons:
    """Reuse a bounded number of images even for thousands of rows."""
    def __init__(self, master, dark=False):
        self.master, self.dark, self.cache = master, dark, {}

    def get(self, name, kind, mark):
        key = (file_type(name, kind), mark)
        if key not in self.cache:
            # Inset row contents inside the tree cell, without moving its frame.
            image = tk.PhotoImage(master=self.master, width=60, height=22)
            for y, row in enumerate(icon_pixels(*key, self.dark)):
                for x, color in enumerate(row):
                    if color is not None:
                        image.put(color, (x + 12, y))
            self.cache[key] = image
        return self.cache[key]
