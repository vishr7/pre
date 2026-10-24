# PRE evaluation workflow

Keep the existing Gemini reviewer. Establish a baseline before changing prompts or considering fine-tuning. These scripts do not train a model or alter the live Review feature.

## Commands

```sh
npm run eval:check
npm run eval:prepare -- --input /path/to/normalized-papers.jsonl
npm run eval:review -- --input /path/to/normalized-papers.jsonl --split test --limit 5 --live
npm run eval:format
```

Outputs go to ignored `.runtime/evaluations/<command>-<timestamp>/`. Use `--out PATH` to choose a destination. Gemini calls only happen with `eval:review --live`, use the existing server-side `.env` settings, send paper text to Gemini, and incur API usage. The current reviewer may make multiple calls for its review and arithmetic audit. For the three synthetic smoke examples, use `--split all --limit 3 --live`; they are not a representative evaluation set.

## Preparing external data

No external datasets are downloaded or bundled. Obtain access and retain the applicable license/attribution before normalizing NLPeer, ReGround, or DISAPERE. Public access or noncommercial use alone does not establish every permission. Do not accept dataset agreements automatically through these scripts.

Create one JSON object per line:

```json
{"id":"example-1","paper_id":"stable-paper-id","group_id":"shared-id-across-versions-and-datasets","source":"dataset-name-and-version","license":"license-name-or-reference","text":"Complete paper text being reviewed","venue":"generic","human_validated":false,"expected_issues":[{"quote":"Exact passage from the paper","category":"experimental"}]}
```

- NLPeer: extract the submission's structured paper text and associate its reviews. Have a person verify reference issues before adding `expected_issues`; review prose is not automatically an exact paper quotation.
- ReGround: use evidence alignments to propose reference passages; check that each quoted string occurs in the normalized paper, and manually verify the relation.
- DISAPERE: use sentence labels for supplementary review-category evaluation, not as standalone full-paper inputs. Do not fabricate a paper for a review sentence.
- Keep references/decisions separate from model input. Only paper text and venue are sent to the reviewer.
- Set one `group_id` for all reviews, revisions and cross-dataset copies of a paper. Defaults use source + paper_id, so cross-dataset matching requires explicit IDs. Exact whitespace-normalized duplicates with different groups are rejected; fuzzy duplicates still require manual deduplication.
- Splits use a stable SHA-256 hash of the group: approximately 80/10/10 train/validation/test. Small fixture sets may have empty splits. Fix the dataset before comparing prompt versions; use validation for development and reserve test for final checks.

## Interpreting results

`report.json` records model, Git commit, input digest, per-paper errors, latency, output-schema checks, verbatim quote accuracy, broken action links, and category-plus-quote overlap with reference issues. `human-review.jsonl` contains blank supported/useful/severity judgments for a reviewer to fill in.

Reference overlap is a diagnostic, **not scientific correctness or semantic recall**: a comment can quote a relevant passage while making a wrong criticism. No precision claim can be made from incomplete reference issues. Human judgments are required for supported criticism, useful fixes, correct severity, and false positives. Scores are not calibrated acceptance probabilities. The pipeline evaluates the product's post-validation response, so quote checks reflect its filtering as well as Gemini; they are not raw-model hallucination rates. API failures remain failures rather than receiving perfect scores.

The included examples are project-authored synthetic smoke tests, marked `human_validated: false`. They establish plumbing, not evidence of review quality. No baseline improvement is claimed until real held-out data has been evaluated.

## Formatting benchmark

`format-fixtures.json` covers ordinary prose/headings/equations, a captioned booktabs table, and a requested page break. `eval:format` compiles the fixtures using PRE's actual runtime and saves PDFs, logs, and warning summaries. It uses Tectonic and may need package downloads on the first run. It does not call Gemini.

Inspect PDFs for margins, text clipping, heading hierarchy, table fit, caption placement and pagination. Every result retains `visual_review_required: true`; compilation success is not aesthetic correctness. Add permitted official venue templates as separate fixtures without replacing their layouts. This initial suite tests PRE's default renderer, not AI formatting skill; compare generated examples against the same checks and human checklist before claiming model improvements.
