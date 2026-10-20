import sqlite3
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. OLDAL BEÁLLÍTÁSAI ÉS ADATBÁZIS
# ==========================================
st.set_page_config(page_title="Alfa Arrabona CRM", page_icon="💼", layout="wide")

DB_FILE = "crm_data_v2.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
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
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO users (username, password, name, role, is_active)
            VALUES ('admin', 'admin123', 'Főigazgató', 'Igazgató', 1)
        """)
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. KIZÁRÓLAG A VÁLASZADÓ TÁBLÁZATOK BEKÖTÉSE
# ==========================================
# Itt KIZÁRÓLAG a válaszokat / kitöltéseket gyűjtő Google Forms Sheet ID-kat adjuk meg!
SHEET_SOURCES = [
    {
        "name": "Vállalkozói Felmérés (Válaszadók)",
        "id": "1Gw6teVYi940HdPHiO5WoSrEqKSfnZtv5RTl_tAFDEis", # A válaszadó Sheet ID-ja
        "worksheet": "Munkalap1"
    },
    {
        "name": "Ügyfélklub Regisztráltak",
        "id": "1kIdVrApf2VQgQTV3VuZpMNaXYCYu_RvowvPCC54SK-c",
        "worksheet": "Ügyfélklub Tagok"
    }
]

def sync_google_sheets_to_crm():
    """Kizárólag a ténylegesen VÁLASZOLÓ / KITÖLTŐ ügyfeleket emeli át a CRM-be."""
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

                    # Csak akkor tekintjük érvényes kitöltésnek/visszajelzésnek, ha van név és e-mail
                    if email and nev:
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
        username = st.text_input("Felhasználónév")
        password = st.text_input("Jelszó", type="password")
        if st.button("Belépés", use_container_width=True):
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

current_user = st.session_state["user"]

st.sidebar.title(f"👤 {current_user['name']}")
st.sidebar.caption(f"Szerepkör: {current_user['role']}")

if st.sidebar.button("🔄 Élő Google Sheets Szinkronizálás"):
    count = sync_google_sheets_to_crm()
    st.sidebar.success(f"{count} új valódi lead beolvasva!")

# Adatbázis kitisztítása (felesleges nyers tömeges adatok törlése)
if current_user["role"] == "Igazgató":
    if st.sidebar.button("🧹 Nyers/Hibás Leadek Törlése (
