import streamlit as st
import librosa
import numpy as np
import requests
import io

st.set_page_config(page_title="Тренажёр чтения Корана", page_icon="📖", layout="centered")

st.title("📖 Личный тренажёр чтения Корана")
st.caption("Эталон: шейх Махмуд Халиль аль-Хусари")

st.info(
    "⚠️ **Важно понимать, что именно измеряет этот инструмент.** "
    "Он сравнивает темп, ритм и общий звуковой рисунок вашего чтения с эталонным. "
    "Он **не проверяет** конкретные правила таджвида (гунна, ихфа, идгам, точная "
    "длительность мадда) — для этого нужен отдельный слух устаза. "
    "Используйте это как помощь для самоконтроля темпа и общего звучания, "
    "а не как замену занятиям с учителем."
)


@st.cache_data(show_spinner=False)
def get_husary_audio(sura: int, ayat: int) -> bytes | None:
    """Скачивает аудио аята в исполнении аль-Хусари с базы EveryAyah."""
    sura_str = str(sura).zfill(3)
    ayat_str = str(ayat).zfill(3)
    url = f"https://everyayah.com/data/Husary_Muallim_128kbps/{sura_str}{ayat_str}.mp3"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.content
    except requests.RequestException:
        return None


def analyze(ref_bytes: bytes, user_bytes: bytes) -> dict:
    """Сравнивает эталонную и пользовательскую запись по темпу и звуковому рисунку."""
    y_ref, sr_ref = librosa.load(io.BytesIO(ref_bytes), sr=None)
    y_user, sr_user = librosa.load(io.BytesIO(user_bytes), sr=None)

    # Хромаграммы — для общего звукового/мелодического рисунка
    chroma_ref = librosa.feature.chroma_stft(y=y_ref, sr=sr_ref)
    chroma_user = librosa.feature.chroma_stft(y=y_user, sr=sr_user)
    D_chroma, wp_chroma = librosa.sequence.dtw(X=chroma_user, Y=chroma_ref, subseq=True)
    chroma_cost = D_chroma[-1, -1] / len(wp_chroma)
    chroma_similarity = max(0.0, min(100.0, 100 - chroma_cost * 10))

    # MFCC — ближе к тембру и артикуляции звука, чем чистая мелодия
    mfcc_ref = librosa.feature.mfcc(y=y_ref, sr=sr_ref, n_mfcc=13)
    mfcc_user = librosa.feature.mfcc(y=y_user, sr=sr_user, n_mfcc=13)
    D_mfcc, wp_mfcc = librosa.sequence.dtw(X=mfcc_user, Y=mfcc_ref, subseq=True)
    mfcc_cost = D_mfcc[-1, -1] / len(wp_mfcc)
    mfcc_similarity = max(0.0, min(100.0, 100 - mfcc_cost * 2))

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

ref_audio = get_husary_audio(int(sura), int(ayat))

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
        result = analyze(ref_audio, user_bytes)

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
            "Заметная разница в темпе с эталоном. Возможно, вы тянете мадд дольше/короче "
            "положенного, либо торопитесь/затягиваете общий темп чтения."
        )
    else:
        st.success("Темп чтения близок к эталонному.")

    st.caption(
        "Напоминание: показатели отражают акустическое сходство, а не формальную "
        "проверку правил таджвида. Для точной проверки макариджа и конкретных "
        "правил лучше свериться с учителем."
    )
