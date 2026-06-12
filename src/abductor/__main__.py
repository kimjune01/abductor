"""Enable `python -m abductor` as a fallback when the PATH shim is unavailable."""

from abductor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
