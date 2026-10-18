# Agents

Each agent is its own GitHub Actions workflow on `ubuntu-latest`.
Agents do not depend on each other. They read and write versioned JSON under `state/agents/`
(schema 1.0.0) and, when they have data, files under `data/agents/`.
A missing, stale or malformed file is a warning. The consumer keeps going.
Checkpoints are commits on the branch `agents/data` (no force push).
Root `manifest.json` and `legal/ledger/sources.json` are not edited by these workflows.

Halt every agent by setting the repository variable `AGENTS_HALT` or `LANGUAGE_PRODUCTION_HALT` to `true`.

The legal license check and the content-policy filter (alcohol Q154, gambling Q11416, sexual content Q154136, dance Q11639) stay in force.
GPL, CC-BY-SA-3.0, NC, ND, UniMorph, Apertium and unverified OmegaWiki stay out.
There is no paid API and no synthetic vocabulary.

The public-pr-merge-gate stays. It rejects CI-skip tokens and is required for pull requests into `main`.
Bot output does not open a pull request, because a `GITHUB_TOKEN` pull request does not run that gate.

| Agent | Schedule (UTC) | Workflow |
| --- | --- | --- |
| `harvest-wikidata` | 07:00, 13:00, 19:00, 01:00 and 03:37, 09:37, 15:37, 21:37 UTC | `.github/workflows/agent_harvest_wikidata.yml` |
| `harvest-kaikki` | 01:17, 07:17, 13:17, 19:17 UTC | `.github/workflows/agent_harvest_kaikki.yml` |
| `harvest-tatoeba` | 02:27, 08:27, 14:27, 20:27 UTC | `.github/workflows/agent_harvest_tatoeba.yml` |
| `harvest-ud` | 04:47 and 16:47 UTC | `.github/workflows/agent_harvest_ud.yml` |
| `classifier` | every 4 hours from 01:12 UTC | `.github/workflows/agent_classifier.yml` |
| `grammar` | 01:22, 07:22, 13:22, 19:22 UTC | `.github/workflows/agent_grammar.yml` |
| `qa` | 02:32, 08:32, 14:32, 20:32 UTC | `.github/workflows/agent_qa.yml` |
| `legal` | 03:42, 09:42, 15:42, 21:42 UTC | `.github/workflows/agent_legal.yml` |
| `packs` | 04:52, 10:52, 16:52, 22:52 UTC | `.github/workflows/agent_packs.yml` |
| `health` | every 4 hours from 00:08 UTC | `.github/workflows/agent_health.yml` |
| `janitor` | every 4 hours from 01:18 UTC | `.github/workflows/agent_janitor.yml` |
| `coverage` | every 4 hours from 02:28 UTC | `.github/workflows/agent_coverage.yml` |
| `watchdog` | hourly at minute 48 | `.github/workflows/agent_watchdog.yml` |
| `docs` | 05:03 UTC daily | `.github/workflows/agent_docs.yml` |
| `test-gap` | 06:13 UTC daily | `.github/workflows/agent_test_gap.yml` |
| `schema-guard` | 04:23 and 16:23 UTC | `.github/workflows/agent_schema_guard.yml` |
| `links` | 05:33 and 17:33 UTC | `.github/workflows/agent_links.yml` |
| `performance` | 06:43 and 18:43 UTC | `.github/workflows/agent_performance.yml` |
| `cleanup` | 07:53 UTC daily | `.github/workflows/agent_cleanup.yml` |
| `triage` | 03:09 and 15:09 UTC | `.github/workflows/agent_triage.yml` |
| `codeql` | 03:19 UTC daily | `.github/workflows/agent_codeql.yml` |

## harvest-wikidata

Bounded CC0 Wikidata lexeme harvest, sharded by language and section.

Inputs: catalog taxonomy, state/agents/plan.json, content-policy blocklist

Outputs: data/agents/harvest/wikidata/<lang>/<section>.json and a heartbeat

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## harvest-kaikki

Bounded Kaikki/Wiktionary extract. Keeps a row only with a Wikidata anchor.

Inputs: Wiktionary copyright snapshot, concept graph

Outputs: data/agents/harvest/kaikki/<lang>/<section>.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## harvest-tatoeba

Author-attributed Tatoeba sentences under CC-BY-2.0-FR.

Inputs: verified Tatoeba language codes, terms snapshot

Outputs: data/agents/harvest/tatoeba/<lang>/sentences.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## harvest-ud

Universal Dependencies sample, only when that treebank notice matches.

Inputs: per-treebank license notice

Outputs: data/agents/harvest/ud/<lang>/<treebank>.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## classifier

Map stored rows onto taxonomy sections and estimated CEFR levels.

Inputs: data/agents/harvest, concept graph

Outputs: data/agents/classified/rows.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## grammar

Fill grammar, verb and sentence slots from profiles and stored rows.

Inputs: language profiles, classified rows

Outputs: data/agents/grammar/<lang>.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## qa

Re-check sampled rows for ids, policy, script, duplicates and placeholders.

Inputs: classified rows or harvest rows

Outputs: state/agents/qa-report.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## legal

Keep attribution consistent and block only real license conflicts.

Inputs: license snapshots, harvested rows

Outputs: state/agents/legal-report.json and data/agents/attribution/

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## packs

Build candidate SQLite packs from real rows. Does not flip the root manifest.

Inputs: traceable harvested rows

Outputs: data/agents/packs/<lang>.sqlite and checksums

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## health

Record each failed run signature with its root cause. The same run id is counted once. A second run of that signature opens one GitHub issue with the structural fix. A later run does not open another issue and does not rerun the failed job. If `ROOT_CAUSES.md` already names the signature, the health agent leaves that entry as the tracker.

Inputs: GitHub workflow runs, `state/repair/<signature>.json`, `ROOT_CAUSES.md` when present

Outputs: `state/repair/<signature>.json`

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## janitor

Update green bot pull requests and squash-merge them. No force push.

Inputs: open pull requests and check rolls

Outputs: merged pull requests or update commits

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## coverage

Compute gaps from stored rows and choose the next shards.

Inputs: harvest files, previous metrics

Outputs: STATUS.md, state/agents/plan.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## watchdog

Re-dispatch agents whose heartbeat is missing or older than eight hours.

Inputs: state/agents/*.json heartbeats

Outputs: workflow_dispatch calls, capped per run

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## docs

Refresh STATUS from stored rows and check the roster against workflow files.

Inputs: AGENTS.md roster, data files

Outputs: STATUS.md and state/agents/docs-report.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## test-gap

List modules that no test imports. It does not invent tests for them.

Inputs: tools/ and tests/

Outputs: state/agents/test-gap.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## schema-guard

Check the SQLite v2 contract constants. Missing packs are a warning.

Inputs: tools/pack_v2 contract

Outputs: state/agents/schema-guard.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## links

HEAD recorded source and license URLs. A failure is a warning, not a crash.

Inputs: catalog/organization/sources.v1.json

Outputs: state/agents/links.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## performance

Record pack and data sizes and flag a large jump from the last snapshot.

Inputs: data/agents and packs/

Outputs: state/agents/performance.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## cleanup

Delete only merged agent branches. Never main and never unmerged work.

Inputs: git branches merged into main

Outputs: deleted refs under safe prefixes, state/agents/cleanup.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## triage

Dedupe issues by title and comment with the matching agent name.

Inputs: open issues

Outputs: issue comments and state/agents/triage.json

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.

## codeql

Free CodeQL analysis for Python. Independent of the other agents.

Inputs: repository source

Outputs: GitHub code scanning alerts

Halt: `AGENTS_HALT=true` or `LANGUAGE_PRODUCTION_HALT=true`.
