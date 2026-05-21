# Vibe2Day Skills

Agentskills.io-compatible skills for vertical AI workflows across the [Vibe2Day](https://github.com/Vibe2DayVibe2Morrow) portfolio — biographical content (Epoch Time Atlas), anime production (Sakuga Studio), language learning (Chinese Memory), dental clinics (SmileCraft), and 50+ other base44 apps.

Each skill codifies the working knowledge of one vertical workflow. They run inside the Codex super app, Claude Code, Cursor, Hermes Agent, or any agent that loads markdown-based skills on the [agentskills.io](https://agentskills.io) standard.

## Skill catalog

| # | Skill | Folder | What it does | APIs |
|---|---|---|---|---|
| 1 | [Epoch Primary Source Grounder](skills/epoch-primary-source-grounder) | `skills/epoch-primary-source-grounder` | Resolve a historical figure to canonical Wikipedia + Wikidata facts, surface Wikisource works BY the figure, and pull Internet Archive period biographies. Shaped to feed the Epoch six-scene VO arc. | Wikipedia, Wikidata, Wikisource, Internet Archive — all free, no auth required |

More skills coming. Tentative roadmap:

- `sakuga-identity-threading` — Soul V2 → Reference → Character identity threading on the Higgsfield REST API for anime production
- `base44-deploy-loop` — auto-loop pattern: PR → deploy log → smoke test → fix → terminate on clean 200 + RLS pass
- `vibe-os-asset-router` — cross-app media routing via the vibe-os workspace custom integration
- `epoch-vo-timing` — apply the VO timing formula to a draft script and surface lines over 7.0s

## Install one skill

For Codex super app:

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/Vibe2DayVibe2Morrow/vibe2day-skills /tmp/vibe2day-skills
cp -R /tmp/vibe2day-skills/skills/epoch-primary-source-grounder "$HOME/.codex/skills/"
```

For Claude Code, copy into `~/.claude/skills/` instead. For Cursor, reference via `.cursorrules` or your custom rules file. Any agent that supports the agentskills.io standard can load these directly.

## Layout

- `skills/` — standalone agentskills.io skills, each with `SKILL.md` + `scripts/` + `references/` + `agents/`
- `README.md` — this file
- `LICENSE` — MIT

## Design principles

These skills follow a few opinionated rules learned from Vibe2Day's production work on 60+ base44 apps:

- **Stdlib-only Python where possible.** Skills should run in fresh containers without `pip install`.
- **Free public APIs by default.** Paid APIs only when no free alternative exists, and always with the per-call cost annotated in `references/api-notes.md`.
- **Visual Identity Gate before generation.** Any skill that produces user-facing artifacts must verify a brand spec is loaded before generating (Crimson Pro for Epoch, identity sheet for Sakuga, clinical-not-sci-fi for SmileCraft). No default-AI-aesthetic fallbacks.
- **Mini-app handoff over export dance.** Where a UI is involved, agent and human share the same surface and database. No "agent generates → export → human imports to edit" handoff loops.
- **Rate-limit-aware.** Skills calling public APIs pace at 5 req/sec per host and respect `Retry-After` on 429.
- **Provenance on every output.** Generated artifacts should carry the skill name, version, date, and command so future regens are reproducible.

See the individual `SKILL.md` files for specific calling conventions.

## License

[MIT](LICENSE). Use these skills in your own projects. Attribution welcome but not required.

## Author

Built by [Vibe2Day](https://github.com/Vibe2DayVibe2Morrow). Maintained as the canonical skill catalog for the Vibe2Day base44 app portfolio.
