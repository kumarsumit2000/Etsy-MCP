# Etsy MCP

Python MCP server for managing an Etsy shop end-to-end from Claude.

**Status:** Phase 0 — auth foundation. See [docs/superpowers/specs/2026-05-04-etsy-mcp-design.md](docs/superpowers/specs/2026-05-04-etsy-mcp-design.md) for full design.

## Quick start

1. Follow [SETUP.md](SETUP.md) to create your Etsy developer app.
2. Copy `.env.example` to `.env` and fill in `ETSY_KEYSTRING` and `ETSY_SHARED_SECRET`.
3. Run the OAuth bootstrap:
   ```bash
   source .venv/bin/activate
   python scripts/bootstrap_oauth.py
   ```
4. Paste the printed `shop_id` into `.env` as `ETSY_SHOP_ID`.
5. Add the MCP to Claude Code (see SETUP.md § "Wire MCP into Claude").
6. From Claude, call `etsy_whoami` to verify.

## Layout

```
etsy_mcp/         Python package — auth, http, errors
scripts/          one-time bootstrap scripts
tests/            pytest suite
server.py         FastMCP entrypoint
```

## Development

```bash
pip install -r requirements-dev.txt
pytest                 # run unit tests
pytest -v -k auth      # focused
```
