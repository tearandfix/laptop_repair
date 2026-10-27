# Changelog

## 1.2.0

- Add manual `unrepairable` and `parted_out` statuses.
- Recover donor-linked parts into separate inventory batches.
- Record frozen transfer values and donor credits when recovered parts are reused.
- Sell recovered parts and chassis/scrap, with cancellable sales and stock returns.
- Show donor recovery summaries and distinguish cash, estimates, and internal transfers in business totals.
- Automatically upgrade existing databases to schema version 3 while preserving records and relationships.

## 1.1.0

- Add a multiline resale listing description to laptop records.

## 1.0.0

- Initial laptop tracking, parts inventory, attachments, profit calculations, and Home Assistant add-on.
