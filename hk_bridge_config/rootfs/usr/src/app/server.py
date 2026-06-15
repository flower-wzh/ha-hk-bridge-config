"""
HomeKit Bridge 配置器 - Flask 后端 (v2)
新增:
  - /api/devices: 返回 area → device → entities 树(含 friendly_name / state / in_config)
  - /api/categories [GET/POST]: 读/写自定义 bridge 分类
  - /api/auto_assign: 按分类规则给所有 entity 自动归类
  - /api/save_all: 全量保存(分类 + 分配 + 名称)
  - /api/init_status: 判断当前是首次还是修改模式
兼容: /api/bridges /api/save /api/reload /api/preview /api/backups /api/restore
"""
import os
import re
import json
import logging
import requests
import yaml as pyyaml
from flask import Flask, request, jsonify, render_template
from collections import OrderedDict, defaultdict

import yaml_ops


class IngressPrefixFix:
    """HA ingress 在请求头里设 X-Ingress-Path(老 HA 是 X-Forwarded-Prefix),
    把这个值映射到 WSGI 的 SCRIPT_NAME,这样 url_for 拼前缀时才能拿到。

    HA 转发时有时会剥前缀有时不剥 — 我们从 PATH_INFO 里把前缀也剥掉,
    让 Flask 路由只看到真实的 /api/... 路径,而不是 /api/hassio_ingress/<token>/api/...。"""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # 找 ingress 前缀 — HA 实际设什么头不确定,所以所有可能的都试一遍
        prefix = (
            environ.get('HTTP_X_INGRESS_PATH', '')
            or environ.get('HTTP_X_FORWARDED_PREFIX', '')
            or environ.get('HTTP_X_FORWARDED_PATH', '')
            or environ.get('HTTP_X_ORIGINAL_URI', '')
        )
        # 一次性把所有 ingress 候选头和 SCRIPT_NAME/PATH_INFO 打到日志,辅助诊断
        LOG.warning(
            "[ingress] PATH_INFO=%r SCRIPT_NAME_before=%r prefix=%r "
            "X-Ingress-Path=%r X-Forwarded-Prefix=%r X-Original-URI=%r",
            environ.get('PATH_INFO'),
            environ.get('SCRIPT_NAME'),
            prefix,
            environ.get('HTTP_X_INGRESS_PATH', ''),
            environ.get('HTTP_X_FORWARDED_PREFIX', ''),
            environ.get('HTTP_X_ORIGINAL_URI', ''),
        )
        if prefix:
            environ['SCRIPT_NAME'] = prefix
            # 如果 PATH_INFO 还带着前缀,剥掉;HA 已经剥过就不动
            path_info = environ.get('PATH_INFO', '')
            if path_info.startswith(prefix):
                environ['PATH_INFO'] = path_info[len(prefix):] or '/'
        return self.app(environ, start_response)

APP_PORT = int(os.environ.get('APP_PORT', 8099))
YAML_PATH = os.environ.get('YAML_PATH', '/config/homekit_bridges.yaml')
CATEGORIES_PATH = os.environ.get('CATEGORIES_PATH', '/config/hk_bridge_categories.yaml')
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
HA_API = 'http://supervisor/core/api'

# 静态资源 cache busting — 每次发版与 config.yaml 同步 bump,模板用作 ?v=
# 浏览器看到 URL 变就会重新下载,绕过 HA ingress / 浏览器自身的旧文件缓存
APP_VERSION = '2.0.10'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
LOG = logging.getLogger('hk_bridge_config')

app = Flask(__name__)

# HA ingress 反代在前面 — 让 Flask 拿到 ingress 前缀,url_for 才能拼对
# /api/hassio_ingress/<token>/static/...。IngressPrefixFix 读 X-Ingress-Path
# (新 HA) 或 X-Forwarded-Prefix (老 HA),写到 SCRIPT_NAME。
app.wsgi_app = IngressPrefixFix(app.wsgi_app)


# ============== HA API 工具 ==============

def ha_headers():
    return {
        'Authorization': f'Bearer {SUPERVISOR_TOKEN}',
        'Content-Type': 'application/json',
    }


def ha_get(path, **params):
    url = HA_API + path
    LOG.info(f"GET {url} params={params}")
    r = requests.get(url, headers=ha_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def ha_post(path, json_body):
    url = HA_API + path
    LOG.info(f"POST {url}")
    r = requests.post(url, headers=ha_headers(), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else []


# ============== 数据聚合 ==============

# 跳过的 entity 模式(可优化)
SKIP_ENTITY_PREFIXES = ('midea_',)  # 旧 midea_smart_home 残留
SKIP_DOMAINS = set()  # 不过滤 domain,前端 filter


def _should_skip(entity_id):
    return any(entity_id.startswith(p + '.') for p in SKIP_ENTITY_PREFIXES)


def _area_lookup():
    """从 HA area registry 取 area_id -> name。失败返回 {}"""
    try:
        areas = ha_get('/config/area_registry/list')
        return {a['area_id']: a['name'] for a in areas if a.get('area_id')}
    except Exception as e:
        LOG.warning(f"area_registry 403/失败: {e}")
        return {}


def _entity_area_lookup():
    """entity_id -> area_id。失败返回 {}"""
    try:
        ents = ha_get('/config/entity_registry/list')
        return {e['entity_id']: e.get('area_id') for e in ents if e.get('entity_id')}
    except Exception as e:
        LOG.warning(f"entity_registry 失败: {e}")
        return {}


def _device_lookup():
    """device_id -> {name, area_id, manufacturer, model}"""
    try:
        devs = ha_get('/config/device_registry/list')
        return {
            d['id']: {
                'name': d.get('name') or '未命名设备',
                'area_id': d.get('area_id'),
                'manufacturer': d.get('manufacturer'),
                'model': d.get('model'),
            }
            for d in devs if d.get('id')
        }
    except Exception as e:
        LOG.warning(f"device_registry 失败: {e}")
        return {}


def _device_id_for_entity(entity_id, ent_to_device):
    """entity_id -> device_id"""
    return ent_to_device.get(entity_id)


def _entity_device_lookup():
    try:
        ents = ha_get('/config/entity_registry/list')
        return {e['entity_id']: e.get('device_id') for e in ents if e.get('entity_id')}
    except Exception as e:
        LOG.warning(f"entity_registry 失败: {e}")
        return {}


def _device_id_prefix(entity_id):
    """从 entity_id 抽 device 段: sensor.zimi_cn_xxx_temperature -> zimi_cn_xxx"""
    parts = entity_id.split('.', 1)
    if len(parts) < 2:
        return entity_id
    rest = parts[1]
    # 找连续 4 段以上(数字/字母)作为 device 段
    toks = rest.split('_')
    if len(toks) >= 4 and any(re.match(r'^[0-9a-f]{6,}$', t) for t in toks):
        return '_'.join(toks[:3])
    # 否则用前 2 段
    return '_'.join(toks[:2])


def _friendly_name_device_prefix(friendly_name):
    """从 friendly_name '美的中央空调 当前温度' 抽 '美的中央空调'"""
    if not friendly_name:
        return ''
    # 中文名通常前 4-8 字是设备名
    return friendly_name.split(' ')[0] if ' ' in friendly_name else friendly_name[:6]


# ============== 路由 ==============

@app.route('/')
def index():
    # Flask 3.0 / Werkzeug 3.0 移除了 request.script_name 属性,要用 environ 拿
    # 这是 HA ingress 在 X-Ingress-Path 头里设的值(经中间件写到 SCRIPT_NAME)
    ingress_prefix = request.environ.get('SCRIPT_NAME', '')
    return render_template('index.html', ingress_prefix=ingress_prefix, app_version=APP_VERSION)


@app.route('/api/health')
def health():
    return jsonify({
        'ok': True,
        'yaml_path': YAML_PATH,
        'categories_path': CATEGORIES_PATH,
        'has_token': bool(SUPERVISOR_TOKEN),
    })


@app.route('/api/init_status')
def init_status():
    """判断首次还是修改模式"""
    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
        have_yaml = True
        n = len(bridges)
        existing_entities = set()
        for b in bridges:
            for e in (b.get('filter', {}) or {}).get('include_entities', []) or []:
                existing_entities.add(e)
    except Exception:
        have_yaml = False
        n = 0
        existing_entities = set()

    return jsonify({
        'have_yaml': have_yaml,
        'bridge_count': n,
        'existing_entity_count': len(existing_entities),
        'is_first_run': not have_yaml or n == 0,
    })


@app.route('/api/devices')
def api_devices():
    """
    返回 area -> device -> entities 树:
    [
      {
        'area_id': 'xxx', 'area_name': '客厅',
        'devices': [
          { 'key': '...', 'name': '美的中央空调',
            'manufacturer': '...', 'model': '...',
            'entities': [{'entity_id', 'domain', 'friendly_name', 'state', 'in_config'}]
          }
        ]
      },
      { 'area_id': None, 'area_name': '未分组', 'devices': [...] }
    ]
    """
    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
        existing = set()
        for b in bridges:
            for e in (b.get('filter', {}) or {}).get('include_entities', []) or []:
                existing.add(e)
    except Exception:
        existing = set()

    states = ha_get('/states')
    areas = _area_lookup()
    ent_to_area = _entity_area_lookup()
    devs = _device_lookup()
    ent_to_dev = _entity_device_lookup()

    # 按 (area_id, device_key) 聚合
    bucket = defaultdict(lambda: defaultdict(list))
    for s in states:
        eid = s['entity_id']
        if _should_skip(eid):
            continue
        domain = eid.split('.')[0]
        fname = (s.get('attributes') or {}).get('friendly_name', eid)

        # 优先级: device_registry > entity_registry > 启发式
        dev_id = ent_to_dev.get(eid)
        if dev_id and dev_id in devs:
            dev_name = devs[dev_id]['name']
            area_id = devs[dev_id].get('area_id') or ent_to_area.get(eid)
        else:
            dev_name = _friendly_name_device_prefix(fname) or _device_id_prefix(eid)
            area_id = ent_to_area.get(eid)
            dev_id = f'heuristic:{dev_name}'

        bucket[area_id][dev_id].append({
            'entity_id': eid,
            'domain': domain,
            'friendly_name': fname,
            'state': s.get('state'),
            'in_config': eid in existing,
            'unit': (s.get('attributes') or {}).get('unit_of_measurement'),
            'device_class': (s.get('attributes') or {}).get('device_class'),
        })

    out = []
    for area_id, devs_map in bucket.items():
        area_name = areas.get(area_id, '未分组') if area_id else '未分组'
        dev_list = []
        for dev_id, ents in devs_map.items():
            if dev_id in devs:
                d = devs[dev_id]
                dev_list.append({
                    'key': dev_id,
                    'name': d['name'],
                    'manufacturer': d.get('manufacturer'),
                    'model': d.get('model'),
                    'entities': sorted(ents, key=lambda e: e['entity_id']),
                })
            else:
                # 启发式设备,用第一个 entity 的 prefix 命名
                first = ents[0]
                dev_name = _friendly_name_device_prefix(first['friendly_name']) or _device_id_prefix(first['entity_id'])
                dev_list.append({
                    'key': dev_id,
                    'name': dev_name,
                    'manufacturer': None,
                    'model': None,
                    'entities': sorted(ents, key=lambda e: e['entity_id']),
                })
        # 设备按名字排序
        dev_list.sort(key=lambda d: d['name'])
        out.append({
            'area_id': area_id,
            'area_name': area_name,
            'devices': dev_list,
            'entity_count': sum(len(d['entities']) for d in dev_list),
        })
    # 区域排序: 已命名在前
    out.sort(key=lambda a: (a['area_name'] == '未分组', a['area_name']))
    return jsonify({'areas': out})


@app.route('/api/categories', methods=['GET'])
def get_categories():
    cats = yaml_ops.read_categories(CATEGORIES_PATH)
    return jsonify({'categories': cats, 'is_default': not os.path.exists(CATEGORIES_PATH)})


@app.route('/api/categories', methods=['POST'])
def save_categories():
    data = request.get_json(force=True)
    cats = data.get('categories', [])
    if not isinstance(cats, list):
        return jsonify({'error': 'categories must be list'}), 400
    try:
        bak = yaml_ops.write_categories(CATEGORIES_PATH, cats)
    except Exception as e:
        LOG.exception("write categories failed")
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'backup': bak, 'count': len(cats)})


@app.route('/api/auto_assign', methods=['POST'])
def api_auto_assign():
    """
    body: {}  (从 /api/devices 拉数据后,前端直接对 entity 调匹配)
    返回: {assignment: {category_id: [entity_ids], '_unassigned': [...]}}
    """
    data = request.get_json(force=True) or {}
    cats = yaml_ops.read_categories(CATEGORIES_PATH)
    # 前端可以传 entities(避免再调 /api/devices),否则这里再拉
    if 'entities' in data:
        entities = data['entities']
    else:
        states = ha_get('/states')
        entities = [{
            'entity_id': s['entity_id'],
            'domain': s['entity_id'].split('.')[0],
            'friendly_name': (s.get('attributes') or {}).get('friendly_name', s['entity_id']),
        } for s in states if not _should_skip(s['entity_id'])]
    assignment = yaml_ops.auto_assign(entities, cats)
    return jsonify({'assignment': assignment})


@app.route('/api/save_all', methods=['POST'])
def save_all():
    """
    body:
      {
        "categories": [...],          # 分类配置(更新)
        "assignment": {cat_id: [ent_id], '_unassigned': [...]},  # 分配结果
        "name_overrides": {ent_id: 'name'},  # 自定义名
        "reload_bridges": true        # 是否触发 reload
      }
    """
    data = request.get_json(force=True)
    cats = data.get('categories')
    assignment = data.get('assignment') or {}
    name_overrides = data.get('name_overrides') or {}
    do_reload = data.get('reload_bridges', True)

    if cats:
        try:
            yaml_ops.write_categories(CATEGORIES_PATH, cats)
        except Exception as e:
            return jsonify({'error': f'write categories failed: {e}'}), 500
    else:
        cats = yaml_ops.read_categories(CATEGORIES_PATH)

    try:
        bridges_existing = yaml_ops.read_yaml(YAML_PATH)
    except FileNotFoundError:
        bridges_existing = []
    except Exception as e:
        return jsonify({'error': f'read bridges yaml failed: {e}'}), 500

    # 生成新 bridges
    new_bridges = yaml_ops.generate_bridges_from_categories(
        bridges_existing, cats, assignment, name_overrides
    )

    # 写入 yaml
    try:
        bak_bridges = yaml_ops.write_yaml(YAML_PATH, new_bridges)
    except Exception as e:
        LOG.exception("write bridges yaml failed")
        return jsonify({'error': f'write yaml failed: {e}'}), 500

    # 触发 reload
    reload_result = None
    if do_reload and SUPERVISOR_TOKEN:
        try:
            entries = ha_get('/config/config_entries/entry')
            hk = [e for e in entries if e.get('domain') == 'homekit' and e.get('source') == 'import']
            results = []
            for e in hk:
                try:
                    ha_post('/services/homeassistant/reload_config_entry', {'entry_id': e['entry_id']})
                    results.append({'title': e.get('title'), 'ok': True})
                except Exception as ex:
                    results.append({'title': e.get('title'), 'ok': False, 'error': str(ex)})
            reload_result = results
        except Exception as e:
            LOG.warning(f"reload failed: {e}")
            reload_result = {'error': str(e)}

    return jsonify({
        'ok': True,
        'backup': bak_bridges,
        'reload': reload_result,
        'bridges': [
            {
                'port': b['port'],
                'name': b['name'],
                'count': len((b.get('filter', {}) or {}).get('include_entities', []) or []),
            } for b in new_bridges
        ],
    })


# ============== 兼容旧 API ==============

@app.route('/api/bridges')
def get_bridges():
    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    entity_map = {}
    if SUPERVISOR_TOKEN:
        try:
            for s in ha_get('/states'):
                entity_map[s['entity_id']] = {
                    'friendly_name': s['attributes'].get('friendly_name', s['entity_id']),
                    'state': s.get('state'),
                    'domain': s['entity_id'].split('.')[0],
                }
        except Exception as e:
            LOG.warning(f"states failed: {e}")

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
    if not SUPERVISOR_TOKEN:
        return jsonify({'entities': [], 'error': 'No SUPERVISOR_TOKEN'}), 503
    try:
        states = ha_get('/states')
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    out = []
    for s in states:
        ent = s['entity_id']
        if _should_skip(ent):
            continue
        out.append({
            'entity_id': ent,
            'domain': ent.split('.')[0],
            'friendly_name': s['attributes'].get('friendly_name', ent),
            'state': s.get('state'),
        })
    return jsonify({'entities': out, 'count': len(out)})


@app.route('/api/save', methods=['POST'])
def save():
    """兼容旧 API: 单 bridge 修改"""
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

    return jsonify({'ok': True, 'backup': bak, 'bridge': {'port': bridge_id, 'count': len(included)}})


@app.route('/api/reload', methods=['POST'])
def reload_all():
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
    data = request.get_json(force=True)
    bridge_id = data.get('bridge_id')
    included = data.get('included_entities', [])
    ec = data.get('entity_config', {})

    if not bridge_id:
        return jsonify({'error': 'bridge_id required'}), 400

    try:
        bridges = yaml_ops.read_yaml(YAML_PATH)
        new_bridges = yaml_ops.apply_changes(bridges, bridge_id, included, ec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    orig = next((b for b in bridges if str(b.get('port')) == str(bridge_id)), None)
    new = next((b for b in new_bridges if str(b.get('port')) == str(bridge_id)), None)
    if not orig or not new:
        return jsonify({'error': 'bridge not found'}), 404

    orig_inc = set((orig.get('filter', {}) or {}).get('include_entities', []) or [])
    new_inc = set(included)
    added = sorted(new_inc - orig_inc)
    removed = sorted(orig_inc - new_inc)
    return jsonify({
        'added': added, 'removed': removed,
        'count_old': len(orig_inc), 'count_new': len(new_inc),
    })


@app.route('/api/backups')
def list_backups_route():
    return jsonify({'backups': yaml_ops.list_backups(YAML_PATH), 'count': len(yaml_ops.list_backups(YAML_PATH))})


@app.route('/api/restore', methods=['POST'])
def restore():
    data = request.get_json(force=True)
    bak = data.get('backup_path')
    if not bak:
        return jsonify({'error': 'backup_path required'}), 400
    try:
        yaml_ops.restore_backup(bak, YAML_PATH)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})


# ============== 启动 ==============

if __name__ == '__main__':
    LOG.info(f"HomeKit Bridge 配置器 v2 starting, port={APP_PORT}, yaml={YAML_PATH}")
    app.run(host='0.0.0.0', port=APP_PORT, debug=False, use_reloader=False)
