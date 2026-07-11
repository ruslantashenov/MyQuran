import streamlit as st
import librosa
import numpy as np
import requests
import io
import base64
import os
import soundfile as sf

st.set_page_config(page_title="Тренажёр чтения Корана", page_icon="📖", layout="centered")


@st.cache_data(show_spinner=False)
def load_font_css() -> tuple[str, str]:
    """Встраивает шрифт Uthman Taha Naskh (файл рядом с app.py) через @font-face.
    Возвращает (css, диагностика)."""
    directory = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(directory, "KFGQPC_Uthman_Taha_Naskh_Regular.ttf")
    if not os.path.exists(font_path):
        try:
            files_here = os.listdir(directory)
        except OSError:
            files_here = []
        return "", (
            f"Файл шрифта не найден по пути `{font_path}`. "
            f"Файлы в этой папке репозитория: {files_here}. "
            f"Проверьте, что .ttf лежит РЯДОМ с app.py (не во вложенной папке) "
            f"и называется ровно `KFGQPC_Uthman_Taha_Naskh_Regular.ttf`."
        )
    with open(font_path, "rb") as f:
        font_b64 = base64.b64encode(f.read()).decode("ascii")
    css = f"""
    <style>
    @font-face {{
        font-family: 'UthmanTahaNaskh';
        src: url(data:font/ttf;base64,{font_b64}) format('truetype');
    }}
    </style>
    """
    return css, ""


font_css, font_debug = load_font_css()
if font_css:
    st.markdown(font_css, unsafe_allow_html=True)
elif font_debug:
    st.warning(f"⚠️ Шрифт не подключился: {font_debug}")

st.title("📖 Личный тренажёр чтения Корана")
st.caption("Эталон: шейх Махмуд Халиль аль-Хусари")

st.info(
    "⚠️ **Важно понимать, что именно измеряет этот инструмент.** "
    "Он сравнивает темп, ритм и общий звуковой рисунок вашего чтения с эталонным, "
    "и подсвечивает в тексте, ГДЕ по правилам должны применяться таджвид-правила "
    "(это определяется из письменного текста — надёжно). "
    "Но он **не проверяет на слух**, правильно ли вы сделали саму гунну, ихфа или "
    "идгам — для этого нужен человек. Используйте как помощь для самоконтроля "
    "и подсказку, где именно вслушаться в эталон."
)

# ---------------------------------------------------------------------------
# Правила таджвида: определяем по написанному тексту (надёжно, без ИИ)
# ---------------------------------------------------------------------------

TAJWEED_COLORS = {
    "madd": ("#2144C1", "Мадд (продление)"),
    "qalqalah": ("#DD0008", "Калькаля"),
    "ikhfa": ("#9400A8", "Ихфа"),
    "idgham_ghunnah": ("#169777", "Идгам с гунной"),
    "idgham_no_ghunnah": ("#169200", "Идгам без гунны"),
    "iqlab": ("#26BFFD", "Иклаб"),
    "ghunnah": ("#FF7E1E", "Гунна (шадда на ن/م)"),
}

QALQALAH_LETTERS = set("قطبجد")
IDGHAM_GHUNNAH_LETTERS = set("ينمو")   # ي ن م و
IDGHAM_NO_GHUNNAH_LETTERS = set("لر")   # ل ر
IQLAB_LETTER = "ب"
IZHAR_LETTERS = set("ءهعحغخ")

FATHA, DAMMA, KASRA, SUKUN, SHADDA = "\u064E", "\u064F", "\u0650", "\u0652", "\u0651"
TANWEEN = {"\u064B", "\u064C", "\u064D"}
MADD_LETTERS = {"ا": FATHA, "و": DAMMA, "ي": KASRA}
DAGGER_ALIF = "\u0670"  # маленький "кинжальный" алиф — тоже мадд (напр. الرَّحْمَٰنِ)
MADDAH = "\u0653"       # знак мадда над алифом (напр. آمنوا)


def analyze_word_tajweed(word: str) -> list[tuple[int, int, str]]:
    """Возвращает список (start, end, rule_key) диапазонов внутри слова."""
    spans = []
    chars = list(word)
    for i, ch in enumerate(chars):
        # Калькаля: буква из قطبجد + сукун
        if ch in QALQALAH_LETTERS and i + 1 < len(chars) and chars[i + 1] == SUKUN:
            spans.append((i, i + 2, "qalqalah"))

        # Гунна: шадда на нун или мим
        if ch in "نم" and i + 1 < len(chars) and chars[i + 1] == SHADDA:
            spans.append((i, i + 2, "ghunnah"))

        # Мадд: алиф/вав/я после соответствующей краткой гласной
        if ch in MADD_LETTERS and i > 0 and chars[i - 1] == MADD_LETTERS[ch]:
            spans.append((max(0, i - 1), i + 1, "madd"))

        # Мадд через кинжальный алиф / знак мадда (напр. الرَّحْمَٰنِ, آمنوا)
        if ch in (DAGGER_ALIF, MADDAH):
            spans.append((max(0, i - 1), i + 1, "madd"))

        # Танвин / нун сакин — определяем следующую букву (в этом же слове)
        is_noon_sakin = ch == "ن" and i + 1 < len(chars) and chars[i + 1] == SUKUN
        is_tanween = ch in TANWEEN
        if is_noon_sakin or is_tanween:
            nxt = None
            for j in range(i + 1, len(chars)):
                if chars[j] not in (SUKUN,) and chars[j].strip():
                    nxt = chars[j]
                    break
            if nxt:
                if nxt == IQLAB_LETTER:
                    spans.append((i, i + 1, "iqlab"))
                elif nxt in IDGHAM_GHUNNAH_LETTERS:
                    spans.append((i, i + 1, "idgham_ghunnah"))
                elif nxt in IDGHAM_NO_GHUNNAH_LETTERS:
                    spans.append((i, i + 1, "idgham_no_ghunnah"))
                elif nxt in IZHAR_LETTERS:
                    pass  # изхар — обычное чтение, без спец. подсветки
                elif nxt not in ("ن",):
                    spans.append((i, i + 1, "ikhfa"))
    return spans


def render_tajweed_html(ayah_text: str, flagged_words: set[int] | None = None) -> tuple[str, dict]:
    """Строит HTML с подсветкой + собирает статистику встреченных правил.
    flagged_words — индексы слов (по порядку в ayah_text.split(' ')), которые
    отмечаются красной подчёркой как места вероятного расхождения со звуком эталона."""
    flagged_words = flagged_words or set()
    found = {}
    words_html = []
    for w_idx, word in enumerate(ayah_text.split(" ")):
        spans = analyze_word_tajweed(word)
        if not spans:
            word_html = word
        else:
            tag_per_char = {}
            for start, end, rule in spans:
                for idx in range(start, end):
                    tag_per_char[idx] = rule
                found[rule] = found.get(rule, 0) + 1

            chars = list(word)
            html_parts = []
            i = 0
            while i < len(chars):
                rule = tag_per_char.get(i)
                if rule:
                    j = i
                    while j < len(chars) and tag_per_char.get(j) == rule:
                        j += 1
                    color, _ = TAJWEED_COLORS[rule]
                    segment = "".join(chars[i:j])
                    html_parts.append(f'<span style="color:{color}">{segment}</span>')
                    i = j
                else:
                    html_parts.append(chars[i])
                    i += 1
            word_html = "".join(html_parts)

        if w_idx in flagged_words:
            word_html = (
                f'<span style="border-bottom:4px solid #E00000; padding-bottom:2px;" '
                f'title="Возможное расхождение со звуком эталона">{word_html}</span>'
            )
        words_html.append(word_html)

    html = " ".join(words_html)
    return html, found


def show_legend(found_rules: dict):
    if found_rules:
        legend_bits = []
        for rule, count in found_rules.items():
            color, name = TAJWEED_COLORS[rule]
            legend_bits.append(f'<span style="color:{color}">●</span> {name} ({count})')
        st.caption(" &nbsp;&nbsp; ".join(legend_bits), unsafe_allow_html=True)


def arabic_block(html: str):
    st.markdown(
        f'<div dir="rtl" style="font-size:30px; line-height:2.3; text-align:right; '
        f'font-family: \'UthmanTahaNaskh\', \'Traditional Arabic\', \'Amiri\', serif;">{html}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_husary_audio(sura: int, ayat: int) -> bytes | None:
    sura_str, ayat_str = str(sura).zfill(3), str(ayat).zfill(3)
    url = f"https://everyayah.com/data/Husary_Muallim_128kbps/{sura_str}{ayat_str}.mp3"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.content
    except requests.RequestException:
        return None


@st.cache_data(show_spinner=False)
def get_ayah_text(sura: int, ayat: int) -> str | None:
    url = f"https://api.alquran.cloud/v1/ayah/{sura}:{ayat}/quran-uthmani"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()["data"]["text"]
    except (requests.RequestException, KeyError, ValueError):
        return None


@st.cache_data(show_spinner=False)
def get_page_ayahs(page: int) -> list[dict] | None:
    """Возвращает список аятов целой страницы мусхафа (1–604), с номерами суры/аята."""
    url = f"https://api.alquran.cloud/v1/page/{page}/quran-uthmani"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()["data"]["ayahs"]
        result = []
        for a in data:
            result.append({
                "text": a.get("text", ""),
                "sura": a.get("surah", {}).get("number"),
                "ayat": a.get("numberInSurah"),
                "sura_name": a.get("surah", {}).get("name", ""),
            })
        return result
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


@st.cache_data(show_spinner=False)
def combine_ayah_audio(ayah_refs: tuple[tuple[int, int], ...]) -> bytes | None:
    """Склеивает эталонные записи нескольких аятов подряд в одну дорожку (с паузами)."""
    sr_target = 22050
    segments = []
    for sura, ayat in ayah_refs:
        mp3 = get_husary_audio(sura, ayat)
        if mp3 is None:
            return None
        y, _ = librosa.load(io.BytesIO(mp3), sr=sr_target)
        segments.append(y)
        segments.append(np.zeros(int(0.4 * sr_target), dtype=y.dtype))  # пауза между аятами
    if not segments:
        return None
    combined = np.concatenate(segments)
    buf = io.BytesIO()
    sf.write(buf, combined, sr_target, format="WAV")
    return buf.getvalue()


def find_mismatch_words(ayah_text: str, ref_bytes: bytes, user_bytes: bytes) -> set[int]:
    """Приблизительно определяет, какие слова аята звучали заметно иначе, чем у
    эталона. Это НЕ проверка правильности таджвида — только акустическое
    расхождение (могло быть вызвано неверным словом, паузой, случайным шумом
    и т.п.). Работает через выравнивание DTW и деление аудио на слова
    пропорционально длине слов в тексте (приближение, не точная разметка)."""
    words = ayah_text.split(" ")
    if not words:
        return set()

    try:
        y_ref, sr = librosa.load(io.BytesIO(ref_bytes), sr=None)
        y_user, sr_user = librosa.load(io.BytesIO(user_bytes), sr=None)
        if sr_user != sr:
            y_user = librosa.resample(y_user, orig_sr=sr_user, target_sr=sr)

        mfcc_ref = librosa.feature.mfcc(y=y_ref, sr=sr, n_mfcc=13)
        mfcc_user = librosa.feature.mfcc(y=y_user, sr=sr, n_mfcc=13)
        _, wp = librosa.sequence.dtw(X=mfcc_user, Y=mfcc_ref, subseq=True)
        wp = wp[::-1]  # librosa отдаёт путь от конца к началу — разворачиваем

        n_ref_frames = mfcc_ref.shape[1]
        weights = [max(len(w), 1) for w in words]
        total = sum(weights)
        bounds = np.cumsum([0] + weights) / total * n_ref_frames

        word_costs = [[] for _ in words]
        for ui, ri in wp:
            dist = float(np.linalg.norm(mfcc_user[:, ui] - mfcc_ref[:, ri]))
            for wi in range(len(words)):
                if bounds[wi] <= ri < bounds[wi + 1]:
                    word_costs[wi].append(dist)
                    break

        avg_costs = np.array([np.mean(c) if c else 0.0 for c in word_costs])
        if avg_costs.std() <= 0:
            return set()
        threshold = avg_costs.mean() + 0.75 * avg_costs.std()
        return {i for i, c in enumerate(avg_costs) if c > threshold and c > 0}
    except Exception:
        return set()


def analyze_audio(ref_bytes: bytes, user_bytes: bytes) -> dict:
    y_ref, sr_ref = librosa.load(io.BytesIO(ref_bytes), sr=None)
    y_user, sr_user = librosa.load(io.BytesIO(user_bytes), sr=None)

    chroma_ref = librosa.feature.chroma_stft(y=y_ref, sr=sr_ref)
    chroma_user = librosa.feature.chroma_stft(y=y_user, sr=sr_user)
    D_chroma, wp_chroma = librosa.sequence.dtw(X=chroma_user, Y=chroma_ref, subseq=True)
    chroma_similarity = max(0.0, min(100.0, 100 - (D_chroma[-1, -1] / len(wp_chroma)) * 10))

    mfcc_ref = librosa.feature.mfcc(y=y_ref, sr=sr_ref, n_mfcc=13)
    mfcc_user = librosa.feature.mfcc(y=y_user, sr=sr_user, n_mfcc=13)
    D_mfcc, wp_mfcc = librosa.sequence.dtw(X=mfcc_user, Y=mfcc_ref, subseq=True)
    mfcc_similarity = max(0.0, min(100.0, 100 - (D_mfcc[-1, -1] / len(wp_mfcc)) * 2))

    dur_ref = librosa.get_duration(y=y_ref, sr=sr_ref)
    dur_user = librosa.get_duration(y=y_user, sr=sr_user)

    return {
        "chroma_similarity": chroma_similarity,
        "mfcc_similarity": mfcc_similarity,
        "dur_ref": dur_ref,
        "dur_user": dur_user,
    }


def comparison_ui(ref_audio: bytes | None, key: str, label: str, ayah_text: str | None = None):
    """Общий блок: эталонное аудио + запись + сравнение. ref_audio может быть
    записью одного аята или склеенным диапазоном/целой страницей.
    Если передан ayah_text (только для одного аята) — после сравнения
    дополнительно показывает текст с подсветкой подозрительных слов."""
    if ref_audio:
        st.markdown("**🎧 Эталонное чтение (Аль-Хусари):**")
        st.audio(ref_audio, format="audio/wav" if ref_audio[:4] == b"RIFF" else "audio/mp3")
    else:
        st.error("Не удалось загрузить эталонное аудио для этого фрагмента.")

    st.markdown("**🎙 Запишите ваше чтение:**")
    user_audio = st.audio_input("Нажмите, чтобы начать запись", key=f"rec_{key}")

    if st.button("🔥 Сравнить с эталоном", type="primary",
                  disabled=not (ref_audio and user_audio), key=f"btn_{key}"):
        user_bytes = user_audio.read()
        with st.spinner("Анализирую..."):
            result = analyze_audio(ref_audio, user_bytes)

        st.subheader(f"📊 Результаты ({label})")
        c1, c2 = st.columns(2)
        c1.metric("Совпадение звукового рисунка", f"{result['chroma_similarity']:.0f}%")
        c2.metric("Совпадение артикуляции (MFCC)", f"{result['mfcc_similarity']:.0f}%")
        st.write(
            f"**Длительность эталона:** {result['dur_ref']:.1f} сек · "
            f"**Ваша длительность:** {result['dur_user']:.1f} сек"
        )
        diff = abs(result["dur_ref"] - result["dur_user"])
        if diff > 2.0:
            st.warning(
                "Заметная разница в темпе. Проверьте по подсветке выше, где в этом "
                "фрагменте есть мадд — возможно, там вы недотягиваете или тянете дольше."
            )
        else:
            st.success("Темп чтения близок к эталонному.")

        if ayah_text:
            with st.spinner("Ищу места расхождения со звуком эталона..."):
                flagged = find_mismatch_words(ayah_text, ref_audio, user_bytes)
            st.markdown("**🔴 Слова с наибольшим акустическим расхождением:**")
            html, _ = render_tajweed_html(ayah_text, flagged_words=flagged)
            arabic_block(html)
            if flagged:
                st.warning(
                    "Слова с красной подчёркой звучали заметно иначе, чем в эталоне "
                    "в это же время записи. Это **не подтверждённая ошибка** — просто "
                    "сигнал 'вслушайтесь сюда ещё раз'. Причиной может быть неверное "
                    "слово, запинка, пауза длиннее обычной или просто шум записи."
                )
            else:
                st.caption("Явных мест сильного расхождения не найдено.")

        st.caption(
            "Напоминание: цифры отражают акустическое сходство целиком, а не "
            "формальную проверку правил таджвида по отдельности."
        )


def comparison_block(sura: int, ayat: int):
    """Сравнение для одного аята."""
    ref_audio = get_husary_audio(sura, ayat)
    ayah_text = get_ayah_text(sura, ayat)
    comparison_ui(ref_audio, key=f"{sura}_{ayat}", label=f"Аят {sura}:{ayat}", ayah_text=ayah_text)


def comparison_block_multi(ayah_list: list[dict], label: str):
    """Сравнение для нескольких аятов подряд (диапазон или целая страница)."""
    refs = tuple((a["sura"], a["ayat"]) for a in ayah_list)
    ref_audio = combine_ayah_audio(refs)
    key = "_".join(f"{s}-{a}" for s, a in refs)
    combined_text = " ".join(a["text"] for a in ayah_list)
    comparison_ui(ref_audio, key=key, label=label, ayah_text=combined_text)


# ---------------------------------------------------------------------------
# Интерфейс
# ---------------------------------------------------------------------------

mode = st.radio("Режим чтения:", ["По аяту", "По странице мусхафа"], horizontal=True)
show_tajweed = st.toggle("🎨 Подсветка правил таджвида", value=True)

if mode == "По аяту":
    col1, col2 = st.columns(2)
    with col1:
        sura = st.number_input("Номер суры", min_value=1, max_value=114, value=1, step=1)
    with col2:
        ayat = st.number_input("Номер аята", min_value=1, max_value=286, value=1, step=1)

    st.markdown("### 📜 Текст аята")
    ayah_text = get_ayah_text(int(sura), int(ayat))
    if ayah_text:
        if show_tajweed:
            html, found = render_tajweed_html(ayah_text)
            arabic_block(html)
            show_legend(found)
        else:
            arabic_block(ayah_text)
    else:
        st.warning("Не удалось загрузить текст аята.")

    st.markdown("---")
    comparison_block(int(sura), int(ayat))

else:
    page = st.number_input("Номер страницы мусхафа (1–604)", min_value=1, max_value=604, value=1, step=1)

    ayahs = get_page_ayahs(int(page))
    st.markdown(f"### 📜 Страница {int(page)}")

    if ayahs:
        for a in ayahs:
            if show_tajweed:
                html, _ = render_tajweed_html(a["text"])
                arabic_block(html)
            else:
                arabic_block(a["text"])
        st.caption(f"На странице: {ayahs[0]['sura_name']} — всего аятов: {len(ayahs)}")

        st.markdown("---")
        st.markdown("**Как будете записывать чтение?**")
        record_mode = st.radio(
            "Способ записи:",
            ["Один аят", "Диапазон аятов", "Вся страница"],
            horizontal=True,
            key=f"recmode_{page}",
        )

        options = [f"{a['sura']}:{a['ayat']} — {a['sura_name']}" for a in ayahs]

        if record_mode == "Один аят":
            choice = st.selectbox("Аят для записи", options)
            idx = options.index(choice)
            chosen = ayahs[idx]
            st.markdown("---")
            comparison_block(chosen["sura"], chosen["ayat"])

        elif record_mode == "Диапазон аятов":
            c1, c2 = st.columns(2)
            with c1:
                start_choice = st.selectbox("С аята", options, index=0)
            with c2:
                end_choice = st.selectbox("По аят", options, index=len(options) - 1)
            start_idx = options.index(start_choice)
            end_idx = options.index(end_choice)
            if start_idx > end_idx:
                st.warning("Начальный аят должен быть раньше конечного.")
            else:
                selected = ayahs[start_idx:end_idx + 1]
                st.caption(f"Выбрано аятов: {len(selected)}")
                st.markdown("---")
                comparison_block_multi(selected, label=f"{start_choice} — {end_choice}")

        else:  # Вся страница
            st.caption(f"Будет записана и сравнена вся страница целиком ({len(ayahs)} аятов).")
            st.markdown("---")
            comparison_block_multi(ayahs, label=f"Страница {int(page)}")
    else:
        st.warning("Не удалось загрузить эту страницу. Проверьте номер (1–604).")
