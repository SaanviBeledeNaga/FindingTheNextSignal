# Running PHARMA-SCOPE 0.6.1

The interactive browser dashboard replaces the terminal UI and uses the existing Python research engine. This release is prepared for the local Windows installation; public deployment has not been performed.

## Local installation

```powershell
python -m pip install -e ".[ai,search]"
python -m pharma_scope web --open
```

Run these commands from the project folder. The dashboard is http://127.0.0.1:8765. Keep the server running. `start.ps1` opens it as well. Opening does not spend API quota; starting or continuing research does. Settings remain in `.env`; investigations remain in `.pharma`.

## Updates and rollback

Back up `.pharma` before changing versions. Replace source files without replacing `.env` or research archives, reinstall, and restart. Existing saved findings receive new reporting-scope checks. Old wheels remain in `outputs/releases` for rollback; older terminal releases require their former dependencies. The 0.6.1 wheel contains web assets and excludes removed terminal modules.

## Access through an existing SSH server

If a server is available, install Python 3.11+, transfer source, configure keys locally there, and run the dashboard on that server's loopback interface. From the laptop:

```sh
ssh -L 8765:127.0.0.1:8765 user@server
```

Use http://127.0.0.1:8765 locally. This requires an existing server and does not provision paid hosting. SSH forwarding has not been exercised from this workspace. Do not expose the built-in loopback server directly to the public internet.

## Hosting boundary

A static frontend host alone cannot run the current Python/LangGraph/PyMuPDF worker, SQLite archive and model subprocesses. Public deployment requires a compatible backend, authenticated access and durable storage. The dashboard's mutation token, Host checks and Origin checks protect local requests; they are not multiuser authentication. API keys do not belong in browser JavaScript.

The historical Dockerfile remains for batch CLI research. Compose is not configured as a deployed web service. Container builds and remote hosting were not verified in this release.
