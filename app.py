import os
import re
import urllib.parse
from urllib.parse import urlparse, parse_qs

import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI

# -----------------------------
# Helpers
# -----------------------------
def extract_video_id(url: str) -> str:
    """
    Desteklenen formatlar:
      - https://www.youtube.com/watch?v=VIDEOID
      - https://youtu.be/VIDEOID
      - https://www.youtube.com/shorts/VIDEOID
    """
    url = url.strip()

    # Direkt ID verilmiş olabilir (11 char)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    u = urlparse(url)

    # youtu.be/VIDEOID
    if u.netloc in {"youtu.be", "www.youtu.be"}:
        vid = u.path.strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
            return vid

    # youtube.com/watch?v=VIDEOID
    if u.path == "/watch":
        qs = parse_qs(u.query)
        vid = (qs.get("v") or [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
            return vid

    # youtube.com/shorts/VIDEOID
    m = re.search(r"/shorts/([A-Za-z0-9_-]{11})", u.path)
    if m:
        return m.group(1)

    raise ValueError("Video ID çıkarılamadı. Link formatını kontrol et.")


def fetch_transcript_text(video_id: str, languages=("tr", "tr-TR", "en")) -> str:
    ytt_api = YouTubeTranscriptApi()
    fetched = ytt_api.fetch(video_id, languages=list(languages))
    # senin yaklaşımınla aynı: snippet textleri birleştir
    return " ".join(s.text.strip() for s in fetched.snippets if s.text).strip()


def x_intent_url(tweet_text: str) -> str:
    """
    X (Twitter) compose ekranını açar ve metni doldurur.
    """
    encoded = urllib.parse.quote(tweet_text)
    return f"https://twitter.com/intent/tweet?text={encoded}"


def generate_3_tweets(transcript: str, model: str) -> list[str]:
    """
    Transcript çok uzun olabilir; MVP için kaba bir limit uyguluyoruz.
    (İstersen sonraki iterasyonda chunk+map-reduce yaparız.)
    """

    client = OpenAI()

    prompt = f"""
Aşağıdaki YouTube transkriptinden videonun en önemli 3 konusunu çıkar.
Her konu için Türkçe tek bir tweet yaz.

Kurallar:
- Tam olarak 3 tweet döndür.
- Her tweet tek paragraf olsun.
- Konular birbirinden farklı olsun.
- Tweetlerde gereksiz emoji/hashtag kullanma.
- Fazla genel konuşma: somut, videodaki ana iddiaları/başlıkları yakala.
- Tweetleri bir haber kanalı üslubuyla oluştur.
- Çıktıyı JSON olarak döndür: {{"tweets":["...","...","..."]}}

TRANSKRIPT:
{transcript}
""".strip()

    resp = client.responses.create(
        model=model,
        input=prompt,
    )

    # Responses API’nin "output_text" alanı düz metni verir.
    # Biz JSON istediğimiz için burada basit bir JSON parse deniyoruz.
    text = resp.output_text.strip()
    # Güvenli parse: JSON dışı bir şey dönerse fallback
    import json
    try:
        obj = json.loads(text)
        tweets = obj.get("tweets", [])
    except Exception:
        tweets = []

    tweets = [t.strip() for t in tweets if isinstance(t, str) and t.strip()]
    return tweets[:3]


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="YouTube → 3 Tweet", layout="centered")

st.title("YouTube videosu → 3 tweet")
st.write("YouTube linkini gir, transkripti alıp videonun en önemli konularından 3 tweet üretelim.")

url = st.text_input("YouTube linki (veya video id)", placeholder="https://www.youtube.com/watch?v=...")

model = st.selectbox(
    "Model",
    options=["gpt-4.1-mini", "gpt-4.1", "gpt-5-mini", "gpt-5"],
    index=0,
)

if st.button("Tweet üret", type="primary"):
    if not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY env değişkeni yok. Önce ayarla.")
        st.stop()

    try:
        video_id = extract_video_id(url)
    except Exception as e:
        st.error(str(e))
        st.stop()

    with st.spinner("Transkript çekiliyor..."):
        try:
            transcript = fetch_transcript_text(video_id)
        except Exception as e:
            st.error(f"Transkript alınamadı: {e}")
            st.stop()

    st.subheader("Transkript (önizleme)")
    st.text_area(" ", transcript[:2000] + ("..." if len(transcript) > 2000 else ""), height=180)

    with st.spinner("Tweetler üretiliyor..."):
        tweets = generate_3_tweets(transcript, model=model)

    st.subheader("Tweetler")
    if len(tweets) < 3:
        st.warning("Model beklenen JSON formatında dönmedi veya içerik eksik. Tekrar deneyebilirsin.")
        st.code(tweets or "Boş çıktı", language="text")
    else:
        for i, t in enumerate(tweets, 1):
            col_text, col_btn = st.columns([0.88, 0.12], vertical_alignment="top")

            with col_text:
                st.markdown(f"**Tweet {i}**")
                st.write(t)

            with col_btn:
                st.markdown(
                    f"""
                    <a href="{x_intent_url(t)}" target="_blank"
                       style="text-decoration:none;font-size:26px;line-height:1;">
                        𝕏
                    </a>
                    """,
                    unsafe_allow_html=True,
                )

            st.divider()
