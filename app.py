import streamlit as st
import librosa
import numpy as np
import requests
import io
import re

st.set_page_config(page_title="Тренажёр чтения Корана", page_icon="📖", layout="centered")

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


def render_tajweed_html(ayah_text: str) -> tuple[str, dict]:
    """Строит HTML с подсветкой + собирает статистику встреченных правил."""
    found = {}
    words_html = []
    for word in ayah_text.split(" "):
        spans = analyze_word_tajweed(word)
        if not spans:
            words_html.append(word)
            continue
        # берём самый "сильный" тег на каждый символ (простая приоритизация)
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
        words_html.append("".join(html_parts))

    html = " ".join(words_html)
    return html, found


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
    """Получает арабский текст аята (Uthmani script) через alquran.cloud API."""
    url = f"https://api.alquran.cloud/v1/ayah/{sura}:{ayat}/quran-uthmani"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data["data"]["text"]
    except (requests.RequestException, KeyError):
        return None


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


col1, col2 = st.columns(2)
with col1:
    sura = st.number_input("Номер суры", min_value=1, max_value=114, value=1, step=1)
with col2:
    ayat = st.number_input("Номер аята", min_value=1, max_value=286, value=1, step=1)

ayah_text = get_ayah_text(int(sura), int(ayat))
ref_audio = get_husary_audio(int(sura), int(ayat))

st.markdown("### 📜 Текст аята")
if ayah_text:
    html, found_rules = render_tajweed_html(ayah_text)
    st.markdown(
        f'<div dir="rtl" style="font-size:32px; line-height:2.2; text-align:right; '
        f'font-family: \'Traditional Arabic\', \'Amiri\', serif;">{html}</div>',
        unsafe_allow_html=True,
    )
    if found_rules:
        legend_bits = []
        for rule, count in found_rules.items():
            color, name = TAJWEED_COLORS[rule]
            legend_bits.append(
                f'<span style="color:{color}">●</span> {name} ({count})'
            )
        st.caption(" &nbsp;&nbsp; ".join(legend_bits), unsafe_allow_html=True)
    else:
        st.caption("В этом аяте не обнаружено выделяемых правил (или все — изхар).")
else:
    st.warning("Не удалось загрузить текст аята.")

if ref_audio:
    st.markdown("**🎧 Эталонное чтение (Аль-Хусари):**")
    st.audio(ref_audio, format="audio/mp3")
else:
    st.error("Не удалось загрузить эталонное аудио. Проверьте номер суры/аята.")

st.markdown("---")
st.markdown("**🎙 Запишите ваше чтение:**")
user_audio = st.audio_input("Нажмите, чтобы начать запись")

if st.button("🔥 Сравнить с эталоном", type="primary", disabled=not (ref_audio and user_audio)):
    with st.spinner("Анализирую..."):
        user_bytes = user_audio.read()
        result = analyze_audio(ref_audio, user_bytes)

    st.subheader(f"📊 Результаты (Аят {int(sura)}:{int(ayat)})")

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
            "Заметная разница в общем темпе с эталоном. Проверьте по подсвеченному "
            "выше тексту, где в этом аяте есть мадд — возможно, там вы либо "
            "недотягиваете, либо тянете дольше положенного."
        )
    else:
        st.success("Общий темп чтения близок к эталонному.")

    st.caption(
        "Напоминание: цифры отражают акустическое сходство целиком, а не "
        "пословную проверку. Подсветка текста выше показывает, ГДЕ по правилам "
        "должны быть мадд/ихфа/идгам и т.д. — сверяйтесь на слух с эталоном "
        "именно в этих местах."
    )
