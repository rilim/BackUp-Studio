# BackUp Studio 2.6.0

A local Windows app for comparing folders, backing up selected files, restoring them and cleaning up the backup.

## Changes in 2.6.0

Scan differences now reuses separate SHA-256 hashes for source and backup files
whose identity, size and timestamps are unchanged. Cached files are still opened
and their first byte is read so newly inaccessible files are reported. New and
changed files are fully hashed. Full scan reads every file and refreshes the
cache; use it periodically to catch content changes that preserve metadata.
The first scan also reads every file. After an interrupted scan, the same button
offers Scan again. File-row checkboxes and icons have a 12-pixel internal inset.

## Earlier 2.5.0 changes

Backup, Restore and Backup cleanup share the same list layout. Restore options
and the cleanup explanation are inside the folder panel; compact statistics
leave more room for rows. Compact mode also considers actual remaining table
space. The list fills available space and scrolls without growing with its data;
Expand list still opens a separate resizable window. The fixed details strip
does not grow when a file is selected.

Both tables now use built-in icons for folders, PDF, documents, spreadsheets,
slides, text, images, audio, video, archives, code, applications and generic files.
Icons depend on the filename extension and do not open files or call the shell.
Unknown unreadable objects use a generic icon. Cached images are shared by rows.
The checkbox remains to the left of the type icon and path. Clicking an icon or
path focuses the row; the checkbox and Space toggle selection. Double-clicking
retains its previous behavior. Both themes/languages, filters, export, independent
column widths and horizontal scrolling remain. File-operation code is unchanged.

## Previous changes in 2.4.4

Fixed the column-controller event registration error that prevented 2.4.3 from
starting. Tk treats dot-prefixed binding tags as window names; the controller
now uses a unique class tag with a non-dot prefix. Column resizing is retained.

## Previous changes in 2.4.3

Dragging a separator resizes only that column in both file tables. Other widths
stay fixed; overflowing columns are accessible with horizontal scrolling. Widths
and horizontal position survive filtering, sorting, row selection and refreshes.
The main and expanded tables each remember their widths for the current session,
including page/theme changes and reopening the expanded list. A restart uses the
defaults. Initially the path column fills the viewport until any column is
manually resized; window resizing then preserves the user's chosen widths.

## Previous changes in 2.4.2

Sidebar navigation retains its background, text and border colors during scans
and file operations. The selected page stays highlighted and other pages keep
their usual colors. Navigation is still disabled while busy, in both themes.
Other disabled action buttons keep their existing styling.

## Previous changes in 2.4.1

Paths are displayed without the technical `\\?\` prefix in folder/exclusion
entries, progress, confirmations, issues, history, copied errors and exported
logs. UNC paths use the usual `\\server\share` form. Quoted/escaped paths inside
Windows errors are made readable too. Old history files are preserved; their
display and exported copy are cleaned. Internal long-path I/O and file-operation
behavior are unchanged.

## Previous changes in 2.4.0

Individual read errors no longer block other verified files. Unreadable entries
remain visible and disabled; use the Read issues filter or File details. An
unreadable branch and its parent directories are protected, while readable siblings
remain actionable. Root scan/identity failures still block the entire operation.

After a verified archive has been saved, Windows cleanup can clear a file's
read-only attribute and retry removal. Other flags and ACLs are preserved; if the
same file survives failure or cancellation, its read-only flag is restored.

The issues window has a scrollbar, error count and Copy errors button. The
exclusions window has search, both scrollbars and total/visible/selected counts.
Windows automatically excludes top-level System Volume Information and $RECYCLE.BIN
on both sides; these rules are displayed in the exclusions window. Nested ordinary
folders with these names are not automatically excluded.

History distinguishes scan-protected entries from execution failures and records
their paths/reasons. Unknown contents of an unreadable folder are not counted as
known files. Antivirus protection is never bypassed.

When the backup is an entire drive (e.g. `U:\`), choose a version folder outside
both working drives in Settings before archiving. Removing only empty folders
does not require an archive.

## Previous changes in 2.3.0

Exclusions now accept literal names such as `2010 - Yes [EP]`, Unicode and
punctuation without treating square brackets as patterns. Windows I/O uses a
consistent extended-path format for long paths. Archive containment no longer
compares inconsistent resolved forms of a missing file path. Shared archive
parents are created before parallel workers start. Symlink/junction checks remain.

An empty folder temporarily reported as nonempty is retried after checking its
contents again. Real remaining contents are preserved. Errors report the operation
stage and path; exported logs include system error codes. Failed archiving explains
why a parent folder was kept.

Extract the complete new ZIP into a separate folder. The app should display
**2.6.0**. Settings and existing backups are preserved. This code-only update reuses
the verified 2.2.0 launcher; its Windows file properties may retain that version.

## Start without installing Python

Extract **BackUp_Studio_Windows_x64.zip** completely, then open `BackUpStudio/BackUpStudio.exe`. Keep `_internal` next to the EXE. On Windows 10/11 x64, no Python installation is needed. Use `Demonstracija.bat` to try a temporary sample instead of your own folders.

## Choose the language and appearance

Open **Settings → Language and appearance**, select **English / Lithuanian** and **Light / Dark**, then click **Save settings**. The display changes immediately and your choices are remembered. An existing comparison and its selection stay in place when you change these preferences.
The settings pane scrolls when needed; **Save settings** stays visible at the bottom of the window.
Disabled buttons use a neutral background, readable text, a subtle border and the normal pointer in both themes. Enabled primary actions retain the teal accent.

## Back up, restore and clean up

1. Choose **Backup**, **Restore** or **Backup cleanup** in the sidebar.
2. Select the **Source** and **Backup** folders. Use **Edit exclusions** to omit specific folders and everything inside them on both sides.
3. Click **Scan differences**. Scanning reads and checks file contents without changing either folder.
4. Search or filter the results and select the items you want. The **When selected** column explains the planned action.
5. Click the action button at the bottom and review the confirmation before proceeding.

**Restore** offers missing files only or an option to overwrite existing files. **Backup cleanup** archives selected files before deleting them from the backup. It removes selected folders only when they are empty. **Activity history** shows results and archived versions.

Empty-folder deletion retries follow **Settings → Retry count**, including the first attempt. The default is 3 attempts, with 1- and 2-second pauses. Every attempt rechecks both roots, the target folder's identity and its absence from the source. New or unselected contents are preserved, and **Stop** interrupts the retry wait. Persistent access errors are reported; ACLs are never automatically changed. Read-only file handling is described above.

The version archive is placed next to the backup by default (for example, `Copy.versions`). You can change its location under **Settings**. Existing files can also be archived before overwriting. The program does not automatically delete old versions.

## Notes

**Expand list** opens a separate resizable/maximizable window. Search, filters,
sorting and checkmarks are shared with the main list; closing it preserves the
selection without rescanning. Switching workspace pages closes this window.
Use **File details** or Enter for details. Both lists scroll without growing with
the number of files. The main information strip has a stable height and scrolls
long descriptions, so selecting a file never shrinks the list. Dark-theme settings
arrows are larger, light-colored and highlighted on hover.

Quick scans reuse SHA-256 hashes where file metadata is unchanged; full scans
read contents on both sides. Selected files and new copies remain checked during
operations. Partial scan failures protect affected paths; root failures block
all actions. Backups stored on the same physical disk do not protect against disk
failure. The Windows EXE was built on Linux and has not been run on a Windows PC
in this environment.

The test suite covers file operations, paths, GUI logic and hash cache behavior.
Native Windows GUI execution still needs verification there.
New GUI cases cover equal list height across modes/themes/languages and icon/
mouse behavior in both tables. These visual integration checks were not run here.

For complete details, see `Naudojimo_instrukcija.md` (Lithuanian). Source users can run `python main.py` with Python 3.10+ and Tkinter; the Windows EXE package includes its own runtime.
