"""
Generate 20 mixed-confidence PO XML files:
  8 GREEN  - real customers + real crosswalk part numbers
  7 YELLOW - real customers + 1 known part + 1 fake part
  5 RED    - completely unknown companies (no crosswalk match)
"""
import os, random, requests, base64

BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(BASE, "test_data")
API    = "https://enpro-po-agent.fly.dev"
AUTH   = ("enpro", "EnPro2026!")

# ── Ship-to addresses (exact ship2_name from customer_crosswalk.csv) ──────────

SHIP = {
    "203471": ("Grain Processing Corp.",    "1600 Oregon St",        "Muscatine",    "IA", "52761-1404"),
    "207607": ("Steel Dynamics, Inc.",       "4500 County Road 59",   "Butler",       "IN", "46721-9747"),
    "202846": ("Equistar Chemical",          "3400 Anamosa Rd",       "Clinton",      "IA", "52732-9700"),
    "208421": ("USS - Gary Works",           "1 N Buchanan St",       "Gary",         "IN", "46402-1060"),
    "204260": ("Evonik Corporation",         "1650 Lilly Rd",         "Lafayette",    "IN", "47909"),
    "201006": ("Bayer Cropscience LP",       "8400 Hawthorn Rd",      "Kansas City",  "MO", "64120"),
    "306771": ("Koch Fertilizer Company LLC","2825 Mount Pleasant St", "Burlington",  "IA", "52601-2096"),
    "200543": ("AmeriChem Systems, Incorporated","1740 Molitor Rd",   "Aurora",       "IL", "60505-1346"),
    "200121": ("ADM Bio Products",           "4666 E Faries Pkwy",    "Decatur",      "IL", "62526-5630"),
    "206035": ("Nucor Steel",                "4537 S Nucor Rd",       "Crawfordsville","IN","47933-7969"),
    "207716": ("Cargill",                    "17540 Monroe Wapello Rd","Eddyville",   "IA", "52553-8032"),
    "200513": ("American Crystal Sugar Co.", "2500 N 11th St",        "Moorhead",     "MN", "56560"),
    "208426": ("Kurita America Inc.",        "6600 94th Ave N",       "Minneapolis",  "MN", "55445"),
    "205592": ("Caterpillar Tractor Co 29",  "1300 4-H Park Road",    "Pontiac",      "IL", "61764"),
    "205382": ("Minnesota Mining &amp; Mfg.","22614 Route 84 N",      "Cordova",      "IL", "61242-9779"),
}

PARTS = {
    "9000238":           ("Seal Kit",            "EA", 45.00),
    "Z16820-250D":       ("Diaphragm Assembly",  "EA", 3319.00),
    "HE3-490-D":         ("Filter Element",      "EA", 6143.00),
    "669339":            ("O-Ring Kit",          "EA", 50.00),
    "490.646.1Y.BC":     ("Shaft Seal",          "EA", 24.73),
    "770104-000207":     ("Bearing Assembly",    "EA", 256.86),
    "PH0260":            ("Pump Housing",        "EA", 125.00),
    "T10540036":         ("Filter Cartridge",    "EA", 73.21),
    "SHAFT-A":           ("Drive Shaft Assembly","EA", 7140.00),
    "460.646.17.BC.00A": ("Mechanical Seal",     "EA", 24.73),
    "P1MCW1140066CXAG":  ("Control Valve Positioner","EA", 6490.31),
}

def items_xml(lines):
    out = ""
    for i, (part, desc, price, qty, uom) in enumerate(lines, 1):
        out += f"""
      <ItemOut lineNumber="{i}" quantity="{qty}" requestedDeliveryDate="2026-07-30">
        <ItemID><SupplierPartID>{part}</SupplierPartID></ItemID>
        <ItemDetail>
          <UnitPrice><Money currency="USD">{price:.2f}</Money></UnitPrice>
          <Description xml:lang="en">{desc}</Description>
          <UnitOfMeasure>{uom}</UnitOfMeasure>
        </ItemDetail>
      </ItemOut>"""
    return out

def make_xml(po_no, ship_name, add1, city, state, zip_, buyer, email, lines, src, sender_id):
    total = sum(p * q for _, _, p, q, _ in lines)
    domain = "AribaNetworkId" if src == "ariba" else "CoupaSupplierNetwork"
    ver    = ' orderVersion="1"' if src == "ariba" else ""
    ts     = f"2026-06-04T{8 + random.randint(0,8):02d}:{random.randint(0,59):02d}:00-06:00"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE cXML SYSTEM "http://xml.cXML.org/schemas/cXML/1.2.069/cXML.dtd">
<cXML payloadID="{po_no}-{random.randint(10000,99999)}@enpro.com" timestamp="{ts}" version="1.2.069">
  <Header>
    <From><Credential domain="{domain}"><Identity>{sender_id}</Identity></Credential></From>
    <To><Credential domain="{domain}"><Identity>{"AN01234567890" if src=="ariba" else "CSN-ENPRO-SUPPLIER"}</Identity></Credential></To>
    <Sender>
      <Credential domain="{domain}"><Identity>{sender_id}</Identity></Credential>
      <UserAgent>{"Ariba Buyer 9R1" if src=="ariba" else "Coupa Procurement 23.0"}</UserAgent>
    </Sender>
  </Header>
  <Request>
    <OrderRequest>
      <OrderRequestHeader orderID="{po_no}" orderDate="2026-06-04" orderType="regular"{ver}>
        <Total><Money currency="USD">{total:.2f}</Money></Total>
        <ShipTo>
          <Address>
            <Name xml:lang="en">{ship_name}</Name>
            <PostalAddress>
              <Street>{add1}</Street>
              <City>{city}</City>
              <State>{state}</State>
              <PostalCode>{zip_}</PostalCode>
              <Country isoCountryCode="US">United States</Country>
            </PostalAddress>
          </Address>
        </ShipTo>
        <Contact role="purchasingAgent">
          <Name xml:lang="en">{buyer}</Name>
          <Email>{email}</Email>
        </Contact>
        <Extrinsic name="AribaNetwork.PaymentTermsExplanation">Net 30</Extrinsic>
      </OrderRequestHeader>{items_xml(lines)}
    </OrderRequest>
  </Request>
</cXML>"""

# ── GREEN POs (8) — real customers, all parts in crosswalk ───────────────────
green_pos = [
    ("203471", "4500998112-B1", "ariba",  "AN-GPC-03471",  "Dale Voss",    "dvoss@grainprocessing.com",
     [("460.646.17.BC.00A", "Mechanical Seal",        24.73, 12, "EA"),
      ("HE3-490-D",          "Filter Element",        6143.00, 2, "EA")]),
    ("207607", "431908-B1",     "coupa",  "CSN-SDI-7607",  "Phil Gerber",  "pgerber@steeldynamics.com",
     [("9000238",  "Seal Kit",     45.00, 8, "EA"),
      ("PH0260",   "Pump Housing",125.00, 3, "EA")]),
    ("202846", "4406338812-B1", "ariba",  "AN-EQU-02846",  "Carol Ness",   "cness@equistar.com",
     [("SHAFT-A",     "Drive Shaft Assembly 316SS", 6526.00, 1, "EA"),
      ("Z16820-250D", "Diaphragm Assembly",         3319.00, 2, "EA")]),
    ("208421", "21845992-B1",   "coupa",  "CSN-USS-8421",  "Bob Pringle",  "bpringle@uss.com",
     [("770104-000207","Bearing Assembly", 256.86, 6, "EA"),
      ("669339",        "O-Ring Kit",       50.00,24, "EA")]),
    ("204260", "4710471882-B1", "ariba",  "AN-EVON-04260", "Hans Mueller", "hans.mueller@evonik.com",
     [("T10540036","Filter Cartridge",73.21, 8, "EA"),
      ("9000238",  "Seal Kit",        45.00, 4, "EA")]),
    ("201006", "618031902-B1",  "coupa",  "CSN-BAYER-1006","Sara Wyatt",   "sara.wyatt@bayer.com",
     [("PH0260",      "Pump Housing",125.00, 4, "EA"),
      ("490.646.1Y.BC","Shaft Seal",  24.73, 6, "EA")]),
    ("306771", "202617449-B1",  "ariba",  "AN-KOCH-6771",  "Craig Dobb",   "cdobb@kochfert.com",
     [("HE3-490-D","Filter Element",6143.00, 2, "EA"),
      ("9000238",  "Seal Kit",       45.00, 8, "EA")]),
    ("200543", "39210-B1",      "coupa",  "CSN-ACHEM-0543","Tony Ferraro", "tferraro@americhemsystems.com",
     [("669339",     "O-Ring Kit",           50.00, 6, "EA"),
      ("Z16820-250D","Diaphragm Assembly", 3319.00, 1, "EA")]),
]

# ── YELLOW POs (7) — real customer match + 1 known part + 1 unknown part ─────
yellow_pos = [
    ("200121", "4500862341-B1", "ariba", "AN-ADM-200121",  "Jennifer Walsh","jwalsh@adm.com",
     [("9000238",      "Seal Kit",              45.00, 6, "EA"),
      ("FAKE-PART-YL1","Unknown Component",    150.00, 2, "EA")]),
    ("206035", "NUC-2026-B1",   "coupa", "CSN-NUCOR-6035", "Mike Reynolds", "mreynolds@nucor.com",
     [("HE3-490-D",      "Filter Element",    6143.00, 4, "EA"),
      ("UNKN-VALVE-123","Control Valve (TBD)", 850.00, 1, "EA")]),
    ("207716", "4521318204-B1", "ariba", "AN-CARGILL-7716","Tom Brandt",    "tom_brandt@cargill.com",
     [("490.646.1Y.BC",  "Shaft Seal",          24.73, 8, "EA"),
      ("RAND-SEAL-456", "Mechanical Seal NLA", 175.00, 4, "EA")]),
    ("200513", "CP-ACS-B1",     "coupa", "CSN-ACS-0513",   "Paula Norling", "pnorling@crystalsugar.com",
     [("770104-000207",   "Bearing Assembly",  256.86, 4, "EA"),
      ("FAKE-BEARING-Y4","Thrust Bearing NLA", 320.00, 2, "EA")]),
    ("208426", "KWT-PO-B1",     "ariba", "AN-KURITA-8426", "Greg Holt",     "g.holt@kurita-water.com",
     [("PH0260",           "Pump Housing",     125.00, 2, "EA"),
      ("NO-MATCH-PUMP-Y5","Pump Head Assembly",490.00, 1, "EA")]),
    ("205592", "CP-CAT-B1",     "coupa", "CSN-CAT-5592",   "Rachel Simmons","rsimmons@cat.com",
     [("SHAFT-A",          "Drive Shaft",     7140.00, 1, "EA"),
      ("UNK-COUPLING-Y6","Flex Coupling NLA", 245.00, 2, "EA")]),
    ("205382", "4823219007-B1", "ariba", "AN-3M-05382",    "Diane Park",    "dpark@mmm.com",
     [("P1MCW1140066CXAG",  "Control Valve Positioner", 6490.31, 1, "EA"),
      ("FAKE-POSITIONER-Y7","Valve Actuator NLA",        980.00, 1, "EA")]),
]

# ── RED POs (5) — completely unknown companies, no crosswalk match ────────────
red_pos = [
    ("Acme Chemical Corporation",  "123 Industrial Blvd",   "Provo",      "UT","84601",
     "R-ACME-2026-001", "ariba", "AN-ACME-CHEM-9001",  "Bob Smith",    "bsmith@acmechem.com",
     [("ACME-FILTER-001","Bulk Filter Housing",    420.00, 5, "EA"),
      ("ACME-PUMP-002",  "Circulation Pump",      1850.00, 1, "EA")]),
    ("Global Process Systems Inc", "456 Technology Dr",     "Boise",      "ID","83701",
     "GPS-PO-2026-8844","coupa", "CSN-GLOBALPS-8844", "Linda Torres", "ltorres@globalps.com",
     [("GPS-VALVE-A1",   "Globe Valve 2in",        315.00, 8, "EA"),
      ("GPS-FILTER-B2",  "Process Filter",         890.00, 2, "EA")]),
    ("Pacific Coast Filtration LLC","789 Harbor Way",       "Bellingham","WA","98225",
     "PCF-2026-00331",  "ariba", "AN-PACCOAST-0331", "James Chen",   "jchen@paccoastfilt.com",
     [("PCF-CART-001",   "Filter Cartridge 10mic", 88.50, 24, "EA"),
      ("PCF-HOUS-002",   "Filter Housing SS",     445.00,  4, "EA")]),
    ("Mountain West Industries",   "321 Commerce Pkwy",     "Helena",     "MT","59601",
     "MWI-PO-2026-1122","coupa", "CSN-MWI-1122",     "Sarah Davis",  "sdavis@mwimt.com",
     [("MWI-SEAL-X1",    "Face Seal Kit",          67.00, 10, "EA"),
      ("MWI-BEAR-X2",    "Roller Bearing",        195.00,  6, "EA")]),
    ("Coastal Petroleum Services", "654 Refinery Rd",       "Mobile",     "AL","36601",
     "CPS-2026-55001",  "ariba", "AN-CPSALABAMA-1",  "Mike Johnson", "mjohnson@coastalpetro.com",
     [("CPS-VALVE-001",  "Gate Valve 4in",        1240.00, 3, "EA"),
      ("CPS-GASKET-002", "Spiral Wound Gasket",     42.00,20, "EA")]),
]

# ── Generate files and upload ─────────────────────────────────────────────────

results = []

print("=== Generating GREEN POs (8) ===")
for cid, po_no, src, sender, buyer, email, lines in green_pos:
    name, add1, city, state, zip_ = SHIP[cid]
    xml = make_xml(po_no, name, add1, city, state, zip_, buyer, email, lines, src, sender)
    fname = f"mixed_green_{po_no}.xml"
    path  = os.path.join(OUTDIR, fname)
    open(path, "w", encoding="utf-8").write(xml)

    resp = requests.post(
        f"{API}/api/v1/intake/upload",
        auth=AUTH,
        files={"file": (fname, open(path,"rb"), "application/xml")},
        data={"source": src},
        timeout=30
    )
    d = resp.json()
    conf  = d.get("confidence", d.get("status", "?"))
    cname = d.get("customer_match", {}).get("name", "?")
    score = d.get("customer_match", {}).get("score", 0)
    print(f"  {po_no:25s} → {conf.upper():8s} | customer={cname} | score={score:.2f}")
    results.append((po_no, conf, cname))

print("\n=== Generating YELLOW POs (7) ===")
for cid, po_no, src, sender, buyer, email, lines in yellow_pos:
    name, add1, city, state, zip_ = SHIP[cid]
    xml = make_xml(po_no, name, add1, city, state, zip_, buyer, email, lines, src, sender)
    fname = f"mixed_yellow_{po_no}.xml"
    path  = os.path.join(OUTDIR, fname)
    open(path, "w", encoding="utf-8").write(xml)

    resp = requests.post(
        f"{API}/api/v1/intake/upload",
        auth=AUTH,
        files={"file": (fname, open(path,"rb"), "application/xml")},
        data={"source": src},
        timeout=30
    )
    d = resp.json()
    conf  = d.get("confidence", d.get("status", "?"))
    cname = d.get("customer_match", {}).get("name", "?")
    score = d.get("customer_match", {}).get("score", 0)
    items = d.get("item_scores", [])
    matched = len([x for x in items if x > 0])
    print(f"  {po_no:25s} → {conf.upper():8s} | customer={cname} | items={matched}/{len(items)}")
    results.append((po_no, conf, cname))

print("\n=== Generating RED POs (5) ===")
for (company, add1, city, state, zip_, po_no, src, sender, buyer, email, lines) in red_pos:
    xml = make_xml(po_no, company, add1, city, state, zip_, buyer, email, lines, src, sender)
    fname = f"mixed_red_{po_no}.xml"
    path  = os.path.join(OUTDIR, fname)
    open(path, "w", encoding="utf-8").write(xml)

    resp = requests.post(
        f"{API}/api/v1/intake/upload",
        auth=AUTH,
        files={"file": (fname, open(path,"rb"), "application/xml")},
        data={"source": src},
        timeout=30
    )
    d = resp.json()
    conf  = d.get("confidence", d.get("status", "?"))
    cname = d.get("customer_match", {}).get("name", "no match")
    score = d.get("customer_match", {}).get("score", 0)
    print(f"  {po_no:25s} → {conf.upper():8s} | customer={cname} | score={score:.2f}")
    results.append((po_no, conf, cname))

print("\n=== SUMMARY ===")
green  = [r for r in results if r[1] == "green"]
yellow = [r for r in results if r[1] == "yellow"]
red    = [r for r in results if r[1] == "red"]
dup    = [r for r in results if r[1] == "duplicate"]
print(f"  GREEN:     {len(green)}/8")
print(f"  YELLOW:    {len(yellow)}/7")
print(f"  RED:       {len(red)}/5")
if dup: print(f"  DUPLICATE: {len(dup)} (rerun to generate new PO numbers)")
