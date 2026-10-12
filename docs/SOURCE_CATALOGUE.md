# Source catalogue and coverage

Snapshot checked on October 12, 2026. Counts describe the local development database and committed discovery artifacts; the public site has not been deployed.

## Published inventory

The previous expansion grew the local database from approximately 25 jobs in one Swedish feed to 2,629 records with published status across six feeds. A fresh read through the public search query returns **2,621 visible jobs**: eight published records are already past their provider expiry. Three additional records have expired status. These numbers will change with refreshes and time-based expiry.

| Configured source | Published status |
| --- | ---: |
| Himalayas | 1,956 |
| JobTech / Arbetsförmedlingen | 381 |
| Arbeitnow | 175 |
| Jobicy | 84 |
| Remote OK | 25 |
| Remotive | 8 |
| Total | 2,629 |

The committed `jobs.json` contains 3,432 exported jobs. That standalone export also includes employer boards and is **not** the database or the public inventory. Keyword classification includes roles using AI tools as well as roles building AI systems; it is not a manual relevance assessment of every advertisement.

`sources.global.json` is the enabled six-feed configuration from the expansion. It enables automatic publication for those sources; use it deliberately. The disabled template in `sources.example.json` remains suitable for configuring new sources. Collector scheduling persists in SQLite, so rerunning a collector does not bypass refresh intervals.

```bash
python3 backend/ingestion.py --config sources.global.json
```

## Employer directory and attribution

[`data/source-candidates.json`](../data/source-candidates.json) contains **9,935** distinct board mappings: 4,966 Greenhouse, 2,856 Ashby and 2,113 Lever. All catalogue entries have `enabled: false`, `auto_publish: false` and no recorded job redistribution permission.

The mappings are adapted from [LastRound AI's ATS company directory](https://github.com/fyrosofttech/lastroundai-hiring-data/tree/2816bfadd65b7bbec23701dd036bcc7496c729db/ats-directory), attributed to [LastRound AI](https://lastroundai.com/blog/salary-transparency-study-2026), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Signal converted the CSV to normalized provider/board candidates and added disabled collection defaults. The catalogue's `directory` object records the source URL, immutable upstream commit, fetch date and SHA-256 hashes of the CSV, license and supporting documentation. This license covers directory mappings; it does not establish permission to republish employer job descriptions.

To import an updated local CSV, retain its license and provenance:

```bash
python3 backend/discovery.py import-directory \
  --input /tmp/directory.csv --output /tmp/source-candidates.json \
  --license-file /tmp/directory-LICENSE \
  --source-url 'https://example.org/path/to/reviewed-directory.csv' \
  --fetched-at '2026-10-12T00:00:00Z' \
  --attribution 'Directory publisher' \
  --attribution-url 'https://example.org/directory'
```

Replace the illustrative URLs, attribution and timestamp with the actual reviewed source. Optional `--upstream-commit`, `--readme-file` and `--method-file` retain supporting provenance. The importer accepts the reviewed LastRound CSV format and CC BY 4.0 license, not arbitrary directory formats.

## Bounded endpoint observations

```bash
python3 backend/discovery.py validate \
  --input data/source-candidates.json \
  --output /tmp/signal-validation.json \
  --limit 100 --workers 4 --pace-seconds 0.75
```

Validation examines the **first** `--limit` candidates. To cover a different provider or batch, create a filtered candidate JSON file first; naming an output file after a provider does not select that provider. The `parse_board_url` Python helper recognizes supplied public ATS URLs. Career-page HTML extraction remains follow-up work; there is no arbitrary-site crawler.

Historical reports committed during the expansion overlap:

| Report | Actual provider coverage | Observations | Nonempty | Empty | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| `validation-report.json` | Ashby | 100 | 83 | 10 | 7 |
| `validation-report-greenhouse.json` | Ashby, despite filename | 50 | 41 | 5 | 4 |
| `validation-gh.json` | Ashby, despite filename | 20 | 17 | 2 | 1 |
| `validation-gh-lv.json` | 30 Greenhouse + 30 Lever | 60 | 47 | 8 | 5 |

Deduplicating by `source_id` and keeping the latest `checked_at` yields **160 observed boards: 130 nonempty, 18 empty and 12 errors**. Do not sum these reports as independent coverage. These are historical endpoint observations, not a fresh availability guarantee. The validator now rejects records without titles; old reports have not been regenerated under that stricter check. Counts of AI keyword matches are estimates, not approved listings.

Discovery neither ingests nor publishes jobs. Review permission and source requirements before moving a candidate into the ingestion configuration. See [ingestion setup](INGESTION.md) and [source policy](JOB_SOURCE_POLICY.md).
