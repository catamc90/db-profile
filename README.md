# DB Profile

A simple Navicat-style MySQL / MariaDB client for Linux, written in Python with PyQt6 and PyMySQL.

## Run

```bash
./run.sh                      # creates .venv on first run
./install-desktop-entry.sh    # optional: add to the application menu
```

## Features (v0.1)

- **Connections**: save, edit, delete and test connections. They are stored in `~/.config/dbprofile/connections.json` with mode 600. Untick "Save password" to be asked for the password each time.
- **Object tree**: connection → databases → tables and views, loaded when you expand a node. Right-click to create or drop a database, or to truncate or drop a table.
- **Objects tab**: a permanent first tab. Selecting a database in the tree lists its tables and views here, with row count, engine, size, last update, collation and comment. You can sort, filter by name, and select several tables to open them all into tabs at once (double-click, Enter, or right-click).
- **Tabs**: each table opens once; opening it again switches to its existing tab. Middle-click a tab to close it. Right-click the tab bar for Close, Close Others, Close Tabs to the Right and Close All. Tabs with unsaved edits ask before closing.
- **Query editor**: SQL highlighting and line numbers. Run with **Ctrl+Enter** or **F5**; with text selected, only the selection runs. A script with several statements gets one result tab per SELECT. Stop cancels the running query with `KILL QUERY`. Results are capped at 10,000 rows.
- **Table viewer**: paged data with WHERE and ORDER BY filters. Edit cells, add rows, delete rows and set NULL, then save everything in one transaction or discard it. Also shows the Structure and DDL tabs. Editing needs a primary key; views are read-only.
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
| `dbprofile/query_tab.py` | SQL editor tab |
| `dbprofile/table_tab.py` | table data / structure / DDL tab |
| `dbprofile/result_view.py` | results grid and editable model |
| `dbprofile/sql_editor.py` | editor widget and highlighter |
| `dbprofile/theme.py` | flat Navicat-like stylesheet and palette |
| `dbprofile/icons.py` | flat vector icons drawn with QPainter |
| `dbprofile/worker.py` | runs queries off the UI thread |
