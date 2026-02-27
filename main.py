import requests 
import psycopg2
import os
import time 
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

BASE_URL = "https://api.nysed.gov/rosa/V2"
ENDPOINT = "/byProfessionAndName"

API_KEY = os.getenv("API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL") # Railway Postgres gives you this

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "x-oapi-key": API_KEY
}

session = requests.Session()
session.headers.update(HEADERS)

prefixes = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL)

    #     host=os.getenv("DB_HOST"),
    #     port=os.getenv("DB_PORT"),
    #     dbname=os.getenv("DB_NAME"),
    #     user=os.getenv("DB_USER"),
    #     password=os.getenv("DB_PASSWORD")
    # )

# get a single page of results for a given prefix and page number
def fetch_page(prefix, page_number, page_size=100):
    params = {
        "name": prefix.lower(),
        "professionCode": "022",
        "pageNumber": page_number,
        "pageSize": page_size
    }
    for attempt in range(5):
        response = session.get(BASE_URL + ENDPOINT, params=params)
        if response.status_code == 200:
            return response.json()
        if response.status_code in (408, 429, 500, 502, 503, 504):
            wait = 2 * (attempt + 1)
            print(f"{prefix} page {page_number}: Received {response.status_code}. Retrying in {wait}s")
            time.sleep(wait)
        else:
            print(f"ERROR: {response.status_code} - {response.text}")
            return None
        
    print(f"{prefix} page {page_number}: failed after retries")
    return None 
    

# iterate through all pages for one prefix
def iterate_pages_for_prefix(prefix, page_size=100):
    page_number = 0
    while True:
        data = fetch_page(prefix, page_number, page_size=page_size)
        if data is None:
            print(f"{prefix} page {page_number}: Skipping due to fetch error")
            break

        yield data
        time.sleep(0.2)  # small delay to avoid hitting rate limits
       
        total_pages = data.get("totalPages")
        if total_pages is not None:
            if page_number >= total_pages -1:
                break 
            page_number += 1
            continue
        else:
            items = data.get("content", []) 
            if items is not None and len(items) == 0:   #If the page has no records, stop paging. Otherwise go to the next page
                break 
            page_number += 1

# iterate through all prefixes and all pages for each prefix 
def iterate_all_prefixes(page_size=100):
    for prefix in prefixes:
        for page_data in iterate_pages_for_prefix(prefix, page_size=page_size):
            yield prefix, page_data


def clean_date(val):
    val = v(val)
    if not val or str(val).lower() in ("null", "not on file"):
        return None 
    return datetime.strptime(str(val), "%B %d, %Y").date()

# helper func to extract value from dict 
def v(x):
    if isinstance(x, dict):
        return x.get("value")
    return x
# helper func to extract fields from page data and return list of dicts for each row 
def extract_rows(page_data):
    rows = []
    if not page_data:
        return rows
    items = page_data.get("content", [])
    for r in items:
        rows.append({
            "license_number": v(r.get("licenseNumber")),
            "name": v(r.get("name")),
            "profession": v(r.get("profession")),
            "address": v(r.get("address")) or " ".join(
                part for part in [v(r.get("city")), v(r.get("state"))] if part
            ) or None,
            "date_of_licensure": clean_date(v(r.get("dateOfLicensure"))),
        })
    return rows


# create table in Postgres to store the data
def create_table(conn):
    curr = conn.cursor()
    curr.execute("""
        CREATE TABLE IF NOT EXISTS rn_licenses (
            license_number TEXT PRIMARY KEY,
            name TEXT,
            profession TEXT,
            address TEXT,
            date_of_licensure DATE
        );
    """)
    conn.commit()
    curr.close()

# helper func to filter existing info in db 
def filter_existing_rows(conn, rows):
    curr = conn.cursor()
    license_numbers = [r["license_number"] for r in rows]
    curr.execute("""
        SELECT license_number FROM rn_licenses WHERE license_number = ANY(%s)
                 """, (license_numbers,))
    existing_license_numbers = set(r[0] for r in curr.fetchall())
    new_rows = [r for r in rows if r["license_number"] not in existing_license_numbers]
    if not new_rows:
        curr.close()
        return []
    print(f"Found {len(new_rows)} new rows to insert")
    curr.close()
    return new_rows


# insert rows into Postgres table
def insert_rows(conn, rows):
    curr = conn.cursor()
    for r in rows:
        curr.execute("""
            INSERT INTO rn_licenses (
                license_number, name, 
                profession, address, date_of_licensure)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (license_number) DO UPDATE SET 
                     name = EXCLUDED.name,
                     address = EXCLUDED.address,
                     date_of_licensure = EXCLUDED.date_of_licensure,
                     profession = EXCLUDED.profession
        """,(
            r["license_number"],
            r["name"],
            r["profession"],
            r["address"],
            r["date_of_licensure"]
        ))
    conn.commit()
    curr.close()


def main():
    total = 0

    conn = get_db_connection()
    create_table(conn)

    for prefix in prefixes:
        for page in iterate_pages_for_prefix(prefix):
            rows = extract_rows(page)

            rows_insert = filter_existing_rows(conn, rows)  # added this after collecting all the prefix data to now get the new row data to avoid going through each page of each prefix 
            if not rows_insert:
                print(f"{prefix}: No new rows to insert")
                break

            insert_rows(conn, rows_insert)
            total += len(rows_insert)
            print(f"{prefix}: Inserted {len(rows_insert)} | Total Records: {total}")
    conn.close()


if __name__ == "__main__":
    main()

    
    