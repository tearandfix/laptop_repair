# Laptop Repair Manager

A web-based application for tracking broken laptops purchased on eBay, their journey to Ukraine, repair costs, parts inventory, and resale profit. Designed to run as a **Home Assistant add-on** with sidebar access through **Ingress**, or as a standalone local application.

All purchases and sales are entered manually. The initial currency is **Ukrainian hryvnia (UAH)**.

**Version 1.0.0:** The application and Home Assistant add-on package are implemented. See [Run locally](#run-locally) to try it, or [Install in Home Assistant](#install-in-home-assistant) for deployment.

## Contents

- [Features](#features)
- [Laptop records and statuses](#laptop-records-and-statuses)
- [Parts inventory](#parts-inventory)
- [Costs and profit](#costs-and-profit)
- [Attachments](#attachments)
- [Application screens](#application-screens)
- [Install in Home Assistant](#install-in-home-assistant)
- [Run locally](#run-locally)
- [Run with Docker](#run-with-docker)
- [Configuration and storage](#configuration-and-storage)
- [Backups and recovery](#backups-and-recovery)
- [Architecture](#architecture)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Initial scope](#initial-scope)

## Features

- Create, view, edit, and delete laptop records.
- Manually change laptop status at any point in the repair/resale process.
- Search laptops by title and filter by status.
- Maintain a separate parts inventory with quantities and unit prices.
- Assign parts to laptops and automatically deduct stock.
- Return stock when a repair-part assignment is reduced or removed.
- Preserve assigned part prices so later inventory price changes do not rewrite repair costs.
- Upload and download documents, invoices, receipts, and photos for each laptop.
- Calculate repair costs, total costs, and profit automatically.
- View aggregate spending, available stock value, sales revenue, and realized profit.
- Store data persistently in SQLite and an attachments directory.
- Access the application through Home Assistant Ingress without a separate application login.

## Laptop records and statuses

Each laptop has the following information:

| Field | Description |
| --- | --- |
| Title | Required descriptive name, such as `Lenovo ThinkPad T480 — no power`. |
| Purchase price | Amount paid for the laptop in UAH, including any purchasing fees. |
| Shipping cost | Total shipping cost in UAH, entered separately from purchase price. |
| Status | One of the eight statuses below; defaults to `purchased`. |
| Repair parts | Assigned inventory parts, quantities, and recorded unit prices. |
| Attached files | Uploaded documents and photos associated with this laptop. |
| Resale price | Optional sale amount in UAH; leave empty until known. |
| Notes | Optional free-text repair notes or purchase details. |
| eBay URL | Optional link to the original listing. |

### Statuses

The stored status values are exactly:

1. `purchased`
2. `shipped_usa`
3. `np_accepted`
4. `shipped_ua`
5. `delivered`
6. `fixed`
7. `listed`
8. `sold`

The interface presents readable labels, such as “Shipped USA” and “NP accepted.” A dropdown allows any status to be selected manually: stages may be skipped, and a record may be moved backwards. Status changes do not change inventory quantities or set a resale price automatically.

Deleting a laptop returns its assigned parts to stock and removes its attachment records and files. The interface asks for confirmation before deletion.

## Parts inventory

Each inventory item contains:

| Field | Description |
| --- | --- |
| Title | Required part name. |
| Unit price | Cost of one unit in UAH. |
| Comment | Optional description, compatibility information, or supplier notes. |
| Stock quantity | Non-negative whole number of currently available, unassigned units. |

Stock can be edited to record new purchases or correct an inventory count. The quantity entered is the **available quantity**, not the total quantity including parts already installed in laptops.

### Assignment rules

- Assigning `N` units to a laptop deducts `N` from available stock.
- An assignment requires a positive whole-number quantity and enough available stock.
- Increasing an assignment deducts the additional quantity; decreasing it returns the difference.
- Removing an assignment returns its entire quantity to stock.
- Changes are made within a database transaction to prevent overselling during simultaneous requests.
- Editing a stale inventory form is rejected if its stock or details changed after the form was opened. Reload the record before saving again.
- Each new assignment records the part's current unit price and title. Later edits to the inventory item do not change that assignment's recorded cost or name.
- Updating an existing assignment's quantity preserves its recorded unit price. To use a new price, add a separate assignment.
- The same inventory item may appear in more than one assignment on a laptop, allowing different recorded prices.
- Inventory items that have never been assigned can be permanently deleted.
- An item referenced by an assignment is archived when deleted. Its history remains accessible through the laptop, but it cannot be assigned again until restored.
- Archived items can be restored from the inventory screen. Returning assigned stock to an archived item increases its quantity without automatically restoring it.

The application tracks quantities and per-assignment costs, not individual part serial numbers or purchase batches.

## Costs and profit

Amounts are stored as **integer kopiykas** and displayed as UAH with two decimal places. Calculations do not use binary floating-point money values.

```text
Repair cost = sum(assigned quantity × recorded unit price)

Total cost = purchase price + shipping cost + repair cost

Profit = resale price − total cost
```

Purchasing fees are included in the entered purchase price. There is no separate fee calculation or automatic currency conversion.

### Example

| Item | Amount |
| --- | ---: |
| Purchase price | 4,000.00 UAH |
| Shipping cost | 800.00 UAH |
| SSD: 1 × 650.00 UAH | 650.00 UAH |
| RAM: 2 × 300.00 UAH | 600.00 UAH |
| **Total cost** | **6,050.00 UAH** |
| Resale price | 8,000.00 UAH |
| **Profit** | **1,950.00 UAH** |

- An empty resale price means profit is unknown, displayed as a dash. A resale price of zero is a valid entered value.
- A laptop can show calculated profit before it is marked `sold`; dashboard **realized profit** only includes sold laptops with a resale price entered.
- Sold laptops without a resale price are highlighted so missing amounts are visible.
- Dashboard **sales revenue** sums entered resale prices for sold laptops.
- Dashboard **recorded laptop costs** sums purchase, shipping, and assigned-parts costs across all laptop records.
- Dashboard **unsold laptop investment** sums those costs for laptops not marked `sold`.
- Dashboard **available stock value** sums available quantity × current unit price, including archived stock. This is an inventory valuation, not a record of cash purchases.

## Attachments

Upload one or more files from a laptop's detail page. Each attachment shows its original filename and size, and supports downloading and deletion.

- Files are stored with generated identifiers; user-provided names are not used as storage paths.
- Downloads are served as attachments rather than executing uploaded content in the browser.
- Maximum file size: **20 MiB per file**.
- Upload up to **10 files at once**. If any file exceeds the limit, the entire upload is rejected without saving a partial batch.
- Original filenames are preserved for display and downloads.
- Files and their metadata persist across application restarts and add-on updates.

## Application screens

### Dashboard

Summary cards show laptop count, unsold laptop investment, recorded laptop costs, available stock value, sales revenue, and realized profit. Status counts link to the corresponding filtered laptop list.

### Laptops

A searchable, status-filtered list shows each laptop's title, status, purchase price, shipping, repair cost, total cost, resale price, and profit. Select a record to edit its details, assign parts, or manage attachments.

### Parts inventory

View active or archived items, search titles and comments, add new inventory items, edit prices and stock, and delete/archive or restore items.

The layout is responsive for desktop and mobile browsers. All assets are served locally; no external CDN is required.

## Install in Home Assistant

Requires a Home Assistant installation with **Supervisor and add-on support**, such as Home Assistant OS. A Home Assistant Container installation can instead run this application separately with Docker.

### Local add-on installation

1. Copy the complete `laptop_repair` directory from this project into Home Assistant's local add-ons directory:

   ```text
   /addons/laptop_repair/
   ```

   The copied directory must contain `config.yaml`, `Dockerfile`, `requirements.txt`, and `app/`.

2. Open **Settings → Add-ons → Add-on Store** and check for updates/reload the store.
3. Find **Laptop Repair Manager** under local add-ons and select **Install**.
4. Start the add-on and enable **Start on boot** if desired.
5. Select **Open Web UI**, or enable **Show in sidebar**.

The add-on builds locally for `amd64` and `aarch64`. The application listens internally on port `8099`. Ingress is enabled, and no host port is published by default.

The add-on does not require access to Home Assistant's API or devices. Its database, attachments, and session-signing secret live in its persistent `/data` directory.

### Updates

Back up the add-on, replace the local add-on source with the new version, reload the store, and rebuild/update it using Home Assistant. Do not remove its persistent data. See [Backups and recovery](#backups-and-recovery).

## Run locally

Requires Python **3.11 or later**.

From the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r laptop_repair/requirements.txt
DATA_DIR="$PWD/data" .venv/bin/python -m uvicorn app.main:app \
  --app-dir laptop_repair --host 127.0.0.1 --port 8099
```

Open **http://127.0.0.1:8099**.

The database schema and upload directory are initialized automatically on startup. No external database service is needed.

For development, add `--reload` to the Uvicorn command.

## Run with Docker

From the project root:

```sh
docker build -t laptop-repair-manager ./laptop_repair
docker run --detach --name laptop-repair-manager \
  --publish 127.0.0.1:8099:8099 \
  --volume laptop-repair-data:/data \
  laptop-repair-manager
```

Open **http://127.0.0.1:8099**. The named Docker volume retains data when the container is replaced.

To follow logs:

```sh
docker logs --follow laptop-repair-manager
```

Home Assistant Ingress supplies authenticated access. Standalone mode has no built-in user accounts; the examples bind to localhost. For remote standalone access, put it behind an authenticated reverse proxy.

## Configuration and storage

| Setting | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `/data` | Directory for persistent application data. Set to a writable local directory when running outside Docker. |
| Internal HTTP port | `8099` | Container/Ingress listener. Local Uvicorn commands may choose another port. |
| Currency | `UAH` | Fixed for the initial release. |
| Attachment limit | `20 MiB` | Maximum size of each uploaded file. |

Storage layout:

```text
/data/
├── laptop_repair.sqlite3    # Laptop, parts, assignment, and attachment metadata
├── session.key             # Persistent cookie-signing secret
└── uploads/                # Uploaded files, stored under generated names
```

Ingress-aware links, form submissions, redirects, and asset URLs respect Home Assistant's `X-Ingress-Path` header. Forms include CSRF tokens, and database operations use parameterized SQL.

## Backups and recovery

### Home Assistant

Include **Laptop Repair Manager** in your Home Assistant backups. The add-on requests a cold backup so its database and uploaded files are copied consistently while it is stopped. Restore the add-on and its data together through Home Assistant's backup interface.

### Standalone

1. Stop the application/container.
2. Back up the **entire data directory or Docker volume**, including the SQLite database, `uploads/`, and `session.key`.
3. Restart the application.

To restore, stop the application, replace its data with the backed-up contents, ensure the files are writable by the application, and start it again.

Backing up only the database does not back up attachments. CSV exports and automated off-site backups are outside the initial scope.

## Architecture

- **Backend:** Python and FastAPI.
- **Views:** Jinja2 server-rendered HTML with standard forms and a small local JavaScript helper for confirmation dialogs.
- **Styling:** Local responsive CSS.
- **Database:** SQLite with foreign-key checks and transactional stock adjustments.
- **HTTP server:** Uvicorn.
- **Deployment:** Docker image packaged as a Home Assistant add-on.

Server-rendered forms keep this first release lightweight without requiring a frontend build tool or external JavaScript framework.

Project layout:

```text
.
├── README.md
├── requirements-dev.txt
├── pytest.ini
├── ruff.toml
├── tests/
└── laptop_repair/
    ├── config.yaml
    ├── Dockerfile
    ├── requirements.txt
    ├── requirements.in
    ├── DOCS.md
    └── app/
        ├── __init__.py
        ├── main.py
        ├── db.py
        ├── services.py
        ├── templates/
        └── static/
```

### Data model

- `laptops`: editable purchase/sale details and status.
- `parts`: inventory details, available stock, and archive flag.
- `laptop_parts`: laptop/part references, quantity, and snapshots of assigned title/unit price.
- `attachments`: laptop reference, original filename, generated storage name, and file size.

Laptop totals are calculated from assignments rather than saved as independently editable totals. Stock mutations and their associated assignment changes commit or roll back together.

## Development and testing

Install development dependencies and run tests from the project root:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check laptop_repair/app tests
```

Tests use isolated temporary data directories. The verification suite covers:

- Exact UAH arithmetic, including empty and zero resale prices.
- Stock assignment, quantity changes, returns, and insufficient-stock rejection.
- Historical assignment prices after inventory edits.
- Archiving/restoring referenced inventory items.
- Laptop deletion returning stock and removing attachments.
- All eight statuses and manual out-of-order changes.
- Upload/download behavior and file-size limits.
- Ingress-prefixed URLs and redirects.
- CSRF protection and validation errors.
- Dashboard revenue/profit rules.

Runtime dependencies, including transitive dependencies, are pinned in `laptop_repair/requirements.txt`; direct dependency ranges live in `requirements.in`. To refresh the lock using [uv](https://docs.astral.sh/uv/), run:

```sh
uv pip compile laptop_repair/requirements.in --python-version 3.11 \
  --output-file laptop_repair/requirements.txt
```

Run the tests after updating dependencies. The Docker image uses Python 3.13. Run one application process against each data directory; the provided Uvicorn command uses one worker.

### Initial release verification

- **42 automated tests passed** on Python 3.13, covering the workflows above.
- A real Chromium walkthrough verified creating a part and laptop, assigning stock, uploading a file, recording a sale, and displaying the calculated profit.
- Desktop and mobile layouts were checked at 1440 px and 390 px viewport widths.
- Python lint checks passed.
- Docker image builds and installation on a live Home Assistant host still need deployment verification; a Docker daemon was unavailable in the implementation environment.

## Troubleshooting

### The add-on does not appear in the store

Confirm that `/addons/laptop_repair/config.yaml` exists and that the add-on directory was not copied with an extra nesting level. Reload/check for updates in the add-on store.

### The application cannot write its database or upload files

Check the add-on/container logs and ensure the configured data directory exists or can be created, is writable, and has free disk space.

### A part cannot be assigned

Confirm that the item is active, the requested quantity is a positive whole number, and available stock is sufficient. Assigned quantities are already excluded from the available stock count.

### Profit is blank or absent from the dashboard

A blank resale price means per-laptop profit is unknown. Dashboard realized profit additionally requires the laptop's status to be `sold`.

### A form reports an expired or invalid session

Reload the page and submit again. This can happen after restoring data or changing the session key. Cookies must be enabled.

### Links fail when opened through Home Assistant

Open the application using **Open Web UI** or its Ingress sidebar entry. A custom reverse proxy must preserve the correct path prefix and forwarding behavior.

## Initial scope

This release focuses on a single shared repair/resale workspace. It does not include eBay imports, exchange-rate conversion, separate selling-fee fields, individual user accounts/roles, serialized parts, purchasing batches, or an accounting ledger.
