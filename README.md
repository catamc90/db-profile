# DB Profile

A simple Navicat-style MySQL / MariaDB client for Linux, written in Python with PyQt6 and PyMySQL.

## Run

```bash
./run.sh                      # creates .venv on first run
./install-desktop-entry.sh    # optional: add to the application menu
```

## Features (v0.1)

- **Connections**: save, edit, delete and test connections. They are stored in `~/.config/dbprofile/connections.json` with mode 600. Untick "Save password" to be asked for the password each time.
- **Import / Export Connections** (File menu, or right-click the connection list):
  - Imports **Navicat `.ncx` files**, including saved passwords from Navicat 12 and later (AES) and Navicat 11 and earlier (Blowfish). MySQL and MariaDB connections are imported; other types are listed and skipped.
  - Tunnels (SSH, HTTP) and SSL settings are not imported; the import list flags each affected connection.
  - Existing connections can be skipped, renamed or replaced.
  - Exports to `.ncx`, which Navicat can import, or to DB Profile `.json`. Export files are saved with mode 600.
- **Object tree**: connection → databases → **Tables / Views / Functions / Queries** groups, like Navicat, loaded when you expand a node. Right-click to create or drop a database, or to truncate or drop a table.
- **Objects tab**: a permanent first tab. Selecting a database in the tree lists its tables and views here, with row count, engine, size, last update, collation and comment. You can sort, filter by name, and select several tables to open them all into tabs at once (double-click, Enter, or right-click).
- **Tabs**: each table opens once; opening it again switches to its existing tab. Middle-click a tab to close it. Right-click the tab bar for Close, Close Others, Close Tabs to the Right and Close All. Tabs with unsaved edits ask before closing.
- **Functions**: the Function toolbar button or the Functions group lists functions and stored procedures, with return type, determinism, security, definer and dates.
  - The designer tab edits the `CREATE` statement. **Save** (Ctrl+S) replaces the routine, and if the new version fails, the previous one is put back.
  - **Execute** (F5) asks for the parameter values and runs `SELECT fn(...)` or `CALL proc(...)`. Each result set gets its own tab, and OUT/INOUT values are shown afterwards.
  - **New Function** starts from a function or procedure template.
- **Saved queries**: each database has a **Queries** group, and the Query toolbar button lists them in the Objects tab with their modified date and size.
  - In a query tab, **Save** (Ctrl+S) stores the SQL under a name in the database chosen in the toolbar; **Save As…** (Ctrl+Shift+S) saves a copy, also into another database. Unsaved edits show a `*` in the tab title, and closing asks to save them.
  - Double-click a query to open it (it opens once, like tables). Right-click to rename or delete; several can be deleted at once from the Objects tab.
  - Queries are plain `.sql` files in `~/.config/dbprofile/queries/<connection>/<database>/`. Deleting a connection keeps its saved queries, unless you tick “Also delete its saved queries” in the confirmation.
- **Users**: the User toolbar button, or right-click a connection → Users.
  - The list shows each account's host, authentication plugin, and locked/expired status.
  - The user editor has **General** (name, host, password, account lock), **Server Privileges** (`ON *.*`, plus Grant Option), **Privileges** and **SQL Preview** tabs. Privileges are grouped (Data, Structure, Routines & Events, Other, Administration), each group with a select-all box. Quick-set buttons (Read Only, Read/Write, All, None) and search are available, and changes are shown in blue until saved. The Privileges tab lists the databases on the left with a summary of the access to each, and edits the selected one on the right. Only the differences are applied, as `CREATE/RENAME/ALTER USER`, `GRANT` and `REVOKE`.
- **Query editor**: SQL highlighting and line numbers. Run with **Ctrl+Enter** or **F5**; with text selected, only the selection runs. A script with several statements gets one result tab per SELECT. `DELIMITER $$` lines work as in the mysql client, so you can create routines with `BEGIN … END` bodies, and `CALL` shows every result set. Stop cancels the running query with `KILL QUERY`. Results are capped at 10,000 rows.
- **Table viewer**: paged data with WHERE and ORDER BY filters. Edit cells, add rows, delete rows and set NULL, then save everything in one transaction or discard it. Also shows the Structure and DDL tabs. Editing needs a primary key; views are read-only.
- **Export Wizard** (Objects toolbar, right-click a database or table, the table tab's Export button, or Export Result in a query tab):
  - Pick a format: CSV, TXT, JSON, XML, HTML, Excel (.xlsx) or SQL INSERT script.
  - Pick the tables and an output folder, then set the format options (delimiter, text qualifier, line endings, encoding, NULL text, header row; CREATE/DROP TABLE and records per INSERT for SQL).
  - Rows are streamed from the server, so big tables don't load into memory. A progress bar and log show the run.
- **Import Wizard**:
  - Import from CSV, TXT, JSON or Excel, with a live preview.
  - Import into an existing table, or a new one with column types guessed from the data.
  - Map fields by name.
  - Navicat's import modes: **Append, Update, Append/Update, Delete, Copy**. Options: empty values as NULL, a transaction (all or nothing), or continue on error (bad records are skipped and logged).
- **Dump SQL File** (right-click a database): structure and data, or structure only, of tables, views, functions and procedures. **Execute SQL File** (right-click a connection or database) runs a `.sql` file, such as a dump, with progress.
- **Results grid**: copy cells as TSV with Ctrl+C, or right-click to export to CSV.

## Look

A flat light theme modeled on Navicat, with no gradients and no shadows. It uses the Qt Fusion style with a custom palette and stylesheet (`dbprofile/theme.py`). The icons are flat and drawn in code (`dbprofile/icons.py`), so they stay sharp at any size and need no image files.

## Layout

| File | Purpose |
|---|---|
| `dbprofile/db.py` | connecting, SQL splitting, running queries |
| `dbprofile/config.py` | saved connection profiles |
| `dbprofile/main_window.py` | window, object tree, tabs |
| `dbprofile/objects_tab.py` | Objects list of the selected database |
| `dbprofile/routine_tab.py` | function / procedure designer and executor |
| `dbprofile/users_tab.py` | user list and user / privilege editor |
| `dbprofile/query_tab.py` | SQL editor tab |
| `dbprofile/table_tab.py` | table data / structure / DDL tab |
| `dbprofile/result_view.py` | results grid and editable model |
| `dbprofile/sql_editor.py` | editor widget and highlighter |
| `dbprofile/theme.py` | flat Navicat-like stylesheet and palette |
| `dbprofile/icons.py` | flat vector icons drawn with QPainter |
| `dbprofile/transfer.py` | import / export engine: formats, dump, import modes |
| `dbprofile/transfer_wizards.py` | Import / Export wizards, dump and SQL file dialogs |
| `dbprofile/worker.py` | runs queries off the UI thread |
