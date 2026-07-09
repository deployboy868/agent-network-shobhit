"""
Chat with an employee's digital twin (human → agent demo).

Run:
  PYTHONPATH=. python -m agent_network.demo.talk_to_twin
  PYTHONPATH=. python -m agent_network.demo.talk_to_twin --twin emp-manager --as emp-intern
"""

from __future__ import annotations

import argparse
import logging
import sys

from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID, SAMPLE_EMPLOYEES

logging.basicConfig(level=logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description="Chat with a digital twin")
    parser.add_argument(
        "--twin",
        default=DEMO_MANAGER_ID,
        help="Whose twin to talk to (default: emp-manager)",
    )
    parser.add_argument(
        "--as",
        dest="requester",
        default=DEMO_INTERN_ID,
        help="Who you are — the person asking (default: emp-intern)",
    )
    args = parser.parse_args()

    try:
        session = TwinChatSession(args.twin, requester_employee_id=args.requester)
    except ValueError as e:
        print(f"Error: {e}")
        print("Available employees:")
        for emp in SAMPLE_EMPLOYEES:
            absent = "absent" if emp.is_absent else "present"
            print(f"  {emp.employee_id} — {emp.name} ({absent})")
        return 1

    print("=== Agent Social Network — Talk to a Twin ===\n")
    print(session.greeting())
    print("\nType 'quit' or 'exit' to leave.\n")

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if not user:
            continue
        if user.lower() in {"quit", "exit", "q"}:
            print("Bye.")
            return 0

        reply = session.handle(user)
        print(f"\nTwin: {reply}\n")


if __name__ == "__main__":
    sys.exit(main())
