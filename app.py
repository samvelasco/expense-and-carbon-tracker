import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
import json
import base64
from datetime import datetime

st.set_page_config(page_title="Tracker")

# ---- Connect to Google Sheets (using the robot account) ----
@st.cache_resource
def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["sheet_id"]).sheet1

# ---- Connect to Groq (the AI that reads the receipt) ----
groq_client = Groq(api_key=st.secrets["groq_api_key"])

# A small lookup table for common merchant name cleanup.
# We'll expand this over time as you see more variations.
MERCHANT_ALIASES = {
    "starbucks": "Starbucks",
    "sbux": "Starbucks",
    "walmart": "Walmart",
    "wm supercenter": "Walmart",
    "target": "Target",
    "publix": "Publix",
    "shell": "Shell",
    "exxon": "Exxon",
}

def normalize_merchant(raw_name):
    cleaned = raw_name.lower().strip()
    for key, clean_name in MERCHANT_ALIASES.items():
        if key in cleaned:
            return clean_name
    # If we don't recognize it, just tidy up capitalization
    return raw_name.strip().title()

def extract_receipt_data(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    prompt = """You are reading a receipt photo. Return ONLY a JSON object with these
    exact fields, no other text:
    {
      "merchant": "the store or business name as printed",
      "date": "YYYY-MM-DD, your best guess if unclear",
      "total": "the final total as a number, no currency symbol",
      "category": "one of: Groceries, Dining, Transportation, Utilities,
                   Shopping, Entertainment, Health, Travel, Other",
      "estimated_carbon_kg": "your best rough estimate of CO2 kg for this
                   purchase category and amount, as a number",
      "payment_method": "cash, card, or unknown"
    }"""

    response = groq_client.chat.completions.create(
        model="qwen/qwen3.6-27b",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)

# ---------------- The actual page ----------------
st.title("Tracker")

workspace = st.selectbox("Workspace", ["Personal", "genCLEO"])
photo = st.camera_input("Take a photo of your receipt")

if photo is not None:
    with st.spinner("Reading receipt..."):
        image_bytes = photo.getvalue()
        data = extract_receipt_data(image_bytes)
        clean_merchant = normalize_merchant(data.get("merchant", "Unknown"))

    st.success("Here's what I found — check it over before saving:")
    st.write(data)

    if st.button("Save to sheet"):
        sheet = get_sheet()
        sheet.append_row([
            data.get("date", ""),
            workspace,
            clean_merchant,
            data.get("category", ""),
            data.get("total", ""),
            data.get("estimated_carbon_kg", ""),
            "",  # Submitted By — filled in once we add login
            "",  # Status — used later for entity approval
            data.get("payment_method", ""),
            "",  # Notes
            "",  # Receipt Link
            json.dumps(data),  # Raw Extract, our safety net
        ])
        st.success("Saved!")

st.divider()
st.subheader("Recent entries")
try:
    sheet = get_sheet()
    records = sheet.get_all_records()
    if records:
        st.dataframe(records[-10:])
    else:
        st.write("No entries yet — take a photo above to add your first one.")
except Exception as e:
    st.write("Connect your sheet in secrets to see entries here.")
