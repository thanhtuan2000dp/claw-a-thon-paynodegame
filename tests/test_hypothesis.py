"""Multi-turn Hypothesis Checker smoke test (live LLM + Google Play).

Simulates a conversation: a vague claim -> the agent asks for missing context ->
the user fills it -> the agent returns a data-backed verdict. Run:

  ./venv/bin/python tests/test_hypothesis.py
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["CONVERSATION_DIR"] = "/tmp/hc_convo"
shutil.rmtree("/tmp/hc_convo", ignore_errors=True)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(override=True)

from core.deps import build_deps  # noqa: E402
from outputs.markdown import MarkdownOutput  # noqa: E402
from usecases.uc_hypothesis_check import HypothesisCheckUseCase  # noqa: E402


class Ctx:
    def __init__(self, sid):
        self.session_id = sid


def main():
    deps = build_deps()
    uc = HypothesisCheckUseCase()
    ctx = Ctx("hc-test-1")
    md = MarkdownOutput()

    turns = [
        "Tôi nghĩ bản cập nhật gần đây làm tụt rating của Instagram (package com.instagram.android)",
        "Trên Android, build mới nhất, do lỗi đăng nhập (login)",
        "rating giảm, do lỗi đăng nhập",
    ]
    for i, msg in enumerate(turns, 1):
        res = uc.run({"statement": msg}, deps, ctx)
        print(f"===== TURN {i}: {msg!r}")
        print("status:", res.get("status"))
        print(md.render(res))
        print()
        if res.get("status") == "complete":
            print(">>> verdict:", res.get("verdict"), "| confidence:", res.get("confidence"))
            break


if __name__ == "__main__":
    main()
