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

# ============ CONFIG ============
TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
BOT_USERNAME = "Durva_mentor_bot"
SPACE_HOST = os.environ.get("RENDER_HOST", "durva-doubtsolver.onrender.com")

WOLFRAM_KEYS = [os.environ.get(f"WOLFRAM_APPID{i}") for i in range(1, 9) if os.environ.get(f"WOLFRAM_APPID{i}")]
GEMINI_KEYS = [os.environ.get(f"GEMINI_KEY_{i}") for i in range(1, 11) if os.environ.get(f"GEMINI_KEY_{i}")]
GROQ_KEYS = [os.environ.get(f"GROQ_API_KEY_{i}") for i in range(1, 5) if os.environ.get(f"GROQ_API_KEY_{i}")]
if not GROQ_KEYS and os.environ.get("GROQ_API_KEY"):
    GROQ_KEYS.append(os.environ.get("GROQ_API_KEY"))

app = Flask(__name__)

# ============ KEY ROTATORS ============
wolfram_key_index = 0
gemini_key_index = 0
groq_key_index = 0
wolfram_lock = threading.Lock()
gemini_lock = threading.Lock()
groq_lock = threading.Lock()

def get_wolfram_key():
    global wolfram_key_index
    with wolfram_lock:
        if not WOLFRAM_KEYS:
            return None
        key = WOLFRAM_KEYS[wolfram_key_index % len(WOLFRAM_KEYS)]
        wolfram_key_index = (wolfram_key_index + 1) % len(WOLFRAM_KEYS)
        return key

def get_gemini_key():
    global gemini_key_index
    with gemini_lock:
        if not GEMINI_KEYS:
            return None
        key = GEMINI_KEYS[gemini_key_index % len(GEMINI_KEYS)]
        gemini_key_index = (gemini_key_index + 1) % len(GEMINI_KEYS)
        return key

def get_groq_client():
    global groq_key_index
    with groq_lock:
        if not GROQ_KEYS:
            return None
        key = GROQ_KEYS[groq_key_index % len(GROQ_KEYS)]
        groq_key_index = (groq_key_index + 1) % len(GROQ_KEYS)
        return Groq(api_key=key)

# ============ WEBHOOK SETUP ============
def set_webhook():
    webhook_url = f"https://{SPACE_HOST}/webhook"
    url = f"{TELEGRAM_API}/setWebhook"
    response = requests.post(url, json={"url": webhook_url}, timeout=10)
    result = response.json()
    logging.info(f"Webhook set: {result}")
    return result

def get_bot_username():
    try:
        url = f"{TELEGRAM_API}/getMe"
        response = requests.get(url, timeout=10)
        data = response.json()
        username = data["result"]["username"]
        logging.info(f"Bot username: {username}")
        return username
    except Exception as e:
        logging.warning(f"Username fetch error: {e}")
        return BOT_USERNAME

# ============ SYSTEM PROMPT ============
SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai jo 11th-12th ke students ki help karta hai.
SUBJECTS: Physics, Chemistry, Math, Biology (PCMB)
LANGUAGE: Hinglish mein jawab de. Scientific terms English mein rakho.
LENGTH: Maximum 8-10 steps, har step 1-2 lines ka. Short aur clear.
FORMATTING: Koi ## headers nahi, Koi $ signs nahi, Koi * ** _ nahi, Koi LaTeX nahi, koi Markdown nahi.
"""

# ============ SUBJECT DETECTOR ============
def detect_subject(text):
    text_lower = text.lower()
    math_keywords = ['integrate', 'differentiate', 'derivative', 'integral', 'matrix', 'limit',
                     'solve', 'equation', 'trigonometry', 'sin', 'cos', 'tan', 'log', 'algebra']
    physics_keywords = ['force', 'velocity', 'acceleration', 'current', 'voltage', 'resistance',
                        'energy', 'power', 'momentum', 'torque', 'gravity', 'motion', 'wave', 'optics']
    chemistry_keywords = ['mole', 'molarity', 'reaction', 'bond', 'organic', 'acid', 'base',
                          'titration', 'equilibrium', 'element', 'compound', 'valency']
    biology_keywords = ['cell', 'dna', 'rna', 'protein', 'mitosis', 'meiosis', 'chromosome',
                        'genetic', 'disorder', 'autosomal', 'enzyme', 'hormone', 'tissue', 'organ']
    scores = {
        'math': sum(1 for k in math_keywords if k in text_lower),
        'physics': sum(1 for k in physics_keywords if k in text_lower),
        'chemistry': sum(1 for k in chemistry_keywords if k in text_lower),
        'biology': sum(1 for k in biology_keywords if k in text_lower),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'general'

def is_numerical(text):
    has_numbers = bool(re.search(r'\d+', text))
    calc_words = ['calculate', 'find', 'value', 'compute', 'evaluate', 'determine',
                  'what is', 'solve', 'numerically', 'how much', 'how many']
    has_calc = any(w in text.lower() for w in calc_words)
    return has_numbers and has_calc

# ============ GEMINI VISION - SIRF EXTRACT ============
def extract_question_from_image(image_base64):
    total_keys = len(GEMINI_KEYS) if GEMINI_KEYS else 1
    for _ in range(total_keys):
        key = get_gemini_key()
        if not key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
            prompt = """Extract the question from this image exactly as written.
Only return the question text, nothing else.
Do not solve it, do not add explanation.
Just extract the text of the question accurately."""
            payload = {
                "contents": [{"parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}
                ]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500}
            }
            r = requests.post(url, json=payload, timeout=40)
            if r.status_code == 200:
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            logging.error(f"Gemini vision error: {e}")
    return None

# ============ WOLFRAM ALPHA ============
def solve_with_wolfram(query):
    for _ in range(len(WOLFRAM_KEYS) if WOLFRAM_KEYS else 0):
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
        except Exception as e:
            logging.error(f"Wolfram error: {e}")
    return None

# ============ GROQ ============
def solve_with_groq(question, wolfram_result=None):
    for _ in range(len(GROQ_KEYS) if GROQ_KEYS else 1):
        groq_client = get_groq_client()
        if not groq_client:
            return None
        try:
            if wolfram_result:
                user_msg = f"Question: {question}\n\nWolfram Alpha answer:\n{wolfram_result}\n\nAb is answer ko step-by-step simple Hinglish mein explain karo."
            else:
                user_msg = question
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                model="llama-3.3-70b-versatile",
                max_tokens=1000,
                temperature=0.3
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            logging.error(f"Groq error: {e}")
    return None

# ============ MAIN SOLVER ============
def solve_question(chat_id, question):
    try:
        subject = detect_subject(question)
        numerical = is_numerical(question)
        logging.info(f"Subject: {subject}, Numerical: {numerical}")

        if numerical and subject in ['math', 'physics', 'chemistry']:
            wolfram_result = solve_with_wolfram(question)
            reply = solve_with_groq(question, wolfram_result)
        else:
            reply = solve_with_groq(question)

        if reply:
            send_message(chat_id, clean_response(reply))
        else:
            send_message(chat_id, "Sorry bhai, abhi answer nahi de pa raha. Thodi der baad try karo!")
    except Exception as e:
        logging.error(f"Solve error: {e}")
        send_message(chat_id, "Kuch error aa gaya. Dobara try karo!")

# ============ IMAGE HANDLER ============
def process_image(chat_id, file_id, instruction):
    try:
        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        img_response = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")

        send_message(chat_id, "Image dekh raha hoon... ek second!")
        extracted_question = extract_question_from_image(img_base64)

        if not extracted_question:
            send_message(chat_id, "Image se question nahi padh paya. Clear image bhejo!")
            return

        full_question = f"{extracted_question}\n{instruction}".strip() if instruction else extracted_question
        solve_question(chat_id, full_question)
    except Exception as e:
        logging.error(f"Image error: {e}")
        send_message(chat_id, "Image process nahi ho payi. Dobara try karo!")

# ============ UTILS ============
def clean_response(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'[*#`_$]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def send_message(chat_id, text):
    try:
        max_len = 4000
        if len(text) > max_len:
            parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for part in parts:
                requests.post(f"{TELEGRAM_API}/sendMessage",
                              json={"chat_id": chat_id, "text": part}, timeout=30)
                time.sleep(0.5)
        else:
            requests.post(f"{TELEGRAM_API}/sendMessage",
                          json={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        logging.warning(f"Send failed: {e}")

# ============ WEBHOOK ============
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
                instruction = caption.replace(bot_tag, "").strip()
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, instruction)).start()
            return "ok", 200

        if bot_tag.lower() in text.lower():
            clean_text = text.replace(bot_tag, "").strip()
            replied = message.get("reply_to_message", None)
            if replied:
                replied_text = replied.get("text", "") or replied.get("caption", "")
                clean_text = f"{replied_text}\n{clean_text}".strip()
            if not clean_text:
                send_message(chat_id, "Bhai question toh do!")
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
    app.run(host="0.0.0.0", port=8080)
