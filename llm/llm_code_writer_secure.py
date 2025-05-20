import sys
import json
import openai
import os
from dotenv import load_dotenv
from openai import OpenAI

"""
    @author: Roshan Samantaray
"""

load_dotenv()

def build_secure_prompt (rule: dict) -> str:
    return f'''
    You are a secure Java coding assistant.

    Your task is to generate a **secure** Java code example using the class `{rule['className']}`.
    
    Use only the CrySL rule below as the authoritative source of correct and secure usage patterns:
    
    Objects: {rule['objects']}
    Events: {rule['events']}
    Order: {rule['order']}
    Constraints: {rule['constraints']}
    Requires: {rule['requires']}
    Ensures: {rule['ensures']}
    Forbidden Methods: {rule['forbidden']}
    
    Guidelines:
    - All parameters (e.g., key sizes, algorithms) **must strictly match** the CrySL rule constraints.
    - If multiple allowed values are listed (e.g., keysize ∈ 3072, 4096), always choose the **strongest / highest** secure value.
    - Do not use values like 2048 if they are not explicitly allowed.
    - Include short inline comments using `//` to explain why each usage is secure.
    - Output only Java code — no extra prose or explanation.
    
    Ensure the code is syntactically correct and demonstrates the most secure, compliant usage of this API.
    '''.strip()

def main():
    # Load rule JSON from Java
    json_file_path = sys.argv[1]
    with open(json_file_path, 'r', encoding='utf-8') as f:
        rule = json.load(f)

    # Decide secure or insecure
    example_type = rule.get("exampleType", "secure").lower()
    label = "secure" if "secure" in example_type else "insecure"

    # Build appropriate prompt
    if label == "secure":
        prompt = build_secure_prompt(rule)
    else:
        print("Error in Secure Code Generation")

    # Call LLM
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    # Output generated Java code
    print(response.choices[0].message.content)

if __name__=="__main__":
    main()