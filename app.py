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

# 8 Wolfram Keys ko ek list me load karna
WOLFRAM_KEYS = [os.environ.get(f"WOLFRAM_APPID{i}") for i in range(1, 9) if os.environ.get(f"WOLFRAM_APPID{i}")]
if not WOLFRAM_KEYS and os.environ.get("WOLFRAM_APP_ID"): # Backup agar purana variable ho
    WOLFRAM_KEYS.append(os.environ.get("WOLFRAM_APP_ID"))

GEMINI_KEYS = [os.environ.get(f"GEMINI_KEY_{i}") for i in range(1, 11) if os.environ.get(f"GEMINI_KEY_{i}")]

SPACE_HOST = os.environ.get("RENDER_HOST", "durva-doubtsolver.onrender.com")
TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"
ALLOWED_GROUP_ID = -1003946747894
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
- Agar student ne kaha "explain in english" — toh English mein jawab de
- Agar student ne kuch nahi kaha — toh question ki language dekh ke jawab de
- Scientific terms hamesha English mein rakho

LENGTH RULES:
- Maximum 8-10 steps, har step 1-2 lines ka
- Seedha point pe aao
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

BIOLOGY RULES:
- NCERT based answers do
- Diagrams describe karo clearly
- Process steps mein likho (mitosis, meiosis, etc.)
- Terms bold mat karo, seedha likho

ACCURACY:
- Pehle soch ke solve karo
- Formula likho, values daalo, calculate karo
- Final answer clearly likho: "Answer: 0.75"
"""

# ============ SUBJECT DETECTOR ============
def detect_subject(text):
    text_lower = text.lower()
    math_keywords = ['integrate', 'differentiate', 'derivative', 'integral', 'matrix', 'determinant',
                     'limit', 'solve', 'equation', 'polynomial', 'trigonometry', 'sin', 'cos', 'tan',
                     'algebra', 'calculus', 'vector', 'probability', 'permutation', 'combination',
                     'binomial', 'sequence', 'series', 'parabola', 'ellipse', 'hyperbola', 'circle']
    physics_keywords = ['force', 'velocity', 'acceleration', 'current', 'voltage', 'resistance',
                        'energy', 'power', 'momentum', 'torque', 'frequency', 'wavelength',
                        'electric', 'magnetic', 'circuit', 'lens', 'mirror', 'refraction',
                        'gravity', 'newton', 'ohm', 'capacitor', 'inductor', 'photon', 'electron',
                        'nuclear', 'motion', 'wave', 'optics', 'thermodynamics', 'pressure']
    chemistry_keywords = ['mole', 'molarity', 'reaction', 'bond', 'organic', 'inorganic',
                          'element', 'compound', 'acid', 'base', 'salt', 'oxidation', 'reduction',
                          'electron', 'proton', 'neutron', 'atomic', 'molecule', 'polymer',
                          'hybridization', 'isomer', 'alkane', 'alkene', 'alkyne', 'benzene',
                          'equilibrium', 'ph', 'buffer', 'titration', 'enthalpy', 'entropy']
    biology_keywords = ['cell', 'dna', 'rna', 'protein', 'mitosis', 'meiosis', 'chromosome',
                        'gene', 'mutation', 'photosynthesis', 'respiration', 'enzyme', 'hormone',
                        'organ', 'tissue', 'blood', 'heart', 'brain', 'nerve', 'muscle',
                        'bacteria', 'virus', 'fungi', 'plant', 'animal', 'ecosystem', 'evolution',
                        'digestion', 'excretion', 'reproduction', 'ncert', 'bio']
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

# ============ NUMERICAL DETECTOR ============
def is_numerical(text):
    numerical_patterns = [
        r'\d+\.?\d*\s*(m/s|km/h|kg|newton|joule|watt|volt|amp|ohm|tesla|mol|atm|pa|k|°c)',
        r'calculate|find the value|what is the|numerical|compute|evaluate',
        r'\d+\s*[\+\-\×\÷\*\/]\s*\d+',
        r'=\s*\?',
        r'\d+\s*(kg|m|s|a|v|n|j|w)',
    ]
    text_lower = text.lower()
    for pattern in numerical_patterns:
        if re.search(pattern, text_lower):
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
            params = {
                'input': query,
                'format': 'plaintext',
                'output': 'JSON',
                'appid': active_key,
            }
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
            rotate_wolfram_key() # Fail hone par rotate karo
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
            if r.status_code == 429:
                logging.warning(f"Gemini text key index rate limited, rotating...")
                rotate_gemini_key()
                time.sleep(0.5)
                continue
            if r.status_code == 200:
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            logging.error(f"Gemini text error: {e}")
            rotate_gemini_key()
    return None

# ============ GEMINI VISION (IMAGE) ============
def ask_gemini_vision(image_base64, instruction=""):
    total_keys = len(GEMINI_KEYS) if GEMINI_KEYS else 1
    for attempt in range(total_keys * 2):
        key = get_gemini_key()
        if not key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
            if instruction:
                prompt = f"Is image mein jo question hai usse step by step solve karo. Student ki instruction: {instruction}\n\n{SYSTEM_PROMPT}"
            else:
                prompt = f"Is image mein jo bhi question ya problem hai usse pehle extract karo phir step by step solve karo.\n\n{SYSTEM_PROMPT}"
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
            if r.status_code == 429:
                logging.warning(f"Gemini vision key index rate limited, rotating...")
                rotate_gemini_key()
                time.sleep(0.5)
                continue
            if r.status_code == 200:
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            logging.error(f"Gemini vision error: {e}")
            rotate_gemini_key()
    return None

# ============ CLEAN RESPONSE ============
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

# ============ SEND MESSAGE ============
def send_message(chat_id, text):
    max_len = 4000
    if len(text) <= max_len:
        for attempt in range(3):
            try:
                url = f"{TELEGRAM_API}/sendMessage"
                requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
                return
            except Exception as e:
                logging.warning(f"Send attempt {attempt+1} failed: {e}")
    else:
        parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
        for part in parts:
            try:
                url = f"{TELEGRAM_API}/sendMessage"
                requests.post(url, json={"chat_id": chat_id, "text": part}, timeout=30)
                time.sleep(0.5)
            except Exception as e:
                logging.warning(f"Split send failed: {e}")

# ============ PROCESS TEXT ============
def process_message(chat_id, text):
    try:
        subject = detect_subject(text)
        numerical = is_numerical(text)
        logging.info(f"Subject: {subject}, Numerical: {numerical}")

        if numerical and subject in ['math', 'physics', 'chemistry']:
            wolfram_result = solve_with_wolfram(text)
            if wolfram_result:
                combined_prompt = f"""Student ka question: {text}
Wolfram Alpha ne ye calculate kiya:
{wolfram_result}
Ab is calculation ko student ko step by step explain karo. Wolfram ka answer use karo, apni calculation mat karo."""
                gemini_reply = ask_gemini_text(combined_prompt)
                if gemini_reply:
                    send_message(chat_id, clean_response(gemini_reply))
                    return
                reply = get_groq_answer(text, extra_context=wolfram_result)
                send_message(chat_id, clean_response(reply))
                return

        if subject == 'biology' or not numerical:
            reply = get_groq_answer(text)
            send_message(chat_id, clean_response(reply))
            return

        gemini_reply = ask_gemini_text(f"{SYSTEM_PROMPT}\n\nQuestion: {text}")
        if gemini_reply:
            send_message(chat_id, clean_response(gemini_reply))
            return

        reply = get_groq_answer(text)
        send_message(chat_id, clean_response(reply))

    except Exception as e:
        logging.error(f"Process error: {e}")
        send_message(chat_id, "Kuch error aa gaya, dobara try karo!")

# ============ GROQ ANSWER ============
def get_groq_answer(text, extra_context=""):
    try:
        user_content = text
        if extra_context:
            user_content = f"{text}\n\nCalculation reference:\n{extra_context}"
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            model="llama-3.3-70b-versatile",
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq error: {e}")
        return "Error aa gaya, dobara try karo!"

# ============ PROCESS IMAGE ============
def process_image(chat_id, file_id, instruction):
    try:
        logging.info(f"Image processing — instruction: {instruction}")

        file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}", timeout=10).json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        img_response = requests.get(file_url, timeout=30)
        img_base64 = base64.b64encode(img_response.content).decode("utf-8")

        gemini_reply = ask_gemini_vision(img_base64, instruction)
        if gemini_reply:
            send_message(chat_id, clean_response(gemini_reply))
            return

        logging.warning("Gemini vision failed, trying Groq fallback...")
        if instruction:
            prompt = f"Is image mein jo question hai usse solve karo. Instruction: {instruction}"
        else:
            prompt = "Is image mein jo question hai usse step by step solve karo"

        # Fixed model name here to standard Groq vision model
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
            model="llama-3.2-11b-vision-preview",
        )
        reply = clean_response(chat_completion.choices[0].message.content)
        send_message(chat_id, reply)

    except Exception as e:
        logging.error(f"Image error: {e}")
        send_message(chat_id, "Image solve nahi ho paya, dobara try karo!")

# ============ WEBHOOK ============
def get_replied_message_text(message):
    replied = message.get("reply_to_message", None)
    if replied:
        return replied.get("text", "") or replied.get("caption", "")
    return ""

def set_webhook():
    try:
        webhook_url = f"https://{SPACE_HOST}/webhook"
        url = f"{TELEGRAM_API}/setWebhook?url={webhook_url}"
        r = requests.get(url, timeout=30)
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

        if photo:
            logging.info(f"Photo received — caption: {caption}")
            if bot_tag.lower() in caption.lower():
                instruction = re.sub(re.escape(bot_tag), '', caption, flags=re.IGNORECASE).strip()
                file_id = photo[-1]["file_id"]
                threading.Thread(target=process_image, args=(chat_id, file_id, instruction)).start()
            return "ok", 200

        if bot_tag.lower() in text.lower():
            clean_text = re.sub(re.escape(bot_tag), '', text, flags=re.IGNORECASE).strip()
            simple_commands = ["solve", "karo", "help", "explain", "batao", "solve karo"]
            if not clean_text or clean_text.lower() in simple_commands:
                replied_text = get_replied_message_text(message)
                if replied_text:
                    instruction = clean_text if clean_text else ""
                    clean_text = f"{replied_text}\nInstruction: {instruction}".strip() if instruction else replied_text
                else:
                    send_message(chat_id, "Bhai koi question toh likho ya kisi question pe reply karke tag karo!")
                    return "ok", 200
            threading.Thread(target=process_message, args=(chat_id, clean_text)).start()

    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    return "PCMB Bot with Key Rotators is running!", 200

if __name__ == "__main__":
    get_bot_username()
    set_webhook()
    logging.info("PCMB Bot start ho gaya!")
    app.run(host="0.0.0.0", port=8080)
