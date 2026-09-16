# Domain Finder

Domain Finder is a Python CLI for generating domain-name ideas and checking their registry state with RDAP and WHOIS.

The checker distinguishes an unregistered domain from a domain that is explicitly reported as registrable. A missing RDAP/WHOIS record is not treated as a guarantee that a registrar can sell the name.

## Requirements

- Python 3.10 or newer
- CI continuously verifies CPython 3.10–3.14; Python 3.15 pre-releases are tested experimentally until 3.15 reaches GA.
- An OpenAI API key, or an OpenAI-compatible API endpoint

## Install

```bash
git clone https://github.com/Ramenm/domain_finder.git
cd domain_finder
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development tools:

```bash
pip install -e ".[dev]"
pre-commit install
```
## Configure

Copy the example environment file and add your API key:

```bash
cp .env.example .env
```

Minimum configuration:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o
OPENAI_BASE_URL=https://api.openai.com/v1
```

Domain-checking, retry, cache, timeout, and concurrency settings are documented in `.env.example`.

## Use

Interactive mode:

```bash
domain-finder wizard
```

Direct mode:

```bash
domain-finder run --topic "developer tools"
```
Example with multiple TLDs and parallel checking:

```bash
domain-finder run \
  --topic "database monitoring" \
  --tld com \
  --tld io \
  --iterations 3 \
  --per-request 50 \
  --workers 20
```

Use `domain-finder run --help` for the full option list.

## Domain statuses

The checker can return these main states:

- `REGISTERED` — a domain object exists.
- `UNREGISTERED` — no domain object was found, but purchase is not confirmed.
- `RESERVED` — registry or ICANN policy blocks ordinary registration.
- `REGISTRABLE` — an explicit registry/WHOIS signal says the name is available for registration.
- `UNKNOWN`, `RATE_LIMITED`, `NETWORK_ERROR`, `UNSUPPORTED`, `INVALID` — no purchase claim is made.

Registrar checkout remains the final authority for actual registration, pricing, and eligibility.

## Results and exit behavior

`results.txt` contains confirmed registrable domains. With `--skip-check`, it intentionally contains generated names without making an availability claim.

`results.csv` is the authoritative report for every processed candidate. Its columns are `domain`, `status`, `available`, `source`, `checked_at`, and `detail`. Re-running a search updates an older `skipped` or inconclusive row when a later registry check has a more definitive result.

During long work the CLI reports generation and checking phases. Redirected/non-interactive output stays plain and does not depend on terminal control sequences.

Exit behavior is intentionally strict: invalid input/configuration uses exit code `2`, a run with no usable generation result uses `1`, and Ctrl+C uses `130`. Partial generation failures preserve completed work and are reported explicitly instead of being presented as a clean success.

## Development

Run the default offline test suite:

```bash
pytest
```

Run repository checks:

```bash
pre-commit run --all-files
```

The default pytest configuration excludes tests marked `network` and `slow`.

Architecture notes are in `docs/architecture.md`.

## License

MIT. See `LICENSE`.
