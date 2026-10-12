# Hosting Signal on your own machine

The intended public address is `https://signal.tnhc.dev`. The application will run on the owner's machine; Cloudflare manages the domain and does not need to run the application or database.

The repository now includes a separate **public browsing runtime**. It serves search, filters, saved jobs, full descriptions and application links using the same Python search code as the development app. It has no employer, moderator, payment or ingestion endpoints and ignores development identity headers. This is the first public-hosting stage, not the completed paid marketplace.

## Run the public application locally

From the repository root on Linux, with Python 3.10+:

```bash
python3 -m venv .venv-public
.venv-public/bin/python -m pip install -r requirements-public.txt

# Create a separate empty database for deployment preparation.
# Do not copy test fixtures or the development database into production.
PYTHONPATH=backend .venv-public/bin/python -c 'from pathlib import Path; from local_server import initialize; initialize(Path("signal-public.sqlite3"))'

SIGNAL_DB_PATH="$PWD/signal-public.sqlite3" \
  .venv-public/bin/gunicorn --config deploy/gunicorn.conf.py \
  --chdir backend 'public_server:create_app()'
```

Open `http://127.0.0.1:8001`. The initialized database has no jobs. Public requests use read-only SQLite connections and will never create an empty database if the configured path is wrong. `/api/v1/health` reports readiness and returns 503 when the database/schema cannot be read.

Keep the existing local employer/operations app at port 8000. Production sign-in, company accounts and real payments still need implementation before those actions are offered publicly. Ingestion runs in its own process against an explicitly selected database; new source records still require review by default. Do not expose the local development app as a workaround for missing public staff access.

## Keep the public process running with systemd

The user service template expects a stable project link at `~/.local/share/signal` and a private environment file. These commands install the unit but do not change DNS or open firewall ports:

```bash
mkdir -p "$HOME/.local/share" "$HOME/.config/signal" "$HOME/.config/systemd/user"
# Run only when this link does not already exist; do not replace another project.
ln -s "$PWD" "$HOME/.local/share/signal"
cp deploy/signal-public.service "$HOME/.config/systemd/user/"
```

Create `~/.config/signal/public.env` with the absolute path to the intended database:

```ini
SIGNAL_DB_PATH=/absolute/path/to/signal-public.sqlite3
SIGNAL_BIND=127.0.0.1:8001
```

Then run:

```bash
chmod 600 "$HOME/.config/signal/public.env"
systemctl --user daemon-reload
systemctl --user enable --now signal-public.service
systemctl --user status signal-public.service
journalctl --user -u signal-public.service -n 50
```

User services normally depend on the user's session. If this machine must serve jobs while logged out or after reboot, arrange system-level service management or user lingering with the machine administrator. Database backups should use SQLite's backup facility so a concurrent collector cannot leave an inconsistent file copy.

## Connect the domain when ready

Route only `signal.tnhc.dev` through the machine's existing HTTPS reverse proxy or tunnel to `http://127.0.0.1:8001`. Leave port 8000 private. The concrete DNS/proxy change depends on the machine's existing routing setup; this repository does not change it automatically.

Terminate TLS at that proxy/tunnel and verify its certificate covers `signal.tnhc.dev`. Keep the Gunicorn listener on loopback. Test `/api/v1/health`, search and direct `/jobs/{id}` navigation through the HTTPS hostname before opening traffic. Employer/admin/payment requests must continue to be unavailable on this browsing-only build.

## Validation

```bash
npm test
SIGNAL_BROWSER_EXECUTABLE=/path/to/chromium npm run test:public-browser
```

The public browser suite starts Gunicorn with a disposable database. Omit `SIGNAL_BROWSER_EXECUTABLE` if Playwright's Chromium is installed. `SIGNAL_PUBLIC_PYTHON` can select a different Python executable with the pinned Gunicorn dependency installed.

The runtime uses [Gunicorn's WSGI application-factory support](https://gunicorn.org/quickstart/) behind a proxy; the [deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/) explains the loopback/proxy boundary. No Flask dependency is required by this application.
