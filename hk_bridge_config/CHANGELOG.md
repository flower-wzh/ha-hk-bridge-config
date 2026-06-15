# Changelog

## 2.0.2 (2026-06-15)
- **修复**:给 Flask 加 `ProxyFix(x_prefix=1)` 中间件,ingress 模式下 `url_for` 才能正确生成 `/api/hassio_ingress/<token>/static/...` 前缀
- **修复**:把 `request.script_name` 暴露为 `window.INGRESS_BASE`,`app.js` 里的 `fetch('/api/...')` 改为带 ingress 前缀(单点在 `api()` 函数内处理)

## 2.0.1 (2026-06-15)
- **修复**:外网 ingress 反代下 `/static/app.js` `/static/style.css` 写死路径导致 JS/CSS 404 → 改为 `{{ url_for('static', filename='...') }}` 让 Flask 生成正确路径

## 2.0.0 (2026-06-15)
- **重写 UI**:现代暗色风格,圆角/阴影/微动画/响应式
- **设备分组树**:左侧按 area → device 二级树,带勾选状态指示
- **实体卡片网格**:6 个分类桶各自独立卡片,显示 friendly_name + entity_id + domain + state
- **自定义分类**:分类管理抽屉,拖拽排序、增删改、规则配置(domain / 名字包含 / entity_id 包含)
- **手动 + 规则双匹配**:实体先按手动规则,后按自动规则(按分类顺序)
- **未分配桶**:自动把不匹配任何分类的实体归到这里,可视化看到漏网之鱼
- **全量保存**:`/api/save_all` 一次写完 6 个 bridge yaml + 分类配置 + 触发 reload
- **保留兼容**:`/api/bridges` `/api/save` `/api/preview` `/api/auto_assign` 等老接口仍可用
- **分组数据源**:HA area/device/entity registry(失败则降级到 entity_id 启发式)
- **自动跳过**:旧 `midea_` 前缀实体(参考 reference_ha_integrations)

## 1.0.0 (2026-06-14)
- 首次发布
- 可视化调整 6 个 HomeKit bridge 的 include_entities 和 entity_config
- 按 domain / 搜索过滤 entity
- 中文人名编辑
- 一键保存 + 备份 + reload 6 个 bridge entry
- 预览 diff
- 撤销最近保存(从 .bak 恢复)
