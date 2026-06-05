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
MISTRAL_KEYS = [os.environ.get(f"MISTRAL_API_KEY_{i}") for i in range(1, 6) if os.environ.get(f"MISTRAL_API_KEY_{i}")]
if not MISTRAL_KEYS and os.environ.get("MISTRAL_API_KEY"):
    MISTRAL_KEYS.append(os.environ.get("MISTRAL_API_KEY"))
GROQ_KEYS = [os.environ.get(f"GROQ_API_KEY_{i}") for i in range(1, 6) if os.environ.get(f"GROQ_API_KEY_{i}")]
if not GROQ_KEYS and os.environ.get("GROQ_API_KEY"):
    GROQ_KEYS.append(os.environ.get("GROQ_API_KEY"))

logging.info(f"Wolfram keys: {len(WOLFRAM_KEYS)}, Mistral keys: {len(MISTRAL_KEYS)}, Groq keys: {len(GROQ_KEYS)}")

app = Flask(__name__)

wolfram_key_index = 0
mistral_key_index = 0
groq_key_index = 0
wolfram_lock = threading.Lock()
mistral_lock = threading.Lock()
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

def get_mistral_key():
    global mistral_key_index
    with mistral_lock:
        if not MISTRAL_KEYS:
            return None
        key = MISTRAL_KEYS[mistral_key_index % len(MISTRAL_KEYS)]
        mistral_key_index = (mistral_key_index + 1) % len(MISTRAL_KEYS)
        return key

SYSTEM_PROMPT = """Tu ek expert JEE aur NEET doubt solver bot hai jo 11th-12th ke students ki help karta hai.
SUBJECTS: Physics, Chemistry, Math, Biology (PCMB)

LANGUAGE RULES:
- Hinglish mein jawab de by default
- Agar student bole "english mein" toh English mein jawab de
- Scientific terms hamesha English mein rakho

MOST IMPORTANT — RESPONSE MODE:

MODE 1 — SOLVE (default, jab sirf question pucha ho):
- Sirf solving steps do — jo steps answer tak le jaayein wahi likho
- Agar 2 steps mein answer aata hai toh 2 steps, agar 6 chahiye toh 6 — jo zaroori ho utna
- Koi theory nahi, koi concept explanation nahi, koi extra lines nahi
- Bas: step → step → Answer
- Last line hamesha: Answer: [answer]
- Example (matrix question):
  bᵢⱼ = 3^(i-j)·aᵢⱼ → B = D₃·A·D₃⁻¹ → det(B) = det(A) = 2
  cᵢⱼ = 4^(i-j)·bᵢⱼ → C = D₄·A·D₄⁻¹ → det(C) = det(A) = 2
  det(BC) = det(B)·det(C) = 2×2 = 4
  Answer: 4

MODE 2 — EXPLANATION (sirf tab jab student specifically maange):
- Student ne "explain karo", "samjhao", "why", "kaise", "concept batao" likha ho
- Tab concept + theory + detailed steps do
- Clearly samjhao kyun aur kaise

VARIABLES AUR EXPRESSIONS:
- Powers: n², x³, n(n-1)
- Fractions: n(n-1)/2
- Exponents: 2^(n(n-1)/2)
- Greek: θ α β π Δ ω λ
- Variables clearly likho — blank mat chhodna

FORMATTING:
- Koi ## headers nahi
- Koi $ signs nahi
- Koi LaTeX nahi
- Koi * ** _ nahi
- Steps: 1. 2. 3. (sirf MODE 2 mein)

FORMATTING RULES — BAHUT IMPORTANT:
- Har step alag line pe likho — kabhi ek line mein mat thonso
- Matrix elements semicolon se mat likho — alag alag clearly likho
- Agar 3 steps hain toh teen alag lines hongi, har ek clear
- Ek line mein sirf ek cheez — zyada nahi
- Example of GOOD formatting:
  bᵢⱼ = 3^(i-j) · aᵢⱼ
  B = D₃ · A · D₃⁻¹
  det(B) = det(A) = 2
  Answer: 4

IMAGE READING — CRITICAL:
- Jab image se question padho toh symbols dhyan se dekho
- · (dot) matlab multiply hai, - (minus) alag hai — confuse mat karna
- 3^(i-j) · aᵢⱼ matlab 3^(i-j) times aᵢⱼ, minus nahi
- Question ko exactly as given use karo, apni taraf se change mat karo

ACCURACY: Pehle soch ke solve karo. Galat assume mat karo — jaise det(A)=2 ka matlab A=2I nahi hota."""

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

    # Math keywords
    math_words = [
        # Basic operations
        'calculate', 'compute', 'evaluate', 'simplify', 'expand', 'factorize', 'factorise',
        'find', 'solve', 'determine', 'what is', 'how much', 'how many', 'numerically',
        # Algebra
        'equation', 'quadratic', 'polynomial', 'roots', 'zeros', 'factor', 'expression',
        'inequality', 'system of equations', 'linear', 'variable', 'coefficient',
        'arithmetic', 'geometric', 'progression', 'series', 'sequence', 'sum of',
        'binomial', 'permutation', 'combination', 'nCr', 'nPr', 'factorial',
        # Calculus
        'integrate', 'integration', 'differentiate', 'differentiation', 'derivative',
        'limit', 'lim', 'continuity', 'differentiable', 'maxima', 'minima',
        'area under', 'volume of', 'rate of change', 'tangent', 'normal to curve',
        # Matrices & Determinants
        'det', 'determinant', 'matrix', 'matrices', 'inverse', 'transpose',
        'eigenvalue', 'eigenvector', 'rank', 'trace', 'adjoint', 'cofactor',
        'singular', 'non-singular', 'identity matrix',
        # Trigonometry
        'sin', 'cos', 'tan', 'cot', 'sec', 'cosec', 'csc',
        'angle', 'trigonometric', 'inverse trig', 'arcsin', 'arccos', 'arctan',
        'principal value', 'general solution', 'height and distance',
        # Coordinate Geometry
        'distance', 'midpoint', 'slope', 'intercept', 'line', 'circle',
        'parabola', 'ellipse', 'hyperbola', 'conic', 'locus', 'chord',
        'tangent to', 'normal to', 'focus', 'directrix', 'eccentricity',
        # 3D & Vectors
        'vector', 'magnitude', 'dot product', 'cross product', 'scalar',
        'unit vector', 'position vector', 'projection', 'angle between',
        'plane', 'line in 3d', 'distance from', 'direction cosine',
        # Probability & Stats
        'probability', 'P(', 'bayes', 'mean', 'median', 'mode', 'variance',
        'standard deviation', 'distribution', 'binomial distribution',
        'poisson', 'normal distribution', 'expected value',
        # Number Theory
        'lcm', 'hcf', 'gcd', 'prime', 'divisible', 'remainder', 'modulo',
        'complex number', 'imaginary', 'real part', 'argument', 'modulus',
        'equal to', 'equals', 'find the value', 'value of',
    ]

    # Physics keywords
    physics_words = [
        # Mechanics
        'velocity', 'acceleration', 'displacement', 'distance', 'speed',
        'force', 'mass', 'weight', 'momentum', 'impulse', 'power', 'work',
        'energy', 'kinetic', 'potential', 'friction', 'tension', 'normal force',
        'projectile', 'circular motion', 'angular velocity', 'torque',
        'moment of inertia', 'angular momentum', 'rotational', 'rolling',
        'collision', 'elastic', 'inelastic', 'centre of mass',
        'gravitation', 'orbital', 'escape velocity', 'satellite',
        # Thermodynamics
        'temperature', 'heat', 'specific heat', 'thermal', 'conduction',
        'convection', 'radiation', 'entropy', 'enthalpy', 'internal energy',
        'carnot', 'efficiency', 'ideal gas', 'pressure', 'volume', 'boyle',
        'charles', 'isothermal', 'adiabatic', 'isobaric', 'isochoric',
        # Waves & Oscillations
        'frequency', 'wavelength', 'amplitude', 'time period', 'wave',
        'sound', 'doppler', 'resonance', 'standing wave', 'beats',
        'simple harmonic', 'shm', 'oscillation', 'pendulum', 'spring',
        # Optics
        'refraction', 'reflection', 'lens', 'mirror', 'focal length',
        'refractive index', 'snell', 'total internal reflection',
        'optical', 'magnification', 'image', 'object distance',
        'prism', 'dispersion', 'interference', 'diffraction', 'polarization',
        # Electricity & Magnetism
        'current', 'voltage', 'resistance', 'capacitance', 'inductance',
        'ohm', 'kirchhoff', 'circuit', 'power dissipation', 'electric field',
        'magnetic field', 'flux', 'emf', 'charge', 'coulomb',
        'capacitor', 'inductor', 'transformer', 'alternating current', 'ac', 'dc',
        # Modern Physics
        'photoelectric', 'photon', 'wavelength of electron', 'de broglie',
        'half life', 'radioactive', 'decay', 'nuclear', 'binding energy',
        'bohr model', 'energy level', 'ionization energy',
    ]

    all_keywords = math_words + physics_words
    text_lower = text.lower()
    return any(w in text_lower for w in all_keywords) or (has_numbers and any(
        w in text_lower for w in ['value', 'find', 'solve', 'calculate', 'equal']))


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

def solve_with_mistral_text(question, wolfram_result=None):
    for _ in range(len(MISTRAL_KEYS) if MISTRAL_KEYS else 1):
        key = get_mistral_key()
        if not key:
            return None
        try:
            if wolfram_result:
                user_msg = f"Question: {question}\n\nWolfram Alpha answer:\n{wolfram_result}\n\nAb is answer ko step-by-step simple Hinglish mein explain karo."
            else:
                user_msg = question
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "mistral-large-latest",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ],
                "max_tokens": 1000,
                "temperature": 0.3
            }
            r = requests.post("https://api.mistral.ai/v1/chat/completions",
                            headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            else:
                logging.error(f"Mistral text error {r.status_code}: {r.text}")
        except Exception as e:
            logging.error(f"Mistral text error: {e}")
    return None

def solve_with_mistral_vision(image_base64, instruction):
    for _ in range(len(MISTRAL_KEYS) if MISTRAL_KEYS else 1):
        key = get_mistral_key()
        if not key:
            return None
        try:
            prompt = instruction if instruction else "Is image mein jo question hai usse step by step solve karo. Saare variables clearly likho."
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "pixtral-12b-2409",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.3
            }
            r = requests.post("https://api.mistral.ai/v1/chat/completions",
                            headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            else:
                logging.error(f"Mistral error {r.status_code}: {r.text}")
        except Exception as e:
            logging.error(f"Mistral vision error: {e}")
    return None

def solve_question(chat_id, question):
    try:
        wolfram_result = None
        if is_numerical(question):
            wolfram_result = solve_with_wolfram(question)
            logging.info(f"Wolfram result: {wolfram_result[:100] if wolfram_result else 'None'}")
        # Groq pehle try karo, fail hone pe Mistral
        reply = solve_with_groq_text(question, wolfram_result)
        if not reply:
            logging.info("Groq failed, trying Mistral...")
            reply = solve_with_mistral_text(question, wolfram_result)
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

        # Step 1: Mistral Vision se image analyze karo
        mistral_text = solve_with_mistral_vision(img_base64, instruction)

        if not mistral_text:
            send_message(chat_id, "Image solve nahi ho payi. Text mein question likho!")
            return

        # Step 2: Check karo numerical hai ya theory
        wolfram_result = None
        if is_numerical(mistral_text):
            wolfram_result = solve_with_wolfram(mistral_text)
            logging.info(f"Wolfram (image): {wolfram_result[:100] if wolfram_result else 'None'}")

        # Step 3: Wolfram result ho toh Groq se explain karo, warna Mistral Vision ka answer use karo
        if wolfram_result:
            final_reply = solve_with_groq_text(mistral_text, wolfram_result)
            if not final_reply:
                final_reply = solve_with_mistral_text(mistral_text, wolfram_result)
        else:
            final_reply = mistral_text

        if final_reply:
            send_message(chat_id, clean_response(final_reply))
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
            replied_text = get_replied_message_text(message)

            # Agar koi replied message hai, usse hamesha combine karo
            if replied_text:
                if clean_text:
                    clean_text = f"Pehle wala question/answer:\n{replied_text}\n\nStudent ka request: {clean_text}"
                else:
                    clean_text = replied_text

            # Agar kuch bhi nahi mila
            if no
