"""
yaml 读写核心: 维护 homekit_bridges.yaml 的结构与顺序。
"""
import os
import copy
import shutil
import datetime
import logging
import yaml
from collections import OrderedDict

LOG = logging.getLogger(__name__)

# 字段顺序(写入时按这个顺序)
BRIDGE_FIELD_ORDER = ['name', 'port', 'filter', 'entity_config', 'mode', 'advertise_ip', 'ip_address']
FILTER_FIELD_ORDER = ['include_entities', 'include_domains', 'include_entity_globs', 'exclude_entities', 'exclude_domains', 'exclude_entity_globs']


class OrderedDumper(yaml.SafeDumper):
    """保序 Dumper"""
    pass


def _dict_representer(dumper, data):
    return dumper.represent_mapping(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        data.items()
    )


OrderedDumper.add_representer(dict, _dict_representer)
OrderedDumper.add_representer(OrderedDict, _dict_representer)


def read_yaml(path):
    """读 yaml,返回 list(6 个 bridge dict)"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"yaml not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError(f"yaml root must be list, got {type(data).__name__}")
    return data


def write_yaml(path, bridges):
    """写 yaml,字段按顺序,中文字符串加引号保持可读"""
    # 转换为 OrderedDict 保序
    ordered = []
    for b in bridges:
        ob = OrderedDict()
        for k in BRIDGE_FIELD_ORDER:
            if k in b and b[k] is not None:
                ob[k] = b[k]
        # 其他未列出的字段
        for k, v in b.items():
            if k not in ob:
                ob[k] = v
        # filter 内部也排序
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

    # 备份
    backup_path = backup(path)

    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(
            ordered,
            f,
            Dumper=OrderedDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=4096,           # 不自动折行
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


def find_bridge(bridges, identifier):
    """根据 entry_id 找 bridge(title 含端口号,如 51801)"""
    for b in bridges:
        title = b.get('name', '') + ':' + str(b.get('port', ''))
        if str(identifier) in title or title == str(identifier):
            return b
    # fallback: 第二个参数
    for i, b in enumerate(bridges):
        if str(i) == str(identifier):
            return b
    return None


def apply_changes(bridges, bridge_id, included_entities, entity_config):
    """
    修改指定 bridge:
      - included_entities: 该 bridge 当前的 entity_id 列表(已含增减)
      - entity_config: {entity_id: {name: "..."}, ...}
    返回修改后的 bridges(原 list 副本)
    """
    bridges = [copy.deepcopy(b) for b in bridges]  # 深拷贝,避免污染原数据(尤其 preview 调用时)
    target = None
    target_idx = None
    for i, b in enumerate(bridges):
        if str(b.get('port', '')) == str(bridge_id) or str(bridge_id) in (b.get('name', '') + ':' + str(b.get('port', ''))):
            target = b
            target_idx = i
            break
    if target is None:
        raise ValueError(f"Bridge {bridge_id} not found")

    # filter.include_entities
    target.setdefault('filter', {})
    target['filter']['include_entities'] = list(included_entities)

    # entity_config(只保留 included 的)
    new_ec = OrderedDict()
    for ent in included_entities:
        if ent in entity_config and entity_config[ent].get('name'):
            new_ec[ent] = {'name': entity_config[ent]['name']}
        else:
            # 自动派生一个 friendly_name
            new_ec[ent] = {'name': derive_name(ent)}
    # 按 entity_id 排序
    target['entity_config'] = OrderedDict(sorted(new_ec.items(), key=lambda x: x[0]))

    bridges[target_idx] = target
    return bridges


def derive_name(entity_id):
    """简单派生:把 device_id 部分转中文(无法智能命名,只去掉 device_id)"""
    parts = entity_id.split('.', 1)
    if len(parts) < 2:
        return entity_id
    domain, rest = parts
    # 去掉 device_id 前缀
    suffix = rest.split('_', 1)
    if len(suffix) < 2:
        return entity_id
    return suffix[1].replace('_', ' ').strip()


def list_backups(yaml_path, limit=20):
    """列出所有备份文件,按 mtime 倒序"""
    import glob
    pattern = yaml_path + '.bak.*'
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return [{'path': f, 'mtime': os.path.getmtime(f), 'name': os.path.basename(f)} for f in files[:limit]]


def restore_backup(backup_path, target_path):
    """从备份恢复"""
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    shutil.copy2(backup_path, target_path)
    return True
