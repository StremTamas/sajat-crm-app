import datetime
import math
import random
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.service_account import Credentials
import gspread
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# ==========================================
# 1. OLDAL BEÁLLÍTÁSAI ÉS STÍLUS
# ==========================================
st.set_page_config(
    page_title="Alfa Arrabona CRM", page_icon="💼", layout="wide"
)

st.markdown(
    """
    <style>
    .stApp {
        background-color: #f8f9fa;
    }
    section[data-testid="stSidebar"] {
        background-color: #1e293b !important;
    }
    section[data-testid="stSidebar"] * {
        color: #ffffff !important;
    }
    section[data-testid="stSidebar"] button {
        background-color: #334155 !important;
        color: #ffffff !important;
        border: 1px solid #475569 !important;
        border-radius: 6px !important;
    }
    section[data-testid="stSidebar"] button:hover {
        background-color: #475569 !important;
    }
    .main button {
        color: #0f172a !important;
        font-weight: bold !important;
    }
    .new-lead-card {
        background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%);
        color: white;
        padding: 15px 20px;
        border-radius: 10px;
        font-weight: bold;
        font-size: 16px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .red-alert-box {
        background-color: #ffe5e5;
        border-left: 5px solid #ff4b4b;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 10px;
        color: #900000;
    }
    </style>
""",
    unsafe_allow_html=True,
)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "arrabonainsurance@gmail.com"
SENDER_NAME = "Insurance Arrabona"
SENDER_PASSWORD = "aqzs okrl jewl ypdw"

# --- E-MAIL KÉPEK LINKEI ---
LOGO_URL = "https://lh3.googleusercontent.com/d/IDE_JON_A_LOGO_ID"
PORTRAIT_URL = "https://lh3.googleusercontent.com/d/IDE_JON_AZ_ARCKEP_ID"

# --- GOOGLE SHEET AZONOSÍTÓK ---
CRM_BEALLITASOK_SHEET_ID = "1XwKnEFG5w7y0iFhBksiwQn62E3pLQBv0UwK_258T4Ng"

RECRUITMENT_FORM_SPREADSHEET_ID = (
    "1hlFrgfdUDANg1m2gIA6w_10kI5ODQ_TIw8v9-WmYf-g"
)
POSSIBLE_FORM_SHEETS = [
    "Form Responses 1",
    "Űrlapválaszok 1",
    "Form-válaszok 1",
    "Válaszok",
]

# --- ADATBÁZIS CSATLAKOZÁS (POSTGRESQL / SUPABASE) ---
def get_db_connection():
    if "DATABASE_URL" not in st.secrets:
        st.error("⛔ Hiányzik a DATABASE_URL a Streamlit Secrets legfelső sorából!")
        st.stop()
    try:
        conn = psycopg2.connect(st.secrets["DATABASE_URL"], cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        st.error(f"❌ Részletes adatbázis csatlakozási hiba: {e}")
        st.stop()

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            role VARCHAR(100) NOT NULL,
            manager_id INTEGER,
            is_active INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            client_name VARCHAR(255) NOT NULL,
            phone VARCHAR(100),
            email VARCHAR(255),
            address TEXT,
            contact_person VARCHAR(255),
            source VARCHAR(255),
            status VARCHAR(100) DEFAULT 'Új',
            assigned_manager_id INTEGER,
            assigned_advisor_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    """)
    cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE username = %s", ('admin',))
    res = cursor.fetchone()
    if res['cnt'] == 0:
        cursor.execute("""
            INSERT INTO users (username, password, name, role, is_active)
            VALUES ('admin', 'admin123', 'Strem Tamás', 'Igazgató', 1)
        """)
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. HIVATALOS ADATFORRÁSOK 
# ==========================================
SHEET_SOURCES = [
    {
        "name": "Vállalkozói Felmérés Válaszok",
        "id": "1BGe4tQCN-KRIXaONivmqflyrQtXiJ4ozGr4L9LgOPZs",
        "cooldown_days": 30 
    },
    {
        "name": "Ügyfél Évfordulók",
        "id": "1mFO7kg_JXVLbzSA2r7_gqRRLqhpXyaiUgvlCg-EoxHY",
        "condition_col": "felülvizsgálat", 
        "condition_val": "igen",
        "cooldown_days": 30 
    },
    {
        "name": "VIG B2B Ügyfélklub Adatbázis",
        "id": "1l3_asDDKdePuZjoFBBV7hiG4EzpBHKy3Rc467yt2uTc",
        "cooldown_days": 30 
    },
    {
        "name": "Promobox ügyfelek",
        "id": "1lvg5SahZ5r9BONF443ZEHj3SIWmxjiNZhbPSU5yj84w",
        "condition_col": "", 
        "condition_val": "igen",
        "cooldown_days": 30 
    },
]

def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=scopes
        )
    else:
        creds = Credentials.from_service_account_file(
            "credentials.json", scopes=scopes
        )
    return gspread.authorize(creds)

def sync_google_sheets_to_crm():
    try:
        client = get_gspread_client()
        conn = get_db_connection()
        cursor = conn.cursor()
        new_leads_count = 0

        for src in SHEET_SOURCES:
            try:
                spreadsheet = client.open_by_key(src["id"])
                cooldown = int(src.get("cooldown_days", 30))
                
                for sheet in spreadsheet.worksheets():
                    all_rows = sheet.get_all_values()

                    if len(all_rows) < 2:
                        continue

                    headers = [str(h).strip().lower() for h in all_rows[0]]
                    
                    feldolgozva_col_idx = None
                    for idx, h in enumerate(headers):
                        if "feldolgozva" in h or "status" in h:
                            feldolgozva_col_idx = idx + 1
                            break

                    for i, row_values in enumerate(all_rows[1:], start=2):
                        r = {}
                        for idx, h in enumerate(headers):
                            val = str(row_values[idx]).strip() if idx < len(row_values) else ""
                            r[h] = val

                        if "condition_col" in src:
                            cond_found = False
                            for k, v in r.items():
                                if src["condition_col"] in k and src["condition_val"] in v.lower():
                                    cond_found = True
                                    break
                            if not cond_found:
                                continue

                        nev = ""
                        email = ""
                        phone = ""
                        feldolgozva = ""
                        extracted_info = []

                        for k, v in r.items():
                            if not email and ("mail" in k or "e-mail" in k):
                                email = v
                            elif not phone and ("telefon" in k or "tel" in k or "mobil" in k):
                                phone = v
                            elif not nev and (
                                "cégnév" in k
                                or "név" in k
                                or "nev" in k  
                                or "cég" in k
                                or "kapcsolattartó" in k
                                or "vállalkozás" in k
                            ):
                                nev = v
                            elif "feldolgozva" in k or "status" in k:
                                feldolgozva = v.upper()

                        if feldolgozva in ["OK", "IGEN", "FELDOLGOZVA", "LEZÁRT"]:
                            continue

                        if not email and not nev and not phone:
                            continue

                        if not nev and email:
                            nev = email.split("@")[0].capitalize()
                        elif not nev and phone:
                            nev = f"Ismeretlen érdeklődő (Tel: {phone})"

                        for k, v in r.items():
                            if v and not any(
                                skip in k
                                for skip in [
                                    "időbélyeg",
                                    "timestamp",
                                    "feldolgozva",
                                    "cégnév",
                                    "e-mail",
                                    "email",
                                    "telefonszám",
                                    "tel",
                                ]
                            ):
                                extracted_info.append(f"{v}")

                        auto_notes = (
                            " | ".join(extracted_info)
                            if extracted_info
                            else "Beérkezett kitöltés"
                        )

                        if src["name"] == "Ügyfél Évfordulók":
                            cursor.execute(
                                f"SELECT id FROM leads WHERE email != '' AND email = %s AND source = %s AND notes = %s AND created_at >= NOW() - INTERVAL '{cooldown} days'",
                                (email, src["name"], auto_notes),
                            )
                        else:
                            cursor.execute(
                                f"""SELECT id FROM leads 
                                   WHERE ((email != '' AND email = %s) 
                                          OR (client_name != '' AND client_name = %s)
                                          OR (phone != '' AND phone = %s))
                                     AND source = %s 
                                     AND created_at >= NOW() - INTERVAL '{cooldown} days'""",
                                (email, nev, phone, src["name"]),
                            )
                            
                        existing = cursor.fetchone()

                        if not existing:
                            cursor.execute(
                                """
                                INSERT INTO leads (client_name, phone, email, address, contact_person, source, status, notes)
                                VALUES (%s, %s, %s, '', %s, %s, 'Új', %s)
                                """,
                                (nev, phone, email, nev, src["name"], auto_notes),
                            )
                            new_leads_count += 1
                            
                            if feldolgozva_col_idx:
                                try:
                                    sheet.update_cell(i, feldolgozva_col_idx, "OK")
                                    time.sleep(1)
                                except Exception as err:
                                    st.sidebar.warning(f"Nem sikerült beírni az OK-t a Sheetbe a(z) {nev} ügyfélnél: {err}")

            except Exception as err:
                st.sidebar.error(f"❌ Hiba ({src['name']}): {err}")
                continue

        conn.commit()
        conn.close()
        st.cache_data.clear()
        return new_leads_count
    except Exception as e:
        st.sidebar.error(f"❌ Általános hiba: {e}")
        return 0

# ==========================================
# 3. KIÉRTÉKELŐ ÉS GYORSÍTÓTÁRAZOTT EGYSÉGEK
# ==========================================
@st.cache_data(ttl=600)
def get_campaign_settings():
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(CRM_BEALLITASOK_SHEET_ID).worksheet("CRM_Beallitasok")
        return sheet.get_all_records()
    except Exception as e:
        st.error(f"Hiba a kampány beállítások betöltésekor: {e}")
        return []

@st.cache_data(ttl=120)
def get_cached_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, role, is_active, manager_id FROM users WHERE is_active = 1")
    users = cursor.fetchall()
    conn.close()
    return [dict(u) for u in users]

def send_email_smtp(to_email, subject, html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

def get_elfogado_email(nev):
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; margin-bottom: 30px;">
            <img src="{LOGO_URL}" alt="Alfa VIG Logo" style="max-height: 70px;">
        </div>
        <p>Kedves {nev}!</p>
        <p>Köszönjük, hogy kitöltötte a kérdőívünket!</p>
        <p>Örömmel értesítjük, hogy a válaszai alapján a profilja megfelel a győri Alfa VIG értékesítési és tanácsadói csapat elvárásainak.</p>
        <p>Kollégánk 2 munkanapon belül keresni fogja Önt a megadott telefonszámon a személyes interjú időpontjának egyeztetése céljából.</p>
        
        <table style="margin-top: 40px; border-collapse: collapse;">
            <tr>
                <td style="padding-right: 20px; vertical-align: top;">
                    <img src="{PORTRAIT_URL}" alt="Strem Tamás" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover;">
                </td>
                <td style="vertical-align: middle;">
                    <p style="margin: 0; font-size: 14px; color: #555555;">Üdvözlettel,</p>
                    <p style="margin: 5px 0 0 0; font-size: 16px;"><strong>Strem Tamás</strong></p>
                    <p style="margin: 2px 0 0 0; font-size: 14px; color: #777777;">Területi Igazgató</p>
                    <p style="margin: 2px 0 0 0; font-size: 13px; color: #999999;"><em>Alfa Vienna Insurance Group – Győri Régió</em></p>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

def get_elutasito_email(nev):
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; margin-bottom: 30px;">
            <img src="{LOGO_URL}" alt="Alfa VIG Logo" style="max-height: 70px;">
        </div>
        <p>Kedves {nev}!</p>
        <p>Köszönjük, hogy időt szánt a kérdőívünk kitöltésére és érdeklődött a győri Alfa VIG karrierlehetőségei iránt.</p>
        <p>Sajnálattal tájékoztatjuk, hogy a jelenlegi nyitott pozícióinkhoz elengedhetetlen a vállalkozói jogviszony keretében történő együttműködés. Mivel Ön jelzése alapján kizárólag főállású/alkalmazotti jogviszonyban gondolkodik, így jelenleg nem tudjuk tovabléptetni a kiválasztási folyamatban.</p>
        <p>Sok sikert kívánunk a további álláskereséséhez!</p>
        
        <table style="margin-top: 40px; border-collapse: collapse;">
            <tr>
                <td style="padding-right: 20px; vertical-align: top;">
                    <img src="{PORTRAIT_URL}" alt="Strem Tamás" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover;">
                </td>
                <td style="vertical-align: middle;">
                    <p style="margin: 0; font-size: 14px; color: #555555;">Üdvözlettel,</p>
                    <p style="margin: 5px 0 0 0; font-size: 16px;"><strong>Strem Tamás</strong></p>
                    <p style="margin: 2px 0 0 0; font-size: 14px; color: #777777;">Területi Igazgató</p>
                    <p style="margin: 2px 0 0 0; font-size: 13px; color: #999999;"><em>Alfa Vienna Insurance Group – Győri Régió</em></p>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

def process_form_evaluations():
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(RECRUITMENT_FORM_SPREADSHEET_ID)

        sheet = None
        for name in POSSIBLE_FORM_SHEETS:
            try:
                sheet = spreadsheet.worksheet(name)
                break
            except Exception:
                continue

        if sheet is None:
            st.error(
                "⛔ **LEÁLLÍTVA:** A Google Form válaszok munkalap nem található az"
                " 'Értékesítési ügynökség válaszok' táblázatban!"
            )
            return
    except Exception as e:
        st.error(f"Hiba a Google Sheet megnyitásakor: {e}")
        return

    records = sheet.get_all_records()
    headers = sheet.row_values(1)

    statusz_col_idx = (
        headers.index("Kiértékelés_Státusz") + 1
        if "Kiértékelés_Státusz" in headers
        else None
    )
    feldolgozott_count = 0

    with st.spinner("Form válaszok beolvasása és kiértékelése folyamatban..."):
        for i, row in enumerate(records, start=2):
            kiertekeles = str(row.get("Kiértékelés_Státusz", "")).strip()

            if kiertekeles in ["", "Új", "Feldolgozatlan"]:
                email = str(row.get("Email", row.get("E-mail cím", ""))).strip()
                nev = str(row.get("Név", "")).strip()

                timestamp = str(
                    row.get("Időbélyeg", row.get("Timestamp", ""))
                ).strip()
                raw_vallalkozo = row.get(
                    "Nyitott vállalkozói jogviszonyra?",
                    row.get("Vállalkozói szándék", ""),
                )
                vallalkozo_valasz = str(raw_vallalkozo).strip().lower()

                if not timestamp or not vallalkozo_valasz:
                    continue

                is_rejected = False
                kizaro_kulcsszavak = [
                    "nem",
                    "főállás",
                    "kizárólag",
                    "alkalmazott",
                    "nem szeretnék",
                ]

                if any(
                    kulcsszo in vallalkozo_valasz for kulcsszo in kizaro_kulcsszavak
                ):
                    is_rejected = True

                if is_rejected:
                    subject = "Tájékoztatás jelentkezésről – Alfa VIG (Győr)"
                    html_body = get_elutasito_email(nev)
                    uj_statusz = "Elutasítva (Kizárólag főállás)"
                    st.warning(
                        f"⛔ **Elutasítva:** {nev} ({email}) — Válasz:"
                        f" '{vallalkozo_valasz}'"
                    )
                else:
                    subject = (
                        "Jelentkezés elfogadva – Interjú egyeztetés – Alfa VIG (Győr)"
                    )
                    html_body = get_elfogado_email(nev)
                    uj_statusz = "Elfogadva"
                    st.success(f"✅ **Elfogadva:** {nev} ({email})")

                try:
                    send_email_smtp(email, subject, html_body)
                    if statusz_col_idx:
                        sheet.update_cell(i, statusz_col_idx, uj_statusz)

                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE leads SET status = %s WHERE email = %s", (uj_statusz, email)
                    )
                    conn.commit()
                    conn.close()

                    feldolgozott_count += 1
                    time.sleep(random.randint(5, 10))
                except Exception as err:
                    st.error(f"Hiba a levél küldésekor ({nev}): {err}")

    if feldolgozott_count > 0:
        st.cache_data.clear()
        st.balloons()
        st.success(
            f"A kiértékelés lefutott! Összesen {feldolgozott_count} új kitöltő kapott"
            " visszajelzést."
        )
    else:
        st.info("Nem található új, kitöltött kérdőív válasz.")


# ==========================================
# 4. BEJELENTKEZÉS ÉS OLDALSÁV
# ==========================================
if "user" not in st.session_state:
    st.session_state["user"] = None

if not st.session_state["user"]:
    st.title("💼 Alfa Arrabona CRM – Bejelentkezés")
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("login_form"):
            username = st.text_input("Felhasználónév (E-mail)")
            password = st.text_input("Jelszó", type="password")
            submitted = st.form_submit_button("Belépés", use_container_width=True, type="primary")
            
            if submitted:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM users WHERE username = %s AND password = %s AND is_active = 1",
                    (username.strip(), password.strip()),
                )
                user = cursor.fetchone()
                conn.close()

                if user:
                    st.session_state["user"] = dict(user)
                    st.rerun()
                else:
                    st.error("Hibás felhasználónév vagy jelszó!")
    st.stop()

current_user = st.session_state["user"]

st.sidebar.title(f"👤 {current_user['name']}")

active_role_view = current_user["role"]
if current_user["role"] == "Asszisztens":
    active_role_view = st.sidebar.selectbox(
        "🔄 Aktív Nézet:",
        options=["Asszisztens (Összes lead)", "Tanácsadó (Saját leadek)"],
        index=0,
    )
    st.sidebar.caption(f"Eredeti szerepkör: {current_user['role']}")
else:
    st.sidebar.caption(f"Szerepkör: {current_user['role']}")

if st.sidebar.button("🔄 Élő Google Sheets Szinkronizálás"):
    count = sync_google_sheets_to_crm()
    if count > 0:
        st.sidebar.success(f"{count} új valódi lead beolvasva!")
    else:
        st.sidebar.info("Nincs új beolvasható lead.")

if st.sidebar.button("🚪 Kijelentkezés"):
    st.session_state["user"] = None
    st.rerun()

menu_options = [
    "Saját Leadek / Dashboard",
    "🗄️ Archívum (Lezárt leadek)",
    "Lead Kiosztás & Visszavétel",
    "🚀 Kampány E-mailek Kiküldése",
    "🗑️ Nyers Leadek Törlése",
    "Új Lead Feltöltés",
    "📥 Toborzási Form Kiértékelés",
    "Felhasználók Kezelése (Jogosultságok)",
    "🔐 Saját Profil & Jelszócsere",
]

menu = st.sidebar.radio("Navigáció", menu_options)

# ==========================================
# 5. MODULOK ÉS NÉZETEK
# ==========================================

if menu in ["Saját Leadek / Dashboard", "🗄️ Archívum (Lezárt leadek)"]:
    is_archive = (menu == "🗄️ Archívum (Lezárt leadek)")
    st.title("🗄️ Archívum (Lezárt leadek)" if is_archive else "📊 Saját Leadek és Visszajelzések")

    conn = get_db_connection()
    
    if not is_archive:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM leads WHERE status = 'Új'")
        unassigned_new_count = cursor.fetchone()['cnt']
        if unassigned_new_count > 0:
            st.markdown(
                f'<div class="new-lead-card">🎉 ÚJ LEAD GENERÁLÓDOTT! Jelenleg'
                f" <strong>{unassigned_new_count} db</strong> még kiosztatlan új lead"
                " várakozik a rendszerben!</div>",
                unsafe_allow_html=True,
            )

    if current_user["role"] == "Igazgató" or (
        current_user["role"] == "Asszisztens"
        and "Összes lead" in active_role_view
    ):
        query = """
            SELECT l.id, l.client_name, l.phone, l.email, l.address, l.contact_person, 
                   l.source, l.status, l.created_at, l.notes,
                   COALESCE(u.name, 'Nincs kiosztva') AS advisor_name
            FROM leads l
            LEFT JOIN users u ON l.assigned_advisor_id = u.id
            ORDER BY l.id DESC
        """
        params = ()
    elif current_user["role"] == "Manager":
        query = """
            SELECT l.id, l.client_name, l.phone, l.email, l.address, l.contact_person, 
                   l.source, l.status, l.created_at, l.notes,
                   COALESCE(u.name, 'Nincs kiosztva') AS advisor_name
            FROM leads l
            LEFT JOIN users u ON l.assigned_advisor_id = u.id
            WHERE l.assigned_advisor_id = %s 
               OR l.assigned_manager_id = %s 
               OR l.assigned_advisor_id IN (SELECT id FROM users WHERE manager_id = %s)
            ORDER BY l.id DESC
        """
        params = (current_user["id"], current_user["id"], current_user["id"])
    else:
        query = """
            SELECT l.id, l.client_name, l.phone, l.email, l.address, l.contact_person, 
                   l.source, l.status, l.created_at, l.notes,
                   COALESCE(u.name, 'Nincs kiosztva') AS advisor_name
            FROM leads l
            LEFT JOIN users u ON l.assigned_advisor_id = u.id
            WHERE l.assigned_advisor_id = %s 
            ORDER BY l.id DESC
        """
        params = (current_user["id"],)

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        if is_archive:
            df = df[df["status"].isin(["Sikeres kötés", "Lezárt"])]
        else:
            df = df[~df["status"].isin(["Sikeres kötés", "Lezárt"])]

    if not df.empty:
        st.subheader("🔍 Szűrők és Keresés")
        s_col1, s_col2, s_col3, s_col4 = st.columns([3, 2, 2, 1])

        with s_col1:
            search_term = st.text_input(
                "🔍 Keresés (Név, E-mail, Tel, Megjegyzés):",
                placeholder="Gépelj be egy nevet vagy telefonszámot...",
            )

        with s_col2:
            sources_list = ["Összes forrás"] + sorted(
                list(df["source"].dropna().unique())
            )
            selected_source = st.selectbox(
                "Leadcsoport / Forrás:", options=sources_list
            )

        with s_col3:
            statuses_list = ["Összes státusz"] + sorted(
                list(df["status"].dropna().unique())
            )
            selected_status = st.selectbox("Státusz:", options=statuses_list)

        with s_col4:
            page_size = st.selectbox("Megjelenítés:", [20, 50, 100], index=0)

        filtered_df = df.copy()

        if search_term.strip():
            term = search_term.strip().lower()
            filtered_df = filtered_df[
                filtered_df["client_name"]
                .astype(str)
                .str.lower()
                .str.contains(term, na=False)
                | filtered_df["email"]
                .astype(str)
                .str.lower()
                .str.contains(term, na=False)
                | filtered_df["phone"]
                .astype(str)
                .str.lower()
                .str.contains(term, na=False)
                | filtered_df["notes"]
                .astype(str)
                .str.lower()
                .str.contains(term, na=False)
            ]

        if selected_source != "Összes forrás":
            filtered_df = filtered_df[filtered_df["source"] == selected_source]
        if selected_status != "Összes státusz":
            filtered_df = filtered_df[filtered_df["status"] == selected_status]

        total_items = len(filtered_df)
        total_pages = max(1, math.ceil(total_items / page_size))

        col_p1, col_p2 = st.columns([1, 4])
        with col_p1:
            current_page = st.number_input(
                f"Oldal (1 - {total_pages}):",
                min_value=1,
                max_value=total_pages,
                value=1,
                step=1,
            )

        start_idx = (current_page - 1) * page_size
        end_idx = start_idx + page_size
        paged_df = filtered_df.iloc[start_idx:end_idx]

        df_display = paged_df.rename(
            columns={
                "id": "ID",
                "client_name": "Ügyfél / Cégnév",
                "phone": "Telefonszám",
                "email": "E-mail cím",
                "address": "Cím",
                "contact_person": "Kapcsolattartó",
                "source": "Forrás",
                "status": "Státusz / Visszajelzés",
                "advisor_name": "Felelős Tanácsadó",
                "created_at": "Létrehozva",
                "notes": "Infó / Munkatárs Megjegyzése",
            }
        )

        all_cols = list(df_display.columns)
        with st.expander("👁️ Megjelenítendő Oszlopok kiválasztása"):
            visible_cols = st.multiselect(
                "Válaszd ki a látható oszlopokat:", default=all_cols, options=all_cols
            )

        st.caption(
            f"Összesen **{total_items} db** találat | Megjelenítve: {start_idx + 1} -"
            f" {min(end_idx, total_items)} db"
        )
        if visible_cols:
            st.dataframe(df_display[visible_cols], use_container_width=True)
        else:
            st.dataframe(df_display, use_container_width=True)

        st.divider()
        st.subheader("📝 Lead Státusz & Visszajelzés Frissítése")
        col1, col2, col3 = st.columns([3, 2, 2])

        with col1:
            lead_opts = {
                row["id"]: (
                    f"{row['client_name']} ({row['source']}) - Status:"
                    f" {row['status']}"
                )
                for _, row in filtered_df.iterrows()
            }
            selected_lead_id = (
                st.selectbox(
                    "Válassz leadet a frissítéshez:", options=list(lead_opts.keys())
                )
                if lead_opts
                else None
            )

        with col2:
            new_status = st.selectbox(
                "Új Státusz:",
                [
                    "Kiosztva",
                    "Folyamatban",
                    "Sikeres kötés",
                    "Nem érhető el",
                    "Nem érdekli / Elutasítva",
                    "Lezárt",
                ],
            )

        with col3:
            new_note = st.text_input("Megjegyzés / Tárgyalási infó:")

        if st.button("Visszajelzés Mentése", type="primary") and selected_lead_id:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE leads SET status = %s, notes = %s WHERE id = %s",
                (new_status, new_note, selected_lead_id),
            )
            conn.commit()
            conn.close()
            st.cache_data.clear()
            st.success("Státusz és visszajelzés sikeresen elmentve!")
            st.rerun()

    else:
        st.info("Jelenleg nincs megjeleníthető lead ebben a nézetben.")

elif menu == "Lead Kiosztás & Visszavétel":
    st.title("🎯 Lead Kiosztás és Visszavétel")

    if current_user["role"] not in ["Igazgató", "Manager", "Asszisztens"]:
        st.warning("Ehhez a menüponthoz nincs jogosultságod.")
        st.stop()

    st.markdown(
        """
        <div class="red-alert-box">
            <strong>🚨 48 Órás Elakadt Leadek Riasztása</strong><br>
            Ez a gomb megkeresi azokat a leadeket, amelyeket több mint 48 órája osztottak ki, de még mindig "Kiosztva" státuszban vannak. Automatikus figyelmeztető e-mailt küld az érintett felelős tanácsadóknak az elmaradt hívásokról.
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    if st.button("🚨 KÉSEDELMES TANÁCSADÓK ÉRTESÍTÉSE (48 ÓRA)", type="primary", use_container_width=True):
        with st.spinner("48 órás leadek keresése és e-mailek küldése..."):
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT l.id, l.client_name, l.assigned_advisor_id, u.name, u.username 
                FROM leads l
                JOIN users u ON l.assigned_advisor_id = u.id
                WHERE l.status = 'Kiosztva' AND l.created_at <= NOW() - INTERVAL '48 hours'
            """)
            stale_leads = cursor.fetchall()
            
            if not stale_leads:
                st.success("🎉 Szuper! Nincsenek 48 óránál régebbi, feldolgozatlan kiosztott leadek.")
            else:
                notifications = {}
                for row in stale_leads:
                    adv_id = row['assigned_advisor_id']
                    if adv_id not in notifications:
                        notifications[adv_id] = {
                            "name": row['name'],
                            "email": row['username'],
                            "leads": []
                        }
                    notifications[adv_id]["leads"].append(row['client_name'])
                    
                sent_count = 0
                for adv_id, data in notifications.items():
                    lead_list_html = "".join([f"<li><b>{lname}</b></li>" for lname in data['leads']])
                    subject = f"🚨 FIGYELMEZTETÉS: {len(data['leads'])} db feldolgozatlan lead (48+ óra)!"
                    body = (
                        f"<p>Kedves {data['name']}!</p>"
                        f"<p>A CRM rendszerünk észlelte, hogy az alábbi ügyfelek / leadek már több mint 48 órája lettek kiosztva számodra, "
                        f"de a státuszuk még nem lett frissítve:</p>"
                        f"<ul>{lead_list_html}</ul>"
                        f"<p>Kérjük, mielőbb lépj be a rendszerbe, vedd fel velük a kapcsolatot és frissítsd a státuszukat!</p>"
                    )
                    
                    try:
                        send_email_smtp(data['email'], subject, body)
                        sent_count += 1
                    except Exception as e:
                        st.error(f"Hiba az e-mail küldésekor ({data['name']}): {e}")
                        
                st.success(f"✅ Riasztás elküldve! {sent_count} munkatárs kapott értesítést a késedelmes leadekről.")
            conn.close()
            time.sleep(3)
            st.rerun()
            
    st.divider()

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if current_user["role"] in ["Igazgató", "Asszisztens"]:
        cursor.execute(
            "SELECT * FROM leads WHERE status != 'Lezárt' AND status != 'Sikeres kötés' ORDER BY id DESC"
        )
        leads = cursor.fetchall()
    else:
        cursor.execute(
            """SELECT * FROM leads 
               WHERE status != 'Lezárt' AND status != 'Sikeres kötés' 
                 AND (assigned_advisor_id = %s 
                      OR assigned_manager_id = %s 
                      OR assigned_advisor_id IN (SELECT id FROM users WHERE manager_id = %s))
               ORDER BY id DESC""",
            (current_user["id"], current_user["id"], current_user["id"])
        )
        leads = cursor.fetchall()
        
    conn.close()

    # Memóriából olvasott munkatárs lista a felgyorsításhoz
    all_cached_users = get_cached_users()
    if current_user["role"] in ["Igazgató", "Asszisztens"]:
        staff = all_cached_users
    else:
        staff = [u for u in all_cached_users if u["id"] == current_user["id"] or u["manager_id"] == current_user["id"]]

    staff_options = {s["id"]: f"{s['name']} ({s['role']})" for s in staff}
    staff_options[None] = "-- Nincs kiosztva / Visszavéve --"

    all_sources = ["Összes forrás"] + sorted(
        list(set([l["source"] for l in leads if l["source"]]))
    )
    s_col1, s_col2 = st.columns([3, 1])
    with s_col1:
        filter_source = st.selectbox(
            "🔍 Szűrés Leadcsoport / Forrás szerint a kiosztáshoz:",
            options=all_sources,
        )
    with s_col2:
        kiosztas_page_size = st.selectbox(
            "📄 Oldalméret:", [20, 50, 100], index=0, key="k_page_size"
        )

    if filter_source != "Összes forrás":
        filtered_leads = [l for l in leads if l["source"] == filter_source]
    else:
        filtered_leads = list(leads)

    tab1, tab2 = st.tabs(
        ["⚡ Tömeges Csoportos Kiosztás", "📝 Egyenkénti Kezelés & Visszavétel"]
    )

    with tab1:
        st.subheader("⚡ Tömeges Lead Kiosztás")
        
        b_col1, b_col2 = st.columns([3, 2])
        with b_col1:
            bulk_target_staff = st.selectbox(
                "Válaszd ki a cél-munkatársat a kijelölt leadekhez:",
                options=list(staff_options.keys()),
                format_func=lambda x: staff_options[x],
                key="bulk_staff_select",
            )

        selected_lead_ids = []
        
        if not filtered_leads:
            st.info("Nincs kiosztható lead a jelenlegi szűrések alapján.")
        else:
            st.caption(
                f"Jelöld ki a csoportosan kiosztandó leadeket (Összesen: {len(filtered_leads)} db):"
            )
            
            select_all = st.checkbox("☑️ **Összes megjelenített lead kijelölése**", key="bulk_select_all")
            
            df_bulk = pd.DataFrame([dict(row) for row in filtered_leads])
            df_bulk = df_bulk[['id', 'client_name', 'email', 'phone', 'source', 'status', 'notes']]
            df_bulk = df_bulk.rename(columns={
                'client_name': 'Név / Cégnév',
                'email': 'E-mail',
                'phone': 'Telefon',
                'source': 'Forrás',
                'status': 'Státusz',
                'notes': 'Infó'
            })
            
            df_bulk.insert(0, "Kijelölve", select_all)
            
            edited_df = st.data_editor(
                df_bulk,
                column_config={
                    "Kijelölve": st.column_config.CheckboxColumn(
                        "Kijelölve",
                        help="Jelöld be a kiosztáshoz",
                        default=False,
                    ),
                    "id": None, 
                },
                disabled=["Név / Cégnév", "E-mail", "Telefon", "Forrás", "Státusz", "Infó"],
                hide_index=True,
                use_container_width=True,
                key="bulk_data_editor"
            )
            
            selected_lead_ids = edited_df[edited_df["Kijelölve"] == True]["id"].tolist()

        with b_col2:
            st.write("")
            st.write("")
            
            if st.button(
                f"🚀 Kijelölt {len(selected_lead_ids)} db lead kiosztása",
                type="primary",
                disabled=len(selected_lead_ids) == 0
            ):
                if selected_lead_ids:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    new_stat = "Kiosztva" if bulk_target_staff is not None else "Új"

                    placeholders = ",".join(["%s"] * len(selected_lead_ids))
                    query = f"UPDATE leads SET assigned_advisor_id = %s, status = %s WHERE id IN ({placeholders})"
                    params = [bulk_target_staff, new_stat] + selected_lead_ids

                    cursor.execute(query, params)
                    
                    if bulk_target_staff is not None:
                        cursor.execute("SELECT name, username FROM users WHERE id = %s", (bulk_target_staff,))
                        t_user = cursor.fetchone()
                        if t_user:
                            t_nev = t_user["name"]
                            t_email = t_user["username"]
                            subject = f"Új leadek ({len(selected_lead_ids)} db) kiosztva részedre - Alfa CRM"
                            body = f"<p>Kedves {t_nev}!</p><p>Kiosztásra került részedre <b>{len(selected_lead_ids)} db új lead</b> a CRM rendszerben.</p><p>Kérlek, lépj be a rendszerbe és kezdd el a feldolgozásukat!</p>"
                            try:
                                send_email_smtp(t_email, subject, body)
                            except Exception as e:
                                st.warning("A leadek kiosztva, de az értesítő e-mailt nem sikerült elküldeni.")

                    conn.commit()
                    conn.close()
                    st.cache_data.clear()

                    st.success(
                        f"Sikeresen kiosztva {len(selected_lead_ids)} db lead, és az értesítő e-mail kiküldve!"
                    )
                    time.sleep(1)
                    st.rerun()

    with tab2:
        st.subheader("📝 Leadek Egyenkénti Kezelése")

        if not filtered_leads:
            st.info("Nincs kezelhető lead a jelenlegi szűrések alapján.")
        else:
            k_total_pages = max(1, math.ceil(len(filtered_leads) / kiosztas_page_size))
            k_page = st.number_input(
                f"Oldal (1 - {k_total_pages}):",
                min_value=1,
                max_value=k_total_pages,
                value=1,
                step=1,
                key="k_page_num",
            )

            k_start = (k_page - 1) * kiosztas_page_size
            k_end = k_start + kiosztas_page_size
            paged_k_leads = filtered_leads[k_start:k_end]

            staff_name_to_id = {v: k for k, v in staff_options.items()}
            staff_names = list(staff_options.values())

            rows_for_df = []
            for l in paged_k_leads:
                current_staff_name = staff_options.get(l["assigned_advisor_id"], staff_options[None])
                rows_for_df.append({
                    "id": l["id"],
                    "Név / Cégnév": l["client_name"],
                    "E-mail": l["email"],
                    "Telefon": l["phone"],
                    "Forrás": l["source"],
                    "Státusz": l["status"],
                    "Infó": l["notes"],
                    "Felelős Tanácsadó": current_staff_name
                })
            
            df_single = pd.DataFrame(rows_for_df)

            edited_df_single = st.data_editor(
                df_single,
                column_config={
                    "id": None,
                    "Felelős Tanácsadó": st.column_config.SelectboxColumn(
                        "Felelős Tanácsadó",
                        help="Kattints duplán a felelős módosításához",
                        options=staff_names,
                        required=True,
                    ),
                },
                disabled=["Név / Cégnév", "E-mail", "Telefon", "Forrás", "Státusz", "Infó"],
                hide_index=True,
                use_container_width=True,
                key="single_data_editor"
            )

            st.divider()
            if st.button("💾 Módosítások Mentése", type="primary", use_container_width=True):
                changed_rows = edited_df_single[edited_df_single["Felelős Tanácsadó"] != df_single["Felelős Tanácsadó"]]
                
                if changed_rows.empty:
                    st.info("Nem történt módosítás a táblázatban.")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    sent_emails = 0
                    
                    for _, row in changed_rows.iterrows():
                        lead_id = row["id"]
                        new_staff_name = row["Felelős Tanácsadó"]
                        new_staff_id = staff_name_to_id[new_staff_name]
                        new_stat = "Kiosztva" if new_staff_id is not None else "Új"
                        
                        cursor.execute(
                            "UPDATE leads SET assigned_advisor_id = %s, status = %s WHERE id = %s",
                            (new_staff_id, new_stat, lead_id),
                        )
                        
                        if new_staff_id is not None:
                            cursor.execute("SELECT name, username FROM users WHERE id = %s", (new_staff_id,))
                            t_user = cursor.fetchone()
                            if t_user:
                                subject = "Új lead kiosztva - Alfa CRM"
                                body = (
                                    f"<p>Kedves {t_user['name']}!</p>"
                                    f"<p>Kiosztásra került részedre egy új lead a CRM rendszerben.</p>"
                                    f"<p><b>Ügyfél neve:</b> {row['Név / Cégnév']}<br>"
                                    f"<b>Forrás:</b> {row['Forrás']}</p>"
                                    f"<p>Kérlek, lépj be a rendszerbe és vedd fel vele a kapcsolatot!</p>"
                                )
                                try:
                                    send_email_smtp(t_user['username'], subject, body)
                                    sent_emails += 1
                                except:
                                    pass
                    
                    conn.commit()
                    conn.close()
                    st.cache_data.clear()
                    
                    st.success(f"✅ {len(changed_rows)} db lead sikeresen frissítve, {sent_emails} db értesítő e-mail kiküldve!")
                    time.sleep(1)
                    st.rerun()

elif menu == "🚀 Kampány E-mailek Kiküldése":
    st.title("🚀 Kampány E-mailek Dinamikus Kiküldése")
    st.write("Válaszd ki a kampányt, írd meg az üzenetet, és küldd ki a Google Sheetben beállított arculattal és képekkel!")
    
    settings_data = get_campaign_settings()
    
    if not settings_data:
        st.warning("⚠️ Nem sikerült beolvasni a kampány beállításokat. Ellenőrizd a Google Sheet ID-t és hogy létezik-e a 'CRM_Beallitasok' fül!")
    else:
        campaign_names = [s.get("Kampány neve", "") for s in settings_data if s.get("Kampány neve")]
        
        selected_campaign = st.selectbox("1. Válaszd ki a Kampányt / Modult:", options=campaign_names)
        
        current_setting = next((s for s in settings_data if s.get("Kampány neve") == selected_campaign), None)
        
        if current_setting:
            with st.expander("📋 Kattints ide a Google Sheetben megadott arculat / beállítások ellenőrzéséhez", expanded=False):
                st.write(f"**Tárgy:** {current_setting.get('E-mail Tárgya', '')}")
                st.write(f"**Aláíró:** {current_setting.get('Aláíró Neve', '')} - {current_setting.get('Aláíró Titulusa', '')}")
                colA, colB = st.columns(2)
                with colA:
                    st.caption("Fő fotó (Fejléc):")
                    fofoto = current_setting.get('Fő fotó URL', '')
                    if fofoto and str(fofoto).strip().startswith('http'):
                        st.image(fofoto.strip(), width=150)
                    else:
                        st.info("Nincs megadva érvényes Fő fotó URL a Google Sheetben.")
                with colB:
                    st.caption("Aláíró portré:")
                    portre = current_setting.get('Aláíró Fotó URL', '')
                    if portre and str(portre).strip().startswith('http'):
                        st.image(portre.strip(), width=80)
                    else:
                        st.info("Nincs megadva érvényes Aláíró fotó URL.")
                        
            st.subheader("2. E-mail szövegének megírása")
            message_body = st.text_area(
                "Írd be az üzenet szövegét. A bekezdéseket és sortöréseket a rendszer automatikusan formázza a levélben:",
                height=250,
                placeholder="Kedves [Név]! (A megszólítást a rendszer automatikusan beilleszti a név alapján!)\n\nÖrömmel értesítjük..."
            )
            
            st.subheader("3. Címzettek kiválasztása")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leads WHERE (status = 'Új' OR status = 'Kiosztva') AND email != ''")
            all_leads = cursor.fetchall()
            conn.close()
            
            lead_opts = {l["id"]: f"[{l['source']}] {l['client_name']} ({l['email']})" for l in all_leads}
            
            default_leads = [l["id"] for l in all_leads if l['source'] == selected_campaign]
            
            selected_lead_ids = st.multiselect(
                "A rendszer alapból felajánlja a kampányhoz tartozó aktív leadeket (de a listát szabadon módosíthatod):", 
                options=list(lead_opts.keys()), 
                format_func=lambda x: lead_opts[x], 
                default=default_leads
            )
            
            st.divider()
            
            if st.button("📧 Levelek Kiküldése most", type="primary"):
                if not message_body.strip():
                    st.error("Kérlek, írj valamilyen szöveget az e-mailbe!")
                elif not selected_lead_ids:
                    st.warning("Nincs kiválasztva egyetlen címzett sem!")
                else:
                    with st.spinner("Levelek kiküldése folyamatban..."):
                        sent_count = 0
                        for lid in selected_lead_ids:
                            lead = next(l for l in all_leads if l["id"] == lid)
                            email_to = lead["email"]
                            nev = lead["client_name"]
                            
                            formatted_body = message_body.replace('\n', '<br>')
                            
                            html_content = f"""
                            <html>
                            <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
                                <div style="text-align: center; margin-bottom: 30px;">
                                    <img src="{current_setting.get('Fő fotó URL', '')}" alt="Kampány Kép" style="max-height: 150px;">
                                </div>
                                <p>Kedves {nev}!</p>
                                <p>{formatted_body}</p>
                                <table style="margin-top: 40px; border-collapse: collapse;">
                                    <tr>
                                        <td style="padding-right: 20px; vertical-align: top;">
                                            <img src="{current_setting.get('Aláíró Fotó URL', '')}" alt="Profilkép" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover;">
                                        </td>
                                        <td style="vertical-align: middle;">
                                            <p style="margin: 0; font-size: 14px; color: #555555;">Üdvözlettel,</p>
                                            <p style="margin: 5px 0 0 0; font-size: 16px;"><strong>{current_setting.get('Aláíró Neve', '')}</strong></p>
                                            <p style="margin: 2px 0 0 0; font-size: 14px; color: #777777;">{current_setting.get('Aláíró Titulusa', '')}</p>
                                        </td>
                                    </tr>
                                </table>
                            </body>
                            </html>
                            """
                            try:
                                send_email_smtp(email_to, current_setting.get('E-mail Tárgya', ''), html_content)
                                sent_count += 1
                                time.sleep(random.uniform(1.0, 2.0))
                            except Exception as e:
                                st.error(f"Hiba a levél küldésekor ({email_to}): {e}")
                        
                        st.balloons()
                        st.success(f"Gratulálok! {sent_count} db személyre szabott, HTML formátumú e-mail sikeresen kiküldve!")

elif menu == "🗑️ Nyers Leadek Törlése":
    st.title("🗑️ Nyers/Hibás Leadek Szelektív Törlése")

    if current_user["role"] not in ["Igazgató", "Asszisztens"]:
        st.warning("Nincs jogosultságod ehhez a menüponthoz.")
        st.stop()

    conn = get_db_connection()
    df_new = pd.read_sql_query("SELECT * FROM leads WHERE status = 'Új' ORDER BY id DESC", conn)

    if df_new.empty:
        st.info("Jelenleg nincs 'Új' státuszú, kiosztatlan lead a rendszerben.")
    else:
        st.write("Válaszd ki azokat a hibás vagy felesleges leadeket, amiket **véglegesen** törölni szeretnél az adatbázisból:")
        
        selected_ids_to_delete = []
        for _, row in df_new.iterrows():
            chk = st.checkbox(
                f"[{row['source']}] {row['client_name']} ({row['email']}) - Tel: {row['phone']} - Infó: {row['notes']}", 
                key=f"del_{row['id']}"
            )
            if chk:
                selected_ids_to_delete.append(row['id'])
        
        st.divider()
        if st.button("🗑️ Kijelölt leadek végleges törlése", type="primary"):
            if selected_ids_to_delete:
                cursor = conn.cursor()
                placeholders = ",".join(["%s"] * len(selected_ids_to_delete))
                cursor.execute(f"DELETE FROM leads WHERE id IN ({placeholders})", selected_ids_to_delete)
                conn.commit()
                st.cache_data.clear()
                st.success(f"{len(selected_ids_to_delete)} db lead sikeresen törölve!")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Nem jelöltél ki egyetlen leadet sem a törléshez!")
    conn.close()

elif menu == "Új Lead Feltöltés":
    st.title("➕ Új Lead Manuális Hozzáadása")
    with st.form("new_lead_form"):
        client_name = st.text_input("Ügyfél / Cégnév")
        phone = st.text_input("Telefonszám")
        email = st.text_input("E-mail cím")
        address = st.text_input("Cím / Székhely")

        source_type = st.selectbox(
            "Forrás típusa:",
            [
                "Promobox Kampány",
                "Vállalkozói Felmérés",
                "Ügyfélklub",
                "Évfordulós Felülvizsgálat",
                "Személyes Ajánlás",
                "Egyéb (Egyedi forrás megadása)",
            ],
        )

        custom_source = st.text_input(
            "Egyedi forrás megnevezése (ha az 'Egyéb' opciót választottad):",
            placeholder="pl. Szeptemberi Networking Est, Facebook hirdetés stb.",
        )

        manual_note = st.text_area(
            "Kezdeti megjegyzés / Igényelt biztosítás típusa:",
            placeholder="pl. Flotta biztosítás iránt érdeklődik, jövő héten hívható.",
        )

        submitted = st.form_submit_button("Lead Rögzítése", type="primary")

        if submitted and client_name:
            if (
                source_type == "Egyéb (Egyedi forrás megadása)"
                and custom_source.strip()
            ):
                final_source = custom_source.strip()
            else:
                final_source = source_type

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO leads (client_name, phone, email, address, source, status, notes)
                VALUES (%s, %s, %s, %s, %s, 'Új', %s)
                """,
                (
                    client_name,
                    phone,
                    email,
                    address,
                    final_source,
                    manual_note.strip(),
                ),
            )
            conn.commit()
            conn.close()
            st.cache_data.clear()
            st.success(f"Új lead sikeresen rögzítve! (Forrás: {final_source})")

elif menu == "📥 Toborzási Form Kiértékelés":
    st.title("📋 Toborzási Kérdőív Kiértékelés")
    st.write(
        "Kattints az alábbi gombra a beérkezett Google Form válaszok manuális"
        " kiértékeléséhez és a visszajelző levelek kiküldéséhez:"
    )

    if st.button("📥 Form válaszok kiértékelése", type="primary"):
        process_form_evaluations()

elif menu == "Felhasználók Kezelése (Jogosultságok)":
    st.title("👥 Felhasználók Kezelése & Jogosultságok")

    if current_user["role"] not in ["Igazgató", "Asszisztens"]:
        st.error("Csak az Igazgató és az Asszisztens kezelheti a felhasználókat.")
        st.stop()

    st.subheader("📋 Rendszerben lévő munkatársak")
    conn = get_db_connection()
    df_users = pd.read_sql_query(
        """
        SELECT u.id AS "ID", u.name AS "Név", u.username AS "Felhasználónév (Email)", 
               u.role AS "Szerepkör", m.name AS "Felettes Manager",
               CASE WHEN u.is_active = 1 THEN 'Aktív' ELSE 'Inaktív' END AS "Státusz"
        FROM users u
        LEFT JOIN users m ON u.manager_id = m.id
        ORDER BY u.id ASC
        """,
        conn,
    )
    conn.close()

    if not df_users.empty:
        st.dataframe(df_users, use_container_width=True)
    else:
        st.info("Még nincsenek rögzített munkatársak.")

    st.divider()

    st.subheader("✏️ Munkatárs Adatainak Módosítása & Jelszó Beállítása")

    all_users = get_cached_users()
    managers = [u for u in all_users if u["role"] in ["Igazgató", "Manager"]]

    manager_opts = {m["id"]: f"{m['name']} ({m['role']})" for m in managers}
    manager_opts[None] = "Nincs (Főigazgató alá tartozik)"

    user_opts = {
    u.get("id"): f"{u.get('name', 'Névtelen')} ({u.get('username', 'n/a')}) - {u.get('role', 'Nincs szerepkör')}"
    for u in all_users if u and u.get("id")
    }

    if user_opts:
        selected_edit_id = st.selectbox(
            "Válaszd ki a módosítandó munkatársat:", options=list(user_opts.keys())
        )

        selected_user = next(
            (u for u in all_users if u["id"] == selected_edit_id), None
        )

        if selected_user:
            with st.form("edit_user_form"):
                edit_name = st.text_input("Teljes Név", value=selected_user["name"])
                edit_username = st.text_input(
                    "Felhasználónév (E-mail cím)", value=selected_user["username"]
                )

                edit_new_pw = st.text_input(
                    "Új jelszó beállítása (Hagyd üresen, ha nem akarod módosítani):",
                    type="password",
                )

                roles = ["Manager", "Tanácsadó", "Asszisztens", "Igazgató"]
                edit_role = st.selectbox(
                    "Szerepkör",
                    options=roles,
                    index=roles.index(selected_user["role"])
                    if selected_user["role"] in roles
                    else 1,
                )

                current_mgr = selected_user.get("manager_id")
                edit_manager = st.selectbox(
                    "Felettes Manager / Igazgató:",
                    options=list(manager_opts.keys()),
                    index=list(manager_opts.keys()).index(current_mgr)
                    if current_mgr in manager_opts
                    else list(manager_opts.keys()).index(None),
                    format_func=lambda x: manager_opts[x],
                )

                edit_active = st.checkbox(
                    "Aktív felhasználó (Beléphet a rendszerbe)",
                    value=bool(selected_user["is_active"]),
                )

                submit_edit = st.form_submit_button(
                    "Módosítások Mentése", type="primary"
                )

                if submit_edit:
                    try:
                        conn = get_db_connection()
                        cursor = conn.cursor()

                        if edit_new_pw.strip():
                            cursor.execute(
                                """
                                UPDATE users 
                                SET name = %s, username = %s, password = %s, role = %s, manager_id = %s, is_active = %s
                                WHERE id = %s
                                """,
                                (
                                    edit_name.strip(),
                                    edit_username.strip(),
                                    edit_new_pw.strip(),
                                    edit_role,
                                    edit_manager,
                                    1 if edit_active else 0,
                                    selected_edit_id,
                                ),
                            )
                        else:
                            cursor.execute(
                                """
                                UPDATE users 
                                SET name = %s, username = %s, role = %s, manager_id = %s, is_active = %s
                                WHERE id = %s
                                """,
                                (
                                    edit_name.strip(),
                                    edit_username.strip(),
                                    edit_role,
                                    edit_manager,
                                    1 if edit_active else 0,
                                    selected_edit_id,
                                ),
                            )

                        conn.commit()
                        conn.close()
                        st.cache_data.clear()
                        st.success(f"Munkatárs adatai sikeresen frissítve: {edit_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Hiba a frissítés során: {e}")

    st.divider()

    st.subheader("➕ Új Munkatárs Hozzáadása")
    with st.form("add_user_form"):
        new_username = st.text_input("Felhasználónév (E-mail)")
        new_name = st.text_input("Munkatárs Teljes Neve")
        new_password = st.text_input("Kezdő Jelszó", type="password")
        new_role = st.selectbox(
            "Szerepkör", ["Manager", "Tanácsadó", "Asszisztens"]
        )

        selected_manager = st.selectbox(
            "Felettes Manager / Igazgató:",
            options=list(manager_opts.keys()),
            format_func=lambda x: manager_opts[x],
            key="new_user_mgr",
        )

        if st.form_submit_button("Felhasználó Létrehozása", type="primary"):
            if new_username and new_password and new_name:
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO users (username, password, name, role, manager_id, is_active)
                        VALUES (%s, %s, %s, %s, %s, 1)
                        """,
                        (
                            new_username.strip(),
                            new_password.strip(),
                            new_name.strip(),
                            new_role,
                            selected_manager,
                        ),
                    )
                    conn.commit()
                    conn.close()
                    st.cache_data.clear()
                    st.success(f"Munkatárs sikeresen hozzáadva: {new_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hiba a létrehozás során: {e}")

elif menu == "🔐 Saját Profil & Jelszócsere":
    st.title("🔐 Saját Profil & Jelszómódosítás")
    st.write(
        f"Bejelentkezve mint: **{current_user['name']}**"
        f" ({current_user['username']})"
    )

    with st.form("change_password_form"):
        old_pw = st.text_input("Jelenlegi jelszó", type="password")
        new_pw = st.text_input("Új jelszó", type="password")
        new_pw_confirm = st.text_input("Új jelszó megerősítése", type="password")
        submit_pw = st.form_submit_button("Jelszó Módosítása", type="primary")

        if submit_pw:
            if old_pw != current_user["password"]:
                st.error("A jelenlegi jelszó nem megfelelő!")
            elif new_pw != new_pw_confirm:
                st.error("A két új jelszó nem egyezik meg!")
            elif len(new_pw) < 6:
                st.warning("Az új jelszónak legalább 6 karakter hosszúnak kell lennie!")
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET password = %s WHERE id = %s",
                    (new_pw.strip(), current_user["id"]),
                )
                conn.commit()
                conn.close()
                st.session_state["user"]["password"] = new_pw.strip()
                st.cache_data.clear()
                st.success("Jelszavadat sikeresen megváltoztattad!")
