# V1-2448 — RUC incorporation date empty on dev (stale parse cache)

## Revision history

| Version | Date | What changed | Why |
|---|---|---|---|
| 1.0 | 2026-11-26 | First version: cause, evidence, fix applied, code change, open items. | Jorge's report V1-2448 (Data Room QA). |

## What was reported

On dev, uploading the RUC certificate (Certificate of Legal Existence) of CONDOMINIO PARQUE
CALIFORNIA DOS left **Fecha de constitución** (`incorporation_date`) empty, and **Años de
operación** (`years_operating`) was empty or wrong. Legal name, RUC number and activity were
filled correctly.

## Cause 1: a bad parse saved in the cache and reused for every upload

The extractor works in two steps:

1. LandingAI **parses** the PDF into text (markdown + chunks).
2. The model **extracts** the fields from that text.

Step 1 costs credits, so its result is saved in S3 by the file's SHA-256 and reused for every
later upload of the same file, in any project:

```
s3://drex-network/ddx-cache/markdown/dpt-2-latest/<sha256>.md
                                                  <sha256>.meta.json
                                                  <sha256>.parse.json
```

The entries never expire, and nothing checks a parse before it is saved.

On **2026-09-11 15:55 UTC** this file (sha256
`1dafb015fb21608e8057cf3b46d782bca2539aa5b8bb1dacd8438c64bac7c24d`) was parsed for the first
time under the model-scoped key (added 2026-07-14, T8.7). LandingAI returned the certificate's
main table with every cell as `<MISSING CELL VALUE>`:

```
<tr><td id="0-8">&lt;MISSING CELL VALUE&gt;</td> ...      ← should be "Fecha de constitución 08/04/2003"
```

The date only appears in that table, so the model never saw it and returned it empty. The name,
RUC number and activity are outside that table, which is why they kept working.

### Evidence

| Check | Result |
|---|---|
| Jorge's PDF vs the sample file | byte-identical (same sha256) |
| Saved parse from 2026-09-11 (`dpt-2-latest/1dafb015….md`) | status/dates table = all `<MISSING CELL VALUE>` |
| Older parse of the same file, 2026-03-17 (old key `ddx-cache/markdown/1dafb015….md`, no longer read) | table complete, "Fecha de constitución 08/04/2003" |
| Dev extractions of this file before 2026-09-11 | `2003-04-08` |
| Dev extractions since 2026-09-11 (projects 160, 162, 172, 226, 246, 248, 250, 258, 262, 266) | empty |
| Local extractor with the cache off | `2003-04-08` every time — which is why it only failed on dev |
| Extractor code and field keys | unchanged since 2026-10-18; keys match extractor, projects registry, frontend |

## Fix applied (2026-11-26)

The three cache objects for this sha256 were deleted. Test repeated locally with the cache **on**
against the real `drex-network` bucket (same as dev):

| Upload | Cache | incorporation_date | years_operating |
|---|---|---|---|
| 1 (project 246) | miss → parsed fresh, new entry saved 14:26 UTC with the table complete | `2003-04-08` | 23 |
| 2 (project 200) | hit → new entry reused | `2003-04-08` | 23 |

Dev now gets the date for this file. Re-uploading it is enough.

## Cause 2: `years_operating` was guessed by the model

The schema described `years_operating` as "computed post-extraction", but no code computed it:
the model was asked for it and guessed (21 or 22 instead of 23).

**Change (this PR):** the field is removed from the schema sent to the model and calculated in
`normalize_legal_information_extraction()` (`categories.py`):

- value = current year − incorporation year; the year is read from any date shape
  (`2003-04-08`, `08/04/2003`, `8 de abril de 2003`, `2003`);
- no date, or a year after today → `null` (never a guess);
- it carries `incorporation_date`'s metadata (confidence, references), so the page that proves
  the date proves the years;
- a targeted / `extract-fields` request for `years_operating` asks the model for
  `incorporation_date` and returns only the requested fields.

Tests: `tests/test_legal_information_years_operating.py` (21). Suite: 171 passed, 1 skipped
(develop: 150 passed, 1 skipped). Local E2E through the projects backend with the real model:
project 258 went from empty/empty to `2003-04-08` / 23.

## Known limits / open items

| # | Item | Status |
|---|---|---|
| O-1 | Any other file can get a bad parse stuck the same way: nothing stops a parse with `<MISSING CELL VALUE>` from being saved. Possible guard: don't save (or re-parse) such a result. | Not done — decided to leave for now (2026-11-26). Clear by hand with the runbook in `src/ddx/api/apis_latest.md` → Parse Cache. |
| O-2 | Projects keeps an AI value whose confidence is above 0.9, so rows that already hold a wrong guess (21/22 at confidence 1) keep it after a re-upload. Fix = data fix or an exception for `years_operating`. | Open |
| O-3 | Until this PR is deployed, dev's extractor still guesses `years_operating`. | Deploy |

## How to spot this again

A specific file extracts wrong on dev but right locally → read its cached `.md` first:

```bash
SHA=$(shasum -a 256 file.pdf | cut -d' ' -f1)
aws s3 cp s3://drex-network/ddx-cache/markdown/dpt-2-latest/$SHA.md - | grep -n "MISSING CELL VALUE"
```
