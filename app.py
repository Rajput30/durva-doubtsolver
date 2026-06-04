import os
import logging
import requests
import threading
import base64
import re
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
BOT_USERNAME = "Durva_mentor_bot"

client = Groq(api_key=GROQ_API_KEY)
logging.info("Groq client ready!")

app = Flask(__name__)

SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai jo 12th ke students ki help karta hai.

LANGUAGE RULES:
- Agar student ne kaha "hinglish mein samjao" ya "hindi mein" — toh Hinglish mein jawab de
- Agar student ne kaha "explain in english" — toh English mein jawab de
- Agar student ne kuch nahi kaha — toh question ki language dekh ke jawab de
- Scientific terms hamesha English mein rakho
- Hinglish matlab: Hindi + English mix — jaise "Pehle hum moles calculate karenge"

LENGTH RULES:
- Maximum 8-10 steps, har step 1-2 lines ka
- Seedha point pe aao, bakwaas mat likho
- Short aur clear rakho

FORMATTING RULES — YE BILKUL MAT USE KARNA:
- Koi ## headers nahi
- Koi $ signs nahi
- Koi \\frac \\theta \\sin \\cos \\tan \\boxed nahi
- Koi * ** _ nahi
- Koi LaTeX nahi, koi Markdown nahi

FORMATTING — HAMESHA AISA LIKHO:
- Powers: x², H₂O, CO₂
- Fractions: (108/144) ya 108÷144
- Multiplication: ×
- Greek letters: θ α β π Δ ω λ μ
- Trig: sin(θ), cos(θ), tan(θ), tan⁻¹
- Steps: 1. 2. 3.

ACCURACY:
- Pehle soch ke solve karo
- Formula likho, values daalo, calculate karo
- Final answer clearly likho: "Answer: 0.75" """

def clean_response(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
    text = re.sub(r'\$.*?\$', '', text)
    text = re.sub(r'\\frac\{(.*?)\}\{(.*?)\}', r'(\1/\2)', text)
    text = re.sub(r'\\boxed\{(.*?)\}', r'Answer: \1', text)
    text = re.sub(r'\\left\(', '(', text)
    text = re.sub(r'\\right\)', ')', text)
    text = re.sub(r'\\tan\^?\{?-1\}?', 'tan⁻¹', text)
    text = re.sub(r'\\tan', 'tan', text)
    text = re.sub(r'\\sin', 'sin', text)
    text = re.sub(r'\\cos', 'cos', text)
    text = re.sub(r'\\theta', 'θ', text)
    text = re.sub(r'\\alpha', 'α', text)
    text = re.sub(r'\\beta', 'β', text)
    text = re.sub(r'\\pi', 'π', text)
    text = re.sub(r'\\Delta', 'Δ', text)
    text = re.sub(r'\\omega', 'ω', text)
    text = re.sub(r'\\lambda', 'λ', text)
    text = re.sub(r'\\mu', 'μ', text)
    text = re.sub(r'\\sigma', 'σ', text)
    text = re.sub(r'\\infty', '∞', text)
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\sqrt\{(.*?)\}', r'√(\1)', text)
    text = re.sub(r'\^\{(.*?)\}', r'^\1', text)
    text = re.sub(r'#{1,6}\s', '', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def send_message(chat_id, text):
    for attempt in range(3):
        try:
            url = f"{TELEGRAM_API}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
            return
        except Exception as e:
            logging.warning(f"Send attempt {attempt+1} failed: {e}")

def get_replied_message_text(message):
    replied = message.get("reply_to_message", None)
    if replied:
        return replied.get("text", "") or replied.get("caption", "")
    return ""

def process_message(chat_id, text):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            model="llama-3.3-70b-versatile",
        )
        reply = clean_response(chat_completion.choices[0].message.content)
        send_message(chat_id, reply)
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        send_message(chat_id, f"Error: {str(e)[:100]}")

def process_image(chat_id, file_id, instruction):
    try:
        logging.info(f"Image processing start — instruction: {instruction}")
        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        img_response = requests.get(file_url, timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")

        if instruction:
            prompt = f"Is image mein jo question hai usse solve karo. Student ki instruction: {instruction}"
        else:
            prompt = "Is image mein jo question hai usse step by step solve karo"

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
        reply = clean_response(chat_completion.choices[0].message.content)
        logging.info("Image processed successfully!")
        send_message(chat_id, reply)
    except Exception as e:
        logging.error(f"Image Error: {e}")
        send_message(chat_id, "Image solve nahi ho paya, dobara try karo!")

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

        if chat_id != ALLOWED_GROUP_ID:
            return "ok", 200

        text = message.get("text", "")
        caption = message.get("caption", "")
        photo = message.get("photo", None)
        bot_tag = f"@{BOT_USERNAME}"

        # Image wala case
        if photo:
            logging.info(f"Photo received — caption: {caption}")
            if bot_tag.lower() in caption.lower():
                instruction = re.sub(re.escape(bot_tag), '', caption, flags=re.IGNORECASE).strip()
                logging.info(f"Bot tagged in image — instruction: {instruction}")
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, instruction)).start()
            else:
                logging.info("Photo received but bot not tagged — ignoring")
            return "ok", 200

        # Text wala case
        if bot_tag.lower() in text.lower():
            clean_text = re.sub(re.escape(bot_tag), '', text, flags=re.IGNORECASE).strip()
            simple_commands = ["solve", "karo", "help", "explain", "batao", "solve karo"]
            if not clean_text or clean_text.lower() in simple_commands:
                replied_text = get_replied_message_text(message)
                if replied_text:
                    instruction = clean_text if clean_text else ""
                    clean_text = f"{replied_text}\nInstruction: {instruction}".strip() if instruction else replied_text
                else:
                    send_message(chat_id, "Bhai koi question toh likho ya kisi question pe reply karke @Durva_mentor_bot solve karo!")
                    return "ok", 200
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
