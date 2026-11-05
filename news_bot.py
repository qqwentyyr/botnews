"""
Бот новостей по золоту и биткоину -> Telegram.
Бесплатная версия: ИИ от Google (Gemini), запуск через GitHub Actions.
Один запуск проверяет новости и завершается.
"""
import json
import os
import time

import feedparser
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Если Google поменяет название модели, замените здесь
# (или задайте секрет GEMINI_MODEL в GitHub).
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-lite-latest"

SEEN_FILE = "seen.json"
MAX_ANALYZE_PER_RUN = 12   # не больше стольких новостей за запуск (лимиты бесплатного плана)
MAX_MESSAGES_PER_RUN = 6   # защита от лавины сообщений
PAUSE_SECONDS = 6          # пауза между запросами к ИИ

KEYWORDS = [
    "bitcoin", "btc", "gold", "bullion", "fed ", "federal reserve", "inflation",
    "etf", "treasury", "rate cut", "rate hike", "tariff", "dollar", "sec ",
    "crypto", "central bank",
]

FEEDS = [
    # Биткоин
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://bitcoinmagazine.com/.rss/full/",
    # Золото и биткоин (Reuters и Bloomberg через Google News)
    "https://news.google.com/rss/search?q=gold+price+site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=gold+site:bloomberg.com&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=bitcoin+site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "https://www.kitco.com/rss/KitcoNews.xml",
]

PROMPT = """Ты помощник по новостям о золоте и биткоине. Тебе дана новость.

Реши, важна ли она. Важно: решения ФРС и ЦБ, инфляция и данные по экономике США,
крупные движения цены, ETF, законы и регулирование, крупные покупки/продажи,
геополитика, влияющая на золото или биткоин. Не важно: мелкие мнения, реклама,
обзоры "что такое биткоин", новости про мелкие альткоины.

Если новость не про золото и не про биткоин, или не важна, верни {"important": false}.

Если важна, верни JSON:
{
  "important": true,
  "asset": "gold" или "bitcoin" или "both",
  "title_ru": "заголовок на русском",
  "text_ru": "перевод сути новости на русском, 2-4 предложения",
  "simple": "что происходит, максимально простыми словами, 2-3 предложения, как для человека, который не разбирается в финансах",
  "direction": "up" или "down" или "sideways",
  "direction_reason": "почему скорее всего такое движение, 1-2 предложения",
  "confidence": "low" или "medium" или "high"
}

Прогноз основывай только на этой новости и общей логике рынка. Не выдумывай цифры.
Верни только JSON, без пояснений и без markdown."""

ARROWS = {"up": "📈 Скорее ВВЕРХ", "down": "📉 Скорее ВНИЗ", "sideways": "➡️ Скорее БОКОВИК (без явного движения)"}
CONF = {"low": "низкая", "medium": "средняя", "high": "высокая"}
ICONS = {"gold": "🥇 Золото", "bitcoin": "₿ Биткоин", "both": "🥇₿ Золото и биткоин"}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_seen(seen_list):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_list[-3000:], f)


def analyze(title, summary):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Заголовок: {title}\n\nТекст: {summary}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
    }
    for attempt in range(3):
        r = requests.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=60)
        if r.status_code == 429:  # слишком часто, ждём и пробуем снова
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    raise RuntimeError("Превышен лимит запросов Gemini")


def send_telegram(data, link, source):
    msg = (
        f"{ICONS.get(data['asset'], '')}\n"
        f"<b>{data['title_ru']}</b>\n\n"
        f"{data['text_ru']}\n\n"
        f"🔗 <a href=\"{link}\">Оригинал ({source})</a>\n\n"
        f"💡 <b>Простыми словами:</b>\n{data['simple']}\n\n"
        f"{ARROWS.get(data['direction'], '')}\n"
        f"{data['direction_reason']}\n"
        f"Уверенность: {CONF.get(data['confidence'], 'низкая')}\n\n"
        f"<i>Это предположение, а не гарантия и не финансовый совет.</i>"
    )
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen_list = load_seen()
    seen = set(seen_list)
    analyzed = 0
    sent = 0

    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print("Ошибка ленты", url, e)
            continue
        source = feed.feed.get("title", "источник")
        for entry in feed.entries[:15]:
            uid = entry.get("id") or entry.get("link")
            if not uid or uid in seen:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")[:2000]

            if first_run:  # первый запуск: только запоминаем старые новости
                seen.add(uid)
                seen_list.append(uid)
                continue

            text_low = (title + " " + summary).lower()
            if not any(k in text_low for k in KEYWORDS):
                seen.add(uid)
                seen_list.append(uid)
                continue

            if analyzed >= MAX_ANALYZE_PER_RUN or sent >= MAX_MESSAGES_PER_RUN:
                continue  # не отмечаем как прочитанную: обработаем в следующий раз

            seen.add(uid)
            seen_list.append(uid)
            analyzed += 1
            try:
                data = analyze(title, summary)
                if data.get("important"):
                    send_telegram(data, entry.get("link", ""), source)
                    sent += 1
            except Exception as e:
                print("Ошибка обработки:", e)
            time.sleep(PAUSE_SECONDS)

    save_seen(seen_list)
    print("Готово. Проанализировано:", analyzed, "Отправлено:", sent)


if __name__ == "__main__":
    main()
