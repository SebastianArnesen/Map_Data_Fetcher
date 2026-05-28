## Contributing

### Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Run

```bash
python -m app.run
```

### Tests + lint

```bash
pytest -q
ruff check .
python -m compileall app geonorge
```

### Debugging flags

- `python -m app.run --no-tooltips`: disables delayed tooltips (useful if investigating tooltip-related crashes)
- `python -m app.run --profile-ui`: logs UI recompute timings (INFO)

