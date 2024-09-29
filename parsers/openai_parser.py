# parsers/openai_parser.py
import openai
import json
import logging
import uuid
from datetime import datetime
from config import OPENAI_API_KEY

openai.api_key = OPENAI_API_KEY
logger = logging.getLogger(__name__)

def generate_signal_id():
    return str(uuid.uuid4())

def parse_signal_with_openai(message_text):
    prompt = f"""
You are an AI assistant that extracts trading signal information from messages.

Extract the following information from the trading signal message:

Message:
\"\"\"
{message_text}
\"\"\"

Provide the information in JSON format with the following fields:
- instrument (string)
- action (string): "Buy", "Sell", "Long", or "Short"
- entry_price_range (object with "low" and "high" as floats, or null)
- stop_loss (float or null)
- take_profits (list of floats or strings)
- notes (list of strings, if any)

Ensure all numerical values are floats. If any field is missing or not applicable, use null.

Example Output:
{{
  "instrument": "NQ",
  "action": "Sell",
  "entry_price_range": null,
  "stop_loss": 20326.25,
  "take_profits": [20286.25, 20237.00, 20190.00],
  "notes": []
}}
"""
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=350,
            temperature=0,
            stop=None
        )
        extracted_data = response.choices[0].text.strip()
        signal_data = json.loads(extracted_data)

        # Add signal_id and initialize execution fields
        signal_data['signal_id'] = generate_signal_id()
        signal_data['orders_placed'] = False
        signal_data['entry_fulfilled'] = False
        signal_data['tp_fulfilled'] = [False] * len(signal_data.get('take_profits', []))
        signal_data['sl_fulfilled'] = False
        signal_data['trade_closed'] = False
        signal_data['execution_details'] = {}
        signal_data['timestamp'] = datetime.utcnow()

        return signal_data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI response: {e}")
        logger.debug(f"OpenAI response: {response.choices[0].text}")
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}")
    return None
