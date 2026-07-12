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
    Ищет файл по нескольким вариантам имени (с пробелами/подчёркиваниями), а если
    не находит точное совпадение — берёт любой .ttf в этой же папке.
    Возвращает (css, диагностика)."""
    directory = os.path.dirname(os.path.abspath(__file__))
    try:
        files_here = os.listdir(directory)
    except OSError:
        files_here = []

    candidates = [
        "KFGQPC_Uthman_Taha_Naskh_Regular.ttf",
        "KFGQPC Uthman Taha Naskh Regular.ttf",
    ]
    font_path = None
    for name in candidates:
        p = os.path.join(directory, name)
        if os.path.exists(p):
            font_path = p
            break

    if font_path is None:
        # запасной вариант: любой .ttf файл в папке рядом с app.py
        ttf_files = [f for f in files_here if f.lower().endswith(".ttf")]
        if ttf_files:
            font_path = os.path.join(directory, ttf_files[0])

    if font_path is None:
        return "", (
            f"Файл шрифта (.ttf) не найден в папке `{directory}`. "
            f"Файлы, которые там реально есть: {files_here}. "
            f"Загрузите .ttf-файл шрифта в корень репозитория, рядом с app.py."
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


def arabic_block(html: str, font_size: int = 30):
    st.markdown(
        f'<div dir="rtl" style="font-size:{font_size}px; line-height:2.3; text-align:right; '
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
def get_surah_list() -> list[dict]:
    """Список всех 114 сур: номер, арабское имя, английское имя, число аятов."""
    url = "https://api.alquran.cloud/v1/surah"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()["data"]
    except (requests.RequestException, KeyError, ValueError):
        return []


@st.cache_data(show_spinner=False)
def get_surah_start_page(sura: int) -> int | None:
    """Номер страницы мусхафа, с которой начинается сура."""
    url = f"https://api.alquran.cloud/v1/ayah/{sura}:1/quran-uthmani"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()["data"].get("page")
    except (requests.RequestException, KeyError, ValueError):
        return None


@st.cache_data(show_spinner=False)
def get_juz_start_page(juz: int) -> int | None:
    """Номер страницы мусхафа, с которой начинается джуз (запрашивает только первый аят джуза)."""
    url = f"https://api.alquran.cloud/v1/juz/{juz}/quran-uthmani?offset=0&limit=1"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        ayahs = r.json()["data"]["ayahs"]
        return ayahs[0].get("page") if ayahs else None
    except (requests.RequestException, KeyError, ValueError, IndexError):
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


RUSSIAN_TRANSLATIONS = {
    "ru.kuliev": "Эльмир Кулиев",
    "ru.osmanov": "Магомед-Нури Османов",
    "ru.porokhova": "Валерия Порохова",
    "ru.abuadel": "Абу Адель",
    "ru.krachkovsky": "Игнатий Крачковский",
    "ru.muntahab": "Аль-Мунтахаб",
    "ru.sablukov": "Гордий Саблуков",
}


@st.cache_data(show_spinner=False)
def get_ayah_translation(sura: int, ayat: int, edition: str = "ru.kuliev") -> str | None:
    """Русский перевод. Если не загрузится — просто не покажем перевод."""
    url = f"https://api.alquran.cloud/v1/ayah/{sura}:{ayat}/{edition}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()["data"]["text"]
    except (requests.RequestException, KeyError, ValueError):
        return None


def _build_ayah_list(arabic_ayahs: list, translation_ayahs: list) -> list[dict]:
    result = []
    for i, a in enumerate(arabic_ayahs):
        t = translation_ayahs[i]["text"] if i < len(translation_ayahs) else None
        result.append({
            "text": a.get("text", ""),
            "translation": t,
            "sura": a.get("surah", {}).get("number"),
            "ayat": a.get("numberInSurah"),
            "sura_name": a.get("surah", {}).get("name", ""),
        })
    return result


@st.cache_data(show_spinner=False)
def get_page_ayahs(page: int, edition: str = "ru.kuliev") -> list[dict] | None:
    """Возвращает список аятов целой страницы мусхафа (1–604), с текстом и переводом.
    Если совместный запрос (арабский+перевод) не удался — пробует запасной вариант
    без перевода, вместо полного отказа."""
    url_multi = f"https://api.alquran.cloud/v1/page/{page}/editions/quran-uthmani,{edition}"
    try:
        r = requests.get(url_multi, timeout=25)
        r.raise_for_status()
        editions = r.json()["data"]
        arabic_ayahs = editions[0]["ayahs"]
        translation_ayahs = editions[1]["ayahs"] if len(editions) > 1 else []
        return _build_ayah_list(arabic_ayahs, translation_ayahs)
    except (requests.RequestException, KeyError, ValueError, TypeError, IndexError):
        pass

    url_arabic = f"https://api.alquran.cloud/v1/page/{page}/quran-uthmani"
    try:
        r = requests.get(url_arabic, timeout=25)
        r.raise_for_status()
        arabic_ayahs = r.json()["data"]["ayahs"]
        return _build_ayah_list(arabic_ayahs, [])
    except (requests.RequestException, KeyError, ValueError, TypeError, IndexError):
        return None


@st.cache_data(show_spinner=False)
def get_juz_ayahs(juz: int, edition: str = "ru.kuliev") -> list[dict] | None:
    """Возвращает список аятов целого джуза (1–30), с текстом и переводом.
    Джуз намного больше страницы (~200 аятов), поэтому даём больше времени на
    ответ и, если совместный запрос не удался, пробуем запасной вариант без перевода."""
    url_multi = f"https://api.alquran.cloud/v1/juz/{juz}/editions/quran-uthmani,{edition}"
    try:
        r = requests.get(url_multi, timeout=30)
        r.raise_for_status()
        editions = r.json()["data"]
        arabic_ayahs = editions[0]["ayahs"]
        translation_ayahs = editions[1]["ayahs"] if len(editions) > 1 else []
        return _build_ayah_list(arabic_ayahs, translation_ayahs)
    except (requests.RequestException, KeyError, ValueError, TypeError, IndexError):
        pass

    url_arabic = f"https://api.alquran.cloud/v1/juz/{juz}/quran-uthmani"
    try:
        r = requests.get(url_arabic, timeout=30)
        r.raise_for_status()
        arabic_ayahs = r.json()["data"]["ayahs"]
        return _build_ayah_list(arabic_ayahs, [])
    except (requests.RequestException, KeyError, ValueError, TypeError, IndexError):
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

SURAH_LIST = get_surah_list()
SURAH_AYAH_COUNTS = {s["number"]: s["numberOfAyahs"] for s in SURAH_LIST}


def next_ayah(sura: int, ayat: int) -> tuple[int, int]:
    max_ayat = SURAH_AYAH_COUNTS.get(sura, 286)
    if ayat < max_ayat:
        return sura, ayat + 1
    if sura < 114:
        return sura + 1, 1
    return sura, ayat


def prev_ayah(sura: int, ayat: int) -> tuple[int, int]:
    if ayat > 1:
        return sura, ayat - 1
    if sura > 1:
        prev_sura = sura - 1
        return prev_sura, SURAH_AYAH_COUNTS.get(prev_sura, 1)
    return sura, ayat


st.session_state.setdefault("cur_sura", 1)
st.session_state.setdefault("cur_ayat", 1)
st.session_state.setdefault("cur_page", 1)
st.session_state.setdefault("cur_juz", 1)
st.session_state.setdefault("reading_mode", "По аяту")

with st.expander("🔖 Быстрый переход (как закладка в книге)"):
    jc1, jc2 = st.columns(2)
    with jc1:
        st.markdown("**К суре:**")
        surah_options = [f"{s['number']}. {s['name']} — {s['englishName']}" for s in SURAH_LIST] or \
            [f"{n}" for n in range(1, 115)]
        surah_choice = st.selectbox("Выберите суру", surah_options, key="surah_jump_select")
        if st.button("Перейти к суре", use_container_width=True):
            sura_num = int(surah_choice.split(".")[0])
            target_page = get_surah_start_page(sura_num)
            if target_page:
                st.session_state["cur_page"] = target_page
                st.session_state["reading_mode"] = "По странице мусхафа"
                st.rerun()
            else:
                st.warning("Не удалось определить страницу этой суры.")
    with jc2:
        st.markdown("**К джузу:**")
        juz_choice = st.number_input("Номер джуза (1–30)", min_value=1, max_value=30, step=1, key="juz_jump_select")
        if st.button("Перейти к джузу", use_container_width=True):
            target_page = get_juz_start_page(int(juz_choice))
            if target_page:
                st.session_state["cur_page"] = target_page
                st.session_state["reading_mode"] = "По странице мусхафа"
                st.rerun()
            else:
                st.warning("Не удалось определить страницу этого джуза.")

mode = st.radio("Режим чтения:", ["По аяту", "По странице мусхафа", "По джузу"], horizontal=True, key="reading_mode")

col_a, col_b = st.columns(2)
with col_a:
    show_tajweed = st.toggle("🎨 Подсветка таджвида", value=True)
with col_b:
    show_translation = st.toggle("🇷🇺 Показывать перевод", value=True)

translation_edition = "ru.kuliev"
if show_translation:
    translation_name = st.selectbox("Переводчик", list(RUSSIAN_TRANSLATIONS.values()), index=0)
    translation_edition = next(
        code for code, name in RUSSIAN_TRANSLATIONS.items() if name == translation_name
    )

font_size = st.select_slider(
    "Размер арабского текста", options=[24, 28, 32, 36, 40, 44, 48], value=32
)


def render_ayah_with_translation(text: str, translation: str | None):
    if show_tajweed:
        html, found = render_tajweed_html(text)
        arabic_block(html, font_size=font_size)
        show_legend(found)
    else:
        arabic_block(text, font_size=font_size)
    if show_translation and translation:
        st.caption(translation)


def multi_ayah_section(ayahs: list[dict], unit_key: str):
    """Общий блок для страницы/джуза: показ текста + выбор способа записи."""
    if show_translation and not any(a.get("translation") for a in ayahs):
        st.caption("ℹ️ Перевод для этого фрагмента сейчас не загрузился — показан только арабский текст.")
    for a in ayahs:
        render_ayah_with_translation(a["text"], a.get("translation"))
    st.caption(f"Сур на этом фрагменте: {ayahs[0]['sura_name']} и др. — всего аятов: {len(ayahs)}")

    st.markdown("---")
    st.markdown("**Как будете записывать чтение?**")
    record_mode = st.radio(
        "Способ записи:",
        ["Один аят", "Диапазон аятов", "Всё целиком"],
        horizontal=True,
        key=f"recmode_{unit_key}",
    )

    options = [f"{a['sura']}:{a['ayat']} — {a['sura_name']}" for a in ayahs]

    if record_mode == "Один аят":
        choice = st.selectbox("Аят для записи", options, key=f"sel_{unit_key}")
        idx = options.index(choice)
        chosen = ayahs[idx]
        st.markdown("---")
        comparison_block(chosen["sura"], chosen["ayat"])

    elif record_mode == "Диапазон аятов":
        c1, c2 = st.columns(2)
        with c1:
            start_choice = st.selectbox("С аята", options, index=0, key=f"start_{unit_key}")
        with c2:
            end_choice = st.selectbox("По аят", options, index=len(options) - 1, key=f"end_{unit_key}")
        start_idx = options.index(start_choice)
        end_idx = options.index(end_choice)
        if start_idx > end_idx:
            st.warning("Начальный аят должен быть раньше конечного.")
        else:
            selected = ayahs[start_idx:end_idx + 1]
            st.caption(f"Выбрано аятов: {len(selected)}")
            st.markdown("---")
            comparison_block_multi(selected, label=f"{start_choice} — {end_choice}")

    else:  # Всё целиком
        st.caption(f"Будет записан и сравнён весь фрагмент целиком ({len(ayahs)} аятов).")
        st.markdown("---")
        comparison_block_multi(ayahs, label=unit_key)


if mode == "По аяту":
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("◀ Пред. аят", use_container_width=True):
            st.session_state["cur_sura"], st.session_state["cur_ayat"] = prev_ayah(
                st.session_state["cur_sura"], st.session_state["cur_ayat"]
            )
    with nav3:
        if st.button("След. аят ▶", use_container_width=True):
            st.session_state["cur_sura"], st.session_state["cur_ayat"] = next_ayah(
                st.session_state["cur_sura"], st.session_state["cur_ayat"]
            )

    col1, col2 = st.columns(2)
    with col1:
        sura = st.number_input("Номер суры", min_value=1, max_value=114, step=1, key="cur_sura")
    with col2:
        ayat = st.number_input("Номер аята", min_value=1, max_value=286, step=1, key="cur_ayat")

    st.markdown("### 📜 Текст аята")
    ayah_text = get_ayah_text(int(sura), int(ayat))
    translation = get_ayah_translation(int(sura), int(ayat), translation_edition) if show_translation else None
    if ayah_text:
        render_ayah_with_translation(ayah_text, translation)
    else:
        st.warning("Не удалось загрузить текст аята.")

    st.markdown("---")
    comparison_block(int(sura), int(ayat))

elif mode == "По странице мусхафа":
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("◀ Пред. страница", use_container_width=True):
            st.session_state["cur_page"] = max(1, st.session_state["cur_page"] - 1)
    with nav3:
        if st.button("След. страница ▶", use_container_width=True):
            st.session_state["cur_page"] = min(604, st.session_state["cur_page"] + 1)

    page = st.number_input("Номер страницы мусхафа (1–604)", min_value=1, max_value=604, step=1, key="cur_page")
    ayahs = get_page_ayahs(int(page), translation_edition)
    st.markdown(f"### 📜 Страница {int(page)}")

    if ayahs:
        multi_ayah_section(ayahs, unit_key=f"page{int(page)}")
    else:
        st.warning("Не удалось загрузить эту страницу. Проверьте номер (1–604).")

else:  # По джузу
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("◀ Пред. джуз", use_container_width=True):
            st.session_state["cur_juz"] = max(1, st.session_state["cur_juz"] - 1)
    with nav3:
        if st.button("След. джуз ▶", use_container_width=True):
            st.session_state["cur_juz"] = min(30, st.session_state["cur_juz"] + 1)

    juz = st.number_input("Номер джуза (1–30)", min_value=1, max_value=30, step=1, key="cur_juz")
    ayahs = get_juz_ayahs(int(juz), translation_edition)
    st.markdown(f"### 📜 Джуз {int(juz)}")

    if ayahs:
        st.caption(
            f"В этом джузе {len(ayahs)} аятов — для ежедневной нормы в 1 джуз в день "
            f"Коран прочитывается за 30 дней."
        )
        multi_ayah_section(ayahs, unit_key=f"juz{int(juz)}")
    else:
        st.warning("Не удалось загрузить этот джуз. Проверьте номер (1–30).")

