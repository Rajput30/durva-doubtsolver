import os
import logging
import requests
import threading
from flask import Flask, request
from groq import Groq
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SPACE_HOST = os.environ.get("RAILWAY_STATIC_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

client = Groq(api_key=GROQ_API_KEY)
logging.info("Groq client ready!")

app = Flask(__name__)

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
                {
                    "role": "system",
                    "content": "Tu ek helpful doubt solver bot hai. Bacchon ke doubts clear aur simple language mein solve kar."
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            model="llama-3.3-70b-versatile",
        )
        reply = chat_completion.choices[0].message.content
        send_message(chat_id, reply)
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        send_message(chat_id, f"Locha ho gaya bhai! Error: {str(e)[:100]}")

def set_webhook():
    try:
        webhook_url = f"https://{SPACE_HOST}/webhook"
        url = f"{TELEGRAM_API}/setWebhook?url={webhook_url}"
        r = requests.get(url, timeout=30)
        logging.info(f"Webhook set: {r.json()}")
    except Exception as e:
        logging.warning(f"Webhook set nahi hua: {e}")

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if "message" not in data:
            return "ok", 200
        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        if text == "/start":
            threading.Thread(target=send_message, args=(chat_id, "Hello Shlok bhai! Main hoon tumhara Durva Doubtsolver Bot. Apne doubts pucho, main solve kar dunga! 🚀")).start()
            return "ok", 200
        threading.Thread(target=process_message, args=(chat_id, text)).start()
    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    set_webhook()
    logging.info("Bot start ho gaya!")
    app.run(host="0.0.0.0", port=8080)
