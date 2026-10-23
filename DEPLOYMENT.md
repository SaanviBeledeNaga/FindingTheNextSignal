# Deploy PHARMA SCOPE

Version 0.3.1 is a terminal application with exported HTML reports. It does not serve a browser application or expose a web endpoint. You can update the application after installation or container deployment. The research workflow is still a preview: current real-company trials produce unresolved hypotheses rather than supported discoveries.

## Free remote sessions with GitHub Codespaces

GitHub states that personal accounts can start Codespaces without payment details. GitHub Free includes 120 core-hours and 15 GB-month of storage per month. A two-core machine uses two core-hours per running hour, so that compute allowance is approximately 60 running hours. With no payment method, usage is blocked when the free allowance is exhausted. Use the smallest machine and stop it after research sessions. Storage usage continues while a codespace is stopped. This is an on-demand research/development environment, not continuous server hosting. Model/search API quotas are separate.

1. Sign into a personal GitHub account and create a private repository for the project. Upload the extracted source package contents, including `.devcontainer`, `.gitignore` and `.env.example`. Do not upload your local `.env` or `.pharma` folder. This release archive excludes those files.
2. In the repository choose **Code**, **Codespaces**, then **Create codespace on main**. Use a two-core machine. The included `.devcontainer/devcontainer.json` configures Python 3.11 and installs the application and search dependencies. The remote Codespaces build has not been executed from this development environment.
3. In the remote terminal create settings once and edit them locally there:

```sh
test -f .env || cp .env.example .env
nano .env
```

Set `PHARMA_PROVIDER=gemini`, `PHARMA_SEARCH_PROVIDER=duckduckgo`, your model ID and your Gemini key. Leave tracing disabled unless you deliberately enable it. Do not paste keys into chat or commit `.env`.

```sh
python -m pharma_scope doctor
python -m pharma_scope demo --tui
python -m pharma_scope investigate "Sun Pharmaceutical Industries" --seconds 900 --tui
```

When using the default data directory, run these commands from the repository root. Keep `.pharma` within the workspace so runs persist between stop/start cycles. Back up important reports and research archives before deleting a codespace or allowing retention expiry; persistence is not permanent archival storage.

To use SSH from your laptop, install GitHub CLI, then run:

```sh
gh auth login
gh codespace ssh
```

The command lets you select your codespace. There is no fixed public server IP to configure. The browser terminal is also available. Authentication and creation of the environment require access to your GitHub account; this package does not create an account or provision a codespace.

For updates, commit reviewed source changes to your private repository and pull them in the codespace. The editable installation uses changed Python source directly on the next run; rerun `python -m pip install -e '.[ai,search]'` when dependencies change. Keep `.env` and `.pharma` outside version control, back up data and finish active runs before updating. Database migrations still need a compatibility review.

References: [starting without payment details](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces), [free usage and billing limits](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces), [SSH with GitHub CLI](https://docs.github.com/en/codespaces/developing-in-a-codespace/using-github-codespaces-with-github-cli).

## Install the versioned release on Windows

The release wheel installs the application rather than relying on an editable source checkout. From the existing project directory, use the wheel in the adjacent releases folder:

```powershell
python -m pip install --upgrade "../releases/pharma_scope-0.3.1-py3-none-any.whl[ai,search]"
pharma doctor
pharma demo --tui
```

Keep your existing `.env` in the directory where you run the command. The application reads configuration and uses `.pharma` relative to that working directory. Keep running from the existing project directory to use your existing saved investigations. `doctor` checks settings presence, not live API access.

```powershell
pharma investigate "Sun Pharmaceutical Industries" --seconds 900 --tui
```

For a separate configuration/data directory, create a folder of your choice, put your `.env` there, change to that folder and run `pharma`. Do not share API keys in messages or include them in a release archive.

## Run on a Docker host through SSH

This requires a machine you can access through SSH with Docker Engine and Compose installed. No remote host is configured by this release. Container execution has not been tested on the development machine because Docker is unavailable there.

Copy the source release to your host and create `.env` there using `.env.example`. Choose model/search providers and supply credentials on the host. Existing local keys and research data are excluded from the release. A new container volume starts empty; existing local runs are not automatically migrated.

From the extracted project directory on the host:

```sh
docker compose build
docker compose run --rm agent doctor
docker compose run --rm agent demo --tui
docker compose run --rm agent investigate "Sun Pharmaceutical Industries" --seconds 900 --tui
```

Connect with `ssh -t your-user@your-host` for an interactive terminal. The container runs as a non-root user. Runtime settings come from `.env`; the build context allowlist includes only application code and package metadata. No API keys are required at image build time. No public ports are opened.

The Compose named volume `research-data` stores SQLite, source archives, checkpoints and reports outside disposable containers. Keep the Compose project name and volume configuration stable during updates.

Export a report into the host directory for downloading with SCP:

```sh
docker compose run --rm -T agent export latest --format html --output /data/latest.html
docker compose run --rm -T --entrypoint python agent -c "from pathlib import Path; import sys; sys.stdout.buffer.write(Path('/data/latest.html').read_bytes())" > latest.html
```

The second command redirects bytes on the remote Linux shell. Download `latest.html` from the host and open it locally.

## Update and roll back

Finish active investigations before replacing application versions. A stopped run can resume from its saved checkpoint with the same data directory; unfinished external requests may repeat after interruption.

For a wheel installation, install the next wheel with `python -m pip install --upgrade` and continue using the same working directory. Keep the previous wheel if you need to reinstall it. The same package also supports development from the editable source checkout, but choose one install method per Python environment.

For a container deployment, keep a copy/tag of the current image, replace the application source with the new release and run `docker compose build`. Subsequent `docker compose run --rm agent ...` commands use the new image and existing named data volume. Keep `.env` when updating source files.

Before upgrades, stop research processes and back up the complete data directory or volume, including SQLite and archived files. A backup of the container volume can be made without copying credentials:

```sh
docker compose run --rm -T --entrypoint tar agent -C /data -czf - . > research-backup.tar.gz
```

Future versions that change the database format need a migration and compatibility review. Reinstalling older code does not reverse a database migration; restore a compatible backup when needed. This release adds fields to newly stored research JSON without changing the SQL tables. Start a new investigation to use all quality checks; an old completed checkpoint does not reevaluate itself.

Docker references: [named-volume persistence and image updates](https://docs.docker.com/compose/gettingstarted/), [runtime configuration](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/), [keeping secrets out of image builds](https://docs.docker.com/build/building/secrets/).
