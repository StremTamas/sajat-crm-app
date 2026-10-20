import datetime
import random
import smtplib
import sqlite3
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.service_account import Credentials
import gspread
import pandas as pd
import streamlit as st

# ==========================================
# 1. OLDAL BEÁLLÍTÁSAI ÉS JAVÍTOTT CSS STÍLUS
# ==========================================
st.set_page_config(
    page_title="Alfa Arrabona CRM", page_icon="💼", layout="wide"
)

# Javított gombkontraszt és olvashatóság
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f8f9fa;
    }
    /* Oldalsáv sötét háttérrel és világos gombokkal */
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
    /* Főoldali gombok olvasható fekete/sötétkék betűkkel */
    .main button {
        color: #0f172a !important;
        font-weight: bold !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

DB_FILE = "crm_data_v2.db"

# SMTP Beállítások e-mail küldéshez
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "arrabonainsurance@gmail.com"
SENDER_NAME = "Insurance Arrabona"
SENDER_PASSWORD = "aqzs okrl jewl ypdw"

FORM_SPREADSHEET_ID = "1hlFrgfdUDANg1m2gIA6w_10kI5ODQ_TIw8v9-WmYf-g"
POSSIBLE_FORM_SHEETS = [
    "Form Responses 1",
    "Űrlapválaszok 1",
    "Form-válaszok 1",
    "Válaszok",
]


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
# 2. HITELESÍTÉS ÉS GOOGLE SHEETS SZINKRON
# ==========================================
SHEET_SOURCES = [
    {
        "name": "Vállalkozói Felmérés (Válaszadók)",
        "id": "1Gw6teVYi940HdPHiO5WoSrEqKSfnZtv5RTl_tAFDEis",
        "worksheet": "Munkalap1",
    },
    {
        "name": "Ügyfélklub Regisztráltak",
        "id": "1kIdVrApf2VQgQTV3VuZpMNaXYCYu_RvowvPCC54SK-c",
        "worksheet": "Ügyfélklub Tagok",
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
        sheet = client.open_by_key(src["id"]).worksheet(src["worksheet"])
        records = sheet.get_all_records()

        for row in records:
          r = {str(k).strip(): str(v).strip() for k, v in row.items()}
          email = r.get(
              "E-mail cím", r.get("Email", r.get("Ügyfél_Email", ""))
          )
          nev = r.get(
              "Cégnév",
              r.get(
                  "Név",
                  r.get("Ügyfél_Neve", r.get("Kapcsolattartó", "")),
              ),
          )
          phone = r.get("Telefonszám", r.get("Ügyfél_Telefonszám", ""))
          cim = r.get("Székhely / Cím", r.get("Ügyfél_Címe", ""))
          kapcsolattarto = r.get(
              "Kapcsolattartó neve", r.get("Kapcsolattartó", "")
          )

          if email and nev:
            cursor.execute(
                "SELECT id FROM leads WHERE email = ? OR (client_name = ? AND"
                " client_name != '')",
                (email, nev),
            )
            if not cursor.fetchone():
              cursor.execute(
                  """
                                INSERT INTO leads (client_name, phone, email, address, contact_person, source, status)
                                VALUES (?, ?, ?, ?, ?, ?, 'Új')
                            """,
                  (nev, phone, email, cim, kapcsolattarto, src["name"]),
              )
              new_leads_count += 1
      except Exception:
        continue

    conn.commit()
    conn.close()
    return new_leads_count
  except Exception:
    return 0


# ==========================================
# 3. KIÉRTÉKELŐ ÉS E-MAIL KÜLDŐ SEGÉDFÜGGVÉNYEK
# ==========================================
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
    <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6;">
        <p>Kedves {nev}!</p>
        <p>Köszönjük, hogy kitöltötte a kérdőívünket!</p>
        <p>Örömmel értesítjük, hogy a válaszai alapján a profilja megfelel a győri Alfa VIG értékesítési és tanácsadói csapat elvárásainak.</p>
        <p>Kollégánk 2 munkanapon belül keresni fogja Önt a megadott telefonszámon a személyes interjú időpontjának egyeztetése céljából.</p>
        <br>
        <p>Üdvözlettel,<br><strong>Strem Tamás</strong><br>Területi Igazgató<br><em>Alfa Vienna Insurance Group – Győri Régió</em></p>
    </body>
    </html>
    """


def get_elutasito_email(nev):
  return f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.6;">
        <p>Kedves {nev}!</p>
        <p>Köszönjük, hogy időt szánt a kérdőívünk kitöltésére és érdeklődött a győri Alfa VIG karrierlehetőségei iránt.</p>
        <p>Sajnálattal tájékoztatjuk, hogy a jelenlegi nyitott pozícióinkhoz elengedhetetlen a vállalkozói jogviszony keretében történő együttműködés. Mivel Ön jelzése alapján kizárólag főállású/alkalmazotti jogviszonyban gondolkodik, így jelenleg nem tudjuk továbbléptetni a kiválasztási folyamatban.</p>
        <p>Sok sikert kívánunk a további álláskereséséhez!</p>
        <br>
        <p>Üdvözlettel,<br><strong>Strem Tamás</strong><br>Területi Igazgató<br><em>Alfa Vienna Insurance Group – Győri Régió</em></p>
    </body>
    </html>
    """


def process_form_evaluations():
  try:
    gc = get_gspread_client()
    spreadsheet = gc.open_by_key(FORM_SPREADSHEET_ID)

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
              "UPDATE leads SET status = ? WHERE email = ?", (uj_statusz, email)
          )
          conn.commit()
          conn.close()

          feldolgozott_count += 1
          time.sleep(random.randint(10, 20))
        except Exception as err:
          st.error(f"Hiba a levél küldésekor ({nev}): {err}")

  if feldolgozott_count > 0:
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
    username = st.text_input("Felhasználónév (E-mail)")
    password = st.text_input("Jelszó", type="password")
    if st.button("Belépés", use_container_width=True, type="primary"):
      conn = get_db_connection()
      cursor = conn.cursor()
      cursor.execute(
          "SELECT * FROM users WHERE username = ? AND password = ? AND"
          " is_active = 1",
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
st.sidebar.caption(f"Szerepkör: {current_user['role']}")

if st.sidebar.button("🔄 Élő Google Sheets Szinkronizálás"):
  count = sync_google_sheets_to_crm()
  st.sidebar.success(f"{count} új valódi lead beolvasva!")

if current_user["role"] in ["Igazgató", "Asszisztens"]:
  if st.sidebar.button("🧹 Nyers/Hibás Leadek Törlése"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM leads WHERE status = 'Új'")
    conn.commit()
    conn.close()
    st.sidebar.warning("Még nem kiosztott leadek törölve!")
    st.rerun()

if st.sidebar.button("🚪 Kijelentkezés"):
  st.session_state["user"] = None
  st.rerun()

menu_options = [
    "Saját Leadek / Dashboard",
    "Lead Kiosztás & Visszavétel",
    "Új Lead Feltöltés",
    "📥 Toborzási Form Kiértékelés",
    "Felhasználók Kezelése (Jogosultságok)",
    "🔐 Saját Profil & Jelszócsere",
]

menu = st.sidebar.radio("Navigáció", menu_options)

# ==========================================
# 5. MODULOK ÉS NÉZETEK
# ==========================================

if menu == "Saját Leadek / Dashboard":
  st.title("📊 Saját Leadek és Visszajelzések")
  conn = get_db_connection()

  if current_user["role"] in ["Igazgató", "Asszisztens"]:
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
  else:
    query = (
        "SELECT * FROM leads WHERE assigned_advisor_id = ? ORDER BY id DESC"
    )
    params = (current_user["id"],)

  df = pd.read_sql_query(query, conn, params=params)
  conn.close()

  if not df.empty:
    # Címeinek magyarosítása a megjelenítéshez
    df_display = df.rename(
        columns={
            "id": "ID",
            "client_name": "Ügyfél / Cégnév",
            "phone": "Telefonszám",
            "email": "E-mail cím",
            "address": "Cím",
            "contact_person": "Kapcsolattartó",
            "source": "Forrás",
            "status": "Státusz / Visszajelzés",
            "assigned_manager_id": "Manager ID",
            "assigned_advisor_id": "Tanácsadó ID",
            "created_at": "Létrehozva",
            "notes": "Munkatárs Megjegyzése",
        }
    )
    st.dataframe(df_display, use_container_width=True)

    st.divider()
    st.subheader("📝 Lead Státusz & Visszajelzés Frissítése")
    col1, col2, col3 = st.columns([3, 2, 2])

    with col1:
      lead_opts = {
          row["id"]: (
              f"{row['client_name']} ({row['source']}) - Jelenlegi status:"
              f" {row['status']}"
          )
          for _, row in df.iterrows()
      }
      selected_lead_id = st.selectbox(
          "Válassz leadet a frissítéshez:", options=list(lead_opts.keys())
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
      new_note = st.text_input("Megjegyzés / Visszajelzés:")

    if st.button("Visszajelzés Mentése", type="primary"):
      conn = get_db_connection()
      cursor = conn.cursor()
      cursor.execute(
          "UPDATE leads SET status = ?, notes = ? WHERE id = ?",
          (new_status, new_note, selected_lead_id),
      )
      conn.commit()
      conn.close()
      st.success("Státusz és visszajelzés sikeresen elmentve!")
      st.rerun()

  else:
    st.info("Jelenleg nincs megjeleníthető lead.")

elif menu == "Lead Kiosztás & Visszavétel":
  st.title("🎯 Lead Kiosztás és Visszavétel")

  if current_user["role"] not in ["Igazgató", "Manager", "Asszisztens"]:
    st.warning("Ehhez a menüponthoz nincs jogosultságod.")
    st.stop()

  conn = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      "SELECT * FROM leads WHERE status != 'Lezárt' ORDER BY id DESC"
  )
  leads = cursor.fetchall()

  cursor.execute("SELECT id, name, role FROM users WHERE is_active = 1")
  staff = cursor.fetchall()
  conn.close()

  st.subheader("Meglévő Leadek Kezelése")
  for l in leads:
    col1, col2, col3 = st.columns([3, 3, 2])
    with col1:
      st.write(
          f"**{l['client_name']}** ({l['source']}) - Status: `{l['status']}`"
      )
      st.caption(
          f"E-mail: {l['email']} | Tel: {l['phone']} | Megjegyzés:"
          f" {l['notes'] if l['notes'] else 'Nincs'}"
      )
    with col2:
      staff_options = {s["id"]: f"{s['name']} ({s['role']})" for s in staff}
      staff_options[None] = "-- Nincs kiosztva / Visszavéve --"

      current_assigned = l["assigned_advisor_id"]

      selected_staff = st.selectbox(
          "Felelős hozzárendelése",
          options=list(staff_options.keys()),
          index=list(staff_options.keys()).index(current_assigned)
          if current_assigned in staff_options
          else 0,
          format_func=lambda x: staff_options[x],
          key=f"staff_{l['id']}",
      )
    with col3:
      if st.button("Mentés / Kiosztás", key=f"btn_{l['id']}"):
        conn = get_db_connection()
        cursor = conn.cursor()
        new_stat = "Kiosztva" if selected_staff is not None else "Új"
        cursor.execute(
            "UPDATE leads SET assigned_advisor_id = ?, status = ? WHERE id = ?",
            (selected_staff, new_stat, l["id"]),
        )
        conn.commit()
        conn.close()
        st.success("Lead sikeresen frissítve / kiosztva!")
        st.rerun()

elif menu == "Új Lead Feltöltés":
  st.title("➕ Új Lead Manuális Hozzáadása")
  with st.form("new_lead_form"):
    client_name = st.text_input("Ügyfél / Cégnév")
    phone = st.text_input("Telefonszám")
    email = st.text_input("E-mail cím")
    address = st.text_input("Cím / Székhely")
    source = st.selectbox(
        "Forrás",
        [
            "Promobox Kampány",
            "Vállalkozói Felmérés",
            "Ügyfélklub",
            "Évfordulós Felülvizsgálat",
            "Személyes Ajánlás",
        ],
    )
    submitted = st.form_submit_button("Lead Rögzítése", type="primary")

    if submitted and client_name:
      conn = get_db_connection()
      cursor = conn.cursor()
      cursor.execute(
          """
                INSERT INTO leads (client_name, phone, email, address, source, status)
                VALUES (?, ?, ?, ?, ?, 'Új')
            """,
          (client_name, phone, email, address, source),
      )
      conn.commit()
      conn.close()
      st.success("Új lead sikeresen rögzítve!")

elif menu == "📥 Toborzási Form Kiértékelés":
  st.title("📋 Toborzási Kérdőív Kiértékelés")
  st.write(
      "Kattints az alábbi gombra a beérkezett Google Form válaszok manuális"
      " kiértékeléséhez és a visszajelző levelek kiküldéséhez:"
  )

  if st.button("📥 Form válaszok kiértékelése", type="primary"):
    process_form_evaluations()

elif menu == "Felhasználók Kezelése (Jogosultságok)":
  st.title("👥 Felhasználók & Belépési Jogosultságok")

  if current_user["role"] not in ["Igazgató", "Asszisztens"]:
    st.error("Csak az Igazgató és az Asszisztens kezelheti a felhasználókat.")
    st.stop()

  # 1. MEGLÉVŐ FELHASZNÁLÓK LISTÁJA
  st.subheader("📋 Rendszerben lévő munkatársak")
  conn = get_db_connection()
  df_users = pd.read_sql_query(
      """
        SELECT u.id AS "ID", u.name AS "Név", u.username AS "Felhasználónév (Email)", 
               u.role AS "Szerepkör", m.name AS "Felettes Manager"
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

  # 2. ÚJ MUNKATÁRS HOZZÁADÁSA
  st.subheader("➕ Új Munkatárs Hozzáadása")
  with st.form("add_user_form"):
    new_username = st.text_input("Felhasználónév (E-mail)")
    new_name = st.text_input("Munkatárs Teljes Neve")
    new_password = st.text_input("Kezdő Jelszó", type="password")
    new_role = st.selectbox(
        "Szerepkör", ["Manager", "Tanácsadó", "Asszisztens"]
    )

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, role FROM users WHERE role IN ('Igazgató',"
        " 'Manager')"
    )
    managers = cursor.fetchall()
    conn.close()

    manager_opts = {m["id"]: f"{m['name']} ({m['role']})" for m in managers}
    manager_opts[None] = "Nincs (Főigazgató alá tartozik)"

    selected_manager = st.selectbox(
        "Felettes Manager / Igazgató:",
        options=list(manager_opts.keys()),
        format_func=lambda x: manager_opts[x],
    )

    if st.form_submit_button("Felhasználó Létrehozása", type="primary"):
      if new_username and new_password and new_name:
        try:
          conn = get_db_connection()
          cursor = conn.cursor()
          cursor.execute(
              """
                        INSERT INTO users (username, password, name, role, manager_id, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
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
            "UPDATE users SET password = ? WHERE id = ?",
            (new_pw.strip(), current_user["id"]),
        )
        conn.commit()
        conn.close()
        st.session_state["user"]["password"] = new_pw.strip()
        st.success("Jelszavadat sikeresen megváltoztattad!")
