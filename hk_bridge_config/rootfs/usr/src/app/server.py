"""
HomeKit Bridge 配置器 - Flask 后端
"""
import os
import sys
import json
import logging
import requests
import yaml as pyyaml
from flask import Flask, request, jsonify, render_template, Response
from collections import OrderedDict

import yaml_ops

# ============== 配置 ==============
APP_PORT = int(os.environ.get('APP_PORT', 8099))
YAML_PATH = os.environ.get(
    'YAML_PATH',
    '/config/homekit_bridges.yaml'  # 默认值,add-on 在容器内 /config 即 HA 的 /config
)
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
HA_API = 'http://supervisor/core/api'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
LOG = logging.getLogger('hk_bridge_config')

app = Flask(__name__)


# ============== 工具 ==============
def ha_headers():
    return {
        'Authorization': f'Bearer {SUPERVISOR_TOKEN}',
        'Content-Type': 'application/json',
    }


def ha_get(path, **params):
    """调 HA REST API"""
    url = HA_API + path
    LOG.info(f"GET {url} params={params}")
    r = requests.get(url, headers=ha_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def ha_post(path, json_body):
    url = HA_API + path
    LOG.info(f"POST {url} body_keys={list(json_body.keys()) if isinstance(json_body, dict) else type(json_body).__name__}")
    r = requests.post(url, headers=ha_headers(), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else []


# ============== 路由 ==============
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health')
def health():
    return jsonify({'ok': True, 'yaml_path': YAML_PATH, 'has_token': bool(SUPERVISOR_TOKEN)})


@app.route('/api/bridges')
def get_bridges():
    """读 yaml + HA states,返回 6 bridge 详情"""
    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
    except Exception as e:
        LOG.exception("Read yaml failed")
        return jsonify({'error': str(e)}), 500

    # 从 HA 拿所有 entity 的 friendly_name(用本地 token 也行,这里用 supervisor token)
    entity_map = {}
    if SUPERVISOR_TOKEN:
        try:
            states = ha_get('/states')
            for s in states:
                entity_map[s['entity_id']] = {
                    'friendly_name': s['attributes'].get('friendly_name', s['entity_id']),
                    'state': s.get('state'),
                    'domain': s['entity_id'].split('.')[0],
                }
        except Exception as e:
            LOG.warning(f"Failed to fetch HA states: {e}")

    out = []
    for i, b in enumerate(bridges):
        included = (b.get('filter', {}) or {}).get('include_entities', []) or []
        ec = b.get('entity_config', {}) or {}
        bridge_entities = []
        for ent in included:
            meta = entity_map.get(ent, {})
            bridge_entities.append({
                'entity_id': ent,
                'domain': ent.split('.')[0],
                'name': ec.get(ent, {}).get('name', '') if isinstance(ec.get(ent), dict) else '',
                'friendly_name': meta.get('friendly_name', ent),
                'state': meta.get('state'),
            })
        out.append({
            'index': i,
            'name': b.get('name', ''),
            'port': b.get('port'),
            'mode': b.get('mode', 'bridge'),
            'count': len(included),
            'entities': bridge_entities,
        })
    return jsonify({'bridges': out, 'total_included': sum(len(o['entities']) for o in out)})


@app.route('/api/entities')
def get_entities():
    """HA 全部 entity,带 friendly_name,用于「+ 添加 entity」"""
    if not SUPERVISOR_TOKEN:
        return jsonify({'entities': [], 'error': 'No SUPERVISOR_TOKEN'})
    try:
        states = ha_get('/states')
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    out = []
    for s in states:
        ent = s['entity_id']
        out.append({
            'entity_id': ent,
            'domain': ent.split('.')[0],
            'friendly_name': s['attributes'].get('friendly_name', ent),
            'state': s.get('state'),
        })
    return jsonify({'entities': out, 'count': len(out)})


@app.route('/api/save', methods=['POST'])
def save():
    """
    body:
      {
        "bridge_id": 51801,       // port
        "included_entities": [...],
        "entity_config": {"entity_id": {"name": "..."}, ...}
      }
    写 yaml + 备份 + reload
    """
    data = request.get_json(force=True)
    bridge_id = data.get('bridge_id')
    included = data.get('included_entities', [])
    ec = data.get('entity_config', {})

    if not bridge_id:
        return jsonify({'error': 'bridge_id required'}), 400

    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
    except Exception as e:
        return jsonify({'error': f'Read yaml failed: {e}'}), 500

    try:
        bridges = yaml_ops.apply_changes(bridges, bridge_id, included, ec)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

    try:
        bak = yaml_ops.write_yaml(YAML_PATH, bridges)
    except Exception as e:
        LOG.exception("Write yaml failed")
        return jsonify({'error': f'Write failed: {e}'}), 500

    # 触发 reload 6 个 bridge
    reload_result = None
    if SUPERVISOR_TOKEN:
        try:
            entries = ha_get('/config/config_entries/entry')
            hk_entries = [e for e in entries if e.get('domain') == 'homekit' and e.get('source') == 'import']
            results = []
            for e in hk_entries:
                eid = e['entry_id']
                try:
                    ha_post('/services/homeassistant/reload_config_entry', {'entry_id': eid})
                    results.append({'entry_id': eid, 'title': e.get('title'), 'ok': True})
                except Exception as ex:
                    results.append({'entry_id': eid, 'title': e.get('title'), 'ok': False, 'error': str(ex)})
            reload_result = results
        except Exception as e:
            LOG.warning(f"Reload bridge entries failed: {e}")
            reload_result = {'error': str(e)}

    return jsonify({
        'ok': True,
        'backup': bak,
        'reload': reload_result,
        'bridge': {'port': bridge_id, 'count': len(included)},
    })


@app.route('/api/reload', methods=['POST'])
def reload_all():
    """手动 reload 6 个 bridge(不修改 yaml)"""
    if not SUPERVISOR_TOKEN:
        return jsonify({'error': 'No SUPERVISOR_TOKEN'}), 503
    try:
        entries = ha_get('/config/config_entries/entry')
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    hk = [e for e in entries if e.get('domain') == 'homekit' and e.get('source') == 'import']
    results = []
    for e in hk:
        try:
            ha_post('/services/homeassistant/reload_config_entry', {'entry_id': e['entry_id']})
            results.append({'title': e.get('title'), 'ok': True})
        except Exception as ex:
            results.append({'title': e.get('title'), 'ok': False, 'error': str(ex)})
    return jsonify({'results': results, 'count': len(results)})


@app.route('/api/preview', methods=['POST'])
def preview():
    """生成 yaml diff 预览(不改文件)"""
    data = request.get_json(force=True)
    bridge_id = data.get('bridge_id')
    included = data.get('included_entities', [])
    ec = data.get('entity_config', {})

    if not bridge_id:
        return jsonify({'error': 'bridge_id required'}), 400

    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
    except Exception as e:
        return jsonify({'error': f'Read failed: {e}'}), 500

    try:
        new_bridges = yaml_ops.apply_changes(bridges, bridge_id, included, ec)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

    # 找原 bridge 和新 bridge
    orig = next((b for b in bridges if str(b.get('port')) == str(bridge_id)), None)
    new = next((b for b in new_bridges if str(b.get('port')) == str(bridge_id)), None)
    if not orig or not new:
        return jsonify({'error': 'bridge not found'}), 404

    orig_inc = set((orig.get('filter', {}) or {}).get('include_entities', []) or [])
    new_inc = set(included)
    added = sorted(new_inc - orig_inc)
    removed = sorted(orig_inc - new_inc)

    orig_ec = orig.get('entity_config', {}) or {}
    new_ec_dict = {k: (v.get('name', '') if isinstance(v, dict) else '') for k, v in ec.items() if v}
    name_changes = []
    for ent, new_name in new_ec_dict.items():
        old_name = (orig_ec.get(ent, {}) or {}).get('name', '') if isinstance(orig_ec.get(ent), dict) else ''
        if old_name != new_name:
            name_changes.append({'entity_id': ent, 'old': old_name, 'new': new_name})

    return jsonify({
        'added': added,
        'removed': removed,
        'name_changes': name_changes,
        'count_old': len(orig_inc),
        'count_new': len(new_inc),
    })


@app.route('/api/backups')
def list_backups():
    """列出备份文件"""
    backups = yaml_ops.list_backups(YAML_PATH)
    return jsonify({'backups': backups, 'count': len(backups)})


@app.route('/api/restore', methods=['POST'])
def restore():
    """从 .bak 恢复"""
    data = request.get_json(force=True)
    bak = data.get('backup_path')
    if not bak:
        return jsonify({'error': 'backup_path required'}), 400
    try:
        yaml_ops.restore_backup(bak, YAML_PATH)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    # 尝试 reload(没 token 时会返回 error,但 yaml 已成功恢复)
    try:
        resp = reload_all()
        reload_result = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    except Exception as e:
        reload_result = {'error': str(e)}
    return jsonify({'ok': True, 'reload': reload_result})


# ============== 启动 ==============
if __name__ == '__main__':
    LOG.info(f"HomeKit Bridge 配置器 starting, port={APP_PORT}, yaml={YAML_PATH}, has_token={bool(SUPERVISOR_TOKEN)}")
    # disable Flask reloader (容器中)
    app.run(host='0.0.0.0', port=APP_PORT, debug=False, use_reloader=False)
