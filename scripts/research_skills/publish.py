"""把采集结果整理成运行时科研技能目录。

分类规则直接复用运行时的 ``src/utils/research_catalog``，避免两处定义漂移。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (str(ROOT), str(SCRIPT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from src.utils.research_catalog import CATEGORIES, SCHEMA_VERSION, classify  # noqa: E402
from sources import EXCLUDED_SKILL_NAMES  # noqa: E402

# 单个技能在目录里最多记多少个文件，避免个别超大技能把目录撑爆
_MAX_SKILL_FILES = 80


def build_catalog(collected: dict) -> dict:
    """把采集结果整理成目录结构；同名技能只保留首次出现的一条。"""
    skills = []
    seen = set()
    excluded = []
    for raw in collected.get("skills", []):
        name = str(raw.get("name") or "").strip()
        source = raw.get("source") or {}
        if not name or not source.get("repository") or not source.get("commit"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if key in EXCLUDED_SKILL_NAMES:
            excluded.append(name)
            continue
        description = str(raw.get("description") or "").strip()
        category = classify(name, description)
        files = [
            str(item).strip() for item in (raw.get("files") or []) if str(item).strip()
        ]
        if len(files) > _MAX_SKILL_FILES:
            kept = ["SKILL.md"] if "SKILL.md" in files else []
            rest = [item for item in files if item != "SKILL.md"]
            kept += rest[: _MAX_SKILL_FILES - len(kept)]
            files = sorted(kept)
        skills.append(
            {
                "name": name,
                "description": description,
                "category": category,
                "category_zh": CATEGORIES.get(category, CATEGORIES["unclassified"]),
                "license": str(raw.get("license") or "").strip(),
                "files": files,
                "source": {
                    "repository": source["repository"],
                    "commit": source["commit"],
                    "path": source.get("path", ""),
                    "url": source.get("url", ""),
                },
            }
        )

    sources = {}
    for skill in skills:
        source = skill["source"]
        entry = sources.setdefault(
            source["repository"],
            {
                "repository": source["repository"],
                "commit": source["commit"],
                "skill_count": 0,
            },
        )
        entry["skill_count"] += 1

    categories = {}
    for skill in skills:
        categories[skill["category"]] = categories.get(skill["category"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories": CATEGORIES,
        "category_counts": categories,
        "excluded_count": len(excluded),
        "sources": sorted(sources.values(), key=lambda item: item["repository"]),
        "skills": skills,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成运行时科研技能目录")
    parser.add_argument("--input", type=Path, required=True, help="采集结果 JSON")
    parser.add_argument("--output", type=Path, required=True, help="目录输出路径")
    args = parser.parse_args()

    collected = json.loads(args.input.read_text(encoding="utf-8"))
    catalog = build_catalog(collected)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    print(
        f"目录条目 {len(catalog['skills'])} 个，来源仓库 {len(catalog['sources'])} 个"
    )
    for category, count in sorted(
        catalog["category_counts"].items(), key=lambda item: -item[1]
    ):
        print(f"  {CATEGORIES.get(category, category):<16} {count}")
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
