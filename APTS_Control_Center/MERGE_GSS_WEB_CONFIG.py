"""Add gss_web to an existing Control Center config without replacing user paths."""
import json
from pathlib import Path
from datetime import datetime
p=Path(__file__).resolve().parent/'config.json'
data=json.loads(p.read_text(encoding='utf-8-sig'))
if 'gss' not in data.get('modules',{}):raise SystemExit('Missing gss module in config.json')
if 'gss_web' in data['modules']:raise SystemExit('gss_web already configured; no change')
backup=p.with_name('config.before-gss-web.'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.json')
backup.write_bytes(p.read_bytes())
data['modules']['gss_web']={'root':'','port':8802,'python':'','env':{}}
p.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print('gss_web added; existing module configuration preserved. Backup:',backup.name)
