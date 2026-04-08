---
name: research-sync
description: Use when someone asks to sync Zotero papers to Notion, update the literature review database, add a new paper to Notion, or poll Zotero for new research. Also triggered by scheduled polling.
argument-hint: [collection name]
---

## What This Skill Does

Fetches new papers from the Zotero Web API and syncs them into a Notion literature review database. The Notion schema is read dynamically at runtime — no hardcoded columns — so it works across different research projects and fields.

---

## Required Environment Variables

Before running, confirm these are set:

| Variable | Description |
|---|---|
| `ZOTERO_API_KEY` | Zotero Web API key (from zotero.org/settings/keys) |
| `ZOTERO_USER_ID` | Zotero user ID (numeric, found on zotero.org/settings/keys) |
| `NOTION_API_KEY` | Notion integration token (from notion.so/my-integrations) |
| `NOTION_DATABASE_ID` | The ID of the target Notion literature review database |

If any are missing, tell the user which ones are absent and stop. Do not proceed with partial credentials.

---

## State File

Track sync state in: `.research-sync-state.json` in the current working directory.

Schema:
```json
{
  "last_zotero_version": 0,
  "last_synced_at": "ISO-8601 timestamp",
  "database_id": "notion-database-id"
}
```

Create the file with version `0` if it does not exist.

---

## Steps

### 1. Load credentials and state

- Read env vars listed above.
- Read or create `.research-sync-state.json`.
- If `` is provided, restrict the Zotero fetch to that collection name. Otherwise sync all items.

### 2. Fetch Notion database schema

Call the Notion API to retrieve the database schema:

```
GET https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}
Headers:
  Authorization: Bearer {NOTION_API_KEY}
  Notion-Version: 2022-06-28
```

Extract all property names and their types from `response.properties`. Store this as the **active schema** for step 4.

### 3. Fetch new Zotero items

Call the Zotero API for items newer than the last synced version:

```
GET https://api.zotero.org/users/{ZOTERO_USER_ID}/items
Params:
  since={last_zotero_version}
  format=json
  itemType=-attachment
  sort=dateAdded
  direction=desc
Headers:
  Zotero-API-Key: {ZOTERO_API_KEY}
```

- If a collection argument was given, resolve it to a collection key first:
  `GET https://api.zotero.org/users/{ZOTERO_USER_ID}/collections`
  Then filter items to that collection.

- Capture the `Last-Modified-Version` header from the response — save it as `last_zotero_version` after a successful sync.

If no new items are found, tell the user "No new items since last sync" and stop.

### 4. Map Zotero metadata to Notion properties

For each Zotero item, build a Notion page payload by matching Zotero fields to Notion column names using **fuzzy name matching** (case-insensitive, ignore plurals and punctuation):

| Zotero field | Likely Notion column names |
|---|---|
| `title` | Title, Name, Paper Title |
| `creators` (formatted) | Authors, Author, Contributors |
| `date` / `year` | Year, Date, Publication Year |
| `publicationTitle` / `journalAbbreviation` | Journal, Publication, Venue |
| `DOI` | DOI, doi |
| `abstractNote` | Abstract, Summary |
| `tags` (array) | Tags, Keywords, Topics |
| `url` | URL, Link |
| `itemType` | Type, Item Type |
| `zoteroKey` (item.key) | Zotero ID, Zotero Key |

**Rules:**
- Only populate columns that exist in the active schema. Ignore Zotero fields with no matching column.
- For multi-select Notion columns (tags), convert Zotero tags array to multi-select values.
- For date columns, format as `YYYY` (year only) unless the column type is `date`, in which case use ISO-8601.
- For rich text / text columns, truncate to 2000 characters max.
- Leave unmatched Notion columns empty — do NOT invent values.

### 5. Preview before writing

Show the user a summary table of what will be synced:

```
Papers to sync: N

| # | Title | Authors | Year | Matched Notion columns |
|---|-------|---------|------|------------------------|
| 1 | ...   | ...     | ...  | Title, Authors, DOI... |
```

Ask: "Proceed with syncing these N papers to Notion? (yes / skip [#] / cancel)"

- If user says **yes**: proceed to step 6.
- If user says **skip [#]**: remove those items and proceed.
- If user says **cancel**: abort and do not write anything.

### 6. Write to Notion

For each paper, check if a page already exists in the database with the same DOI or Zotero Key:

```
POST https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query
Body: { "filter": { "property": "DOI", "rich_text": { "equals": "{doi}" } } }
```

- If a matching page exists: only update **empty** properties. Never overwrite a field the user has already filled in.
- If no match: create a new page with `POST https://api.notion.com/v1/pages`.

### 7. Update state and report

- Write the new `last_zotero_version` and timestamp to `.research-sync-state.json`.
- Report to the user:

```
Sync complete.
  Created: N new pages
  Updated: N existing pages (empty fields only)
  Skipped: N (already fully populated)
Last synced version: {version}
```

---

## Notes

- Rate limits: Notion API allows ~3 req/s. Add a small delay between page writes if syncing >10 papers.
- If the Zotero API returns an error, show the HTTP status and message. Do not silently fail.
- If a Notion column type is unknown or unsupported, skip that field and log a warning.
- To set up scheduled polling, tell the user: "Run `/schedule` to automate this sync on a recurring interval."
- This skill does NOT modify or delete existing Notion pages beyond filling empty fields.
