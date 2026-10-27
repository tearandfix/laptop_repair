# Laptop Repair Manager

Start the add-on and select **Open Web UI**. Enable **Show in sidebar** for quick access.

1. Add your repair parts and their available quantities under **Parts inventory**.
2. Select **Add laptop**, enter its purchase/shipping costs in UAH, and save.
3. Open the laptop to assign parts, upload documents, and update its status.
4. Enter a resale price and select `sold` when the sale is complete.

Statuses can be changed manually in any order: `purchased`, `shipped_usa`,
`np_accepted`, `shipped_ua`, `delivered`, `fixed`, `listed`, `sold`,
`unrepairable`, `parted_out`.

Assigning parts deducts stock. Reducing/removing assignments returns stock.
Assigned unit prices are preserved when inventory prices change. Deleting a
referenced inventory item archives it; archived items can be restored.

Profit is resale price minus purchase price, shipping, and all assigned parts.
Fees are included in your entered purchase price. Blank resale prices leave
profit unknown for ordinary laptops. Donor laptops show their net result after
recovery. Dashboard realized profit/loss includes costs of sold laptops with an
entered resale price and laptops marked unrepairable or parted out. Actual
recovery sales increase cash revenue; internal transfers never do.

## Unrepairable laptops

1. Set the donor's status to **Unrepairable**.
2. Use **Recover parts** to create separate inventory batches with a title,
   quantity, estimated unit value, and condition/comment. Each batch keeps its donor.
3. Assign recovered batches from another laptop's repair-parts section. Accept
   the estimated value or enter a transfer value per unit. The donor gets an equal
   credit and the recipient gets a repair cost. Later price edits do not change it.
4. Use **Sell** on a recovered batch to record a direct sale, or **Record chassis /
   scrap sale** for the remainder. Enter actual total proceeds, not a unit price.
5. Mark the donor **Parted out** when dismantling is complete.

Recovered stock estimates are informational and do not reduce losses. Parts
already assigned during repair should be removed from that assignment to return
them to their original stock item, rather than recovered a second time.

Reducing/removing an assignment reverses stock and donor credit together.
**Cancel sale** reverses cash proceeds and returns sold parts to stock; cancelled
sales stay in the donor's history. Correct sales by cancelling and re-entering.
Do not also enter scrap proceeds as the laptop's resale price.

Donors with recovery history cannot be deleted, and recovered batches are
archived rather than deleted. The dashboard separates actual cash, internal
transfers, and stock estimates. Internal transfers are excluded from business
profit, including when the recipient is still unsold.

Version 1.2.0 automatically migrates existing databases while preserving records,
parts assignments, and files. Include the add-on in a backup before upgrading.

Attachments are limited to 20 MiB each, up to 10 files per upload. Deleting a
laptop returns its parts to stock and removes its attachments.

No configuration options are required. Access uses Home Assistant Ingress;
no host port is exposed. Data is stored in `/data`. Include this add-on in
Home Assistant backups to preserve both the database and uploaded files.
The add-on is stopped briefly during backups to keep them consistent.
