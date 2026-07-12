with st.expander("🔖 Быстрый переход (как закладка в книге)"):
    jc1, jc2 = st.columns(2)
    with jc1:
        st.markdown("**К суре:**")
        surah_options = [f"{s['number']}. {s['name']} — {s['englishName']}" for s in SURAH_LIST] or \
            [f"{n}" for n in range(1, 115)]
        
        # Находим индекс Суры Ясин (36), чтобы сделать её примером по умолчанию, или просто берем 0
        default_index = 0
        for idx, opt in enumerate(surah_options):
            if opt.startswith("36."):
                default_index = idx
                break
                
        surah_choice = st.selectbox("Выберите суру", surah_options, index=default_index, key="surah_jump_select")
        if st.button("Открыть страницу суры", use_container_width=True):
            sura_num = int(surah_choice.split(".")[0])
            with st.spinner("Ищу страницу суры..."):
                target_page = get_surah_start_page(sura_num)
            if target_page:
                st.session_state["cur_page"] = target_page
                st.session_state["reading_mode"] = "По странице мусхафа"
                st.success(f"Перешли на страницу {target_page}, где начинается сура!")
                st.rerun()
            else:
                st.warning("Не удалось определить страницу этой суры.")
                
    with jc2:
        st.markdown("**К джузу:**")
        juz_choice = st.number_input("Номер джуза (1–30)", min_value=1, max_value=30, value=20, step=1, key="juz_jump_select")
        if st.button("Открыть страницу джуза", use_container_width=True):
            with st.spinner("Ищу страницу джуза..."):
                target_page = get_juz_start_page(int(juz_choice))
            if target_page:
                st.session_state["cur_page"] = target_page
                st.session_state["reading_mode"] = "По странице мусхафа"
                st.success(f"Перешли на страницу {target_page}, с которой начинается {juz_choice}-й джуз!")
                st.rerun()
            else:
                st.warning("Не удалось определить страницу этого джуза.")
