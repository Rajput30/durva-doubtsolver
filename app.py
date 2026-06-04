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

SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai.

FORMATTING — YE BILKUL MAT USE KARNA:
- Koi ## headers nahi
- Koi $ signs nahi
- Koi \\frac, \\theta, \\sin, \\cos, \\tan, \\boxed, \\left, \\right nahi
- Koi * ** _ ` ~ nahi
- Koi LaTeX nahi, koi Markdown nahi

FORMATTING — HAMESHA AISA LIKHO:
- Powers: x², x³, H₂O, CO₂ (unicode superscript)
- Fractions: (qE/mg) ya qE÷mg
- Multiplication: ×
- Theta: θ, Alpha: α, Beta: β, Pi: π, Delta: Δ
- Sin: sin(θ), Cos: cos(θ), Tan: tan(θ)
- Inverse tan: tan⁻¹(qE/mg)
- Steps: 1. 2. 3. numbered karo
- Plain simple text jo mobile pe clearly padha ja sake

CONTENT RULES:
- Sirf tab reply kar jab mention kiya jaye ya image aaye
- Hindi mein pucha toh Hindi, English mein pucha toh English
- Scientific terms hamesha English mein
- JEE aur NEET level — Physics, Chemistry, Biology, Math
- Step by step solve karo
- Har step mein formula likho, phir values daalo
- Final answer clearly likho
- Calculation double check karo"""

def clean_response(text):
    # LaTeX remove karo
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
    text = re.sub(r'\$.*?\$', '', text)
    text = re.sub(r'\\frac\{(.*?)\}\{(.*?)\}', r'(\1/\2)', text)
    text = re.sub(r'\\boxed\{(.*?)\}', r'\1', text)
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
    text = re.sub(r'\\delta', 'δ', text)
    text = re.sub(r'\\omega', 'ω', text)
    text = re.sub(r'\\lambda', 'λ', text)
    text = re.sub(r'\\mu', 'μ', text)
    text = re.sub(r'\\sigma', 'σ', text)
    text = re.sub(r'\\infty', '∞', text)
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\div', '÷', text)
    text = re.sub(r'\\cdot', '·', text)
    text = re.sub(r'\\sqrt\{(.*?)\}', r'√(\1)', text)
    text = re.sub(r'\^\{(.*?)\}', r'^\1', text)
    text = re.sub(r'_\{(.*?)\}', r'_\1', text)
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

def process_message(chat_id, text):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            model="deepseek-r1-distill-llama-70b",
        )
        reply = clean_response(chat_completion.choices[0].message.content)
        send_message(chat_id, reply)
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        send_message(chat_id, f"Error: {str(e)[:100]}")

def process_image(chat_id, file_id, caption):
    try:
        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        img_response = requests.get(file_url, timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")
        prompt = caption if caption else "Is image mein jo question hai usse solve karo step by step"
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
        if chat_id != ALLOWED_GROUP_ID:
            return "ok", 200
        text = message.get("text", "")
        caption = message.get("caption", "")
        photo = message.get("photo", None)
        if photo:
            mention_in_caption = f"@{BOT_USERNAME}" in caption
            if mention_in_caption or not caption:
                clean_caption = caption.replace(f"@{BOT_USERNAME}", "").strip()
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, clean_caption)).start()
            return "ok", 200
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
