---
name: research-extract
description: Use when someone asks to extract data from the Notion literature review table, analyze research papers, generate a Python script or notebook from Notion, query the literature database, or export research data.
---

## What This Skill Does

Reads the Notion literature review database, asks the user what they want to do with the data, and generates a Python script or Jupyter notebook tailored to that use case.

---

## Required Environment Variables

| Variable | Description |
|---|---|
| `NOTION_API_KEY` | Notion integration token |
| `NOTION_DATABASE_ID` | The ID of the target Notion literature review database |

If either is missing, tell the user and stop.

---

## Steps

### 1. Load credentials

Read `NOTION_API_KEY` and `NOTION_DATABASE_ID` from env vars. Stop if missing.

### 2. Fetch Notion database schema

```
GET https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}
Headers:
  Authorization: Bearer {NOTION_API_KEY}
  Notion-Version: 2022-06-28
```

Extract all column names and types from `response.properties`. Present them to the user so they know what fields are available.

### 3. Ask the user what they want

Show the available columns, then ask:

> "Here are the columns in your literature review table: [list].
> What do you want to do with this data? For example:
> - Filter papers by a specific field (year, tag, status, keyword)
> - Export all or filtered rows to a CSV or BibTeX file
> - Load data into a pandas DataFrame for custom analysis
> - Summary statistics (count by year, tag, status, etc.)
> - Something else — describe it"

Wait for the user's response before proceeding.

### 4. Choose output format

Ask:

> "Should I generate a Python script (.py) or a Jupyter notebook (.ipynb)?"

Default to `.ipynb` if the user is unsure.

Ask for the output file path, or default to `./research_extract.py` or `./research_extract.ipynb`.

### 5. Generate the code

Generate a complete, runnable script or notebook based on the user's use case. The code must:

**Always include:**
- Load credentials from env vars (`os.environ`)
- Fetch the Notion database using the `requests` library (no external Notion SDK required)
- Handle Notion API pagination (fetch all pages, not just the first 100)
- Parse property values by type (title, rich_text, multi_select, date, number, select, checkbox, url)

**Use-case specific sections:**

**Filter / search:**
```python
# Filter rows where column X matches value Y
filtered = [p for p in pages if get_prop(p, 'ColumnName') == 'value']
```

**Export to CSV:**
```python
import csv
with open('output.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
```

**Export to BibTeX:**
Generate BibTeX entries from title, authors, year, journal, DOI fields.

**Pandas DataFrame:**
```python
import pandas as pd
df = pd.DataFrame(rows)
```

**Summary stats:**
```python
print(df['Year'].value_counts())
print(df['Tags'].explode().value_counts())
```

**Notebook analysis:**
Generate cells with:
1. Setup + credentials
2. Data fetch
3. DataFrame creation
4. Analysis cells with markdown headers explaining each section

**Always include a helper function** to extract values from Notion's property format:
```python
def get_prop(page, name):
    prop = page['properties'].get(name, {})
    ptype = prop.get('type')
    if ptype == 'title': return ''.join(t['plain_text'] for t in prop.get('title', []))
    if ptype == 'rich_text': return ''.join(t['plain_text'] for t in prop.get('rich_text', []))
    if ptype == 'multi_select': return [o['name'] for o in prop.get('multi_select', [])]
    if ptype == 'select': return prop.get('select', {}).get('name')
    if ptype == 'date': return prop.get('date', {}).get('start')
    if ptype == 'number': return prop.get('number')
    if ptype == 'checkbox': return prop.get('checkbox')
    if ptype == 'url': return prop.get('url')
    return None
```

### 6. Write the output file

Write the generated code to the path chosen in step 4.

Confirm: "Generated `{path}`. Run it with `python {path}` (or open in Jupyter)."

### 7. Offer to refine

Ask: "Want to add anything else — additional filters, a visualization, or a different export format?"

If yes, loop back to step 3 and append/modify the generated code accordingly.

---

## Notes

- Always use `os.environ.get()` for credentials — never hardcode API keys in generated code.
- Notion returns max 100 pages per request. The fetch function must follow `next_cursor` pagination.
- If the user's request is ambiguous (e.g., "analyze my papers"), ask one clarifying question before generating code.
- Do not generate code that writes back to Notion — this skill is read-only extraction. For writes, direct the user to `/research-sync`.
- If the database has >500 rows, add a note in the generated code about expected runtime.
