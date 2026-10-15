#!/usr/bin/env bash
# Run only from deploy-to-docker.ps1 -InitializeLocal using a verified local bundle.
set -euo pipefail
: "${LOCAL_SITE:?}" "${LOCAL_DB_ROOT_PASSWORD:?}" "${LOCAL_ADMIN_PASSWORD:?}"
cd /workspace/development/frappe-bench
bench set-config -g db_host mariadb
bench set-config -g redis_cache redis://redis-cache:6379
bench set-config -g redis_queue redis://redis-queue:6379
bench set-config -g redis_socketio redis://redis-queue:6379
bench set-config -g socketio_port 9082
bench set-config -g serve_default_site true
if [[ ! -d apps/erpnext ]]; then
    bench get-app --branch version-15 --skip-assets https://github.com/frappe/erpnext.git
fi
if [[ ! -d apps/hrms ]]; then
    bench get-app --branch version-15 --skip-assets https://github.com/frappe/hrms.git
fi
./env/bin/pip install -e apps/rayher_hr_payroll
# These are generated bench configuration files, not application source.
./env/bin/python - <<'PY'
from pathlib import Path
apps = Path('sites/apps.txt')
lines = apps.read_text().splitlines()
if 'rayher_hr_payroll' not in lines:
    apps.write_text('\n'.join(lines + ['rayher_hr_payroll']) + '\n')
procfile = Path('Procfile')
lines = procfile.read_text().splitlines()
procfile.write_text('\n'.join(line for line in lines if not line.startswith(('redis_', 'watch:', 'schedule:'))) + '\n')
PY
(cd apps/rayher_hr_payroll/frontend && yarn install --frozen-lockfile)
bench build
# The bench image ships a MariaDB 11.8 client, while this isolated local
# network uses MariaDB 10.6 without TLS. This generated client setting is
# confined to the local bench container; database ports are not published.
./env/bin/python - <<'PY'
from pathlib import Path
client_config = Path.home() / '.my.cnf'
expected = '[client]\nskip-ssl\n'
if client_config.exists() and client_config.read_text() != expected:
    raise SystemExit('Unexpected existing MariaDB client config; preserving it for inspection.')
client_config.write_text(expected)
client_config.chmod(0o600)
PY
site_state=$(./env/bin/python - <<'PY'
import json
import os
from pathlib import Path
import pymysql
site_config = Path('sites') / os.environ['LOCAL_SITE'] / 'site_config.json'
if not site_config.exists():
    print('missing')
else:
    config = json.loads(site_config.read_text())
    with pymysql.connect(host='mariadb', user=config.get('db_user') or config['db_name'],
                         password=config['db_password'], database=config['db_name']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SHOW TABLES')
            tables = {row[0] for row in cursor.fetchall()}
    if not tables and not Path('.local-ready').exists():
        print('empty')
    elif {'tabDocType', 'tabSingles', 'tabUser'} <= tables:
        print('initialized')
    else:
        raise SystemExit('Partially initialized database contains tables; preserving it for inspection.')
PY
)
if [[ "$site_state" == missing || "$site_state" == empty ]]; then
    site_options=()
    if [[ "$site_state" == empty ]]; then
        echo 'Recovering verified empty database left by interrupted site creation.'
        site_options+=(--force)
    fi
    bench new-site "$LOCAL_SITE" --db-type mariadb --db-host mariadb \
        --db-root-password "$LOCAL_DB_ROOT_PASSWORD" \
        --mariadb-user-host-login-scope '%' --admin-password "$LOCAL_ADMIN_PASSWORD" "${site_options[@]}"
fi
# Only framework and app metadata is installed; no production or demo business data.
bench --site "$LOCAL_SITE" set-config mute_emails 1
bench --site "$LOCAL_SITE" install-app erpnext
bench --site "$LOCAL_SITE" install-app hrms
bench --site "$LOCAL_SITE" install-app rayher_hr_payroll
bench --site "$LOCAL_SITE" disable-scheduler
bench use "$LOCAL_SITE"
touch .local-ready
