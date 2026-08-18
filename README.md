# SlopScraper

A Python pipeline that finds Steam launch options, checks them against a source,
and publishes the ones that survive into a Postgres database.

It is the write side of a two-part system. The read side is
[Vanilla Slops](https://github.com/soundwanders/vanilla-slops), the website that
serves the catalogue.

> **Source-available, not open source.** You are welcome to read this. Please do
> not run it. See [LICENSE](LICENSE). The short version is that this thing
> talks to other people's websites, and I would rather a modified copy of it did
> not.

---

## The idea

Steam lets you pass launch options to a game, and the good ones are genuinely
useful: skip a two-minute intro, force a renderer that stops a game crashing,
cap a frame rate that is cooking your GPU for nothing. The problem is that the
advice is scattered across wikis, forum posts and eight-year-old Reddit threads,
and a lot of it is wrong.

So the governing rule here is narrow:

> **If a claim cannot be traced to a source, it is not published.**
> `NULL` is a deliberate signal, not a gap to fill.

That sounds obvious and is annoyingly expensive in practice. Several rounds of
work on this project have consisted of *deleting* data: engine labels that
nothing could confirm, flags attached to games they do nothing in, descriptions
that were confidently wrong. Coverage went down on purpose each time.

The test for anything entering the database is: **what confirmed this is real?**
If the answer is not a URL or a named reference, it does not ship.

## How that works in practice

**Every published row must name its source.** A database view sits in front of
the table and hides anything that cannot, whether that is an option nothing
links to or an option with no provenance. Roughly a fifth of stored rows are
hidden at any time. They are not deleted; if a later pass confirms one, it
reappears on its own.

**Documentation comes from primary sources or not at all.** Where a flag has a
usage example, that example was verified against the vendor: Unity's manual,
Epic's command-line reference, id Software's released engine source, Valve's
Proton README, the Valve Developer Community. Where none of those documents a
flag, it stays undocumented rather than being filled in from memory. Guessing at
what a flag does is the one failure mode this project cannot afford, because a
plausible wrong answer is worse than a blank.

**Fixes go on the write path, not into a cleanup script.** Cleaning the database
alone gets undone the next time the scraper runs, which has happened here more
than once. A cleanup is the second half of a fix; the parser or validator change
is the first.

**Engines are not inferred.** Steam's API carries no engine information at all
(41 fields, none of them an engine), so engine data comes from PCGamingWiki's
structured infobox data instead. Earlier versions guessed from publisher, price,
genre and franchise name in the title, and every one of those shipped a bug.

## Being a considerate client

This project reads other people's websites, so it tries to cost them as little
as possible:

- **A floor on request rate**, not just a default, with several seconds between
  requests by default.
- **Bulk APIs over page scraping.** Engine metadata for the entire catalogue is
  one structured query cached for a week, rather than a request per game.
- **Aggressive caching**, so a re-run mostly reads from disk.
- **An honest User-Agent** that says what the client is.
- **Access controls are respected.** Where a site has put up a bot challenge,
  this project stops and the data stays undocumented. That has genuinely cost
  coverage here, and it is the correct trade.

If you are reading this because you maintain one of the sites it talks to and
something looks wrong, please open an issue. I would rather hear it directly.

## Architecture

```
slop_scraper/
  main.py               CLI entry point
  core/scraper.py       orchestration, rate limiting, resume state
  database/             all database writes; provenance stamping
  scrapers/             one module per source
  validation/           the gates a row must pass to be stored:
                          description quality, command validity,
                          risk/category tagging, curated flag documentation
  utils/                engine resolution, caching, paths, security limits
```

Three tables and two views. A flag found on many games is stored **once** and
shared through a junction table, so `-novid` is one row rather than ninety.

Runtime state — caches, resume cursors, rollback snapshots — lives under
`_local/` and is not tracked. Neither are the database migrations or the
maintenance scripts; they operate on live data and are not part of what this
repository publishes.

## Status

Personal project, run on demand. There is no scheduler and no service behind
it. It runs when I run it. Numbers move, and anything quoted here would be
stale by the time you read it.

## Acknowledgments

- [PCGamingWiki](https://www.pcgamingwiki.com/): the primary source for both
  launch options and engine data, and the reason the engine column is worth
  anything.
- [ProtonDB](https://www.protondb.com): community reports for Linux and Proton.
- [Steam Community](https://steamcommunity.com/): user-written guides.
- Valve, Epic and id Software, whose published documentation and released engine
  source made accurate flag descriptions possible.
- [Supabase](https://supabase.com/): database and hosting.

## License

All rights reserved. Readable, not reusable; see [LICENSE](LICENSE).
