"""Bedtime stories for ages 5-10: a planned, judged, read-aloud script tuned to the child's age.

    python main.py                                   # asks what story you want
    python main.py "a shy dragon who loves baking" --age 6 --name Maya
    python main.py "..." --plain                     # hide the read-aloud cues
    python main.py "..." --baseline                  # the original single call, for comparison
    python main.py "..." -v                          # show outline, judge results and revisions

Progress goes to stderr; the story goes to stdout. Each turn writes a JSON trace to runs/.
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

from storyteller.checks import strip_cues
from storyteller.config import MAX_AGE, MIN_AGE
from storyteller.llm import ClaudeClient, LLMError, require_api_key
from storyteller.pipeline import baseline, give_feedback, tell_story

"""
Before submitting the assignment, describe here in a few sentences what you would have built next if you spent 2 more hours on this project:

1. Judge calibration: a small labelled set of stories with planted flaws (a cliffhanger ending,
   a scary image, a dropped character) to measure how often the judge passes a bad story or fails
   a good one. The whole loop trusts the judge, so its error rate is the number that matters most.
2. Text-to-speech that performs the read-aloud cues: [whisper] becomes a whisper, [pause] a real
   pause, and [together: ...] waits for the child to join in.
3. Memory across nights: remember characters and refrains the child loved, so "another Bob story"
   continues a small series instead of starting from scratch.
"""

example_requests = "A story about a girl named Alice and her best friend Bob, who happens to be a cat."


def age_arg(value: str) -> int:
    age = int(value)
    if not MIN_AGE <= age <= MAX_AGE:
        raise argparse.ArgumentTypeError(f"age must be between {MIN_AGE} and {MAX_AGE}")
    return age


def show(text: str, plain: bool) -> None:
    print("\n" + (strip_cues(text) if plain else text) + "\n", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bedtime stories for ages 5-10, refined by an LLM judge.")
    parser.add_argument("request", nargs="?", help="what the story should be about")
    parser.add_argument("--age", type=age_arg, help=f"listener's age ({MIN_AGE}-{MAX_AGE}); default 7")
    parser.add_argument("--name", default="", help="listener's name (the child hearing the story)")
    parser.add_argument("--plain", action="store_true", help="hide read-aloud cues")
    parser.add_argument("--baseline", action="store_true", help="run the original single-call version")
    parser.add_argument("--seed", type=int, help="fix the random story sparks (for repeatable runs)")
    parser.add_argument("-v", "--verbose", action="store_true", help="show pipeline details")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(message)s", stream=sys.stderr)
    for noisy in ("anthropic", "httpx", "httpx2", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Short progress lines always; outline and revision notes only with -v.
    logging.getLogger("storyteller.pipeline").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    load_dotenv()

    try:
        require_api_key()  # fail before asking for a story, not after
        request = args.request or input("What kind of story do you want to hear? ").strip() or example_requests
        if args.baseline:
            show(baseline(ClaudeClient(), request), plain=False)
            return

        result = tell_story(lambda hook: ClaudeClient(on_usage=hook), request,
                            age=args.age, name=args.name, seed=args.seed)
        while True:
            if result.status == "story":
                show(result.text, args.plain)
            else:
                print(f"\n{result.message}\n", flush=True)
            if result.session.story is None:  # nothing to revise (redirect, unsafe or error)
                sys.exit(1 if result.status == "error" else 0)
            change = input("Any changes? (press Enter to finish) ").strip()
            if not change:
                break
            result = give_feedback(lambda hook: ClaudeClient(on_usage=hook), result.session, change)
    except (KeyboardInterrupt, EOFError):
        print()
        return
    except LLMError as e:
        sys.exit(str(e))
    print("Sweet dreams!")


if __name__ == "__main__":
    main()
