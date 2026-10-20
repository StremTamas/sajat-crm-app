elif menu == "Felhasználók Kezelése (Jogosultságok)":
  st.title("👥 Felhasználók & Belépési Jogosultságok")

  if current_user["role"] != "Igazgató":
    st.error("Csak az Igazgató kezelheti a felhasználókat.")
    st.stop()

  # 1. MEGLÉVŐ FELHASZNÁLÓK LISTÁJA
  st.subheader("📋 Rendszerben lévő munkatársak")
  conn = get_db_connection()
  df_users = pd.read_sql_query(
      """
        SELECT u.id, u.name AS "Név", u.username AS "Felhasználónév (Email)", 
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
    new_role = st.selectbox("Szerepkör", ["Manager", "Tanácsadó"])

    conn = get_db_connection()
    cursor = conn.cursor()
    # Az Igazgatót és a Managereket is lekérjük felettes opcióként
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

    if st.form_submit_button("Felhasználó Létrehozása"):
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
