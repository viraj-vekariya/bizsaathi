import inspect, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
from sarvamai import SarvamAI
c = SarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))
print(inspect.signature(c.speech_to_text.transcribe))
r = c.chat.completions(model="sarvam-105b", messages=[{"role": "user", "content": 'Return only JSON: {"status":"connected"}'}],
                       reasoning_effort=None, max_tokens=100)
print("CHAT:", r.choices[0].message.content)
