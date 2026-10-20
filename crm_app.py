import datetime
import random
import smtplib
import sqlite3
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials
import gspread
import streamlit as st

# ==========================================
# KONFIGURÁCIÓ & KONSTANSOK
# ==========================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "arrabonainsurance@gmail.com"
SENDER_NAME = "Insurance Arrabona"
SENDER_PASSWORD = "aqzs okrl jewl ypdw"

CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_ID = "1Gw6teVYi940HdPHiO5WoSrEqKSfnZtv5RTl_tAFDEis"
SHEET_FORM_VALASZOK = "Form Responses 1"  # Google Form válaszok lapja
CRM_DB_FILE = "crm_database.db"


# ==========================================
# SEGÉDFÜGGVÉNYEK (E-MAIL ÉS KIÉRTÉKELÉS)
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
  """Elvégzi a Form válaszok manuális kiértékelését és kiküldi a megfelelő válaszleveleket."""
  scopes = [
      "https://www.googleapis.com/auth/spreadsheets",
      "https://www.googleapis.com/auth/drive",
  ]
  creds = Credentials.from_service_account_file(
      CREDENTIALS_FILE, scopes=scopes
  )
  gc = gspread.authorize(creds)

  try:
    sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_FORM_VALASZOK)
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

      # Csak a még fel nem dolgozott sorokat értékeljük ki
      if kiertekeles in ["", "Új", "Feldolgozatlan"]:
        email = str(row.get("Email", "")).strip()
        nev = str(row.get("Név", "")).strip()

        if not email:
          continue

        # Vállalkozói szándék válasz kiolvasása és kisbetűsítése
        vallalkozo_valasz = str(
            row.get(
                "Nyitott vállalkozói jogviszonyra?",
                row.get("Vállalkozói szándék", ""),
            )
        ).lower()

        # VÍZHATLAN SZŰRÉS: Kizárólag főállás / nem vállalkozó szándék kiszűrése
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

        # Döntés és e-mail előkészítése
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

        # Levél küldése és adatbázisok frissítése
        try:
          send_email_smtp(email, subject, html_body)

          # Google Sheets státusz frissítése
          if statusz_col_idx:
            sheet.update_cell(i, statusz_col_idx, uj_statusz)

          # CRM adatbázis (SQLite) frissítése
          conn = sqlite3.connect(CRM_DB_FILE)
          cursor = conn.cursor()
          cursor.execute(
              "UPDATE leads SET status = ? WHERE email = ?", (uj_statusz, email)
          )
          conn.commit()
          conn.close()

          feldolgozott_count += 1
          time.sleep(random.randint(15, 30))  # Késleltetés a spam-védelemhez

        except Exception as err:
          st.error(f"Hiba a levél küldésekor ({nev}): {err}")

  if feldolgozott_count > 0:
    st.balloons()
    st.success(
        f"A kiértékelés lefutott! Összesen {feldolgozott_count} új jelölt kapta"
        " meg a visszajelzést."
    )
  else:
    st.info("Nem található új, kiértékelésre váró kérdőív válasz.")


# ==========================================
# STREAMLIT GOMB MEGJELENÍTÉSE
# ==========================================
st.subheader("📋 Toborzási Kérdőív Kiértékelés")
st.write(
    "Kattints az alábbi gombra a beérkezett Google Form válaszok manuális"
    " kiértékeléséhez és a visszajelző levelek kiküldéséhez:"
)

if st.button("📥 Form válaszok kiértékelése", type="primary"):
  process_form_evaluations()
