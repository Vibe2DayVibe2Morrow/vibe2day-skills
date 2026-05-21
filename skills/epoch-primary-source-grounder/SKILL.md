---
name: epoch-primary-source-grounder
description: "Use when writing Epoch VO scripts and you need primary-source grounding instead of model-averaged history. Resolves a figure name to Wikipedia canonical + Wikidata structured facts, surfaces Wikisource works by the figure, and pulls digitized period biographies from Internet Archive. Output is shaped to feed the six-scene Epoch story arc (Origin -> Rise -> Defining Act -> Crisis -> Mature Power -> Legacy). Stdlib-only Python, no paid APIs, no authentication required."
---

# Epoch Primary Source Grounder

## Overview

Use this skill when writing a 48-second biographical VO for the Epoch channel and you need to ground the script in primary or contemporary sources rather than the model's averaged historical knowledge. The skill resolves a figure name, fetches structured Wikidata facts (birth/death dates, places, occupations, notable works), surfaces works BY the figure from Wikisource where they exist, and pulls digitized period biographies from Internet Archive.

The output is shaped to feed the Epoch six-scene story arc and to be cross-checkable against an audit trail. Every claim in the final VO should be traceable back to a URL in the source bundle.

## Quick Start

Run the helper script directly:

```bash
python3 "$HOME/.codex/skills/epoch-primary-source-grounder/scripts/source_grounder.py" --help
```

Common commands:

```bash
python3 "$HOME/.codex/skills/epoch-primary-source-grounder/scripts/source_grounder.py" \
  ground "Confucius" --json

python3 "$HOME/.codex/skills/epoch-primary-source-grounder/scripts/source_grounder.py" \
  resolve "Marie Curie"

python3 "$HOME/.codex/skills/epoch-primary-source-grounder/scripts/source_grounder.py" \
  archive "Abraham Lincoln" --limit 8 --year-before 1920

python3 "$HOME/.codex/skills/epoch-primary-source-grounder/scripts/source_grounder.py" \
  wikisource "Marcus Aurelius"
```

## Workflow

### 1. Resolve canonical name and structured facts

Start with `resolve` to canonicalize the figure name and pull structured Wikidata facts.

- Returns: canonical Wikipedia title, birth/death dates and places, occupations, notable works, one-paragraph Wikipedia summary, Wikimedia thumbnail URL.
- Use `--json` when the output will be analyzed downstream.
- Verify the canonical name and dates match what's already in your `seedData.js` before proceeding. Wikipedia disambiguation is the first failure mode.

### 2. Surface works BY the figure (Wikisource)

Use `wikisource` if the figure was a writer, philosopher, scientist, or statesman whose own writings exist in the public domain.

- Returns the Wikisource Author: page URL and a list of linked works with direct text URLs.
- Skip this for figures without surviving writings (most pre-literate figures, most figures whose works haven't been digitized in English).
- Quoted passages from primary works are usually the strongest grounding signal for the "Defining Act" or "Legacy" scenes.

### 3. Pull period biographies (Internet Archive)

Use `archive` to find digitized biographies, contemporary accounts, and period scholarly works.

- Filter with `--year-before` (e.g. 1930) to bias toward public-domain 19th/early-20th century scholarship.
- Sorted by download count so well-OCR'd, well-used scans surface first.
- Don't fetch full text from the script. Return URLs, let the writer (or downstream agent) pull selectively from the most promising items.

### 4. Full grounding pass

Use `ground` to chain resolve -> wikisource -> archive in one call. Returns a consolidated bundle suitable for feeding to the VO writer.

The bundle contains:

- `figure`: canonical name, dates, places, summary, portrait URL, occupations, notable works
- `works_by_figure`: list of Wikisource works (if applicable)
- `period_sources`: top N Internet Archive items with creator + year + URL
- `story_arc_seeds`: empty stub for Origin / Rise / Defining Act / Crisis / Mature Power / Legacy. Populate manually during VO writing; do NOT auto-generate.

### 5. Synthesize in-chat

After running the script, do the actual VO writing in the chat:

- Map facts to the six-scene arc: Origin -> Rise -> Defining Act -> Crisis -> Mature Power -> Legacy
- Apply the VO timing formula on each line: `seconds = words * 0.40 + commas * 0.15 + stops * 0.30` (stops = . - : ? !). Target 14-16 words per line, each <= 7.0s.
- House style is non-negotiable: years spelled out ("Lu, five-fifty-one BCE"), place first then person, last line lands the legacy, em-dashes and periods carry weight.
- Cross-check every concrete claim against the source bundle before committing. If a fact isn't grounded, drop it or mark it as inferred. Never fabricate quotes.
- Defensive framing for figures with Veo content-filter risk (real political figures, children, battles): see the Epoch memory for the standard workarounds.

## Output Guidance

- Prefer `--json` when feeding output to the VO writer agent or a downstream timing script.
- Prefer plain output when scanning sources manually before drafting.
- Source bundles can grow; the script truncates summary fields to keep context tight. Bump `--excerpt-chars` only if you specifically need fuller text.
- Always preserve Wikisource and Internet Archive URLs in the output. They are the audit trail when the episode ships to the YouTube channel.
- The Wikimedia thumbnail URL belongs on the figure's `/credits` attribution row, not in the VO output itself.

## Keys

This skill uses only public APIs that require no authentication:

- Wikipedia REST API (`en.wikipedia.org/api/rest_v1`)
- Wikipedia Action API (`en.wikipedia.org/w/api.php`)
- Wikidata Action API (`www.wikidata.org/w/api.php`)
- Wikisource Action API (`en.wikisource.org/w/api.php`)
- Internet Archive Advanced Search (`archive.org/advancedsearch.php`)

Set `EPOCH_GROUNDER_USER_AGENT` to identify your project. Wikipedia asks for a descriptive User-Agent on programmatic traffic. Default is `EpochAtlas-Grounder/0.1 (https://epoch-time-atlas.base44.app)`.

The script paces requests at 5/sec per host and backs off automatically on 429 with `Retry-After` respected.

## References

- `references/api-notes.md` for endpoint reminders and parameter notes
- Epoch house-style spec lives in the memory file: VO timing formula, six-scene story arc, brand stack, image style, Veo content filter workarounds
- `https://epoch-time-atlas.base44.app/credits` for the Wikimedia attribution pattern this skill respects
