import os
import logging
import requests
import threading
import base64
import re
import time
from flask import Flask, request
from groq import Groq
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
BOT_USERNAME = "Durva_mentor_bot"
SPACE_HOST = "durva-doubtsolver.onrender.com"

WOLFRAM_KEYS = [os.environ.get(f"WOLFRAM_APPID{i}") for i in range(1, 9) if os.environ.get(f"WOLFRAM_APPID{i}")]
GROQ_KEYS = [os.environ.get(f"GROQ_API_KEY_{i}") for i in range(1, 5) if os.environ.get(f"GROQ_API_KEY_{i}")]
if not GROQ_KEYS and os.environ.get("GROQ_API_KEY"):
    GROQ_KEYS.append(os.environ.get("GROQ_API_KEY"))

logging.info(f"Wolfram keys: {len(WOLFRAM_KEYS)}, Groq keys: {len(GROQ_KEYS)}")

app = Flask(__name__)

wolfram_key_index = 0
groq_key_index = 0
wolfram_lock = threading.Lock()
groq_lock = threading.Lock()

def get_wolfram_key():
    global wolfram_key_index
    with wolfram_lock:
        if not WOLFRAM_KEYS:
            return None
        key = WOLFRAM_KEYS[wolfram_key_index % len(WOLFRAM_KEYS)]
        wolfram_key_index = (wolfram_key_index + 1) % len(WOLFRAM_KEYS)
        return key

def get_groq_client():
    global groq_key_index
    with groq_lock:
        if not GROQ_KEYS:
            return None
        key = GROQ_KEYS[groq_key_index % len(GROQ_KEYS)]
        groq_key_index = (groq_key_index + 1) % len(GROQ_KEYS)
        return Groq(api_key=key)

SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai jo 11th-12th ke students ki help karta hai.
SUBJECTS: Physics, Chemistry, Math, Biology (PCMB)
LANGUAGE RULES:
- Hinglish mein jawab de by default
- Agar student bole "english mein" toh English mein jawab de
- Scientific terms hamesha English mein rakho
LENGTH: Maximum 8-10 steps, har step 1-2 lines. Short aur clear.
FORMATTING:
- Koi ## headers nahi
- Koi $ signs nahi
- Koi LaTeX nahi
- Koi * ** _ nahi
- Powers: x², H₂O, CO₂
- Fractions: (a/b)
- Multiplication: x
- Greek: θ α β π Δ ω λ
- Steps: 1. 2. 3.
ACCURACY: Pehle soch ke solve karo. Final answer clearly likho."""

def set_webhook():
    try:
        url = f"{TELEGRAM_API}/setWebhook"
        r = requests.post(url, json={"url": f"https://{SPACE_HOST}/webhook"}, timeout=10)
        logging.info(f"Webhook set: {r.json()}")
    except Exception as e:
        logging.warning(f"Webhook error: {e}")

def get_bot_username():
    global BOT_USERNAME
    try:
        r = requests.get(f"{TELEGRAM_API}/getMe", timeout=10).json()
        BOT_USERNAME = r["result"]["username"]
        logging.info(f"Bot username: {BOT_USERNAME}")
    except Exception as e:
        logging.warning(f"Username error: {e}")

def send_message(chat_id, text):
    try:
        max_len = 4000
        if len(text) > max_len:
            for i in range(0, len(text), max_len):
                requests.post(f"{TELEGRAM_API}/sendMessage",
                            json={"chat_id": chat_id, "text": text[i:i+max_len]}, timeout=30)
                time.sleep(0.5)
        else:
            requests.post(f"{TELEGRAM_API}/sendMessage",
                        json={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        logging.warning(f"Send failed: {e}")

def clean_response(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'[#`]', '', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
    text = re.sub(r'\$.*?\$', '', text)
    text = re.sub(r'\\frac\{(.*?)\}\{(.*?)\}', r'(\1/\2)', text)
    text = re.sub(r'\\sqrt\{(.*?)\}', r'√(\1)', text)
    text = re.sub(r'\\theta', 'θ', text)
    text = re.sub(r'\\alpha', 'α', text)
    text = re.sub(r'\\beta', 'β', text)
    text = re.sub(r'\\pi', 'π', text)
    text = re.sub(r'\\Delta', 'Δ', text)
    text = re.sub(r'\\times', '×', text)
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def is_numerical(text):
    has_numbers = bool(re.search(r'\d+', text))
    calc_words = ['calculate', 'find', 'value', 'compute', 'evaluate', 'determine',
                  'what is', 'solve', 'numerically', 'how much', 'how many']
    return has_numbers and any(w in text.lower() for w in calc_words)

def solve_with_wolfram(query):
    for _ in range(len(WOLFRAM_KEYS) if WOLFRAM_KEYS else 0):
        key = get_wolfram_key()
        if not key:
            return None
        try:
            r = requests.get("http://api.wolframalpha.com/v2/query",
                           params={'input': query, 'format': 'plaintext',
                                  'output': 'JSON', 'appid': key}, timeout=15)
            if r.status_code == 200:
                pods = r.json().get('queryresult', {}).get('pods', [])
                parts = []
                for pod in pods:
                    if pod.get('title', '').lower() in ['input', 'input interpretation']:
                        continue
                    for sub in pod.get('subpods', []):
                        t = sub.get('plaintext', '').strip()
                        if t:
                            parts.append(f"{pod['title']}: {t}")
                if parts:
                    return '\n'.join(parts[:5])
        except Exception as e:
            logging.error(f"Wolfram error: {e}")
    return None

def solve_with_groq_text(question, wolfram_result=None):
    for _ in range(len(GROQ_KEYS) if GROQ_KEYS else 1):
        client = get_groq_client()
        if not client:
            return None
        try:
            if wolfram_result:
                user_msg = f"Question: {question}\n\nWolfram Alpha answer:\n{wolfram_result}\n\nAb is answer ko step-by-step simple Hinglish mein explain karo."
            else:
                user_msg = question
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                model="llama-3.3-70b-versatile",
                max_tokens=1000,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Groq text error: {e}")
    return None

def solve_with_groq_vision(image_base64, instruction):
    for _ in range(len(GROQ_KEYS) if GROQ_KEYS else 1):
        client = get_groq_client()
        if not client:
            return None
        try:
            prompt = instruction if instruction else "Is image mein jo question hai usse step by step solve karo."
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                max_tokens=1000,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Groq vision error: {e}")
    return None

def solve_question(chat_id, question):
    try:
        wolfram_result = None
        if is_numerical(question):
            wolfram_result = solve_with_wolfram(question)
            logging.info(f"Wolfram result: {wolfram_result[:100] if wolfram_result else 'None'}")
        reply = solve_with_groq_text(question, wolfram_result)
        if reply:
            send_message(chat_id, clean_response(reply))
        else:
            send_message(chat_id, "Sorry bhai, abhi answer nahi de pa raha. Thodi der baad try karo!")
    except Exception as e:
        logging.error(f"Solve error: {e}")
        send_message(chat_id, "Kuch error aa gaya. Dobara try karo!")

def process_image(chat_id, file_id, instruction):
    try:
        send_message(chat_id, "Image dekh raha hoon... ek second!")
        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        img_response = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")
        reply = solve_with_groq_vision(img_base64, instruction)
        if reply:
            send_message(chat_id, clean_response(reply))
        else:
            send_message(chat_id, "Image solve nahi ho payi. Text mein question likho!")
    except Exception as e:
        logging.error(f"Image error: {e}")
        send_message(chat_id, "Image process nahi ho payi. Dobara try karo!")

def get_replied_message_text(message):
    replied = message.get("reply_to_message", None)
    if replied:
        return replied.get("text", "") or replied.get("caption", "")
    return ""

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return "ok", 200
        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        caption = message.get("caption", "") or ""
        photo = message.get("photo", None)
        bot_tag = f"@{BOT_USERNAME}"

        if photo:
            if bot_tag.lower() in caption.lower():
                instruction = re.sub(re.escape(bot_tag), '', caption, flags=re.IGNORECASE).strip()
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, instruction)).start()
            return "ok", 200

        if bot_tag.lower() in text.lower():
            clean_text = re.sub(re.escape(bot_tag), '', text, flags=re.IGNORECASE).strip()
            simple_commands = ["solve", "karo", "help", "batao", "solve karo"]
            if not clean_text or clean_text.lower() in simple_commands:
                replied_text = get_replied_message_text(message)
                if replied_text:
                    instruction = clean_text if clean_text else ""
                    clean_text = f"{replied_text}\n{instruction}".strip() if instruction else replied_text
                else:
                    send_message(chat_id, "Bhai question toh do ya kisi question pe reply karke @Durva_mentor_bot solve karo!")
                    return "ok", 200
            threading.Thread(target=solve_question, args=(chat_id, clean_text)).start()

    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return "Durva Mentor Bot Active!", 200

if __name__ == "__main__":
    get_bot_username()
    set_webhook()
    logging.info("Bot start ho gaya!")
    app.run(host="0.0.0.0", port=8080)
