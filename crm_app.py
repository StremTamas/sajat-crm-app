import sqlite3
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. OLDAL BEÁLLÍTÁSAI ÉS ADATBÁZIS
# ==========================================
st.set_page_config(page_title="Alfa Arrabona CRM", page_icon="💼", layout="wide")

DB_FILE = "crm_database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Garantálja az adatbázis-szerkezetet ÉS az admin fiók létezését."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Felhasználók tábla
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            manager_id INTEGER,
            is_active INTEGER DEFAULT 1
        )
    """)

    # Leadek tábla
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            contact_person TEXT,
            source TEXT,
            status TEXT DEFAULT 'Új',
            assigned_manager_id INTEGER,
            assigned_advisor_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    """)
    
    # ADMIN FIÓK FELÜLÍRÁSA / GARANTÁLÁSA (admin / admin123)
    cursor.execute("DELETE FROM users WHERE username = 'admin'")
    cursor.execute("""
        INSERT INTO users (username, password, name, role, is_active)
        VALUES ('admin', 'admin123', 'Főigazgató', 'Igazgató', 1)
    """)
    
    conn.commit()
    conn.close()

# Indításkor AZONNAL lefut a helyreállítás
init_db()

# ==========================================
# 2. ÉLŐ GOOGLE SHEETS BEOLVASÁS ÉS SZINKRON
# ==========================================
SHEET_SOURCES = [
    {
        "name": "Promobox Ügyfelek",
        "id": "1aBCdeFGhIJkLMnoPQRstUVwxYZ123456789",
        "worksheet": "Munkalap1"
    },
    {
        "name": "Vállalkozói Felmérés Válaszok",
        "id": "1Gw6teVYi940HdPHiO5WoSrEqKSfnZtv5RTl_tAFDEis",
        "worksheet": "Munkalap1"
    },
    {
        "name": "Ügyfélklub Tagok",
        "id": "1kIdVrApf2VQgQTV3VuZpMNaXYCYu_RvowvPCC54SK-c",
        "worksheet": "Ügyfélklub Tagok"
    }
]

def sync_google_sheets_to_crm():
    """Beolvassa az új leadeket a Google Sheets-ből és beszúrja a CRM-be."""
    try:
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

        client = gspread.authorize(creds)
        conn = get_db_connection()
        cursor = conn.cursor()

        new_leads_count = 0

        for src in SHEET_SOURCES:
            try:
                sheet = client.open_by_key(src["id"]).worksheet(src["worksheet"])
                records = sheet.get_all_records()

                for row in records:
                    r = {str(k).strip(): str(v).strip() for k, v in row.items()}
                    email = r.get("E-mail cím", r.get("Email", r.get("Ügyfél_Email", "")))
                    nev = r.get("Cégnév", r.get("Név", r.get("Ügyfél_Neve", r.get("Kapcsolattartó", ""))))
                    phone = r.get("Telefonszám", r.get("Ügyfél_Telefonszám", ""))
                    cim = r.get("Székhely / Cím", r.get("Ügyfél_Címe", ""))
                    kapcsolattarto = r.get("Kapcsolattartó neve", r.get("Kapcsolattartó", ""))

                    if email or nev:
                        cursor.execute(
                            "SELECT id FROM leads WHERE email = ? OR (client_name = ? AND client_name != '')",
                            (email, nev)
                        )
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO leads (client_name, phone, email, address, contact_person, source, status)
                                VALUES (?, ?, ?, ?, ?, ?, 'Új')
                            """, (nev, phone, email, cim, kapcsolattarto, src["name"]))
                            new_leads_count += 1
            except Exception:
                continue

        conn.commit()
        conn.close()
        return new_leads_count
    except Exception:
        return 0

# ==========================================
# 3. BEJELENTKEZÉS
# ==========================================
if "user" not in st.session_state:
    st.session_state["user"] = None

if not st.session_state["user"]:
    st.title("💼 Alfa Arrabona CRM – Bejelentkezés")
    col1, col2 = st.columns([1, 2])
    with col1:
        username = st.text_input("Felhasználónév (E-mail)")
        password = st.text_input("Jelszó", type="password")
        if st.button("Belépés", use_container_width=True):
            init_db()  # Helyreállítja az admin fiókot belépés előtt
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE username = ? AND password = ?",
                (username.strip(), password.strip())
            )
            user = cursor.fetchone()
            conn.close()
            
            if user:
                st.session_state["user"] = dict(user)
                st.rerun()
            else:
                st.error("Hibás felhasználónév vagy jelszó!")
    st.stop()

# Bejelentkezett felhasználó adatai
current_user = st.session_state["user"]

# Oldalsáv (Sidebar)
st.sidebar.title(f"👤 {current_user['name']}")
st.sidebar.caption(f"Szerepkör: {current_user['role']}")

if st.sidebar.button("🔄 Élő Google Sheets Szinkronizálás"):
    count = sync_google_sheets_to_crm()
    st.sidebar.success(f"{count} új lead beolvasva!")

if st.sidebar.button("Kijelentkezés"):
    st.session_state["user"] = None
    st.rerun()

menu = st.sidebar.radio(
    "Navigáció",
    [
        "Saját Leadek / Dashboard",
        "Lead Kiosztás & Visszavétel",
        "Új Lead Feltöltés",
        "Felhasználók Kezelése (Jogosultságok)"
    ]
)

# ==========================================
# 4. MODULOK ÉS NÉZETEK
# ==========================================

# A) DASHBOARD / SAJÁT LEADEK
if menu == "Saját Leadek / Dashboard":
    st.title("📊 Saját Leadek és Áttekintés")
    conn = get_db_connection()

    if current_user["role"] == "Igazgató":
        query = "SELECT * FROM leads ORDER BY id DESC"
        params = ()
    elif current_user["role"] == "Manager":
        query = """
            SELECT * FROM leads 
            WHERE assigned_manager_id = ? 
               OR assigned_advisor_id IN (SELECT id FROM users WHERE manager_id = ?)
            ORDER BY id DESC
        """
        params = (current_user["id"], current_user["id"])
    else:  # Tanácsadó
        query = "SELECT * FROM leads WHERE assigned_advisor_id = ? ORDER BY id DESC"
        params = (current_user["id"],)

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Jelenleg nincs megjeleníthető lead.")

# B) LEAD KIOSZTÁS & VISSZAVÉTEL
elif menu == "Lead Kiosztás & Visszavétel":
    st.title("🎯 Lead Kiosztás és Visszavétel")

    if current_user["role"] not in ["Igazgató", "Manager"]:
        st.warning("Ehhez a menüponthoz nincs jogosultságod.")
        st.stop()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM leads WHERE status != 'Lezárt' ORDER BY id DESC")
    leads = cursor.fetchall()

    if current_user["role"] == "Igazgató":
        cursor.execute("SELECT id, name, role FROM users WHERE role != 'Igazgató'")
    else:
        cursor.execute("SELECT id, name, role FROM users WHERE manager_id = ?", (current_user["id"],))
    staff = cursor.fetchall()
    conn.close()

    st.subheader("Meglévő Leadek Kezelése")
    for l in leads:
        col1, col2, col3 = st.columns([3, 3, 2])
        with col1:
            st.write(f"**{l['client_name']}** ({l['source']}) - Status: `{l['status']}`")
            st.caption(f"E-mail: {l['email']} | Tel: {l['phone']}")
        with col2:
            staff_options = {s["id"]: f"{s['name']} ({s['role']})" for s in staff}
            staff_options[None] = "-- Nincs kiosztva --"

            selected_staff = st.selectbox(
                "Felelős hozzárendelése",
                options=list(staff_options.keys()),
                format_func=lambda x: staff_options[x],
                key=f"staff_{l['id']}"
            )
        with col3:
            if st.button("Mentés / Kiosztás", key=f"btn_{l['id']}"):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE leads SET assigned_advisor_id = ?, status = 'Kiosztva' WHERE id = ?",
                    (selected_staff, l["id"])
                )
                conn.commit()
                conn.close()
                st.success("Lead sikeresen frissítve!")
                st.rerun()

# C) ÚJ LEAD FELTÖLTÉS
elif menu == "Új Lead Feltöltés":
    st.title("➕ Új Lead Manuális Hozzáadása")
    with st.form("new_lead_form"):
        client_name = st.text_input("Ügyfél / Cégnév")
        phone = st.text_input("Telefonszám")
        email = st.text_input("E-mail cím")
        address = st.text_input("Cím / Székhely")
        source = st.selectbox("Forrás", ["Promobox Kampány", "Vállalkozói Felmérés", "Ügyfélklub", "Évfordulós Felülvizsgálat", "Személyes Ajánlás"])
        submitted = st.form_submit_button("Lead Rögzítése")

        if submitted and client_name:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (client_name, phone, email, address, source, status)
                VALUES (?, ?, ?, ?, ?, 'Új')
            """, (client_name, phone, email, address, source))
            conn.commit()
            conn.close()
            st.success("Új lead sikeresen rögzítve!")

# D) FELHASZNÁLÓK KEZELÉSE
elif menu == "Felhasználók Kezelése (Jogosultságok)":
    st.title("👥 Felhasználók & Belépési Jogosultságok")

    if current_user["role"] != "Igazgató":
        st.error("Csak az Igazgató kezelheti a felhasználókat.")
        st.stop()

    st.subheader("Új Munkatárs Hozzáadása")
    with st.form("add_user_form"):
        new_username = st.text_input("Felhasználónév (E-mail)")
        new_name = st.text_input("Munkatárs Teljes Neve")
        new_password = st.text_input("Kezdő Jelszó", type="password")
        new_role = st.selectbox("Szerepkör", ["Manager", "Tanácsadó"])

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM users WHERE role = 'Manager'")
        managers = cursor.fetchall()
        conn.close()

        manager_opts = {m["id"]: m["name"] for m in managers}
        manager_opts[None] = "Nincs"

        selected_manager = st.selectbox(
            "Felettes Manager (Tanácsadó esetén):",
            options=list(manager_opts.keys()),
            format_func=lambda x: manager_opts[x]
        )

        if st.form_submit_button("Felhasználó Létrehozása"):
            if new_username and new_password and new_name:
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO users (username, password, name, role, manager_id, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """, (new_username, new_password, new_name, new_role, selected_manager))
                    conn.commit()
                    conn.close()
                    st.success(f"Munkatárs sikeresen hozzáadva: {new_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hiba a létrehozás során: {e}")
