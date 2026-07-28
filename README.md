## Expense & Carbon Tracker

## Overview

This tool logs expenses and estimates their carbon footprint from receipt photos. 
The user opens the app, takes or uploads an image of a receipt, an LLM
reads the details, the user confirms them, and it's logged to a shared spreadsheet
with an estimated carbon footprint attached. A weekly email digest keeps
whoever manages expenses in the loop without anyone needing to open the
spreadsheet directly.

While this was originally built for an environmental nonprofit organization, 
it can be easily adapted to general bookkeeping or reimbursement tracking 
for any small team. The carbon-estimate layer is just one thing to drop if 
it's not relevant to your use case.

**Live app:** (https://expense-and-carbon-tracker-qnw8vchs2nksvnigae3nd5.streamlit.app/)


## How it works

- The user uploads a photo or PDF of a receipt, or captures one with their
  camera
- An LLM (via Groq) reads the merchant, date, total, category, and payment
  method, and flags its own confidence in the category
- The user reviews and corrects anything before it's saved 
- Each entry gets an estimated carbon footprint, calculated from EPA
  spend-based emission factors 
- Entries are logged to a Google Sheet, which a companion Apps Script
  summarizes into a weekly email digest: total spend, estimated carbon, a
  breakdown by category and submitter, and a flag for any entries the model
  wasn't confident about

## Tech stack

| Piece | Tool |
|---|---|
| App / UI | [Streamlit](https://streamlit.io) |
| Receipt reading | [Groq](https://groq.com) (vision LLM) |
| Data store | Google Sheets, via [`gspread`](https://docs.gspread.org) |
| Weekly digest | Google Apps Script |
| Carbon methodology | [EPA Supply Chain GHG Emission Factors](https://catalog.data.gov/dataset/supply-chain-greenhouse-gas-emission-factors-v1-3-by-naics-6) |

## Known limitations / next steps

- No real authentication: users type their name into a text field which is not verified;
  Anyone with the app link could submit under any name. A larger group may require a verification step.
- There is no carbon factor for utilities (electricity is outside the EPA dataset's scope).
- "Travel" is broadly defined; a hotel night and a flight have very
  different footprints and are currently averaged into one factor.
- The Apps Script digest and the Streamlit app's expected headers have to be
  kept in sync by hand; the app validates its own headers on load, but the
  script doesn't cross-check against the app automatically.

## Setup

### 1. Google Sheet
Create a sheet with this exact header row, in this order:
```
Date	Merchant	Category	Total ($)	Est. Carbon (kg CO2)	Submitted By	Payment Method	Notes	Raw Extract
```

### 2. Google service account
Create a service account in Google Cloud Console with access to the Sheets
and Drive APIs, share the sheet with its email address, and download the
JSON key.

### 3. Groq API key
Get one from [console.groq.com](https://console.groq.com).

### 4. Local secrets
Create `.streamlit/secrets.toml` (already excluded via `.gitignore`):
```toml
groq_api_key = "your-groq-key"
sheet_id = "your-google-sheet-id"

[gcp_service_account]
# paste the full contents of your service account JSON key here
```

### 5. Install and run
```bash
pip install -r requirements.txt
streamlit run tracker.py
```

### 6. Deploy (optional)
Push to a public GitHub repo, then deploy free via
[Streamlit Community Cloud](https://share.streamlit.io). Point it at the
repo, and paste the same secrets into its dashboard's "Secrets" section
(never into the repo itself).

### 7. Weekly email digest
See [`apps_script/weekly_digest.gs`](apps_script/weekly_digest.gs) for the
Google Apps Script and its setup instructions (in the file's header
comment). It's bound to the spreadsheet directly via Extensions > Apps
Script, not deployed alongside the Streamlit app.

## License

MIT
