import os
import html
from datetime import datetime
import xml.etree.ElementTree as ET

import pandas as pd
import requests

TALLY_URL = "http://103.58.167.165:9002"
COMPANY = "BAGARIA MOTORS PVT LTD"
DATA_DIR = "/Users/gautamchatterjee/Dev/NeuronWise Labs BAGARIA Motors Renault_AMC/Dumps/AMC"
LOG_FILE = os.path.join(DATA_DIR, "tally_import_log.txt")

AMC_FILE = "AMC  IMPORT SHEET FOR MARCH 2025.csv"

VOUCHER_TYPE = "Sales"
UPSERT_VOUCHERS = True

DEFAULT_GODOWN = "Main Location"
DEFAULT_BATCH = "Primary Batch"
DEFAULT_SALES_LEDGER = "Sales A/c"
DEFAULT_ITEM_NAME = "Sales"
DEFAULT_UOM = "Nos"

LEDGER_MAP = {
    "Labour Charges": "Labour Charges A/c",
    "CGST @14%": "CGST @14%",
    "SGST @14%": "SGST @14%",
    "IGST @28%": "IGST @28%",
    "CGST @9%": "CGST@9%",
    "SGST @9%": "SGST@9%",
    "IGST @18%": "IGST@18%",
    "CGST @6%": "CGST @6%",
    "SGST @6%": "SGST @6%",
    "IGST @12%": "IGST @12%",
    "CGST @2.5%": "CGST @2.5%",
    "SGST @2.5%": "SGST @2.5%",
    "IGST @5%": "IGST @5%",
}


def clean(v):
    if pd.isna(v):
        return ""
    return str(v).replace("\t", "").strip()


def x(v):
    return html.escape(clean(v))


def log(msg):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def send_xml(xml):
    headers = {"Content-Type": "application/xml"}
    r = requests.post(TALLY_URL, data=xml.encode("utf-8"), headers=headers, timeout=60)
    return r.text


def ok(resp):
    u = resp.upper()
    if "<RESPONSE>UNKNOWN REQUEST" in u:
        return False
    if "<LINEERROR>" in u:
        return False
    if "<ERRORS>0</ERRORS>" in u:
        return True
    if "<CREATED>" in u or "<ALTERED>" in u:
        return True
    return False


def parse_first_tag(xml_text, tag_name):
    try:
        root = ET.fromstring(xml_text)
        elem = root.find(f".//{tag_name}")
        if elem is not None and elem.text:
            return elem.text.strip()
    except Exception:
        return ""
    return ""


def xml_formula_text(v):
    return clean(v).replace('"', "")


def find_existing_voucher_masterid(voucher_no, voucher_type):
    voucher_no = xml_formula_text(voucher_no)
    voucher_type = xml_formula_text(voucher_type)

    xml = f"""
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Export Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <EXPORTDATA>
   <REQUESTDESC>
    <STATICVARIABLES>
     <SVCURRENTCOMPANY>{html.escape(COMPANY)}</SVCURRENTCOMPANY>
    </STATICVARIABLES>
    <TDL>
     <TDLMESSAGE>
      <COLLECTION NAME="VchLookup" ISMODIFY="No">
       <TYPE>Voucher</TYPE>
       <FETCH>MASTERID,VOUCHERNUMBER,VOUCHERTYPENAME,DATE</FETCH>
       <FILTERS>VchNoFilter,VchTypeFilter</FILTERS>
      </COLLECTION>

      <SYSTEM TYPE="Formulae" NAME="VchNoFilter">$VoucherNumber = "{html.escape(voucher_no)}"</SYSTEM>
      <SYSTEM TYPE="Formulae" NAME="VchTypeFilter">$VoucherTypeName = "{html.escape(voucher_type)}"</SYSTEM>
     </TDLMESSAGE>
    </TDL>
   </REQUESTDESC>
   <REQUESTDATA>
    <TALLYMESSAGE xmlns:UDF="TallyUDF">
     <COLLECTION NAME="VchLookup"/>
    </TALLYMESSAGE>
   </REQUESTDATA>
  </EXPORTDATA>
 </BODY>
</ENVELOPE>
"""
    resp = send_xml(xml)
    return parse_first_tag(resp, "MASTERID")


def to_tally_date(date_str):
    date_str = clean(date_str)
    if not date_str:
        return ""

    supported_formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y-%m-%d",
        "%d-%m-%y",
        "%d-%b-%y",
        "%d-%b-%Y",
    ]

    for fmt in supported_formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y%m%d")
        except ValueError:
            pass

    raise ValueError(f"Unsupported date format: {date_str}")


def amount_to_float(v):
    s = clean(v)
    if not s:
        return 0.0
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_item_name(v):
    s = clean(v)
    while len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1].strip()
    return s.strip()


def build_party_ledger_xml(party_name, amount):
    party_name = html.escape(party_name)
    return f"""
      <LEDGERENTRIES.LIST>
       <LEDGERNAME>{party_name}</LEDGERNAME>
       <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
       <LEDGERFROMITEM>No</LEDGERFROMITEM>
       <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
       <AMOUNT>-{amount:.2f}</AMOUNT>
      </LEDGERENTRIES.LIST>
"""


def build_tax_ledger_xml(ledger_name, amount):
    ledger_name = html.escape(ledger_name)
    return f"""
      <LEDGERENTRIES.LIST>
       <LEDGERNAME>{ledger_name}</LEDGERNAME>
       <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
       <LEDGERFROMITEM>No</LEDGERFROMITEM>
       <ISPARTYLEDGER>No</ISPARTYLEDGER>
       <AMOUNT>{amount:.2f}</AMOUNT>
      </LEDGERENTRIES.LIST>
"""


def build_inventory_entry_xml(item_name, qty, rate, amount, godown_name):
    item_name = normalize_item_name(item_name) or DEFAULT_ITEM_NAME
    item_name_esc = html.escape(item_name)
    godown_esc = html.escape(clean(godown_name) or DEFAULT_GODOWN)

    return f"""
      <ALLINVENTORYENTRIES.LIST>
       <STOCKITEMNAME>{item_name_esc}</STOCKITEMNAME>
       <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
       <RATE>{rate:.2f}/{DEFAULT_UOM}</RATE>
       <AMOUNT>{amount:.2f}</AMOUNT>
       <ACTUALQTY>{qty:.2f} {DEFAULT_UOM}</ACTUALQTY>
       <BILLEDQTY>{qty:.2f} {DEFAULT_UOM}</BILLEDQTY>
       <BATCHALLOCATIONS.LIST>
        <GODOWNNAME>{godown_esc}</GODOWNNAME>
        <BATCHNAME>{html.escape(DEFAULT_BATCH)}</BATCHNAME>
        <INDENTNO>&#4; Not Applicable</INDENTNO>
        <ORDERNO>&#4; Not Applicable</ORDERNO>
        <TRACKINGNUMBER>&#4; Not Applicable</TRACKINGNUMBER>
        <AMOUNT>{amount:.2f}</AMOUNT>
        <ACTUALQTY>{qty:.2f} {DEFAULT_UOM}</ACTUALQTY>
        <BILLEDQTY>{qty:.2f} {DEFAULT_UOM}</BILLEDQTY>
       </BATCHALLOCATIONS.LIST>
       <ACCOUNTINGALLOCATIONS.LIST>
        <LEDGERNAME>{html.escape(DEFAULT_SALES_LEDGER)}</LEDGERNAME>
        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
        <LEDGERFROMITEM>No</LEDGERFROMITEM>
        <ISPARTYLEDGER>No</ISPARTYLEDGER>
        <AMOUNT>{amount:.2f}</AMOUNT>
       </ACCOUNTINGALLOCATIONS.LIST>
      </ALLINVENTORYENTRIES.LIST>
"""


def import_amc_sales_consolidated():
    log("\nSTEP 1 - AMC SALES VOUCHERS (CONSOLIDATED, JOB CARD BILLS STYLE)")

    df = pd.read_csv(os.path.join(DATA_DIR, AMC_FILE))
    df.columns = [clean(c) for c in df.columns]

    required_cols = ["Invoice No.", "Job Card Date", "Customer Name", "Basic Amount"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Required column missing in CSV: {col}")

    df["Invoice No."] = df["Invoice No."].apply(clean)
    df["Job Card No."] = df["Job Card No."].apply(clean) if "Job Card No." in df.columns else ""
    df["Job Card Date"] = df["Job Card Date"].apply(clean)
    df["Customer Name"] = df["Customer Name"].apply(clean)
    df["Name Of Item"] = (
        df["Name Of Item"].apply(normalize_item_name)
        if "Name Of Item" in df.columns
        else DEFAULT_ITEM_NAME
    )
    df["Godown"] = df["Godown"].apply(clean) if "Godown" in df.columns else DEFAULT_GODOWN

    success = 0
    failed = 0
    skipped = 0

    grouped = df.groupby("Invoice No.", dropna=False)

    for invoice_no, group in grouped:
        invoice_no = clean(invoice_no)

        if not invoice_no:
            skipped += 1
            log("VOUCHER SKIPPED | blank invoice number")
            continue

        first_row = group.iloc[0]
        party = clean(first_row.get("Customer Name"))
        job_card_no = clean(first_row.get("Job Card No.")) if "Job Card No." in group.columns else invoice_no
        reference_no = invoice_no

        try:
            date = to_tally_date(first_row.get("Job Card Date"))
        except ValueError as e:
            skipped += 1
            log(f"VOUCHER SKIPPED | invoice={invoice_no} | {str(e)}")
            continue

        if not party or not date:
            skipped += 1
            log(f"VOUCHER SKIPPED | invoice={invoice_no} | party/date missing")
            continue

        inventory_entries_xml = ""
        inventory_total = 0.0
        inventory_line_count = 0

        for _, row in group.iterrows():
            item_name = normalize_item_name(row.get("Name Of Item")) or DEFAULT_ITEM_NAME
            basic_amount = amount_to_float(row.get("Basic Amount"))
            godown_name = clean(row.get("Godown")) or DEFAULT_GODOWN

            if basic_amount == 0:
                continue

            qty = 1.0
            rate = basic_amount

            inventory_entries_xml += build_inventory_entry_xml(
                item_name=item_name,
                qty=qty,
                rate=rate,
                amount=basic_amount,
                godown_name=godown_name,
            )
            inventory_total += round(basic_amount, 2)
            inventory_line_count += 1

        ledger_totals = {}

        labour_total = round(group["Labour Charges"].apply(amount_to_float).sum(), 2) if "Labour Charges" in group.columns else 0.0
        if abs(labour_total) > 0:
            ledger_totals["Labour Charges A/c"] = labour_total

        for csv_col, tally_ledger in LEDGER_MAP.items():
            if csv_col == "Labour Charges":
                continue
            if csv_col in group.columns:
                total_val = round(group[csv_col].apply(amount_to_float).sum(), 2)
                if abs(total_val) > 0:
                    ledger_totals[tally_ledger] = total_val

        gross_total = round(inventory_total + sum(ledger_totals.values()), 2)

        if inventory_line_count == 0 and gross_total == 0:
            skipped += 1
            log(f"VOUCHER SKIPPED | invoice={invoice_no} | no value rows")
            continue

        voucher_action = "Create"
        master_id_xml = ""
        existing_masterid = ""

        if UPSERT_VOUCHERS:
            existing_masterid = find_existing_voucher_masterid(invoice_no, VOUCHER_TYPE)
            if existing_masterid:
                voucher_action = "Alter"
                master_id_xml = f"<MASTERID>{html.escape(existing_masterid)}</MASTERID>"

        ledger_entries_xml = build_party_ledger_xml(party, gross_total)
        for ledger_name, amt in ledger_totals.items():
            ledger_entries_xml += build_tax_ledger_xml(ledger_name, amt)

        xml = f"""
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Import Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <IMPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Vouchers</REPORTNAME>
    <STATICVARIABLES>
     <SVCURRENTCOMPANY>{html.escape(COMPANY)}</SVCURRENTCOMPANY>
    </STATICVARIABLES>
   </REQUESTDESC>
   <REQUESTDATA>
    <TALLYMESSAGE xmlns:UDF="TallyUDF">
     <VOUCHER VCHTYPE="{html.escape(VOUCHER_TYPE)}" ACTION="{voucher_action}" OBJVIEW="Invoice Voucher View">
      {master_id_xml}
      <DATE>{date}</DATE>
      <VCHSTATUSDATE>{date}</VCHSTATUSDATE>
      <REFERENCE>{html.escape(reference_no)}</REFERENCE>
      <VOUCHERTYPENAME>{html.escape(VOUCHER_TYPE)}</VOUCHERTYPENAME>
      <PARTYNAME>{html.escape(party)}</PARTYNAME>
      <PARTYLEDGERNAME>{html.escape(party)}</PARTYLEDGERNAME>
      <VOUCHERNUMBER>{html.escape(invoice_no)}</VOUCHERNUMBER>
      <BASICBUYERNAME>{html.escape(party)}</BASICBUYERNAME>
      <PARTYMAILINGNAME>{html.escape(party)}</PARTYMAILINGNAME>
      <CONSIGNEEMAILINGNAME>{html.escape(party)}</CONSIGNEEMAILINGNAME>
      <BASICBASEPARTYNAME>{html.escape(party)}</BASICBASEPARTYNAME>
      <NUMBERINGSTYLE>Manual</NUMBERINGSTYLE>
      <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
      <ISINVOICE>Yes</ISINVOICE>
      <ISOPTIONAL>No</ISOPTIONAL>
      <ISCANCELLED>No</ISCANCELLED>
      <ISDELETED>No</ISDELETED>
      <IGNOREGSTINVALIDATION>No</IGNOREGSTINVALIDATION>
      <REFERENCE>{html.escape(job_card_no)}</REFERENCE>
{inventory_entries_xml}
{ledger_entries_xml}
     </VOUCHER>
    </TALLYMESSAGE>
   </REQUESTDATA>
  </IMPORTDATA>
 </BODY>
</ENVELOPE>
"""

        resp = send_xml(xml)

        if ok(resp):
            success += 1
            log(
                f"VOUCHER OK    | action={voucher_action} | invoice={invoice_no} | party={party} | "
                f"inventory_total={inventory_total:.2f} | gross={gross_total:.2f} | "
                f"inventory_lines={inventory_line_count} | ledgers={ledger_totals} | "
                f"masterid={existing_masterid}"
            )
        else:
            failed += 1
            log(
                f"VOUCHER FAILED| action={voucher_action} | invoice={invoice_no} | "
                f"masterid={existing_masterid} | {resp.strip()}"
            )

    log(f"VOUCHER SUMMARY | Success={success} Failed={failed} Skipped={skipped}")


def main():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("Tally AMC import started\n")

    import_amc_sales_consolidated()

    log("\nIMPORT COMPLETED")
    log(f"Detailed log saved at: {LOG_FILE}")


if __name__ == "__main__":
    main()