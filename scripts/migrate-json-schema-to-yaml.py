#!/usr/bin/env python3
"""
Convert legacy JSON Schema files to YAML Schema files.

The conversion is intentionally mechanical:
  - ``definitions`` -> ``$defs`` and ``#/definitions/...`` -> ``#/$defs/...``
  - one legacy regex is rewritten to syntax accepted by both Python and Rust
  - composition branches that only contain ``required`` get ``type: object``

The last two changes are needed for the schema to be usable with both Python
``jsonschema`` and the Rust ``ys`` validator. They do not change the result for
the object schemas in this repository.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

VERSIONS_FILE = "VERSIONS"
DEFAULT_DEFINITIONS_DIR = "definitions"

COMPOSITION_KEYWORDS = ("oneOf", "anyOf", "allOf")


class IndentDumper(yaml.SafeDumper):
    """Indent block sequences to match the repository's yamllint config."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)

# Rust's regex crate rejects the original character class. This equivalent
# spelling works in both Python's re module and Rust's regex crate.
PATTERN_FIX = {
    r"^((\$raw)|[A-Za-z0-9.\-_[\]]*)$": r"^((\$raw)|[A-Za-z0-9._\[\]-]*)$",
}


def load_version_config(path=VERSIONS_FILE):
    versions = {
        "MIN_VERSION": 11,
        "MAX_VERSION": 12,
    }
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                try:
                    versions[key] = int(value)
                except ValueError:
                    pass
    except FileNotFoundError:
        print(f"Warning: {path} not found, using defaults", file=sys.stderr)
    return versions


def convert_node(node):
    if isinstance(node, dict):
        converted = {}
        for key, value in node.items():
            if key == "definitions":
                converted["$defs"] = convert_node(value)
            elif key == "$ref" and isinstance(value, str) and value.startswith("#/definitions/"):
                converted[key] = "#/$defs/" + value[len("#/definitions/") :]
            elif key == "pattern" and isinstance(value, str) and value in PATTERN_FIX:
                converted[key] = PATTERN_FIX[value]
            elif key == "patternProperties" and isinstance(value, dict):
                converted[key] = {
                    PATTERN_FIX.get(pattern, pattern): convert_node(subschema)
                    for pattern, subschema in value.items()
                }
            elif key in COMPOSITION_KEYWORDS and isinstance(value, list):
                branches = []
                for branch in value:
                    branch = convert_node(branch)
                    if isinstance(branch, dict) and "required" in branch and "type" not in branch:
                        branch = {"type": "object", **branch}
                    branches.append(branch)
                converted[key] = branches
            else:
                converted[key] = convert_node(value)
        return converted
    if isinstance(node, list):
        return [convert_node(item) for item in node]
    return node


def convert_schema(json_path, yaml_path, remove_json=False):
    with open(json_path, "r", encoding="utf-8") as handle:
        original = json.load(handle)

    converted = convert_node(original)
    if "definitions" in converted:
        raise ValueError(f"{json_path} still contains 'definitions'")
    if "$defs" not in converted:
        raise ValueError(f"{json_path} has no 'definitions'/'$defs' to migrate")

    text = yaml.dump(
        converted,
        Dumper=IndentDumper,
        sort_keys=False,
        default_flow_style=None,
        allow_unicode=True,
        width=1000000,
    )
    with open(yaml_path, "w", encoding="utf-8") as handle:
        handle.write("---\n" + text)

    # Verify that the emitted YAML parses and matches what we intended to write.
    with open(yaml_path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if loaded != converted:
        raise ValueError(f"{yaml_path} does not round-trip to the converted schema")

    if remove_json:
        os.remove(json_path)

    return yaml_path


def main():
    parser = argparse.ArgumentParser(description="Convert JSON Schema files to YAML Schema files")
    parser.add_argument("versions", nargs="*", type=int, help="Schema versions to convert")
    parser.add_argument(
        "--definitions-dir",
        default=DEFAULT_DEFINITIONS_DIR,
        help=f"Definitions directory (default: {DEFAULT_DEFINITIONS_DIR})",
    )
    parser.add_argument("--all", action="store_true", help="Convert all version directories")
    parser.add_argument(
        "--remove-json",
        action="store_true",
        help="Remove the source schema.json after writing schema.yaml",
    )
    args = parser.parse_args()

    if args.versions:
        versions = args.versions
    elif args.all:
        versions = [
            int(path.name[1:])
            for path in Path(args.definitions_dir).glob("v*")
            if path.is_dir() and path.name[1:].isdigit()
        ]
    else:
        config = load_version_config()
        versions = list(range(config["MIN_VERSION"], config["MAX_VERSION"] + 1))

    converted = 0
    for version in sorted(versions):
        version_dir = Path(args.definitions_dir) / f"v{version}"
        json_path = version_dir / "schema.json"
        yaml_path = version_dir / "schema.yaml"

        if not json_path.exists():
            if yaml_path.exists():
                print(f"v{version}: already converted")
            else:
                print(f"v{version}: no schema.json found, skipping")
            continue

        convert_schema(json_path, yaml_path, remove_json=args.remove_json)
        print(f"v{version}: wrote {yaml_path}" + (" and removed schema.json" if args.remove_json else ""))
        converted += 1

    print(f"Converted {converted} schema(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
