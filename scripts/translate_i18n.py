import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv('.env')
api_key = os.environ.get('LLM_API_KEY')
base_url = os.environ.get('LLM_BASE_URL', 'https://api.deepseek.com').rstrip('/')

with open('locales/en.json', 'r', encoding='utf-8') as f:
    en_data = json.load(f)

prompt = """Eres un traductor profesional de software a español neutro.
Traduce el siguiente objeto JSON de inglés a español para una interfaz de usuario.
REGLAS ESTRICTAS:
1. Mantén exactamente las mismas claves JSON.
2. No modifiques ni elimines variables ni placeholders como {count}, {name}, {brand}, {n}, etc.
3. Devuelve ÚNICAMENTE el JSON traducido válido, sin bloques de código markdown ni explicaciones adicionales."""

def translate_chunk(chunk_dict):
    req_body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(chunk_dict, ensure_ascii=False)}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(req_body).encode('utf-8'),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        content = result['choices'][0]['message']['content']
        return json.loads(content)

# We can translate sections
sections = list(en_data.keys())
print("Translating sections:", sections)
es_data = {}

# Group small sections together
group1 = {k: en_data[k] for k in ['common', 'meta', 'nav', 'home']}
group2 = {k: en_data[k] for k in ['main', 'step1', 'step2']}
group3 = {k: en_data[k] for k in ['step3', 'step4', 'step5']}
group4 = {k: en_data[k] for k in ['graph', 'history', 'api', 'progress', 'log', 'report', 'console']}

for idx, grp in enumerate([group1, group2, group3, group4]):
    print(f"Translating group {idx+1}/4...")
    res = translate_chunk(grp)
    es_data.update(res)

with open('locales/es.json', 'w', encoding='utf-8') as f:
    json.dump(es_data, f, ensure_ascii=False, indent=2)

print("Successfully generated locales/es.json!")
