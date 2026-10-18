# Grammar Evidence Factory 1.0.0 — candidate validation only

This independent public sidecar uses the canonical 100 identities in \`catalog/language_registry.v1.json\`, the 25 three-state dimensions in \`standards/morphology/feature_overrides.json\`, approved source evidence in \`legal/ledger/sources.json\`, and lexical/morphology 1.0 contracts. No existing contracts or release manifests are modified.

Grammar identity is \`gr1:<language>:<slug>:v<revision>\` with exact ownership. Every rule distinguishes descriptive from pedagogical explanation; pedagogical rules link to descriptive parents. Explicit prerequisites, exceptions, register, domain, source locators, form features and example span annotations are required. Unknown or inapplicable capabilities never inherit features from other languages or families. Automated checks verify explicit annotations, not free-text semantic correctness.

Promotion needs attested lexeme/sense/form/example identities, identical rule references in example annotations, a reviewer-roster decision bound to the content SHA-256, approved original source artifact digests and existing Route05 rights records. Synthetic fixtures do not grant approval. Upstream Route05 legal gate and authenticated human editorial review remain separate required publication controls.

**Current production rights ledger: empty. Approved grammar rules: 0.** The initial \`rules.jsonl\` is empty deliberately. \`topic_backlog.v1.json\` contains *research topics*, not attested educational rules. Languages not reviewed for topics have \`topic_gap_status=NOT_ASSESSED\`, not an assertion of full coverage.

Run from repository root:

\`\`\`sh
python3 -m unittest discover -s tests/factory_extensions/grammar_evidence -p 'test_*.py' -v
python3 tools/factory_extensions/grammar_evidence/factory.py --repo-root .
python3 tools/factory_extensions/grammar_evidence/factory.py --repo-root . --shard 0 --shards 4
\`\`\`

CLI emits deterministic JSON receipts: candidate hash, shard, language IDs, verified rule/example/domain totals, missing tracked topics, unknown capabilities and blocking reasons per language. Exit code is nonzero on rejected candidates. No pack writing, external network, paid dependencies, or fabricated worker run IDs. Hosted Actions use bounded read-only public runners and publish only genuine step-summary receipts.
