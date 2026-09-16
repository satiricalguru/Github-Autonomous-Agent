"""Minimal real inference checks; never starts GitHub workflows."""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.ai_engine import AIEngine, extract_json_payload
from src.config import AgentConfig


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+", help="Actual agy model IDs to verify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gate = asyncio.Semaphore(2)
    async def check(model):
        async with gate:
            with tempfile.TemporaryDirectory(prefix="github-agent-model-check-") as directory:
                root = Path(directory)
                cfg = AgentConfig(ai_provider="antigravity", model_name=model, github_token=None,
                                  scratch_dir=root, repos_dir=root / "repos", state_file=root / "state.json", provider_timeout=90)
                engine = AIEngine(cfg)
                result = await engine._call_model('Return exactly the JSON object {"integration":"ok"}.')
                passed = extract_json_payload(result or "") == {"integration": "ok"}
                return {"model": model, "passed": passed, "health": engine.get_health()}
    rows = await asyncio.gather(*(check(model) for model in args.models))
    if args.output:
        args.output.write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)

asyncio.run(main())
