#!/usr/bin/env python3
"""Check effective XNU options using the same precedence as the kernel CLI."""
import argparse
import os
from pathlib import Path
from unixnu.config import parse_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--require', action='append', required=True, metavar='XNU_NAME=VALUE')
    args = parser.parse_args()
    config = parse_config(args.config.read_text())
    for item in args.require:
        name, separator, expected = item.partition('=')
        if not separator or not name.startswith('XNU_') or not expected:
            parser.error('each requirement must be XNU_NAME=VALUE')
        value = config.get(name, os.environ.get(name))
        actual = '1' if value is True else '0' if value is False else str(value) if value is not None else None
        if actual != expected:
            raise SystemExit(f'{name}: effective option {actual!r}, expected {expected!r}')
    print('effective XNU build flags verified')


if __name__ == '__main__':
    main()
