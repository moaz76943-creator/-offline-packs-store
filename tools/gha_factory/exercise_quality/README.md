# Evidence-backed Cloze quality gate

Read-only replay QA for GHA-05 `make_cloze`; no new grammar or distractor
generation and no local fabrication of sentence or lexical data. Provide the
candidate and independently supplied approved original sentence, editor span
annotation, source-hashed licence evidence, attested senses, attested forms,
and canonical language IDs to `verify_cloze`.

The module rebuilds the candidate using the **existing** GHA-05 helper and
rejects changes in accepted answer, span, distractors, language, source
identity, attribution and status. Even if it passes, it emits
`quality_status=REVIEW_REQUIRED` and `publication_approved=false`.
Source admission and human semantic review must still be independently proved.

`evaluate_response` returns CORRECT only for exact or Unicode-NFC-equivalent
approved answers; AMBIGUOUS for attested alternatives not on the accepted list;
UNVERIFIED otherwise. It does not manufacture spelling or morphology diagnoses
from edit distance and never treats unsupported dialect variants as wrong.

Offline regression command:

```sh
python3 -m unittest discover -s tests/gha_factory/exercise_quality -p 'test_*.py' -v
```

Workers remain blocked by empty Route05 source approvals and GHA-02 queue
integration; the dedicated public Ubuntu workflow tests synthetic fixtures only.
