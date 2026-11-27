import urllib.request
import urllib.error
import json
import os
from dotenv import load_dotenv

load_dotenv('.env')
key = os.environ.get('LLM_API_KEY')
base_url = os.environ.get('LLM_BASE_URL')

tools = [
    {
        "type": "function",
        "function": {
            "name": "insight_forge",
            "description": "Insight forge tool",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "panorama_search",
            "description": "Panorama search tool",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "quick_search",
            "description": "Quick search tool",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "interview_agents",
            "description": "Interview agents tool",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }
]

req_body = {
    'model': 'openai/gpt-oss-20b',
    'messages': [
        {'role': 'system', 'content': 'You are a research agent. Use tools if needed.'},
        {'role': 'user', 'content': 'Analyze the adoption of Prompta V2.'}
    ],
    'tools': tools,
    'tool_choice': 'auto'
}
req = urllib.request.Request(
    f'{base_url}/chat/completions',
    data=json.dumps(req_body).encode(),
    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
)
try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        choice = res['choices'][0]
        print('Tool calls received:', choice['message'].get('tool_calls'))
        print('Content:', choice['message'].get('content'))
except urllib.error.HTTPError as e:
    print('HTTPError:', e.code, e.read().decode())
