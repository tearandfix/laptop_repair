# Laptop Repair Manager

A web-based application for tracking broken laptops purchased on eBay, their journey to Ukraine, repair costs, parts inventory, and resale profit. Designed to run as a **Home Assistant add-on** with sidebar access through **Ingress**, or as a standalone local application.

All purchases and sales are entered manually. The initial currency is **Ukrainian hryvnia (UAH)**.

**Version 1.2.0:** Includes donor-linked parts recovery, reuse credits, and parts/scrap sales. See [Run locally](#run-locally) to try it, or [Install in Home Assistant](#install-in-home-assistant) for deployment.

## Contents

- [Features](#features)
- [Laptop records and statuses](#laptop-records-and-statuses)
- [Parts inventory](#parts-inventory)
- [Unrepairable laptops and recovery](#unrepairable-laptops-and-recovery)
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
- Recover parts from unrepairable laptops into separate donor-linked stock batches.
- Track internal reuse credits, actual part/scrap sales, and net loss after recovery.
- Cancel recovery sales with automatic stock returns and proceeds reversal.
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
| Status | One of the ten statuses below; defaults to `purchased`. |
| Repair parts | Assigned inventory parts, quantities, and recorded unit prices. |
| Attached files | Uploaded documents and photos associated with this laptop. |
| Resale price | Optional sale amount in UAH; leave empty until known. |
| Resale listing description | Optional multiline text for the resale listing, up to 10,000 characters. Line breaks are preserved on the detail page. |
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
9. `unrepairable`
10. `parted_out`

The interface presents readable labels, such as “Shipped USA” and “NP accepted.” A dropdown allows any status to be selected manually: stages may be skipped, and a record may be moved backwards. Status changes do not change inventory quantities or set a resale price automatically.

Deleting a laptop returns its assigned parts to stock, reverses any associated donor credits, and removes its attachment records and files. The interface asks for confirmation before deletion. A donor with recovered batches or recovery sales cannot be deleted, preserving the history of its original costs and recovered parts; use `parted_out` to close it instead.

## Parts inventory

Each inventory item contains:

| Field | Description |
| --- | --- |
| Title | Required part name. |
| Unit price | Cost of one purchased unit, or estimated value of one recovered unit, in UAH. |
| Comment | Optional description, compatibility information, or supplier notes. |
| Stock quantity | Non-negative whole number of currently available, unassigned units. |
| Donor laptop | For recovered batches, an immutable link to the laptop the parts came from. |

Stock can be edited to record new purchases or correct an inventory count. The quantity entered is the **available quantity**, not the total quantity including parts already installed in laptops.

### Assignment rules

- Assigning `N` units to a laptop deducts `N` from available stock.
- An assignment requires a positive whole-number quantity and enough available stock.
- Increasing an assignment deducts the additional quantity; decreasing it returns the difference.
- Removing an assignment returns its entire quantity to stock.
- Changes are made within a database transaction to prevent overselling during simultaneous requests.
- Editing a stale inventory form is rejected if its stock or details changed after the form was opened. Reload the record before saving again.
- Each new assignment records the part's current unit price and title. Recovered parts allow an optional per-unit transfer value instead of the current estimate. Later edits to inventory do not change an assignment's recorded cost or name.
- Updating an existing assignment's quantity preserves its recorded unit price. To use a new price, add a separate assignment.
- The same inventory item may appear in more than one assignment on a laptop, allowing different recorded prices.
- Purchased items without assignments can be permanently deleted.
- Assigned items and all recovered batches are archived instead of deleted. Their history remains accessible through the laptop, but archived items cannot be assigned or sold until restored.
- Archived items can be restored from the inventory screen. Returning assigned stock to an archived item increases its quantity without automatically restoring it.

The application tracks quantities and per-assignment costs, not individual part serial numbers or purchase batches.

## Unrepairable laptops and recovery

### Recover usable parts

1. Edit the donor laptop and manually select **Unrepairable** when a repair is no longer worthwhile.
2. In its **Recovery & parting out** section, select **Recover parts**.
3. Enter a title, positive whole-number quantity, estimated value per unit, and condition/compatibility comment.
4. Save to create a separate stock batch with a permanent donor link. Identically named purchased or recovered items are not merged.
5. Select **Parted out** when dismantling is complete. Status changes do not move stock or create sales.

For parts you previously assigned during a repair, use **Remove** in the repair-parts list to return them to their existing inventory item. Do not also enter them as newly recovered parts, which would duplicate stock. If the assigned part came from another donor, removal also reverses that donor's transfer credit.

Recovered parts on the shelf have an **estimated inventory value only**. Recovering them does not generate revenue or reduce the donor's net loss. Stock corrections and estimate changes can be made from the batch's inventory edit page; neither generates income.

### Reuse a recovered part

Open the recipient laptop, select the recovered batch in **Repair parts**, and assign a quantity. The dropdown identifies its donor and batch number.

- Leave **Transfer value per unit** blank to use the batch's current estimate, or enter the value you want allocated to this repair.
- The recipient is charged `quantity × recorded transfer value` as part of its repair cost.
- The donor receives an equal **internal transfer credit**.
- The recorded value stays fixed even if the inventory estimate changes later. Quantity edits preserve it.
- Reducing/removing an assignment returns stock and reverses the corresponding credit atomically. Deleting the recipient laptop returns all its assigned stock and credits.
- A recovered batch cannot be assigned back to its own donor.

These credits allocate costs between laptops. They are not cash and are excluded from business-wide revenue and profit, even while the recipient laptop is still unsold.

### Sell recovered parts or remaining scrap

Select **Sell** next to a recovered batch in inventory or on the donor page. Enter quantity and the **total actual sale amount**, not the price per unit. Saving deducts stock and credits the donor with those proceeds. Estimated value is not added again.

Use **Record chassis / scrap sale** for the remaining shell or scrap. This records actual proceeds without a stock movement. If the item is already tracked in inventory, use its batch's Sell action instead. Do not also enter a scrap sale as the laptop's resale price, as that would count it twice.

The donor page lists completed and cancelled recovery sales, including recorded titles, quantities, amounts, comments, and dates. **Cancel sale** reverses the proceeds and returns sold units to their original batch, even if the batch is archived. A cancellation cannot return stock twice. To correct a sale, cancel it and record the corrected sale.

### Donor result and example

```text
Net result after recovery = laptop resale price (if entered)
                          + actual parts/scrap sale proceeds
                          + internal transfer credits
                          − laptop total cost
```

For a donor costing **2,000 UAH**:

| Event | Donor net result |
| --- | ---: |
| Marked unrepairable | −2,000 UAH |
| Recover a screen estimated at 700 UAH | −2,000 UAH |
| Assign that screen to another laptop at a 700 UAH transfer value | −1,300 UAH |
| Sell the remaining chassis for 200 UAH | −1,100 UAH |

The recipient also carries the 700 UAH transfer cost, so the credit and charge cancel across the workspace. Only the 200 UAH sale increases cash revenue. The donor page separately shows original total costs, estimated available recovered stock, transfer credits, actual part sales, actual scrap sales, and the net result.

## Costs and profit

Amounts are stored as **integer kopiykas** and displayed rounded to the nearest whole UAH, without decimal places (for example, `600 UAH`). Half-UAH values round away from zero. Calculations and editable form values retain their exact kopiyka precision; rounding applies only to displayed amounts. Calculations do not use binary floating-point money values.

```text
Repair cost = sum(assigned quantity × recorded unit price)

Total cost = purchase price + shipping cost + repair cost

Profit = resale price − total cost
```

Purchasing fees are included in the entered purchase price. There is no separate fee calculation or automatic currency conversion.

### Example

| Item | Amount |
| --- | ---: |
| Purchase price | 4,000 UAH |
| Shipping cost | 800 UAH |
| SSD: 1 × 650 UAH | 650 UAH |
| RAM: 2 × 300 UAH | 600 UAH |
| **Total cost** | **6,050 UAH** |
| Resale price | 8,000 UAH |
| **Profit** | **1,950 UAH** |

- For a regular laptop, an empty resale price means profit is unknown, displayed as a dash. A resale price of zero is valid. Donors instead show their net result after recovery, starting with their full loss even when no resale price is entered.
- A laptop can show a calculated result before it is marked `sold`. The dashboard uses the recognition rules below rather than summing per-laptop displayed results.
- Sold laptops without a resale price are highlighted so missing amounts are visible.
- **Cash sales revenue** sums resale prices for sold laptops plus all non-cancelled recovery sales, regardless of the donor's current status.
- **Recorded external laptop costs** sums purchase, shipping, and assigned **purchased** parts across all laptops. Internal recovered-part transfer costs are excluded to avoid counting the donor purchase cost twice.
- **Realized profit / loss** is cash sales revenue minus external costs of sold laptops with an entered resale price and laptops marked `unrepairable` or `parted_out`. Written-off donor costs are recognized immediately; subsequent cash recovery sales reduce those losses. Moving a donor back to an open status moves its costs back to open investment.
- **Open laptop investment** includes external costs for laptops not marked `sold`, `unrepairable`, or `parted_out`.
- **Result against all laptop costs** is cash sales revenue minus external costs of every laptop, including open laptops. It is independent of internal transfers.
- **Recovery cash proceeds** and **internal transfer credits** are shown separately. Recovery proceeds are already included in cash sales revenue; transfer credits are never added to business revenue or profit.
- **Available stock value** includes purchased stock and estimated recovered stock, including archived batches. It is inventory valuation, not income or a record of cash purchases. Unassigned purchased stock is not included in laptop costs.

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

Summary cards show laptop count, open investment, external laptop costs, available stock value, cash sales revenue, realized profit/loss, recovery cash proceeds, internal transfers, and the result against all laptop costs. Status counts link to the corresponding filtered laptop list.

### Laptops

A searchable, status-filtered list shows each laptop's title, status, purchase price, shipping, repair cost, total cost, resale price, and net result. Select a record to edit its details, assign parts, or manage attachments. Donor records also show recovered batches, reuse credits, sales history, and recovery actions.

### Parts inventory

View active or archived items, search titles and comments, add new inventory items, edit prices and stock, and delete/archive or restore items.

The layout is responsive for desktop and mobile browsers. All assets are served locally; no external CDN is required.

## Install in Home Assistant

Requires a Home Assistant installation with **Supervisor and add-on support**, such as Home Assistant OS. A Home Assistant Container installation can instead run this application separately with Docker.

### Install from the GitHub repository (recommended)

[![Add this repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ftearandfix%2Flaptop_repair)

Click the button above to open the repository dialog in your Home Assistant instance, then confirm adding the repository. Alternatively, add it manually:

1. Open **Settings → Apps → Install app**. On older Home Assistant versions, this is **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu in the top-right corner and select **Repositories**.
3. Paste this repository URL and select **Add**:

   ```text
   https://github.com/tearandfix/laptop_repair
   ```

   Use the repository URL above, not the URL of the `laptop_repair` subfolder.

4. Close the dialog and find **Laptop Repair Manager** in the store. If it does not appear immediately, use **Check for updates** in the store menu and refresh the page.
5. Open **Laptop Repair Manager** and select **Install**. Home Assistant builds the image on your device, so the first installation can take several minutes and requires internet access to download the base image and dependencies.
6. Once installed, select **Start**. Enable **Start on boot** and **Show in sidebar** if desired.
7. Select **Open Web UI**, or open **Laptop Repairs** from the sidebar.

No configuration options, separate login, or port forwarding are required. The web interface uses Home Assistant Ingress. If startup fails, open the add-on's **Log** tab for details.

The repository root must contain `repository.yaml` alongside the `laptop_repair/` add-on directory. Both are included in this project and must be pushed to GitHub for repository installation to work.

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

For a **GitHub repository installation**:

1. Back up the add-on using Home Assistant's backup interface.
2. Open the app/add-on store and select **⋮ → Check for updates**.
3. Open **Laptop Repair Manager** and select **Update** when a newer version is available.
4. After the update, start the add-on if needed and open its web interface.

For a **local installation**, replace the source in `/addons/laptop_repair/`, reload the store, and rebuild/update the add-on through Home Assistant.

Updates preserve the add-on's `/data` directory. Do not uninstall it to update. See [Backups and recovery](#backups-and-recovery). Maintainers must increase `version` in `laptop_repair/config.yaml` when publishing an update for Home Assistant to offer it.

Version 1.1.0 automatically adds the resale listing description field to existing databases on startup. Existing laptops start with an empty description.

Version 1.2.0 upgrades the database to schema version 3, adding the two donor statuses, batch donor links, and recovery sales. Migration preserves existing laptop IDs, parts assignments, descriptions, and attachments. Schema updates are transactional and references are checked before committing. Existing parts remain purchased stock. Older application versions cannot open this upgraded schema; restore the previous backup if rolling back the application.

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
├── repository.yaml
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
- `parts`: inventory details, available stock, archive flag, and optional immutable donor reference. Each recovered batch is a separate row.
- `laptop_parts`: laptop/part references, quantity, and snapshots of assigned title/unit price or transfer value. Donor credits are derived from these assignments.
- `recovery_sales`: donor reference, optional batch reference (empty for scrap), recorded title/quantity/actual proceeds, comment, and cancellation timestamps.
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
- All ten statuses and manual out-of-order changes.
- Upload/download behavior and file-size limits.
- Ingress-prefixed URLs and redirects.
- CSRF protection and validation errors.
- Dashboard revenue/profit rules.
- Donor-linked recovery, fixed transfer values, and credit reversals on returns or recipient deletion.
- Direct parts/scrap sales, cancellations, and concurrent sale-versus-assignment stock protection.
- Exclusion of estimates and transfers from business profit.
- Version 1/2 database upgrades, preservation of references and files, and migration rollback on invalid references.

Runtime dependencies, including transitive dependencies, are pinned in `laptop_repair/requirements.txt`; direct dependency ranges live in `requirements.in`. To refresh the lock using [uv](https://docs.astral.sh/uv/), run:

```sh
uv pip compile laptop_repair/requirements.in --python-version 3.11 \
  --output-file laptop_repair/requirements.txt
```

Run the tests after updating dependencies. The Docker image uses Python 3.13. Run one application process against each data directory; the provided Uvicorn command uses one worker.

### Verification

- **64 automated tests passed** on Python 3.13, including recovery accounting, stock concurrency, and migration preservation/rollback.
- Real Chromium walkthroughs verified the original purchase/repair/sale workflow and the recovery workflow: donor creation, recovery, transfer, direct sale, scrap sale, cancellation, and net-result display.
- Desktop and mobile layouts were checked at 1440 px and 390 px viewport widths.
- Python lint checks passed.
- Docker image builds and installation on a live Home Assistant host still need deployment verification; a Docker daemon was unavailable in the implementation environment.

## Troubleshooting

### The add-on does not appear in the store

For repository installations, confirm that `https://github.com/tearandfix/laptop_repair` appears under **Repositories**, and that `repository.yaml` has been pushed to the root of its default branch. Check for updates in the store and refresh the page. The add-on supports `amd64` and `aarch64` devices.

For local installations, confirm that `/addons/laptop_repair/config.yaml` exists and that the add-on directory was not copied with an extra nesting level. Reload/check for updates in the add-on store.

### The application cannot write its database or upload files

Check the add-on/container logs and ensure the configured data directory exists or can be created, is writable, and has free disk space.

### A part cannot be assigned

Confirm that the item is active, the requested quantity is a positive whole number, and available stock is sufficient. Assigned and sold quantities are already excluded from available stock. Recovered parts cannot be assigned to their own donor laptop.

### Profit is blank or absent from the dashboard

A blank resale price means ordinary per-laptop profit is unknown. Donors show their net result after recovery instead. Dashboard realized profit/loss recognizes external costs when a laptop is sold with a resale price or marked unrepairable/parted out; recovery sales count when recorded. Estimated stock and internal transfer credits are not business income.

### A form reports an expired or invalid session

Reload the page and submit again. This can happen after restoring data or changing the session key. Cookies must be enabled.

### Links fail when opened through Home Assistant

Open the application using **Open Web UI** or its Ingress sidebar entry. A custom reverse proxy must preserve the correct path prefix and forwarding behavior.

## Initial scope

This release focuses on a single shared repair/resale workspace. It does not include eBay imports, exchange-rate conversion, separate selling-fee fields, individual user accounts/roles, serialized parts, purchasing batches, or an accounting ledger.
