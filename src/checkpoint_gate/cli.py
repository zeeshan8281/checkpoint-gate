from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import read_json, write_json


def main():
    parser = argparse.ArgumentParser(prog="checkpoint-gate")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Freeze generated train/dev/test datasets")
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--per-family", type=int, default=50)
    generate.add_argument("--seed", type=int, default=20261119)
    demo = commands.add_parser("demo", help="Run scripted infrastructure checks; no model or cloud calls")
    demo.add_argument("--data", type=Path, required=True)
    demo.add_argument("--out", type=Path, required=True)
    for name in ("preflight", "smoke", "run"):
        p = commands.add_parser(name)
        p.add_argument("--config", type=Path, default=Path("configs/pilot.json"))
        if name == "preflight":
            p.add_argument("--out", type=Path)
        else:
            p.add_argument("--data", type=Path, required=True)
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--cloud-url")
            p.add_argument("--execute-paid-run", action="store_true",
                           help="Required execution switch; preflight alone never provisions")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            from .dataset import generate
            result = generate(args.out, per_family=args.per_family, seed=args.seed)
            print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
        elif args.command == "demo":
            from .campaign import demo
            result = demo(args.data, args.out)
            print(result["warning"])
            print(json.dumps({k: v["summary"] for k, v in result["conditions"].items()}, indent=2))
        else:
            from .campaign import execute, smoke, validate_config
            from .baseten_backend import preflight
            config = read_json(args.config)
            validate_config(config)
            if args.command == "preflight":
                result = preflight(config)
                if args.out:
                    write_json(args.out, result)
                print(json.dumps(result, indent=2))
            else:
                if not args.execute_paid_run:
                    parser.error("run requires --execute-paid-run; use preflight for an account check")
                if args.command == "smoke":
                    print(json.dumps(smoke(args.data, args.out, config), indent=2))
                else:
                    print(json.dumps(execute(args.data, args.out, config, cloud_url=args.cloud_url), indent=2))
    except (ValueError, RuntimeError, FileExistsError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
