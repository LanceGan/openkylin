import argparse
import json
from pathlib import Path

from kylinbootlab.contracts import ProbeManifest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/kylinbootlab/schemas/probe-manifest-v1.schema.json"


def rendered_schema() -> str:
    schema = ProbeManifest.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://kylinbootlab.dev/schema/probe-manifest-v1.json"
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schema()

    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("probe manifest schema is stale; run scripts/export_schema.py")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
