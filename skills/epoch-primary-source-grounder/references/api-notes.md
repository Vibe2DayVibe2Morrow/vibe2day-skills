# API Notes

This skill uses only public, unauthenticated endpoints.

## Wikipedia

- REST summary: `GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}`
  - Returns `title`, `description`, `extract`, `thumbnail`, `content_urls`.
  - Returns 404 if the title doesn't exist. The script catches this and returns `{}` so the pipeline continues.
- Action API: `GET https://en.wikipedia.org/w/api.php`
  - `action=query&list=search&srsearch=...&srlimit=5` for canonical title resolution.
  - `action=query&prop=pageprops&titles=...` to fetch the `wikibase_item` (Wikidata QID) from a page.

## Wikidata

- Action API: `GET https://www.wikidata.org/w/api.php`
  - `action=wbgetentities&ids={QID}&props=claims` for structured biographical facts.
  - `action=wbgetentities&ids=Q1|Q2|...&props=labels&languages=en` to batch-resolve up to 50 entity IDs into English labels in one call.
- Useful properties:
  - `P569` date of birth
  - `P570` date of death
  - `P19` place of birth
  - `P20` place of death
  - `P106` occupation
  - `P800` notable work
  - `P101` field of work
  - `P18` image (we don't use this; the Wikipedia REST summary thumbnail is good enough)
- Time format: `+0551-09-28T00:00:00Z` or `-0551-01-01T00:00:00Z`. Negative sign means BCE.
- Precision: separate field on the time value. `9 = year`, `10 = month`, `11 = day`. The script uses this to render `551 BCE` (year precision) vs `1879-03-14 CE` (day precision).

## Wikisource

- Action API: `GET https://en.wikisource.org/w/api.php`
  - `action=query&list=search&srsearch=Author:Confucius&srnamespace=102` for Author-page discovery.
  - `action=query&titles=Author:Confucius&prop=links&pllimit=max` for the work list linked from that page.
- Filter out namespace prefixes (File:, Wikisource:, Help:, Author:, Category:, Template:, Portal:) — those aren't works.

## Internet Archive

- Advanced search: `GET https://archive.org/advancedsearch.php?q=...&output=json`
  - Query syntax: `subject:"..."`, `creator:"..."`, `title:"..."`, `year:[* TO 1920]`, `mediatype:texts`.
  - `sort[]=downloads desc` biases toward well-used, well-OCR'd scans.
  - `fl[]=field` selects which fields to return (cuts response size).
- Metadata: `GET https://archive.org/metadata/{identifier}` for full item details on selective deep dives. The skill does not call this; it's available if you want to extend.

## Rate Limits

- Wikipedia and Wikidata: no hard documented limit. The skill paces at 5 req/sec per host and retries 429 with `Retry-After` respected (exponential backoff if not provided).
- Internet Archive: same pacing strategy.
- Always send a descriptive `User-Agent` header. Set `EPOCH_GROUNDER_USER_AGENT` env var. Default: `EpochAtlas-Grounder/0.1 (https://epoch-time-atlas.base44.app)`.

## Notes

- For ancient figures (Confucius, Marcus Aurelius, Buddha), Wikisource is almost always the strongest grounding signal. Their works are public-domain and digitized.
- For 19th-20th century figures (Lincoln, Curie, Tesla), Internet Archive's 1890-1930 scholarly biographies are gold. Public-domain, decent OCR, often contain quoted letters or diary entries.
- For non-Western figures pre-1800, Wikisource coverage thins out. Lean on `--year-before 1950` Internet Archive results in those cases.
- Wikidata's `notable_works` (P800) is a curated short list — usually 3-7 items. It's better than scraping the Wikipedia article for "works" sections.
