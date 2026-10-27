# Laptop Repair Manager

Start the add-on and select **Open Web UI**. Enable **Show in sidebar** for quick access.

1. Add your repair parts and their available quantities under **Parts inventory**.
2. Select **Add laptop**, enter its purchase/shipping costs in UAH, and save.
3. Open the laptop to assign parts, upload documents, and update its status.
4. Enter a resale price and select `sold` when the sale is complete.

Statuses can be changed manually in any order: `purchased`, `shipped_usa`,
`np_accepted`, `shipped_ua`, `delivered`, `fixed`, `listed`, `sold`.

Assigning parts deducts stock. Reducing/removing assignments returns stock.
Assigned unit prices are preserved when inventory prices change. Deleting a
referenced inventory item archives it; archived items can be restored.

Profit is resale price minus purchase price, shipping, and all assigned parts.
Fees are included in your entered purchase price. Blank resale prices leave
profit unknown. Dashboard realized profit includes only sold laptops with an
entered resale price.

Attachments are limited to 20 MiB each, up to 10 files per upload. Deleting a
laptop returns its parts to stock and removes its attachments.

No configuration options are required. Access uses Home Assistant Ingress;
no host port is exposed. Data is stored in `/data`. Include this add-on in
Home Assistant backups to preserve both the database and uploaded files.
The add-on is stopped briefly during backups to keep them consistent.
