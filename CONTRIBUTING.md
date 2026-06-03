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
# macOS/Linux: create and activate a venv first (see README)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.run
```

### Tests + lint

```bash
pytest -q -m "not network"
ruff check .
python -m compileall app geonorge
```

Live Geonorge/Kartverket fetches (optional, slower):

```bash
pytest -q -m network
```

### Scripts

`scripts/` holds one-off dev probes (GeoJSON URL checks, etc.). They are not used by the app at runtime and may hit endpoints other than production defaults in `geonorge/map_selection.py`.

### Debugging flags

- `python -m app.run --no-tooltips`: disables delayed tooltips (useful if investigating tooltip-related crashes)
- `python -m app.run --profile-ui`: logs UI recompute timings (INFO)

