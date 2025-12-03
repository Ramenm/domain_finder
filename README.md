# Domain Finder

⚡ **Domain name generator and checker using LLM with availability checking via RDAP/WHOIS.**

Domain Finder is a powerful CLI tool that leverages Large Language Models (LLMs) to generate creative domain name suggestions based on your topic, then automatically checks their availability using RDAP and WHOIS protocols. Perfect for finding available domains for your next project!

## Features

- 🤖 **LLM-Powered Generation**: Uses OpenAI GPT models to generate creative domain name suggestions based on your topic
- 🔍 **Availability Checking**: Fast and reliable domain availability checking via RDAP (preferred) with WHOIS fallback
- ⚡ **Parallel Processing**: Concurrent domain checking and LLM requests for maximum efficiency
- 💾 **Smart Caching**: Caches domain check results to avoid redundant API calls
- 📊 **Multiple Output Formats**: Export results to both TXT and CSV formats
- 🎯 **Flexible Configuration**: Extensive CLI options and environment variable support
- 🧙 **Interactive Wizard**: User-friendly interactive mode for guided setup
- 🏗️ **Clean Architecture**: Well-structured codebase following Clean Architecture principles

## Requirements

- Python >= 3.10
- OpenAI API key (or compatible API endpoint)

## Installation

### From Source

1. Clone the repository:
```bash
git clone <repository-url>
cd domain_finder
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv

# On Windows
.venv\Scripts\activate

# On Linux/macOS
source .venv/bin/activate
```

3. Install the package in editable mode:
```bash
pip install -e .
```

### Development Dependencies

To install development dependencies (pytest, mypy, ruff, etc.):
```bash
pip install -e ".[dev]"
```

## Configuration

Domain Finder uses environment variables for configuration. Create a `.env` file in the project root:

```env
# Required: OpenAI API Key
OPENAI_API_KEY=your_api_key_here

# Optional: LLM Configuration
OPENAI_MODEL=gpt-4o
OPENAI_BASE_URL=https://api.openai.com/v1

# Optional: Domain Checking Preferences
USE_RDAP=true

# Optional: HTTP Settings
HTTP_TIMEOUT=60.0
RDAP_TIMEOUT=10.0
MAX_CONNECTIONS=100
MAX_KEEPALIVE_CONNECTIONS=20

# Optional: Retry Settings
MAX_RETRIES=3
RETRY_BACKOFF_MIN=1.0
RETRY_BACKOFF_MAX=3.0

# Optional: LLM Concurrency
MAX_CONCURRENT_LLM_REQUESTS=8
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key (required) | - |
| `OPENAI_MODEL` | Default OpenAI model | `gpt-4o` |
| `OPENAI_BASE_URL` | OpenAI API base URL | `https://api.openai.com/v1` |
| `USE_RDAP` | Prefer RDAP over WHOIS | `true` |
| `HTTP_TIMEOUT` | HTTP request timeout (seconds) | `60.0` |
| `RDAP_TIMEOUT` | RDAP request timeout (seconds) | `10.0` |
| `MAX_CONNECTIONS` | Maximum HTTP connections | `100` |
| `MAX_CONCURRENT_LLM_REQUESTS` | Max parallel LLM requests | `8` |

## Usage

Domain Finder provides two main commands: `run` (direct CLI) and `wizard` (interactive mode).

### Command-Line Mode (`run`)

Basic usage:
```bash
domain-finder run --topic "neural networks, benchmarks, model comparison"
```

With custom parameters:
```bash
domain-finder run \
  --topic "AI-powered analytics platform" \
  --iterations 5 \
  --per-request 100 \
  --tld com io ai \
  --llm-workers 2 \
  --workers 20 \
  --min-len 4 \
  --max-len 15 \
  --results results.txt \
  --results-csv results.csv
```

#### Common Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--topic` | `-t` | Domain topic/theme | Required |
| `--iterations` | `-i` | Number of generation passes | `5` |
| `--per-request` | `-n` | Domains per iteration | `100` |
| `--tld` | | Top-level domains (comma-separated) | `com` |
| `--provider` | `-p` | LLM provider | `openai` |
| `--model` | `-m` | Model name | From env |
| `--llm-workers` | | Parallel LLM requests | `1` |
| `--workers` | | Threads for domain checking | `20` |
| `--min-len` | | Minimum domain label length | `4` |
| `--max-len` | | Maximum domain label length | `15` |
| `--rdap` / `--whois` | | Prefer RDAP or WHOIS | From env |
| `--whois-fallback` | | Use WHOIS as fallback | `false` |
| `--skip-check` | | Skip availability check | `false` |
| `--cache-file` | | Cache file path | `domains_cache.json` |
| `--clear-cache` | | Clear cache before start | `false` |
| `--results` | | Results TXT file | `results.txt` |
| `--results-csv` | | Results CSV file | `results.csv` |
| `--cooldown` | | Pause between iterations (sec) | `2.0` |
| `--temperature` | | LLM temperature (0.0-2.0) | `0.7` |
| `--timeout` | | LLM request timeout (sec) | `60.0` |

### Interactive Wizard Mode (`wizard`)

For a guided, interactive experience:
```bash
domain-finder wizard
```

The wizard will prompt you for all necessary parameters step by step.

### Examples

**Find domains for a tech startup:**
```bash
domain-finder run \
  --topic "cloud infrastructure automation" \
  --tld com io tech \
  --iterations 3 \
  --per-request 50
```

**Generate domains without checking availability:**
```bash
domain-finder run \
  --topic "creative design agency" \
  --skip-check \
  --results generated_domains.txt
```

**Use multiple parallel LLM workers for faster generation:**
```bash
domain-finder run \
  --topic "machine learning platform" \
  --llm-workers 3 \
  --per-request 150 \
  --iterations 5
```

## Architecture

Domain Finder follows **Clean Architecture** principles with clear separation of concerns:

```
domain_finder/
├── domain/           # Core business logic and models
│   ├── models.py     # Domain entities (DomainCandidate, DomainCheckResult)
│   ├── services.py   # Domain services (DomainGeneratorService, DomainCheckService)
│   ├── ports.py      # Interfaces/ports for adapters
│   └── errors.py     # Domain-specific exceptions
│
├── application/      # Use cases and application logic
│   ├── use_cases.py  # RunDomainSearchUseCase
│   └── dto.py        # Data Transfer Objects
│
├── infrastructure/   # External adapters and implementations
│   ├── llm/          # LLM provider implementations (OpenAI)
│   ├── whois/        # Domain checking (RDAP, WHOIS clients)
│   ├── cache.py      # Caching implementation
│   ├── persistence.py # Result persistence
│   └── config.py     # Configuration management
│
└── cli/              # Command-line interface
    ├── app.py        # Typer application
    └── commands/     # CLI commands (run, wizard)
```

### Key Components

- **Domain Layer**: Pure business logic, no external dependencies
- **Application Layer**: Orchestrates use cases using domain services
- **Infrastructure Layer**: Implements ports with external services (LLM APIs, RDAP/WHOIS)
- **CLI Layer**: User interface built with Typer and Rich

## Development

### Setup Development Environment

1. Install development dependencies:
```bash
pip install -e ".[dev]"
```

2. Install pre-commit hooks (optional):
```bash
pre-commit install
```

### Running Tests

Run all tests:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=domain_finder --cov-report=html
```

Run specific test file:
```bash
pytest tests/test_domain_services.py
```

### Code Quality

**Linting with Ruff:**
```bash
ruff check domain_finder/
```

**Type checking with mypy:**
```bash
mypy domain_finder/
```

**Format code:**
```bash
ruff format domain_finder/
```

### Project Structure

- **Tests**: Located in `tests/` directory
- **Test Markers**: `unit`, `integration`, `slow`
- **Coverage**: HTML reports generated in `htmlcov/`

## Output Files

### Results TXT (`results.txt`)
Simple text file with one domain per line:
```
example1.com
example2.io
example3.ai
```

### Results CSV (`results.csv`)
CSV file with domain, source, and timestamp:
```csv
domain,source,checked_at
example1.com,rdap,1234567890.123
example2.io,whois,1234567891.456
```

### Cache File (`domains_cache.json`)
JSON cache of domain check results to avoid redundant API calls.

## Troubleshooting

**Issue**: `OPENAI_API_KEY not found`
- **Solution**: Ensure `.env` file exists with `OPENAI_API_KEY` set, or export it as an environment variable

**Issue**: Rate limiting errors
- **Solution**: Reduce `--llm-workers` or increase `--cooldown` between iterations

**Issue**: Domain checking timeout
- **Solution**: Increase `RDAP_TIMEOUT` in `.env` or reduce `--workers`

**Issue**: Too many connection errors
- **Solution**: Reduce `MAX_CONNECTIONS` in `.env` or `--workers` parameter

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Follow the existing code style (enforced by Ruff)
2. Add tests for new features
3. Update documentation as needed
4. Ensure all tests pass before submitting

## License

[Add license information here]

## Acknowledgments

- Built with [Typer](https://typer.tiangolo.com/) for CLI
- Beautiful output with [Rich](https://rich.readthedocs.io/)
- Domain checking via RDAP and WHOIS protocols
