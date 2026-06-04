import os
import logging
import requests
import threading
import base64
from flask import Flask, request
from groq import Groq
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SPACE_HOST = "durva-doubtsolver.onrender.com"
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
ALLOWED_GROUP_ID = -1003946747894
BOT_USERNAME = "durva_doubtsolver_bot"

client = Groq(api_key=GROQ_API_KEY)
logging.info("Groq client ready!")

app = Flask(__name__)

SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai.
- Sirf tab reply kar jab tujhe directly mention kiya jaye (@bot_name) ya koi image bheje
- Agar student ne Hindi mein pucha toh Hindi mein jawab de, agar English mein pucha toh English mein jawab de, agar Hinglish mein pucha tho Hinglish mein jawab do
- Scientific terms, formulas aur technical words hamesha English mein hi likhe — kabhi Hindi mein mat translate karna (jaise Photosynthesis ko "Prakash Sansleshan" mat bolna)
- JEE aur NEET level ke questions solve kar — Physics, Chemistry, Biology, Mathematics
- Step by step explain kar
- Formulas clearly likhe
- Short aur clear jawab de"""

def send_message(chat_id, text):
    for attempt in range(3):
        try:
            url = f"{TELEGRAM_API}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
            return
        except Exception as e:
            logging.warning(f"Send attempt {attempt+1} failed: {e}")

def process_message(chat_id, text):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            model="llama-3.3-70b-versatile",
        )
        reply = chat_completion.choices[0].message.content
        send_message(chat_id, reply)
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        send_message(chat_id, f"Error: {str(e)[:100]}")

def process_image(chat_id, file_id, caption):
    try:
        # Image file path lo
        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

        # Image download karo
        img_response = requests.get(file_url, timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")

        prompt = caption if caption else "Is image mein jo question hai usse solve karo"

        # Groq vision use karo
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]
                }
            ],
            model="meta-llama/llama-4-scout-17b-16e-instruct",
        )
        reply = chat_completion.choices[0].message.content
        send_message(chat_id, reply)
    except Exception as e:
        logging.error(f"Image Error: {e}")
        send_message(chat_id, "Image solve nahi ho paya, text mein likho!")

def set_webhook():
    try:
        webhook_url = f"https://{SPACE_HOST}/webhook"
        url = f"{TELEGRAM_API}/setWebhook?url={webhook_url}"
        r = requests.get(url, timeout=30)
        logging.info(f"Webhook set: {r.json()}")
    except Exception as e:
        logging.warning(f"Webhook set nahi hua: {e}")

def get_bot_username():
    global BOT_USERNAME
    try:
        r = requests.get(f"{TELEGRAM_API}/getMe", timeout=10).json()
        BOT_USERNAME = r["result"]["username"]
        logging.info(f"Bot username: {BOT_USERNAME}")
    except Exception as e:
        logging.warning(f"Username fetch error: {e}")

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if "message" not in data:
            return "ok", 200

        message = data["message"]
        chat_id = message["chat"]["id"]

        # Sirf allowed group
        if chat_id != ALLOWED_GROUP_ID:
            return "ok", 200

        text = message.get("text", "")
        caption = message.get("caption", "")
        photo = message.get("photo", None)

        # Image bheja — solve karo
        if photo:
            mention_in_caption = f"@{BOT_USERNAME}" in caption
            if mention_in_caption or not caption:
                clean_caption = caption.replace(f"@{BOT_USERNAME}", "").strip()
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, clean_caption)).start()
            return "ok", 200

        # Text message — sirf mention pe reply karo
        if f"@{BOT_USERNAME}" in text:
            clean_text = text.replace(f"@{BOT_USERNAME}", "").strip()
            if clean_text:
                threading.Thread(target=process_message, args=(chat_id, clean_text)).start()

    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    get_bot_username()
    set_webhook()
    logging.info("Bot start ho gaya!")
    app.run(host="0.0.0.0", port=8080)
