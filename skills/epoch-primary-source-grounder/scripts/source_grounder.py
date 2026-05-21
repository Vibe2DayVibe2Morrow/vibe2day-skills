#!/usr/bin/env python3
"""Epoch primary-source grounder.

Resolves a historical figure name to Wikipedia canonical, fetches structured
Wikidata facts (birth/death dates and places, occupations, notable works),
surfaces works BY the figure from Wikisource, and pulls digitized period
biographies from Internet Archive. Output is shaped to feed the Epoch
six-scene story arc and produce an auditable source bundle so the VO can
ground concrete claims in real evidence.

Stdlib only. No paid APIs. No authentication. Respects Wikipedia and Internet
Archive rate limits.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import textwrap
import time
import urllib.parse as urlparse_mod
from collections import deque
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WIKIPEDIA_REST_BASE = "https://en.wikipedia.org/api/rest_v1"
WIKIPEDIA_ACTION_BASE = "https://en.wikipedia.org/w/api.php"
WIKISOURCE_ACTION_BASE = "https://en.wikisource.org/w/api.php"
WIKIDATA_ACTION_BASE = "https://www.wikidata.org/w/api.php"
ARCHIVE_SEARCH_BASE = "https://archive.org/advancedsearch.php"

DEFAULT_USER_AGENT = os.environ.get(
    "EPOCH_GROUNDER_USER_AGENT",
    "EpochAtlas-Grounder/0.1 (https://epoch-time-atlas.base44.app)",
)

# Per-host rate limit: 5 requests per second.
RATE_LIMIT_WINDOW = 1.0
RATE_LIMIT_MAX = 5
_host_request_log: dict[str, deque[float]] = {}


class ApiError(RuntimeError):
    """Raised when an API call fails irrecoverably."""


def _host_of(url: str) -> str:
    return urlparse_mod.urlparse(url).netloc


def _wait_for_rate_limit(host: str) -> None:
    log = _host_request_log.setdefault(host, deque(maxlen=RATE_LIMIT_MAX * 2))
    now = time.time()
    while log and now - log[0] > RATE_LIMIT_WINDOW:
        log.popleft()
    if len(log) >= RATE_LIMIT_MAX:
        wait_seconds = RATE_LIMIT_WINDOW - (now - log[0])
        if wait_seconds > 0:
            time.sleep(wait_seconds)
    log.append(time.time())


def _build_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def api_get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET JSON with stdlib only, rate limiting, retries on 429 / transient errors."""
    query = urlencode(
        {k: v for k, v in (params or {}).items() if v is not None},
        doseq=True,
    )
    full_url = f"{url}?{query}" if query else url
    host = _host_of(url)
    _wait_for_rate_limit(host)

    base_headers = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if headers:
        base_headers.update(headers)

    for attempt in range(4):
        request = Request(full_url, headers=base_headers, method="GET")
        try:
            with urlopen(request, timeout=30, context=_build_ssl_context()) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 3:
                retry_after = exc.headers.get("Retry-After")
                sleep_seconds = float(retry_after) if retry_after else float(2 ** attempt)
                time.sleep(sleep_seconds)
                continue
            if exc.code == 404:
                return {}
            raise ApiError(f"{exc.code} {exc.reason}: {body.strip()[:500]}") from exc
        except URLError as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"Network error: {exc.reason}") from exc
    raise ApiError("Request failed after retries.")


def truncate(text: str | None, max_chars: int) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1].rstrip() + "..."


# ---------- Wikipedia ----------

def wikipedia_search_title(name: str) -> str | None:
    """Search Wikipedia for the best matching canonical title."""
    payload = api_get_json(
        WIKIPEDIA_ACTION_BASE,
        {
            "action": "query",
            "list": "search",
            "srsearch": name,
            "srlimit": 5,
            "format": "json",
        },
    )
    hits = (payload.get("query") or {}).get("search") or []
    if not hits:
        return None
    return hits[0].get("title")


def wikipedia_summary(title: str) -> dict[str, Any]:
    """Return the REST API page summary for a canonical title."""
    safe_title = urlparse_mod.quote(title.replace(" ", "_"), safe="")
    url = f"{WIKIPEDIA_REST_BASE}/page/summary/{safe_title}"
    return api_get_json(url)


def wikipedia_wikidata_id(title: str) -> str | None:
    """Resolve a Wikipedia title to its Wikidata QID."""
    payload = api_get_json(
        WIKIPEDIA_ACTION_BASE,
        {
            "action": "query",
            "prop": "pageprops",
            "titles": title,
            "format": "json",
        },
    )
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None


# ---------- Wikidata ----------

def _wikidata_time(claim: dict[str, Any]) -> tuple[str | None, int | None]:
    snak = claim.get("mainsnak") or {}
    if snak.get("snaktype") != "value":
        return None, None
    value = (snak.get("datavalue") or {}).get("value") or {}
    return value.get("time"), value.get("precision")


def _wikidata_entity_id(claim: dict[str, Any]) -> str | None:
    snak = claim.get("mainsnak") or {}
    if snak.get("snaktype") != "value":
        return None
    value = (snak.get("datavalue") or {}).get("value") or {}
    return value.get("id")


def _wikidata_labels(qids: list[str]) -> dict[str, str]:
    """Batch-fetch English labels for a list of QIDs (max 50 per request)."""
    if not qids:
        return {}
    labels: dict[str, str] = {}
    for i in range(0, len(qids), 50):
        batch = qids[i : i + 50]
        payload = api_get_json(
            WIKIDATA_ACTION_BASE,
            {
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": "labels",
                "languages": "en",
                "format": "json",
            },
        )
        entities = payload.get("entities") or {}
        for qid in batch:
            entity = entities.get(qid) or {}
            label = ((entity.get("labels") or {}).get("en") or {}).get("value")
            if label:
                labels[qid] = label
    return labels


def wikidata_facts(qid: str) -> dict[str, Any]:
    """Pull birth/death dates, places, occupations, notable works from Wikidata."""
    payload = api_get_json(
        WIKIDATA_ACTION_BASE,
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims",
            "format": "json",
        },
    )
    entity = (payload.get("entities") or {}).get(qid) or {}
    claims = entity.get("claims") or {}

    def first_time(prop: str) -> tuple[str | None, int | None]:
        for claim in claims.get(prop) or []:
            t, prec = _wikidata_time(claim)
            if t:
                return t, prec
        return None, None

    def collect_qids(prop: str, limit: int = 5) -> list[str]:
        out: list[str] = []
        for claim in (claims.get(prop) or [])[:limit]:
            qid_val = _wikidata_entity_id(claim)
            if qid_val:
                out.append(qid_val)
        return out

    birth_q = collect_qids("P19", 1)
    death_q = collect_qids("P20", 1)
    occ_q = collect_qids("P106", 5)
    works_q = collect_qids("P800", 5)
    field_q = collect_qids("P101", 5)

    all_qids = birth_q + death_q + occ_q + works_q + field_q
    labels = _wikidata_labels(list(dict.fromkeys(all_qids)))

    birth_time, birth_prec = first_time("P569")
    death_time, death_prec = first_time("P570")

    return {
        "birth_date_raw": birth_time,
        "birth_date_precision": birth_prec,
        "death_date_raw": death_time,
        "death_date_precision": death_prec,
        "birth_place": labels.get(birth_q[0]) if birth_q else None,
        "death_place": labels.get(death_q[0]) if death_q else None,
        "occupations": [labels[q] for q in occ_q if q in labels],
        "notable_works": [labels[q] for q in works_q if q in labels],
        "fields_of_work": [labels[q] for q in field_q if q in labels],
    }


def format_wikidata_time(time_str: str | None, precision: int | None) -> str | None:
    """Render a Wikidata time string with BCE/CE and appropriate precision.

    Wikidata precision codes (relevant ones):
      9  = year
      10 = month
      11 = day
    """
    if not time_str:
        return None
    match = re.match(r"^([+-])0*(\d+)-(\d{2})-(\d{2})T", time_str)
    if not match:
        return time_str
    sign, year, month, day = match.groups()
    year_int = int(year)
    era = "BCE" if sign == "-" else "CE"
    if precision is None or precision <= 9:
        return f"{year_int} {era}"
    if precision == 10:
        return f"{year_int}-{month} {era}"
    return f"{year_int}-{month}-{day} {era}"


# ---------- Wikisource ----------

def wikisource_author_page(name: str) -> str | None:
    """Find the Wikisource Author: page for a figure (namespace 102)."""
    payload = api_get_json(
        WIKISOURCE_ACTION_BASE,
        {
            "action": "query",
            "list": "search",
            "srsearch": f"Author:{name}",
            "srnamespace": 102,
            "srlimit": 5,
            "format": "json",
        },
    )
    hits = (payload.get("query") or {}).get("search") or []
    for hit in hits:
        title = hit.get("title", "")
        if title.startswith("Author:"):
            return title
    return None


def wikisource_works(author_page: str, limit: int = 20) -> list[dict[str, str]]:
    """List works linked from a Wikisource Author: page."""
    payload = api_get_json(
        WIKISOURCE_ACTION_BASE,
        {
            "action": "query",
            "titles": author_page,
            "prop": "links",
            "pllimit": "max",
            "format": "json",
        },
    )
    pages = (payload.get("query") or {}).get("pages") or {}
    works: list[dict[str, str]] = []
    for page in pages.values():
        for link in page.get("links") or []:
            title = link.get("title", "")
            if not title:
                continue
            if title.startswith(("File:", "Wikisource:", "Help:", "Author:", "Category:", "Template:", "Portal:")):
                continue
            slug = title.replace(" ", "_")
            works.append(
                {
                    "title": title,
                    "url": f"https://en.wikisource.org/wiki/{urlparse_mod.quote(slug, safe='/')}",
                }
            )
            if len(works) >= limit:
                return works
    return works


# ---------- Internet Archive ----------

def archive_search(name: str, limit: int = 10, year_before: int | None = None) -> list[dict[str, Any]]:
    """Search Internet Archive for biographies, works, and contemporary accounts."""
    name_clean = name.replace('"', '\\"')
    query_parts = [
        f'(subject:"{name_clean}" OR creator:"{name_clean}" OR title:"{name_clean}")',
        "mediatype:texts",
    ]
    if year_before:
        query_parts.append(f"year:[* TO {year_before}]")
    query = " AND ".join(query_parts)

    params = [
        ("q", query),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "creator"),
        ("fl[]", "year"),
        ("fl[]", "mediatype"),
        ("fl[]", "language"),
        ("sort[]", "downloads desc"),
        ("rows", str(limit)),
        ("output", "json"),
    ]
    full_url = f"{ARCHIVE_SEARCH_BASE}?{urlencode(params)}"
    _wait_for_rate_limit(_host_of(full_url))

    request = Request(
        full_url,
        headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30, context=_build_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ApiError(f"{exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise ApiError(f"Network error: {exc.reason}") from exc

    docs = ((payload.get("response") or {}).get("docs")) or []
    results: list[dict[str, Any]] = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        creator = doc.get("creator")
        if isinstance(creator, list):
            creator = ", ".join(c for c in creator if isinstance(c, str))
        language = doc.get("language")
        if isinstance(language, list):
            language = ", ".join(language)
        results.append(
            {
                "identifier": identifier,
                "title": doc.get("title"),
                "creator": creator,
                "year": doc.get("year"),
                "language": language,
                "url": f"https://archive.org/details/{identifier}",
            }
        )
    return results


# ---------- Pipeline ----------

def resolve_figure(name: str) -> dict[str, Any]:
    title = wikipedia_search_title(name)
    if not title:
        return {"query": name, "resolved": False, "error": "Wikipedia search returned no hits."}

    summary = wikipedia_summary(title) or {}
    qid = wikipedia_wikidata_id(title)
    facts = wikidata_facts(qid) if qid else {}

    return {
        "query": name,
        "resolved": True,
        "canonical_title": summary.get("title") or title,
        "wikipedia_url": ((summary.get("content_urls") or {}).get("desktop") or {}).get("page"),
        "wikidata_qid": qid,
        "description": summary.get("description"),
        "extract": summary.get("extract"),
        "thumbnail_url": (summary.get("thumbnail") or {}).get("source"),
        "birth_date": format_wikidata_time(facts.get("birth_date_raw"), facts.get("birth_date_precision")),
        "death_date": format_wikidata_time(facts.get("death_date_raw"), facts.get("death_date_precision")),
        "birth_place": facts.get("birth_place"),
        "death_place": facts.get("death_place"),
        "occupations": facts.get("occupations") or [],
        "notable_works": facts.get("notable_works") or [],
        "fields_of_work": facts.get("fields_of_work") or [],
    }


def ground_figure(
    name: str,
    archive_limit: int = 10,
    archive_year_before: int | None = 1930,
    excerpt_chars: int = 600,
    skip_wikisource: bool = False,
    skip_archive: bool = False,
) -> dict[str, Any]:
    figure = resolve_figure(name)
    if not figure.get("resolved"):
        return {"figure": figure, "works_by_figure": [], "period_sources": [], "story_arc_seeds": _empty_arc()}

    figure["extract"] = truncate(figure.get("extract"), excerpt_chars)

    works: list[dict[str, str]] = []
    if not skip_wikisource:
        author_page = wikisource_author_page(figure["canonical_title"])
        if author_page:
            works = wikisource_works(author_page)

    period_sources: list[dict[str, Any]] = []
    if not skip_archive:
        period_sources = archive_search(
            figure["canonical_title"],
            limit=archive_limit,
            year_before=archive_year_before,
        )

    return {
        "figure": figure,
        "works_by_figure": works,
        "period_sources": period_sources,
        "story_arc_seeds": _empty_arc(),
    }


def _empty_arc() -> dict[str, Any]:
    return {
        "origin": None,
        "rise": None,
        "defining_act": None,
        "crisis": None,
        "mature_power": None,
        "legacy": None,
    }


# ---------- CLI ----------

def _print_json(data: dict[str, Any]) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def cmd_resolve(args: argparse.Namespace) -> int:
    data = resolve_figure(args.name)
    if args.json:
        _print_json(data)
        return 0
    if not data.get("resolved"):
        print(f"Could not resolve: {args.name}", file=sys.stderr)
        return 1
    print(f"# {data['canonical_title']}")
    if data.get("description"):
        print(f"_{data['description']}_")
    if data.get("birth_date") or data.get("death_date"):
        birth = data.get("birth_date") or "?"
        if data.get("birth_place"):
            birth = f"{birth} in {data['birth_place']}"
        death = data.get("death_date") or "?"
        if data.get("death_place"):
            death = f"{death} in {data['death_place']}"
        print(f"Born: {birth}")
        print(f"Died: {death}")
    if data.get("occupations"):
        print(f"Occupations: {', '.join(data['occupations'])}")
    if data.get("notable_works"):
        print(f"Notable works: {', '.join(data['notable_works'])}")
    if data.get("extract"):
        print()
        print(textwrap.fill(data["extract"], width=96))
    print()
    if data.get("wikipedia_url"):
        print(f"Wikipedia: {data['wikipedia_url']}")
    if data.get("thumbnail_url"):
        print(f"Portrait: {data['thumbnail_url']}")
    return 0


def cmd_wikisource(args: argparse.Namespace) -> int:
    author_page = wikisource_author_page(args.name)
    if not author_page:
        result: dict[str, Any] = {"query": args.name, "found": False}
    else:
        works = wikisource_works(author_page, limit=args.limit)
        slug = author_page.replace(" ", "_")
        result = {
            "query": args.name,
            "found": True,
            "author_page": f"https://en.wikisource.org/wiki/{urlparse_mod.quote(slug, safe=':/')}",
            "works": works,
        }
    if args.json:
        _print_json(result)
        return 0
    if not result.get("found"):
        print(f"No Wikisource Author: page found for {args.name}")
        return 0
    print(f"# {args.name} on Wikisource")
    print(f"Author page: {result['author_page']}")
    print(f"Works ({len(result['works'])}):")
    for w in result["works"]:
        print(f"  - {w['title']}")
        print(f"    {w['url']}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    results = archive_search(args.name, limit=args.limit, year_before=args.year_before)
    payload = {
        "query": args.name,
        "year_before": args.year_before,
        "results": results,
    }
    if args.json:
        _print_json(payload)
        return 0
    print(f"# Internet Archive: {args.name}")
    print(f"({len(results)} results, year <= {args.year_before or 'any'})")
    for item in results:
        print(f"- {item.get('title')}")
        if item.get("creator"):
            print(f"  Creator: {item['creator']}")
        if item.get("year"):
            print(f"  Year: {item['year']}")
        print(f"  URL: {item['url']}")
    return 0


def cmd_ground(args: argparse.Namespace) -> int:
    bundle = ground_figure(
        args.name,
        archive_limit=args.archive_limit,
        archive_year_before=args.year_before,
        excerpt_chars=args.excerpt_chars,
        skip_wikisource=args.skip_wikisource,
        skip_archive=args.skip_archive,
    )
    if args.json:
        _print_json(bundle)
        return 0
    fig = bundle.get("figure", {})
    if not fig.get("resolved"):
        print(f"Could not ground: {args.name}", file=sys.stderr)
        return 1
    print(f"# {fig['canonical_title']}")
    birth = fig.get("birth_date") or "?"
    death = fig.get("death_date") or "?"
    print(f"({birth} - {death})")
    if fig.get("description"):
        print(f"_{fig['description']}_")
    if fig.get("occupations"):
        print(f"Occupations: {', '.join(fig['occupations'])}")
    if fig.get("notable_works"):
        print(f"Notable works: {', '.join(fig['notable_works'])}")
    print()
    if fig.get("extract"):
        print(textwrap.fill(fig["extract"], width=96))
        print()
    if bundle.get("works_by_figure"):
        print(f"## Works by {fig['canonical_title']} ({len(bundle['works_by_figure'])})")
        for w in bundle["works_by_figure"][:10]:
            print(f"- {w['title']}")
            print(f"    {w['url']}")
        print()
    if bundle.get("period_sources"):
        print(f"## Period sources ({len(bundle['period_sources'])})")
        for item in bundle["period_sources"][:10]:
            year = item.get("year") or "?"
            creator = item.get("creator") or "?"
            print(f"- [{year}] {item.get('title')} ({creator})")
            print(f"    {item['url']}")
        print()
    if fig.get("wikipedia_url"):
        print(f"Wikipedia: {fig['wikipedia_url']}")
    if fig.get("thumbnail_url"):
        print(f"Portrait (Wikimedia): {fig['thumbnail_url']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Epoch primary-source grounder. Resolves a figure to a canonical Wikipedia page + "
            "structured Wikidata facts, surfaces Wikisource works by the figure, and pulls "
            "Internet Archive period biographies. Output is shaped for the Epoch six-scene VO arc."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_res = sub.add_parser("resolve", help="Resolve canonical Wikipedia + Wikidata facts.")
    p_res.add_argument("name")
    p_res.add_argument("--json", action="store_true")
    p_res.set_defaults(func=cmd_resolve)

    p_ws = sub.add_parser("wikisource", help="Find Wikisource works by the figure.")
    p_ws.add_argument("name")
    p_ws.add_argument("--limit", type=int, default=20)
    p_ws.add_argument("--json", action="store_true")
    p_ws.set_defaults(func=cmd_wikisource)

    p_arc = sub.add_parser("archive", help="Search Internet Archive for biographies and works.")
    p_arc.add_argument("name")
    p_arc.add_argument("--limit", type=int, default=10)
    p_arc.add_argument(
        "--year-before",
        type=int,
        default=None,
        help="Restrict to items dated before this year (e.g. 1930 for public-domain bias).",
    )
    p_arc.add_argument("--json", action="store_true")
    p_arc.set_defaults(func=cmd_archive)

    p_g = sub.add_parser("ground", help="Full pipeline: resolve + wikisource + archive.")
    p_g.add_argument("name")
    p_g.add_argument("--archive-limit", type=int, default=10)
    p_g.add_argument("--year-before", type=int, default=1930)
    p_g.add_argument("--excerpt-chars", type=int, default=600)
    p_g.add_argument("--skip-wikisource", action="store_true")
    p_g.add_argument("--skip-archive", action="store_true")
    p_g.add_argument("--json", action="store_true")
    p_g.set_defaults(func=cmd_ground)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
