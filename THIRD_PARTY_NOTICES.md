# Third-party notices

## Crawl4AI — `antibot_detector.py`

- Source: https://github.com/unclecode/crawl4ai, file `crawl4ai/antibot_detector.py`
- Commit: `30165f1ee1fb61f6cce1477feed2acc5e2181e25`
- SHA-256 of the original file: `c72f772e735a0ea6fea7000cc8e8121afdef4e786efaaadd322ab41abbee62e0`
- License: Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0)
- Copyright: the Crawl4AI authors (UncleCode and contributors)
- Vendored at: `app/scrapers/shared/antibot_detector.py`

Modifications (also listed in the file header): `is_blocked()` gained the
keyword-only parameters `structural` and `local`; the near-empty-200 check and
Tier 3 only run when `structural=True`. A `_LOCAL_PATTERNS` block,
`local_block_reason()` and `shadow_reason()` were appended. Original patterns and
Tier 1/Tier 2 logic are unchanged.

Licensed under the Apache License, Version 2.0; you may not use this file except
in compliance with the License. Unless required by applicable law or agreed to
in writing, software distributed under the License is distributed on an "AS IS"
BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
