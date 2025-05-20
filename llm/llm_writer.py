import sys
import json
import openai
import os
from dotenv import load_dotenv
from openai import OpenAI
import re

"""
    @author: Roshan Samantaray
"""
#Load .env file

load_dotenv()

# Parse input JSON from Java
json_file_path = sys.argv[1]
with open(json_file_path, 'r', encoding='utf-8') as f:
    rule = json.load(f)

# Build prompt from CrySL rule
prompt = f"""
You are a secure Java coding assistant.

Below is a CrySL rule for the class `{rule['className']}`. Your task is to generate a clear, accurate, and well-structured natural language explanation of the rule.

Explain how this class should be used securely by covering the following:

1. **Objects:** Describe what objects are used and how they relate to the class.
2. **Events:** Mention the relevant methods or actions defined in the rule.
3. **Order:** Explain the correct order in which methods must be called, if specified.
4. **Constraints:** Highlight any restrictions or allowed values (e.g., allowed algorithms or key sizes). Emphasize secure choices if multiple are allowed.
5. **Requires:** If the rule requires certain conditions or other object states, mention them clearly.
6. **Ensures:** State what the rule guarantees if used correctly.
7. **Forbidden Methods:** Mention any methods that must NOT be called.

Guidelines:
- Write the explanation in professional, developer-friendly English.
- Do NOT copy the rule verbatim — paraphrase and structure it naturally.
- Do NOT generate code; only generate a natural language explanation.
- If multiple valid configurations exist (e.g., keysize ∈ 3072, 4096), mention the stronger one (4096) as a preferred secure option.

CrySL Rule Input:
-----------------------------------------
Objects: {rule['objects']}
Events: {rule['events']}
Order: {rule['order']}
Constraints: {rule['constraints']}
Requires: {rule['requires']}
Ensures: {rule['ensures']}
Forbidden Methods: {rule['forbidden']}
-----------------------------------------

Now explain the correct and secure usage of `{rule['className']}`.
"""

# Call LLM (set your API key here or via environment)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

#API Call
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3
)

def clean_llm_output(text):
    if not text:
        return ""

    text = re.sub(r"(?i)```[\s]*java", "", text)     # remove ```java
    text = re.sub(r"(?i)```", "", text)              # remove remaining ```
    text = re.sub(r"\*\*", "", text)                 # remove markdown **
    text = re.sub(r"^##\s*", "", text, flags=re.MULTILINE)  # remove markdown headers (##)
    return text.strip()

raw_output = response.choices[0].message.content
cleaned_output = clean_llm_output(raw_output)
print(cleaned_output)