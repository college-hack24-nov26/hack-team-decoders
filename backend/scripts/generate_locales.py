"""Generate frontend locale files from the English source, once.

Run this by hand when English strings change, then commit the output. It is a
build-time tool, not a runtime path: translating the interface on every page load
would burn Sarvam credits on 130 strings that never change, and would put a
network round trip in front of the first paint.

    python scripts/generate_locales.py                # every target language
    python scripts/generate_locales.py --languages kn ta
    python scripts/generate_locales.py --dry-run      # show what would change

Why batching matters: Sarvam allows 10 requests per minute on every plan. One
request per string would be 130 calls per language — over 13 minutes each, and
hours for the full set. Strings are packed into batches under the 2000-character
limit instead, which brings a language down to about four requests.

Batching needs a delimiter, and a translation model is free to alter it. So every
batch is verified: if the number of segments coming back does not match the number
sent, that batch is retried one string at a time. A silently dropped or merged
string would put "[some.key]" on a patient's screen.

The output is machine translation and is marked as such in the file. It is a
starting point for review by someone who speaks the language, not a substitute
for it — the clinical prompts in particular deserve a second pair of eyes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

# Allow running as `python scripts/generate_locales.py` from the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.interview import languages  # noqa: E402
from app.services.translation import (  # noqa: E402
    MAX_INPUT_CHARS,
    TranslationUnavailableError,
    _translate_chunk,
)

LOCALES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"
SOURCE_LANGUAGE = "en"

#: Languages to generate. Deliberately the set Bulbul can also speak, so screen
#: text and audio cover the same languages — a principled line rather than an
#: arbitrary top-N, and it makes "full support" mean one consistent thing.
DEFAULT_TARGETS = ["bn", "mr", "te", "ta", "gu", "kn", "ml", "pa", "od"]

#: Delimiter between batched strings. Punctuation-only lines survive translation
#: far more reliably than numbering, which models like to renumber or localise.
_DELIMITER = "\n@@@\n"

#: Leave room for delimiters inside the 2000-character request limit.
_BATCH_BUDGET = MAX_INPUT_CHARS - 200

#: 10 requests/minute on all plans, so ~6.5s between calls with a little slack.
_REQUEST_INTERVAL_SECONDS = 6.5


#: i18next interpolation placeholders, e.g. ``{{name}}``.
_PLACEHOLDER = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def restore_placeholders(source: str, translated: str) -> str | None:
    """Put the English variable names back inside ``{{ }}``.

    The translator localises the variable name along with the prose: ``{{name}}``
    comes back as ``{{ಹೆಸರು}}`` in Kannada, ``{{नाव}}`` in Marathi. The braces
    survive, so nothing looks wrong, but i18next has no variable by that name and
    silently substitutes nothing — the patient's name never appears.

    Placeholders are restored positionally, which is safe only when the count
    matches. Returns ``None`` when it does not, so the caller can fall back to
    English rather than emit a string with a placeholder in the wrong slot.
    """
    source_vars = _PLACEHOLDER.findall(source)
    if not source_vars:
        return translated

    if len(_PLACEHOLDER.findall(translated)) != len(source_vars):
        return None

    remaining = iter(source_vars)
    return _PLACEHOLDER.sub(lambda _m: "{{" + next(remaining) + "}}", translated)


def repair_file(target_code: str) -> int:
    """Fix localised placeholder names in an existing locale file.

    Offline: needed because the defect is only visible after generation, and
    regenerating costs credits for 130 strings to fix a handful.
    """
    source = json.loads(
        (LOCALES_DIR / SOURCE_LANGUAGE / "translation.json").read_text(encoding="utf-8")
    )
    path = LOCALES_DIR / target_code / "translation.json"
    if not path.is_file():
        return 0

    translated = json.loads(path.read_text(encoding="utf-8"))
    english = dict(flatten(source))
    pairs = flatten({k: v for k, v in translated.items() if k != "_meta"})

    fixed: list[tuple[str, str]] = []
    changed = 0
    for key, value in pairs:
        original = english.get(key, "")
        repaired = restore_placeholders(original, value)
        if repaired is None:
            print(f"    {key}: placeholder count mismatch, using English")
            repaired = original
            changed += 1
        elif repaired != value:
            changed += 1
        fixed.append((key, repaired))

    if changed:
        payload = unflatten(fixed)
        payload["_meta"] = translated.get("_meta", {})
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def flatten(obj: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested translation JSON into dotted-path/value pairs."""
    pairs: list[tuple[str, str]] = []
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            pairs.extend(flatten(value, path))
        else:
            pairs.append((path, str(value)))
    return pairs


def unflatten(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Rebuild nested JSON from dotted-path/value pairs."""
    root: dict[str, Any] = {}
    for path, value in pairs:
        parts = path.split(".")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return root


def make_batches(texts: list[str]) -> list[list[int]]:
    """Group string indices into batches that fit one request."""
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0

    for index, text in enumerate(texts):
        cost = len(text) + len(_DELIMITER)
        # A single oversized string gets its own batch and is split downstream.
        if current and size + cost > _BATCH_BUDGET:
            batches.append(current)
            current, size = [], 0
        current.append(index)
        size += cost

    if current:
        batches.append(current)
    return batches


class _RateLimiter:
    """Spaces requests out so Sarvam does not start returning 429s."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._last = 0.0

    async def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if self._last and elapsed < self._interval:
            await asyncio.sleep(self._interval - elapsed)
        self._last = time.monotonic()


async def _translate_batch(
    client, texts: list[str], target: languages.Language, limiter: _RateLimiter
) -> list[str] | None:
    """Translate several strings in one call, or ``None`` if it came back wrong."""
    await limiter.wait()
    joined = _DELIMITER.join(texts)
    translated = await _translate_chunk(client, joined, "en-IN", target.bcp47)

    parts = [segment.strip() for segment in translated.split("@@@")]
    parts = [part for part in parts if part]

    if len(parts) != len(texts):
        return None
    return parts


async def translate_all(texts: list[str], target_code: str, *, verbose: bool = True) -> list[str]:
    """Translate every string into ``target_code``, batched and verified."""
    import httpx

    target = languages.get(target_code)
    limiter = _RateLimiter(_REQUEST_INTERVAL_SECONDS)
    results: list[str | None] = [None] * len(texts)

    async with httpx.AsyncClient(timeout=120.0) as client:
        for batch_number, indices in enumerate(make_batches(texts), start=1):
            batch = [texts[i] for i in indices]

            grouped = await _translate_batch(client, batch, target, limiter)
            if grouped is not None:
                for index, value in zip(indices, grouped, strict=True):
                    results[index] = value
                if verbose:
                    print(f"    batch {batch_number}: {len(batch)} strings")
                continue

            # Delimiter did not survive. Fall back to one call per string rather
            # than risk misaligning translations against their keys.
            if verbose:
                print(
                    f"    batch {batch_number}: delimiter lost, retrying "
                    f"{len(batch)} strings individually"
                )
            for index in indices:
                await limiter.wait()
                results[index] = await _translate_chunk(client, texts[index], "en-IN", target.bcp47)

    # Anything still missing falls back to English so the UI never shows a raw key.
    return [
        translated if translated else original
        for translated, original in zip(results, texts, strict=True)
    ]


async def generate(target_code: str, *, dry_run: bool = False) -> None:
    source_path = LOCALES_DIR / SOURCE_LANGUAGE / "translation.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    pairs = flatten(source)
    keys = [key for key, _ in pairs]
    texts = [value for _, value in pairs]

    language = languages.get(target_code)
    print(f"\n{language.english_name} ({language.code}) — {len(texts)} strings")

    if dry_run:
        print(f"    would write {LOCALES_DIR / language.code / 'translation.json'}")
        return

    translated = await translate_all(texts, language.code)

    # The model localises variable names inside {{ }}, which breaks interpolation
    # silently. Restore them before writing rather than after review.
    repaired: list[str] = []
    for original, candidate in zip(texts, translated, strict=True):
        fixed = restore_placeholders(original, candidate)
        if fixed is None:
            print("    placeholder lost, falling back to English for one string")
            fixed = original
        repaired.append(fixed)

    payload = unflatten(list(zip(keys, repaired, strict=True)))
    # Recorded in the file itself: whoever reviews this should know it started as
    # machine output, and which source it came from.
    payload["_meta"] = {
        "generatedBy": "scripts/generate_locales.py (Sarvam sarvam-translate:v1)",
        "sourceLanguage": SOURCE_LANGUAGE,
        "reviewed": "no",
    }

    out_path = LOCALES_DIR / language.code / "translation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"    wrote {out_path.relative_to(LOCALES_DIR.parents[2])}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Fix localised {{placeholder}} names in existing files. Makes no API calls.",
    )
    args = parser.parse_args()

    if args.repair:
        total = 0
        for code in args.languages:
            changed = repair_file(code)
            total += changed
            print(f"{code}: {changed} string(s) repaired")
        print(f"\nDone. {total} string(s) repaired across {len(args.languages)} locale(s).")
        return 0

    from app.services.sarvam_keys import get_pool

    if not args.dry_run and not get_pool().configured:
        print("No Sarvam API key configured. Set SARVAM_API_KEY or SARVAM_API_KEYS.")
        return 1

    for code in args.languages:
        if not languages.is_supported(code):
            print(f"Skipping unknown language {code!r}")
            continue
        try:
            await generate(code, dry_run=args.dry_run)
        except TranslationUnavailableError as exc:
            print(f"    FAILED: {exc}")
            return 1

    print("\nDone. Review the output, then register the locales in src/i18n.ts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
