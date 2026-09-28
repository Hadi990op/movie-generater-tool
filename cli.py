#!/usr/bin/env python3
"""CLI: python cli.py generate <name> <synopsis> [--shots N]"""
import argparse
import sys
from pathlib import Path

from movie_generator.agnes_client import AgnesClient
from movie_generator.pipeline import MovieGenerator


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("name")
    g.add_argument("synopsis")
    g.add_argument("--shots", type=int, default=12)
    g.add_argument("--keys", default="keys.json")
    s = sub.add_parser("status")
    s.add_argument("--keys", default="keys.json")

    args = ap.parse_args()
    client = AgnesClient(keys_file=args.keys)

    if args.cmd == "status":
        for st in client.status():
            print(st)
        return

    gen = MovieGenerator(client)
    gen.generate(args.name, args.synopsis, num_shots=args.shots)


if __name__ == "__main__":
    main()
