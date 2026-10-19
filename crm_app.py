import sqlite3
import datetime
import hashlib
import pandas as pd
import streamlit as st

# --- ADATBÁZIS INICIALIZÁLÁSA ---
DB_FILE = "crm_database.db"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users tábla
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL, -- 'Igazgató', 'Manager', 'Tanácsadó'
            manager_id INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Leads tábla
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            contact_person TEXT,
            source TEXT DEFAULT 'Manuális',
            assigned_manager_id INTEGER,
            assigned_advisor_id INTEGER,
            assigned_date DATETIME,
            due_date DATETIME,
            status TEXT DEFAULT 'Új',
            rejection_reason TEXT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Alapértelmezett Igazgató fiók létrehozása (ha még nincs)
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        admin_pass = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, full_name, role, is_active)
            VALUES ('admin', ?, 'Főigazgató', 'Igazgató', 1)
        """,
            (admin_pass,),
        )

    conn.commit()
    conn.close()


init_db()

# --- SEGÉDFÜGGVÉNYEK ---


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def check_login(username, password):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    conn.close()
    if user and user["password_hash"] == hash_password(password):
        return dict(user)
    return None


# --- JOGOSULTSÁG ÉS MUNKAMENET MANAGEMENT ---
st.set_page_config(page_title="Egyedi CRM Rendszer", layout="wide")

if "user" not in st.session_state:
    st.session_state["user"] = None

# --- BEJELENTKEZÉSI FELÜLET ---
if not st.session_state["user"]:
    st.title("🔐 CRM Rendszer - Bejelentkezés")
    with st.form("login_form"):
        username = st.text_input("Felhasználónév (E-mail)")
        password = st.text_input("Jelszó", type="password")
        submit = st.form_submit_button("Belépés")

        if submit:
            user = check_login(username, password)
            if user:
                st.session_state["user"] = user
                st.success(f"Üdvözöljük, {user['full_name']}!")
                st.rerun()
            else:
                st.error(
                    "Érvénytelen felhasználónév, jelszó vagy a fiók inaktiválva lett!"
                )
    st.stop()

# --- BEJELENTKEZETT FELÜLET ---
current_user = st.session_state["user"]
st.sidebar.title(f"👤 {current_user['full_name']}")
st.sidebar.caption(f"Szerepkör: {current_user['role']}")

if st.sidebar.button("Kijelentkezés"):
    st.session_state["user"] = None
    st.rerun()

# --- MENÜPONTOK ROLES ALAPJÁN ---
menu_options = ["Saját Leadek / Dashboard"]

if current_user["role"] in ["Igazgató", "Manager"]:
    menu_options.append("Lead Kiosztás & Visszavétel")

if current_user["role"] == "Igazgató":
    menu_options.append("Új Lead Feltöltés")
    menu_options.append("Felhasználók Kezelése (Jogosultságok)")

choice = st.sidebar.radio("Navigáció", menu_options)

conn = get_db_connection()

# ==========================================
# 1. SAJÁT LEADEK & TERMINÁLÁS (Mindenki)
# ==========================================
if choice == "Saját Leadek / Dashboard":
    st.header("📋 Kezelt / Kiosztott Leadek")

    # Lekérdezés szerepkör alapján
    if current_user["role"] == "Igazgató":
        query = "SELECT * FROM leads"
        leads = conn.execute(query).fetchall()
    elif current_user["role"] == "Manager":
        query = "SELECT * FROM leads WHERE assigned_manager_id = ? OR assigned_advisor_id IN (SELECT id FROM users WHERE manager_id = ?)"
        leads = conn.execute(
            query, (current_user["id"], current_user["id"])
        ).fetchall()
    else:  # Tanácsadó
        query = "SELECT * FROM leads WHERE assigned_advisor_id = ? AND status != 'Elutasítva'"
        leads = conn.execute(query, (current_user["id"],)).fetchall()

    if leads:
        df = pd.DataFrame([dict(row) for row in leads])
        st.dataframe(df, use_container_width=True)

        st.subheader("⚙️ Lead Frissítése / Terminálása")
        selected_lead_id = st.selectbox(
            "Válassz leadet:", df["id"].tolist(), format_func=lambda x: f"ID: {x}"
        )

        lead_data = conn.execute(
            "SELECT * FROM leads WHERE id = ?", (selected_lead_id,)
        ).fetchone()

        if lead_data:
            st.write(
                f"**Ügyfél:** {lead_data['client_name']} | **Tel:** {lead_data['phone']} | **E-mail:** {lead_data['email']}"
            )
            with st.form("status_update_form"):
                new_status = st.selectbox(
                    "Státusz:",
                    [
                        "Új",
                        "Kapcsolatfelvétel alatt",
                        "Sikeres",
                        "Elutasítva",
                        "Visszadobva (Tanácsadó elutasította)",
                    ],
                    index=0,
                )
                reason = st.text_input(
                    "Terminálás / Elutasítás oka:",
                    value=lead_data["rejection_reason"] or "",
                )
                new_note = st.text_area("Új Jegyzet hozzáadása:")
                save_btn = st.form_submit_button("Frissítés Mentése")

                if save_btn:
                    updated_notes = (
                        (lead_data["notes"] or "")
                        + f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {current_user['full_name']}: {new_note}"
                        if new_note
                        else lead_data["notes"]
                    )

                    # Ha a tanácsadó elutasítja, visszakerül az igazgatói/manageri kalapba
                    if new_status == "Visszadobva (Tanácsadó elutasította)":
                        conn.execute(
                            "UPDATE leads SET status = ?, rejection_reason = ?, notes = ?, assigned_advisor_id = NULL WHERE id = ?",
                            (
                                new_status,
                                reason,
                                updated_notes,
                                selected_lead_id,
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE leads SET status = ?, rejection_reason = ?, notes = ? WHERE id = ?",
                            (
                                new_status,
                                reason,
                                updated_notes,
                                selected_lead_id,
                            ),
                        )

                    conn.commit()
                    st.success("Lead sikeresen frissítve!")
                    st.rerun()

# ==========================================
# 2. LEAD KIOSZTÁS ÉS VISSZAVÉTEL
# ==========================================
elif choice == "Lead Kiosztás & Visszavétel":
    st.header("🔀 Leadek Kiosztása és Visszavétele")

    if current_user["role"] == "Igazgató":
        unassigned_leads = conn.execute(
            "SELECT * FROM leads WHERE assigned_manager_id IS NULL AND assigned_advisor_id IS NULL"
        ).fetchall()
        managers = conn.execute(
            "SELECT * FROM users WHERE role = 'Manager' AND is_active = 1"
        ).fetchall()

        st.subheader("1. Kiosztás Managernek")
        if unassigned_leads:
            lead_to_assign = st.selectbox(
                "Kiosztatlan lead kiválasztása:", [l["id"] for l in unassigned_leads]
            )
            target_manager = st.selectbox(
                "Manager kiválasztása:",
                [m["id"] for m in managers],
                format_func=lambda x: [
                    m["full_name"] for m in managers if m["id"] == x
                ][0],
            )
            due_days = st.number_input(
                "Feldolgozási határidő (nap):", min_value=1, value=3
            )

            if st.button("Kiosztás Managernek"):
                due_date = datetime.datetime.now() + datetime.timedelta(
                    days=due_days
                )
                conn.execute(
                    "UPDATE leads SET assigned_manager_id = ?, assigned_date = ?, due_date = ?, status = 'Kiosztva Managernek' WHERE id = ?",
                    (
                        target_manager,
                        datetime.datetime.now(),
                        due_date,
                        lead_to_assign,
                    ),
                )
                conn.commit()
                st.success("Lead sikeresen kiosztva!")
                st.rerun()
        else:
            st.info("Nincs szabad kiosztatlan lead.")

    if current_user["role"] in ["Igazgató", "Manager"]:
        st.subheader("2. Kiosztás Tanácsadónak")
        # Manager csak a saját tanácsadóit látja
        if current_user["role"] == "Manager":
            advisors = conn.execute(
                "SELECT * FROM users WHERE role = 'Tanácsadó' AND manager_id = ? AND is_active = 1",
                (current_user["id"],),
            ).fetchall()
            manager_leads = conn.execute(
                "SELECT * FROM leads WHERE assigned_manager_id = ? AND assigned_advisor_id IS NULL",
                (current_user["id"],),
            ).fetchall()
        else:
            advisors = conn.execute(
                "SELECT * FROM users WHERE role = 'Tanácsadó' AND is_active = 1"
            ).fetchall()
            manager_leads = conn.execute(
                "SELECT * FROM leads WHERE assigned_advisor_id IS NULL"
            ).fetchall()

        if manager_leads and advisors:
            m_lead_id = st.selectbox(
                "Lead kiválasztása Tanácsadónak:", [l["id"] for l in manager_leads]
            )
            target_advisor = st.selectbox(
                "Tanácsadó kiválasztása:",
                [a["id"] for a in advisors],
                format_func=lambda x: [
                    a["full_name"] for a in advisors if a["id"] == x
                ][0],
            )

            if st.button("Kiosztás Tanácsadónak"):
                conn.execute(
                    "UPDATE leads SET assigned_advisor_id = ?, assigned_date = ?, status = 'Kiosztva Tanácsadónak' WHERE id = ?",
                    (target_advisor, datetime.datetime.now(), m_lead_id),
                )
                conn.commit()
                st.success("Lead továbbítva a tanácsadónak!")
                st.rerun()

# ==========================================
# 3. FELHASZNÁLÓK KEZELÉSE & BIZTONSÁG (Igazgató)
# ==========================================
elif choice == "Felhasználók Kezelése (Jogosultságok)":
    st.header("👥 Felhasználók & Belépési Jogosultságok")

    st.subheader("Új Munkatárs Hozzáadása")
    with st.form("new_user_form"):
        new_username = st.text_input("Felhasználónév (E-mail)")
        new_fullname = st.text_input("Munkatárs Teljes Neve")
        new_password = st.text_input("Kezdő Jelszó", type="password")
        new_role = st.selectbox("Szerepkör", ["Manager", "Tanácsadó", "Igazgató"])

        # Managerek listája a tanácsadók hozzárendeléséhez
        managers = conn.execute(
            "SELECT * FROM users WHERE role = 'Manager' AND is_active = 1"
        ).fetchall()
        manager_ctx = st.selectbox(
            "Felettes Manager (Tanácsadó esetén):",
            [None] + [m["id"] for m in managers],
            format_func=lambda x: "Nincs"
            if x is None
            else [m["full_name"] for m in managers if m["id"] == x][0],
        )

        create_u_btn = st.form_submit_button("Felhasználó Létrehozása")

        if create_u_btn:
            if new_username and new_password:
                try:
                    conn.execute(
                        """
                        INSERT INTO users (username, password_hash, full_name, role, manager_id, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """,
                        (
                            new_username,
                            hash_password(new_password),
                            new_fullname,
                            new_role,
                            manager_ctx,
                        ),
                    )
                    conn.commit()
                    st.success(f"Munkatárs ({new_fullname}) sikeresen rögzítve!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Ez a felhasználónév már létezik!")

    st.divider()
    st.subheader("Munkatársak Státusza & Hozzáférés Megvonása")
    all_users = conn.execute(
        "SELECT id, username, full_name, role, is_active FROM users WHERE username != 'admin'"
    ).fetchall()

    if all_users:
        users_df = pd.DataFrame([dict(u) for u in all_users])
        st.dataframe(users_df, use_container_width=True)

        selected_user_id = st.selectbox(
            "Válassz munkatársat a módosításhoz:",
            users_df["id"].tolist(),
            format_func=lambda x: f"{[u['full_name'] for u in all_users if u['id']==x][0]} (ID: {x})",
        )

        u_data = conn.execute(
            "SELECT * FROM users WHERE id = ?", (selected_user_id,)
        ).fetchone()

        col1, col2 = st.columns(2)
        with col1:
            if u_data["is_active"] == 1:
                if st.button("🚫 HOZZÁFÉRÉS MEGVONÁSA (Inaktiválás)", type="primary"):
                    # 1. Inaktiválás
                    conn.execute(
                        "UPDATE users SET is_active = 0 WHERE id = ?",
                        (selected_user_id,),
                    )
                    # 2. Nála lévő aktív leadek visszavétele az igazgatói kalapba
                    conn.execute(
                        "UPDATE leads SET assigned_advisor_id = NULL, status = 'Visszavéve (Távozott munkatárs)' WHERE assigned_advisor_id = ? AND status NOT IN ('Sikeres', 'Elutasítva')",
                        (selected_user_id,),
                    )
                    conn.commit()
                    st.warning(
                        f"{u_data['full_name']} hozzáférése megvonva! Aktív leadjai visszakerültek a központi kalapba."
                    )
                    st.rerun()
            else:
                if st.button("✅ HOZZÁFÉRÉS ÚJRAAKTIVÁLÁSA"):
                    conn.execute(
                        "UPDATE users SET is_active = 1 WHERE id = ?",
                        (selected_user_id,),
                    )
                    conn.commit()
                    st.success(
                        f"{u_data['full_name']} fiókja újra aktiválva lett!"
                    )
                    st.rerun()

conn.close()