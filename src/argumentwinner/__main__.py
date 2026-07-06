"""Entry point.

  python -m argumentwinner            run the Discord bot
  python -m argumentwinner --repl     run the terminal REPL
  python -m argumentwinner --desktop  run the desktop helper (clipboard + hotkey)
"""

from __future__ import annotations

import argparse
import asyncio

from argumentwinner.container import build_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="argumentwinner")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--repl", action="store_true", help="run the terminal REPL instead of the Discord bot"
    )
    mode.add_argument(
        "--desktop",
        action="store_true",
        help="run the desktop helper (clipboard + hotkey; works in any app)",
    )
    args = parser.parse_args()

    app = build_app()
    if args.repl:
        from argumentwinner.adapters.cli.repl import run_repl

        asyncio.run(run_repl(app))
    elif args.desktop:
        from argumentwinner.adapters.desktop.helper import run_desktop

        run_desktop(app)
    else:
        from argumentwinner.adapters.discord.bot import run_bot

        run_bot(app)


if __name__ == "__main__":
    main()
