# Contributing

Contributions, bug fixes, and ideas are welcome. This is a personal tool under the
[MIT License](LICENSE); for anything non-trivial, please open an issue first to
discuss the approach.

## Development setup

```bash
git clone https://github.com/NBPub/karaoke_vid_gen.git
cd karaoke_vid_gen
python -m venv .venv && .venv/Scripts/activate     # Windows; see docs/Installation.md for UNIX + GPU
pip install -r requirements.txt
pip install -e ".[dev]"                            # editable install + pytest
```

The full setup, including the CUDA PyTorch build, is in
[Installation](docs/Installation.md#installation).

## Before opening a PR

- Keep changes scoped, and match the style of the surrounding code.
- Run the suite from the project root: `pytest`. It's fast and offline: the
  ML and network stages are mocked, so no GPU, downloads, or sample audio are
  needed.
- Add tests for new pure logic (timing, parsing, config). See
  [Code → Tests](docs/Code.md#tests) for how the suite is organized.
