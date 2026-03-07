#!/usr/bin/env python3
import argparse
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI


DEFAULT_GATEWAY_BASE_URL = "https://ai-gateway.uni-paderborn.de/v1/"


def _print_ok(message: str) -> None:
    print(f"[OK] {message}")


def _print_fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)


def _require(value: str, name: str) -> str:
    if value:
        return value
    raise RuntimeError(f"{name} is not set.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Minimal UPB AI-Gateway connectivity test (models/chat/embeddings)."
    )
    parser.add_argument(
        "--chat-model",
        default=os.getenv("GATEWAY_CHAT_MODEL", ""),
        help="Gateway chat model (default: GATEWAY_CHAT_MODEL env var).",
    )
    parser.add_argument(
        "--emb-model",
        default=os.getenv("GATEWAY_EMB_MODEL", ""),
        help="Gateway embedding model (default: GATEWAY_EMB_MODEL env var).",
    )
    parser.add_argument(
        "--chat-prompt",
        default="Say hello in one sentence.",
        help="Prompt used for the chat completion test.",
    )
    parser.add_argument(
        "--emb-text",
        default="CrySL rules define correct crypto API usage.",
        help="Input text used for the embeddings test.",
    )
    parser.add_argument(
        "--skip-models",
        action="store_true",
        help="Skip GET /models test.",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Skip chat completion test.",
    )
    parser.add_argument(
        "--skip-emb",
        action="store_true",
        help="Skip embeddings test.",
    )
    args = parser.parse_args()

    load_dotenv()

    api_key = os.getenv("GATEWAY_API_KEY")
    base_url = os.getenv("GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL)

    try:
        api_key = _require(api_key, "GATEWAY_API_KEY")
    except RuntimeError as exc:
        _print_fail(str(exc))
        return 2

    client = OpenAI(api_key=api_key, base_url=base_url)
    _print_ok(f"Client created for base URL: {base_url}")

    failures = 0

    if not args.skip_models:
        try:
            models = client.models.list()
            ids = [m.id for m in models.data]
            _print_ok(f"/models reachable, returned {len(ids)} models.")
            if ids:
                print("  sample:", ", ".join(ids[:5]))
        except Exception as exc:
            failures += 1
            _print_fail(f"/models failed: {exc}")

    if not args.skip_chat:
        if not args.chat_model:
            failures += 1
            _print_fail("Chat test requires --chat-model or GATEWAY_CHAT_MODEL.")
        else:
            try:
                resp = client.chat.completions.create(
                    model=args.chat_model,
                    messages=[
                        {"role": "developer", "content": "You are a helpful assistant."},
                        {"role": "user", "content": args.chat_prompt},
                    ],
                    temperature=0.2,
                )
                text = (resp.choices[0].message.content or "").strip()
                _print_ok(f"Chat completion succeeded with model: {args.chat_model}")
                print("  response:", text[:200] if text else "<empty>")
            except Exception as exc:
                failures += 1
                _print_fail(f"Chat test failed ({args.chat_model}): {exc}")

    if not args.skip_emb:
        if not args.emb_model:
            failures += 1
            _print_fail("Embedding test requires --emb-model or GATEWAY_EMB_MODEL.")
        else:
            try:
                resp = client.embeddings.create(model=args.emb_model, input=[args.emb_text])
                dim = len(resp.data[0].embedding)
                _print_ok(f"Embeddings succeeded with model: {args.emb_model} (dim={dim})")
            except Exception as exc:
                failures += 1
                _print_fail(f"Embedding test failed ({args.emb_model}): {exc}")

    if failures:
        _print_fail(f"{failures} test(s) failed.")
        return 1

    _print_ok("All requested gateway tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
