"""
yaml 读写核心:
  - homekit_bridges.yaml: 6 个 bridge 配置(list 形式)
  - hk_bridge_categories.yaml: 用户自定义 bridge 分类及匹配规则
"""
import os
import copy
import shutil
import datetime
import logging
import re
import yaml
from collections import OrderedDict

LOG = logging.getLogger(__name__)

# 字段顺序(写入时按这个顺序)
BRIDGE_FIELD_ORDER = ['name', 'port', 'filter', 'entity_config', 'mode', 'advertise_ip', 'ip_address']
FILTER_FIELD_ORDER = ['include_entities', 'include_domains', 'include_entity_globs',
                      'exclude_entities', 'exclude_domains', 'exclude_entity_globs']

# 默认 6 个分类(端口固定 51801-51806)
DEFAULT_CATEGORIES = [
    {
        'id': 'hvac', 'name': '暖通空调', 'port': 51801, 'icon': '❄️',
        'rules': [
            {'type': 'domain', 'values': ['climate']},
            {'type': 'domain', 'values': ['select'], 'name_contains': ['swing', '摆风']},
        ],
    },
    {
        'id': 'kitchen', 'name': '厨房家电', 'port': 51802, 'icon': '🍳',
        'rules': [
            {'type': 'name_contains', 'values': ['冰箱', '洗碗机', '净水', '管线机', '电饭煲']},
        ],
    },
    {
        'id': 'laundry', 'name': '衣物护理', 'port': 51803, 'icon': '👕',
        'rules': [
            {'type': 'name_contains', 'values': ['洗衣机', '干衣机', '晾衣机']},
        ],
    },
    {
        'id': 'lighting', 'name': '照明与窗帘', 'port': 51804, 'icon': '💡',
        'rules': [
            {'type': 'domain', 'values': ['light', 'cover', 'switch']},
        ],
    },
    {
        'id': 'security', 'name': '安防与传感器', 'port': 51805, 'icon': '🛡️',
        'rules': [
            {'type': 'domain', 'values': ['binary_sensor', 'sensor']},
        ],
    },
    {
        'id': 'media', 'name': '清洁与影音', 'port': 51806, 'icon': '🎬',
        'rules': [
            {'type': 'domain', 'values': ['media_player', 'vacuum', 'remote']},
        ],
    },
]


class OrderedDumper(yaml.SafeDumper):
    pass


def _dict_representer(dumper, data):
    return dumper.represent_mapping(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        data.items()
    )


OrderedDumper.add_representer(dict, _dict_representer)
OrderedDumper.add_representer(OrderedDict, _dict_representer)


# ============== homekit_bridges.yaml ==============

def read_yaml(path):
    """读 6 bridge yaml,返回 list"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"yaml not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError(f"yaml root must be list, got {type(data).__name__}")
    return data


def write_yaml(path, bridges):
    """写 6 bridge yaml,保序"""
    ordered = []
    for b in bridges:
        ob = OrderedDict()
        for k in BRIDGE_FIELD_ORDER:
            if k in b and b[k] is not None:
                ob[k] = b[k]
        for k, v in b.items():
            if k not in ob:
                ob[k] = v
        if 'filter' in ob and isinstance(ob['filter'], dict):
            f_ord = OrderedDict()
            for k in FILTER_FIELD_ORDER:
                if k in ob['filter']:
                    f_ord[k] = ob['filter'][k]
            for k, v in ob['filter'].items():
                if k not in f_ord:
                    f_ord[k] = v
            ob['filter'] = f_ord
        ordered.append(ob)

    backup_path = backup(path)

    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(
            ordered, f,
            Dumper=OrderedDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=4096,
            indent=2,
        )
    return backup_path


def backup(path):
    """备份原 yaml 到 .bak.YYYYMMDD_HHMMSS"""
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak.{ts}"
    shutil.copy2(path, bak)
    LOG.info(f"Backup: {bak}")
    return bak


def list_backups(yaml_path, limit=20):
    import glob
    pattern = yaml_path + '.bak.*'
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return [{'path': f, 'mtime': os.path.getmtime(f), 'name': os.path.basename(f)} for f in files[:limit]]


def restore_backup(backup_path, target_path):
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    shutil.copy2(backup_path, target_path)
    return True


# ============== hk_bridge_categories.yaml ==============

def read_categories(path):
    """读分类配置,不存在则返回默认 6 分类"""
    if not os.path.exists(path):
        return list(DEFAULT_CATEGORIES)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            LOG.warning("categories file not list, fallback to defaults")
            return list(DEFAULT_CATEGORIES)
        return data
    except Exception as e:
        LOG.warning(f"read categories failed: {e}, fallback to defaults")
        return list(DEFAULT_CATEGORIES)


def write_categories(path, categories):
    """写分类配置"""
    backup_path = None
    if os.path.exists(path):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{path}.bak.{ts}"
        shutil.copy2(path, backup_path)
        LOG.info(f"Backup categories: {backup_path}")

    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(
            categories, f,
            Dumper=OrderedDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=4096,
            indent=2,
        )
    return backup_path


# ============== 分类匹配 ==============

def match_category(entity, rule):
    """
    单条规则匹配:
      rule = {'type': 'domain' | 'name_contains' | 'entity_contains' | 'always',
              'values': [...],
              'name_contains': [...] (可选,domain 类规则可附加)}
    """
    rt = rule.get('type')
    if rt == 'always':
        return True
    if rt == 'domain':
        if entity.get('domain') in (rule.get('values') or []):
            # 可选: 还要满足 name_contains
            nc = rule.get('name_contains') or []
            if not nc:
                return True
            name = entity.get('friendly_name') or entity.get('entity_id', '')
            return any(k in name for k in nc)
    if rt == 'name_contains':
        name = entity.get('friendly_name') or entity.get('entity_id', '')
        return any(k in name for k in (rule.get('values') or []))
    if rt == 'entity_contains':
        return any(k in entity.get('entity_id', '') for k in (rule.get('values') or []))
    if rt == 'manual':
        return entity.get('entity_id') in (rule.get('entities') or [])
    return False


def match_category_all(entity, category):
    """一个分类的所有规则之间是 OR(任一匹配即归此类)"""
    rules = category.get('rules') or []
    if not rules:
        return False
    return any(match_category(entity, r) for r in rules)


def auto_assign(entities, categories):
    """
    按分类顺序(用户拖拽顺序)匹配,匹配上的归到对应分类。
    返回 {category_id: [entity_id, ...]}
    未匹配的归到 '_unassigned'。
    """
    result = {c['id']: [] for c in categories}
    result['_unassigned'] = []
    for e in entities:
        eid = e['entity_id']
        # 手动规则优先
        manual_match = None
        for c in categories:
            for r in c.get('rules', []):
                if r.get('type') == 'manual' and eid in (r.get('entities') or []):
                    manual_match = c['id']
                    break
            if manual_match:
                break
        if manual_match:
            result[manual_match].append(eid)
            continue

        # 自动规则: 按分类顺序,第一个匹配的胜出
        matched = None
        for c in categories:
            rules_no_manual = [r for r in c.get('rules', []) if r.get('type') != 'manual']
            if not rules_no_manual:
                continue
            if any(match_category(e, r) for r in rules_no_manual):
                matched = c['id']
                break
        if matched:
            result[matched].append(eid)
        else:
            result['_unassigned'].append(eid)
    return result


# ============== 全量生成 6 bridge yaml ==============

def generate_bridges_from_categories(bridges_existing, categories, assignment, name_overrides=None):
    """
    接收:
      bridges_existing: 当前 yaml 6 bridge(用于保留 port/name 字段)
      categories: 分类配置
      assignment: {category_id: [entity_id, ...], '_unassigned': [...]}
      name_overrides: {entity_id: '自定义名'}

    返回新的 bridges list(深拷贝, 不污染原数据)
    """
    name_overrides = name_overrides or {}
    new_bridges = []

    for cat in categories:
        if cat['id'] == '_unassigned':
            continue
        # 找现有同名/同 port bridge
        existing = None
        for b in bridges_existing:
            if str(b.get('port')) == str(cat.get('port')):
                existing = b
                break
        if existing is None:
            # fallback by name
            for b in bridges_existing:
                if b.get('name') == cat.get('name'):
                    existing = b
                    break

        bridge = copy.deepcopy(existing) if existing else OrderedDict()
        bridge['name'] = cat['name']
        bridge['port'] = cat['port']
        bridge.setdefault('mode', 'bridge')

        included = list(assignment.get(cat['id']) or [])
        bridge.setdefault('filter', {})
        bridge['filter']['include_entities'] = included

        # entity_config
        ec = OrderedDict()
        for ent in included:
            if ent in name_overrides and name_overrides[ent].strip():
                ec[ent] = {'name': name_overrides[ent].strip()}
            else:
                # 后端服务层注入 friendly_name 时不带;此处先填 entity_id 占位
                ec[ent] = {'name': ent}
        bridge['entity_config'] = ec
        new_bridges.append(bridge)

    return new_bridges


# ============== 旧的 apply_changes (兼容) ==============

def apply_changes(bridges, bridge_id, included_entities, entity_config):
    """兼容旧 API: 修改单个 bridge 的 include_entities + entity_config"""
    bridges = [copy.deepcopy(b) for b in bridges]
    target = None
    target_idx = None
    for i, b in enumerate(bridges):
        if str(b.get('port', '')) == str(bridge_id):
            target = b
            target_idx = i
            break
    if target is None:
        raise ValueError(f"Bridge {bridge_id} not found")

    target.setdefault('filter', {})
    target['filter']['include_entities'] = list(included_entities)

    new_ec = OrderedDict()
    for ent in included_entities:
        if ent in entity_config and entity_config[ent].get('name'):
            new_ec[ent] = {'name': entity_config[ent]['name']}
        else:
            new_ec[ent] = {'name': derive_name(ent)}
    target['entity_config'] = OrderedDict(sorted(new_ec.items(), key=lambda x: x[0]))
    bridges[target_idx] = target
    return bridges


def derive_name(entity_id):
    parts = entity_id.split('.', 1)
    if len(parts) < 2:
        return entity_id
    domain, rest = parts
    suffix = rest.split('_', 1)
    if len(suffix) < 2:
        return entity_id
    return suffix[1].replace('_', ' ').strip()


def find_bridge(bridges, identifier):
    for b in bridges:
        title = b.get('name', '') + ':' + str(b.get('port', ''))
        if str(identifier) in title or title == str(identifier):
            return b
    for i, b in enumerate(bridges):
        if str(i) == str(identifier):
            return b
    return None
