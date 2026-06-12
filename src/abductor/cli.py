"""Command-line entry point for abductor."""

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # placeholder: the gate/enumeration commands land here as the tool migrates in.
    print("abductor 0.0.1 — execution-gated abductive evaluation (scaffold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
