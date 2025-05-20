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

def build_insecure_prompt (rule: dict) -> str:
    return f'''
    You are a Java coding assistant.

    Your task is to generate an **insecure** Java code example using the class `{rule['className']}`.
    
    The CrySL rule below defines correct and secure usage. However, your goal is to create a code snippet that violates this rule while still being syntactically valid:
    
    Objects: {rule['objects']}
    Events: {rule['events']}
    Order: {rule['order']}
    Constraints: {rule['constraints']}
    Requires: {rule['requires']}
    Ensures: {rule['ensures']}
    Forbidden Methods: {rule['forbidden']}
    
    Guidelines:
    - Use parameter values that are *not* listed as valid (e.g., for RSA key size, use 1024 or 2048 instead of 3072 or 4096).
    - Break the expected method call order (e.g., call `generateKeyPair()` before `initialize()`).
    - Use any forbidden methods mentioned, if applicable.
    - Do NOT satisfy the required conditions or methods in the rule.
    
    Output Style:
    - The code must be valid Java and look realistic.
    - Include inline comments using `//` to explain **why each choice is insecure**.
      - Example: `// 2048-bit RSA is too weak for secure usage, even though valid Java`
    - Output only the annotated Java code — no extra explanation or text.
    
    Your goal is to help demonstrate **what insecure code might look like** to compare with a secure version.
    '''.strip()

def main():
    # Load rule JSON from Java
    json_file_path = sys.argv[1]
    with open(json_file_path, 'r', encoding='utf-8') as f:
        rule = json.load(f)

    # Decide secure or insecure
    example_type = rule.get("exampleType", "insecure").lower()
    label = "insecure" if "insecure" in example_type else "secure"

    # Build appropriate prompt
    if label == "insecure":
        prompt = build_insecure_prompt(rule)
    else:
        print("Error in Insecure Code Generation")

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