import argparse
import json
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from utils.gateway_rate_limit import wait_for_gateway_slot

"""
    @author: Roshan Samantaray
"""

DEFAULT_GATEWAY_BASE_URL = "https://ai-gateway.uni-paderborn.de/v1/"
DEFAULT_GATEWAY_CHAT_MODEL = "gwdg.qwen3-30b-a3b-instruct-2507"
OPENAI_DEFAULT_CHAT_MODEL = "gpt-4o-mini"

# Load environment variables for API access.
load_dotenv()


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        raise RuntimeError(f"{var_name} is not set.")
    return value


def _build_client(backend: str) -> OpenAI:
    if backend == "openai":
        return OpenAI(api_key=_require_env("OPENAI_API_KEY"))
    api_key = _require_env("GATEWAY_API_KEY")
    base_url = os.getenv("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL).strip() or DEFAULT_GATEWAY_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url)


def _resolve_chat_model(backend: str, cli_model: Optional[str]) -> str:
    if cli_model and cli_model.strip():
        return cli_model.strip()
    if backend == "openai":
        return OPENAI_DEFAULT_CHAT_MODEL
    return os.getenv("GATEWAY_CHAT_MODEL", "").strip() or DEFAULT_GATEWAY_CHAT_MODEL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate insecure Java examples from CrySL payloads.")
    parser.add_argument("json_path", help="Path to the temp JSON produced by the Java pipeline.")
    parser.add_argument(
        "--rules-dir",
        default="",
        help="Unused in insecure writer; accepted for Java-side argument compatibility.",
    )
    parser.add_argument(
        "--backend",
        choices=["openai", "gateway"],
        required=True,
        help="LLM backend selected by the Java pipeline.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Override chat model. In gateway mode, fallback is "
            "GATEWAY_CHAT_MODEL or the default gwdg.qwen3-30b-a3b-instruct-2507."
        ),
    )
    return parser.parse_args()


# Build a prompt that instructs the LLM to violate the CrySL rule intentionally.
def build_insecure_prompt(rule: dict) -> str:
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


# CLI entrypoint: load rule JSON, build prompt, call LLM, print Java.
def main():
    args = parse_args()
    with open(args.json_path, "r", encoding="utf-8") as f:
        rule = json.load(f)

    # Decide secure or insecure (this script expects insecure by default)
    example_type = rule.get("exampleType", "insecure").lower()
    label = "insecure" if "insecure" in example_type else "secure"

    if label != "insecure":
        print("Error in Insecure Code Generation: expected insecure payload.", file=sys.stderr)
        sys.exit(1)

    prompt = build_insecure_prompt(rule)
    try:
        model = _resolve_chat_model(args.backend, args.model)
        client = _build_client(args.backend)
    except Exception as exc:
        print(f"Backend/model configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.backend == "gateway":
        wait_for_gateway_slot("chat.completions")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    # Output generated Java code
    print(response.choices[0].message.content)


# Standard entry guard for CLI usage.
if __name__ == "__main__":
    main()
