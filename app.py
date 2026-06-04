import os
import logging
import requests
import threading
import base64
import re
import json
import time
from flask import Flask, request
from groq import Groq
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ============ CONFIG ============
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

WOLFRAM_KEYS = [os.environ.get(f"WOLFRAM_APPID{i}") for i in range(1, 9) if os.environ.get(f"WOLFRAM_APPID{i}")]
if not WOLFRAM_KEYS and os.environ.get("WOLFRAM_APP_ID"):
    WOLFRAM_KEYS.append(os.environ.get("WOLFRAM_APP_ID"))

GEMINI_KEYS = [os.environ.get(f"GEMINI_KEY_{i}") for i in range(1, 11) if os.environ.get(f"GEMINI_KEY_{i}")]

SPACE_HOST = os.environ.get("RENDER_HOST", "durva-doubtsolver.onrender.com")
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
BOT_USERNAME = "Durva_mentor_bot"

client = Groq(api_key=GROQ_API_KEY)
app = Flask(__name__)

# ============ WOLFRAM KEY ROTATOR ============
wolfram_key_index = 0
wolfram_lock = threading.Lock()

def get_wolfram_key():
    global wolfram_key_index
    with wolfram_lock:
        if not WOLFRAM_KEYS:
            return None
        return WOLFRAM_KEYS[wolfram_key_index % len(WOLFRAM_KEYS)]

def rotate_wolfram_key():
    global wolfram_key_index
    with wolfram_lock:
        if WOLFRAM_KEYS:
            wolfram_key_index = (wolfram_key_index + 1) % len(WOLFRAM_KEYS)
            logging.info(f"Wolfram key rotated to index {wolfram_key_index}")

# ============ GEMINI KEY ROTATOR ============
gemini_key_index = 0
gemini_lock = threading.Lock()

def get_gemini_key():
    global gemini_key_index
    with gemini_lock:
        if not GEMINI_KEYS:
            return None
        return GEMINI_KEYS[gemini_key_index % len(GEMINI_KEYS)]

def rotate_gemini_key():
    global gemini_key_index
    with gemini_lock:
        if GEMINI_KEYS:
            gemini_key_index = (gemini_key_index + 1) % len(GEMINI_KEYS)
            logging.info(f"Gemini key rotated to index {gemini_key_index}")

# ============ SYSTEM PROMPT ============
SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai jo 11th-12th ke students ki help karta hai.
SUBJECTS: Physics, Chemistry, Math, Biology (PCMB)
LANGUAGE RULES:
- Agar student ne kaha "hinglish mein" ya "hindi mein" — toh Hinglish mein jawab de
- Scientific terms hamesha English mein rakho
LENGTH RULES:
- Maximum 8-10 steps, har step 1-2 lines ka
- Short aur clear rakho
FORMATTING RULES — YE BILKUL MAT USE KARNA:
- Koi ## headers nahi, Koi $ signs nahi, Koi * ** _ nahi, Koi LaTeX nahi, koi Markdown nahi
"""

# ============ SUBJECT DETECTOR ============
def detect_subject(text):
    text_lower = text.lower()
    math_keywords = ['integrate', 'differentiate', 'derivative', 'integral', 'matrix', 'limit', 'solve', 'equation']
    physics_keywords = ['force', 'velocity', 'acceleration', 'current', 'voltage', 'resistance', 'energy']
    chemistry_keywords = ['mole', 'molarity', 'reaction', 'bond', 'organic', 'acid', 'base']
    biology_keywords = ['cell', 'dna', 'rna', 'protein', 'mitosis', 'meiosis', 'chromosome', 'genetic', 'disorder', 'autosomal']
    
    scores = {
        'math': sum(1 for k in math_keywords if k in text_lower),
        'physics': sum(1 for k in physics_keywords if k in text_lower),
        'chemistry': sum(1 for k in chemistry_keywords if k in text_lower),
        'biology': sum(1 for k in biology_keywords if k in text_lower),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return 'general'
    return best

def is_numerical(text):
    numerical_patterns = [r'\d+', r'calculate|find|value|compute|evaluate']
    for pattern in numerical_patterns:
        if re.search(pattern, text.lower()):
            return True
    return False

# ============ WOLFRAM ALPHA ============
def solve_with_wolfram(query):
    attempts = len(WOLFRAM_KEYS) if WOLFRAM_KEYS else 1
    for _ in range(attempts):
        active_key = get_wolfram_key()
        if not active_key:
            return None
        try:
            url = "http://api.wolframalpha.com/v2/query"
            params = {'input': query, 'format': 'plaintext', 'output': 'JSON', 'appid': active_key}
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                pods = data.get('queryresult', {}).get('pods', [])
                result_parts = []
                for pod in pods:
                    title = pod.get('title', '')
                    if title.lower() in ['input', 'input interpretation']:
                        continue
                    for sub in pod.get('subpods', []):
                        plaintext = sub.get('plaintext', '').strip()
                        if plaintext:
                            result_parts.append(f"{title}: {plaintext}")
                if result_parts:
                    return '\n'.join(result_parts[:5])
            rotate_wolfram_key()
        except Exception as e:
            logging.error(f"Wolfram error: {e}")
            rotate_wolfram_key()
    return None

# ============ GEMINI TEXT ============
def ask_gemini_text(prompt):
    total_keys = len(GEMINI_KEYS) if GEMINI_KEYS else 1
    for attempt in range(total_keys * 2):
        key = get_gemini_key()
        if not key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024}
            }
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            rotate_gemini_key()
        except Exception as e:
            logging.error(f"Gemini text error: {e}")
            rotate_gemini_key()
    return None

# ============ GEMINI VISION ============
def ask_gemini_vision(image_base64, instruction=""):
    total_keys = len(GEMINI_KEYS) if GEMINI_KEYS else 1
    for attempt in range(total_keys * 2):
        key = get_gemini_key()
        if not key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
            prompt = f"Solve this step by step. Instruction: {instruction}\n\n{SYSTEM_PROMPT}"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}
                    ]
                }],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500}
            }
            r = requests.post(url, json=payload, timeout=40)
            if r.status_code == 200:
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            rotate_gemini_key()
        except Exception as e:
            logging.error(f"Gemini vision error: {e}")
            rotate_gemini_key()
    return None

def clean_response(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'[\$\*#`_]', '', text)
    return text.strip()

def send_message(chat_id, text):
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        logging.warning(f"Send failed: {e}")

def process_message(chat_id, text):
    try:
        subject = detect_subject(text)
        numerical = is_numerical(text)
        logging.info(f"Processing Text -> Subject: {subject}, Numerical: {numerical}")

        if numerical and subject in ['math', 'physics', 'chemistry']:
            wolfram_result = solve_with_wolfram(text)
            if wolfram_result:
                combined_prompt = f"Question: {text}\nWolfram output: {wolfram_result}\nExplain this simply step-by-step."
                gemini_reply = ask_gemini_text(combined_prompt)
                if gemini_reply:
                    send_message(chat_id, clean_response(gemini_reply))
                    return

        # Core Text Solver via Gemini
        gemini_reply = ask_gemini_text(f"{SYSTEM_PROMPT}\n\nQuestion: {text}")
        if gemini_reply:
            send_message(chat_id, clean_response(gemini_reply))
            return

        # Groq Fallback
        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            model="llama-3.3-70b-versatile",
        )
        send_message(chat_id, clean_response(chat_completion.choices[0].message.content))
    except Exception as e:
        logging.error(f"Process error: {e}")

def process_image(chat_id, file_id, instruction):
    try:
        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        img_response = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")

        gemini_reply = ask_gemini_vision(img_base64, instruction)
        if gemini_reply:
            send_message(chat_id, clean_response(gemini_reply))
            return

        # Groq Vision Fallback
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [{"type": "text", "text": "Solve this problem"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}]}
            ],
            model="llama-3.2-11b-vision-preview",
        )
        send_message(chat_id, clean_response(chat_completion.choices[0].message.content))
    except Exception as e:
        logging.error(f"Image error: {e}")

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if "message" not in data:
            return "ok", 200

        message = data["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        caption = message.get("caption", "")
        photo = message.get("photo", None)
        bot_tag = f"@{BOT_USERNAME}"

        # Group ID Checking hatadi h taaki kisi bhi group me chal sake!
        if photo:
            if bot_tag.lower() in caption.lower():
                instruction = caption.replace(bot_tag, "").strip()
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, instruction)).start()
            return "ok", 200

        if bot_tag.lower() in text.lower():
            clean_text = text.replace(bot_tag, "").strip()
            # Handle reply context
            replied = message.get("reply_to_message", None)
            if replied:
                replied_text = replied.get("text", "") or replied.get("caption", "")
                clean_text = f"{replied_text}\n{clean_text}"
            
            if not clean_text:
                send_message(chat_id, "Bhai question toh dalo!")
                return "ok", 200
                
            threading.Thread(target=process_message, args=(chat_id, clean_text)).start()

    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return "PCMB Global Webhook Active!", 200

if __name__ == "__main__":
    get_bot_username()
    set_webhook()
    app.run(host="0.0.0.0", port=8080)
