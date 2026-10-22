# Quick-commerce reporting

Local web app (localhost:8000) that logs into brand × platform portals, downloads daily reports and pushes them to Google Sheets.

## Setup (per laptop)
1. `./install.sh` (Mac/Linux) or `install.bat` (Windows)
2. Put the shared `service_account.json` in `data/`
3. `./start.sh` / `start.bat`, open **Settings**, paste the shared config Sheet ID, hit Save + Sync
4. Add your passwords for each login (stored in the OS keychain, this laptop only)

## What's shared vs local
- Shared (Google Sheet, tabs `brands` + `accounts`): brands, platforms, login IDs, output sheet IDs
- Local: passwords (keychain), browser sessions (`data/sessions`), run history, downloads

## Adding a real portal
Subclass `app/adapters/base.py:Adapter`, register in `app/adapters/__init__.py` under the platform name. Until then every platform uses the mock adapter.
