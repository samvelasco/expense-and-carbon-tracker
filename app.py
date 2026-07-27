import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
import json
import base64
import hashlib
import fitz

st.set_page_config(page_title="Receipt Tracker", layout="centered")

#Connect to Google Sheets
@st.cache_resource
def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["sheet_id"]).sheet1

EXPECTED_HEADERS = [
    "Date", "Merchant", "Category", "Total ($)", "Est. Carbon (kg CO2)",
    "Submitted By", "Payment Method", "Notes", "Raw Extract"
]

def check_headers(sheet):
    """Confirms the sheet's header row matches what append_row() actually writes.
    Without this, a stale or edited header silently misaligns every column —
    exactly what happened when the old 'Workspace' column was left in place."""
    actual = sheet.row_values(1)
    if actual != EXPECTED_HEADERS:
        st.error(
            "Sheet header row doesn't match what this app writes — saving is "
            "disabled until this is fixed, to avoid silently misaligning columns.\n\n"
            f"Expected: {EXPECTED_HEADERS}\n\nFound: {actual}"
        )
        return False
    return True

#Connect to Groq qwen/qwen3.6-27b
groq_client = Groq(api_key=st.secrets["groq_api_key"])

#A small lookup table for common merchant name cleanup.
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

#Carbon estimation: spend-based emission factors
# Methodology: EPA Supply Chain Greenhouse Gas Emission Factors v1.3 (USEEIO model)
CARBON_FACTORS_KG_PER_DOLLAR = {
    "Groceries": 0.186,       # NAICS 445110, Supermarkets and Other Grocery Stores
    "Dining": 0.22,           # blend of NAICS 722511 (Full-Service, 0.194) and 722513 (Limited-Service, 0.255) restaurants
    "Transportation": 0.183,  # NAICS 447110, Gasoline Stations w/ Convenience Stores
    "Utilities": None,        # not available; electricity excluded 
    "Shopping": 0.164,        # NAICS 452210/452311, Department Stores / Warehouse Clubs
    "Entertainment": 0.20,    # blend of NAICS 713940 (Fitness Centers, 0.235) and 713110 (Amusement Parks, 0.167)
    "Health": 0.13,           # NAICS 446110, Pharmacies and Drug Stores
    "Travel": 0.145,          # NAICS 721110, Hotels and Motels; a flight would be closer to 0.644
    "Other": None,            # no defensible category-level factor -> leave blank
}

def normalize_merchant(raw_name):
    cleaned = raw_name.lower().strip()
    for key, clean_name in MERCHANT_ALIASES.items():
        if key in cleaned:
            return clean_name
    return raw_name.strip().title()

def estimate_carbon_kg(category, total_dollars):
    """Spend-based estimate using EPA-style category factors.
    Returns None when there's no defensible factor."""
    factor = CARBON_FACTORS_KG_PER_DOLLAR.get(category)
    if factor is None or total_dollars is None:
        return None
    return round(factor * total_dollars, 2)

def safe_float(value, default=0.0):
    """Parses totals that may come back as '$12.50' or '12,50', or be blank."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default

def extract_receipt_data(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    prompt = """You are reading a receipt photo. Return ONLY a JSON object with these
    exact fields, no other text:
    {
      "merchant": "the store or business name as printed",
      "date": "YYYY-MM-DD, your best guess if unclear",
      "total": "the final total as a plain number, no currency symbol or commas",
      "category": "one of: Groceries, Dining, Transportation, Utilities,
                   Shopping, Entertainment, Health, Travel, Other",
      "category_confidence": "high or low - use low if the receipt is ambiguous
                   or the category is a guess",
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

def pdf_first_page_to_image_bytes(pdf_bytes):
    """Opens a PDF and turns its first page into a PNG image, in memory."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=200)  # 200 dpi keeps text sharp enough to read
    return pix.tobytes("png")

CATEGORIES = ["Groceries", "Dining", "Transportation", "Utilities",
              "Shopping", "Entertainment", "Health", "Travel", "Other"]

# The actual page
st.title("Receipt Tracker")
st.caption("Snap a receipt, review the details, and it's logged with an estimated carbon footprint.")

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

capture_method = st.radio("How would you like to add a receipt?",
                           ["Upload a photo", "Use camera"], horizontal=True)

if capture_method == "Upload a photo":
    photo = st.file_uploader("Upload a receipt image or PDF",
                              type=["jpg", "jpeg", "png", "pdf"],
                              key=f"uploader_{st.session_state.uploader_key}")
else:
    photo = st.camera_input("Take a photo of your receipt",
                             key=f"camera_{st.session_state.uploader_key}")

if photo is not None:
    raw_bytes = photo.getvalue()
    file_key = hashlib.md5(raw_bytes).hexdigest()

    if st.session_state.get("file_key") != file_key:
        with st.spinner("Reading receipt..."):
            if photo.name.lower().endswith(".pdf"):
                image_bytes = pdf_first_page_to_image_bytes(raw_bytes)
            else:
                image_bytes = raw_bytes
            extracted = extract_receipt_data(image_bytes)
            st.session_state.file_key = file_key
            st.session_state.extracted = extracted
            st.session_state.clean_merchant = normalize_merchant(extracted.get("merchant", "Unknown"))
            st.session_state.preview_bytes = image_bytes

    data = st.session_state.extracted
    clean_merchant = st.session_state.clean_merchant

    st.success("Here's what I found! Edit anything that looks off:")

    if data.get("category_confidence") == "low":
        st.warning("The model wasn't confident about the category on this one — "
                    "double-check it before saving.")

    preview_col, form_col = st.columns([1, 1.3])
    with preview_col:
        st.image(st.session_state.preview_bytes, caption="What we read this from",
                  use_container_width=True)

    with form_col:
        # Fields inside a form only trigger a rerun (and re-check the sheet
        # headers) when Save is pressed — not on every keystroke.
        with st.form("receipt_form"):
            edited_merchant = st.text_input("Merchant", value=clean_merchant)
            edited_date = st.text_input("Date (YYYY-MM-DD)", value=data.get("date", ""))
            default_category = data.get("category", "Other")
            edited_category = st.selectbox(
                "Category",
                CATEGORIES,
                index=CATEGORIES.index(default_category) if default_category in CATEGORIES else 8
            )
            edited_total = st.number_input("Total ($)", value=safe_float(data.get("total")))
            submitted_by = st.text_input("Your name *", value="",
                                          help="Required — so the weekly digest can show who submitted what.")
            notes = st.text_input("Notes (optional)", value="",
                                   placeholder="e.g. which program this supports, why it was purchased")

            carbon_estimate = estimate_carbon_kg(edited_category, edited_total)
            if carbon_estimate is not None:
                st.caption(f"Estimated carbon: ~{carbon_estimate} kg CO2e "
                            f"(spend-based estimate, {edited_category} category)")
            else:
                st.caption("No reliable carbon factor for this category yet — left blank rather than guessing.")

            submit = st.form_submit_button("Save to sheet", use_container_width=True)

    if submit:
        if submitted_by.strip() == "":
            st.error("Enter your name before saving.")
        else:
            sheet = get_sheet()
            if check_headers(sheet):
                sheet.append_row([
                    edited_date,
                    edited_merchant,
                    edited_category,
                    edited_total,
                    carbon_estimate if carbon_estimate is not None else "",
                    submitted_by.strip(),
                    data.get("payment_method", ""),
                    notes.strip(),
                    json.dumps(data),  # Raw Extract, our safety net
                ])
                st.success("Saved! Ready for the next receipt.")
                for key in ["file_key", "extracted", "clean_merchant", "preview_bytes"]:
                    st.session_state.pop(key, None)
                st.session_state.uploader_key += 1
                st.rerun()

st.divider()
st.subheader("Recent entries")
try:
    sheet = get_sheet()
    records = sheet.get_all_records()
    if records:
        recent = records[-10:]
        recent_spend = sum(safe_float(r.get("Total ($)")) for r in recent)
        recent_carbon = sum(
            safe_float(r.get("Est. Carbon (kg CO2)"))
            for r in recent if r.get("Est. Carbon (kg CO2)") not in ("", None)
        )
        c1, c2 = st.columns(2)
        c1.metric("Spend (last 10 entries)", f"${recent_spend:,.2f}")
        c2.metric("Est. carbon (last 10 entries)", f"{recent_carbon:,.2f} kg CO2e")

        st.dataframe(
            recent,
            column_config={
                "Total ($)": st.column_config.NumberColumn(format="$%.2f"),
                "Est. Carbon (kg CO2)": st.column_config.NumberColumn(format="%.2f kg"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.write("No entries yet. Take a photo above to add your first one.")
except Exception:
    st.write("Connect your sheet in secrets to see entries here.")
