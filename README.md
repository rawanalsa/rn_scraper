# rn_scraper

Scrapes NYSED license data (profession code `022`) via the NYSED ROSA API, paginates A–Z, and upserts results into PostgreSQL.

## Features
- Prefix paging (A–Z) with retry + backoff
- Parses license records and normalizes dates
- Creates `rn_licenses` table if missing
- Upserts records by `license_number`

## Requirements
- Python 3.9+
- PostgreSQL database (local or hosted)

## Install
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables
Create a `.env` file (see `.env.example`).

```bash
API_KEY=your_nysed_api_key
DATABASE_URL=postgresql://user:password@host:port/dbname
```

## Run
```bash
python main.py
```

## Push to GitHub
```bash
# First-time setup (run once)
git remote add origin https://github.com/rawanalsa/rn_scraper.git
git branch -M main

# Regular updates
git add .
git commit -m "Update scraper"
git push -u origin main
```

## Output Schema
The script creates this table if it doesn’t exist:

```sql
CREATE TABLE IF NOT EXISTS rn_licenses (
    license_number TEXT PRIMARY KEY,
    name TEXT,
    profession TEXT,
    address TEXT,
    date_of_licensure DATE
);
```

## Notes
- The scraper stops a prefix when a page returns no new rows.
- Backoff and cooldown are built in to reduce rate-limit issues.

## Troubleshooting
- If you see connection errors, confirm `DATABASE_URL` and network access.
- If the API key fails, verify `API_KEY` in `.env`.
