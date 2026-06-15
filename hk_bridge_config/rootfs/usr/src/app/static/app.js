/*
 * HomeKit Bridge 配置器 - v2 前端
 * 设备分组 + 自定义分类 + 实体卡片勾选
 */

const state = {
  areas: [],          // /api/devices 树
  categories: [],     // /api/categories 6 个分类
  assignment: {},     // {cat_id: Set<entity_id>, '_unassigned': Set}
  dirty: false,
  initStatus: null,
  collapsedAreas: new Set(),
  selectedDevice: null,  // 左侧树点击的设备(用于过滤)
  searchTerm: '',
  domainFilter: '',
  bucketFilter: '',
  treeSearchTerm: '',
};

// ============== 工具 ==============
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function toast(msg, type = 'info', duration = 3000) {
  const el = document.createElement('div');
  el.className = 'toast-item ' + type;
  el.textContent = msg;
  $('#toast').appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity .25s';
    setTimeout(() => el.remove(), 250);
  }, duration);
}

async function api(method, path, body) {
  // 用绝对 URL,service worker / iframe baseURI 改不了
  if (path.startsWith('/api/')) {
    path = (window.API_BASE || '') + path;
  }
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function domainIcon(domain) {
  const map = {
    light: '💡', switch: '🔌', climate: '❄️', cover: '🪟', lock: '🔒',
    sensor: '📊', binary_sensor: '🟢', fan: '🌀', media_player: '🎵',
    vacuum: '🤖', remote: '📡', scene: '🎬', script: '⚙️', input_boolean: '🔘',
    select: '🎚️', number: '🔢', timer: '⏱', weather: '🌤',
  };
  return map[domain] || '•';
}

function stateClass(state) {
  if (!state || state === 'unavailable' || state === 'unknown') return 'unavailable';
  if (state === 'on' || state === 'home' || state === 'open') return 'on';
  if (state === 'off' || state === 'closed' || state === 'not_home') return 'off';
  return '';
}

// ============== 初始化 ==============
window.addEventListener('DOMContentLoaded', async () => {
  bindUI();
  await loadHealth();
  await loadInitStatus();
  await Promise.all([loadDevices(), loadCategories()]);
  await autoAssign();
  render();
});

async function loadHealth() {
  try {
    const h = await api('GET', '/api/health');
    $('#stat-yaml').textContent = h.has_token ? '✓ ' + (h.yaml_path.split('/').pop()) : '⚠ yaml 路径异常';
    $('#stat-token').textContent = h.has_token ? '🔑 token OK' : '⚠ 无 token';
  } catch (e) {
    $('#stat-yaml').textContent = '✗ 后端不可达';
    $('#stat-token').textContent = '✗';
  }
}

async function loadInitStatus() {
  try {
    state.initStatus = await api('GET', '/api/init_status');
    if (state.initStatus.is_first_run) {
      toast('首次运行,请选择要加入 6 个 bridge 的实体', 'info', 4000);
    }
  } catch (e) { /* 忽略 */ }
}

async function loadDevices() {
  const data = await api('GET', '/api/devices');
  state.areas = data.areas;
}

async function loadCategories() {
  const data = await api('GET', '/api/categories');
  state.categories = data.categories;
}

async function autoAssign() {
  // 用 device tree 里的全部 entity 调后端 auto_assign
  const all = [];
  for (const a of state.areas) {
    for (const d of a.devices) {
      for (const e of d.entities) all.push(e);
    }
  }
  const data = await api('POST', '/api/auto_assign', { entities: all });
  state.assignment = {};
  for (const [k, v] of Object.entries(data.assignment)) {
    state.assignment[k] = new Set(v);
  }
  // 确保 _unassigned 存在
  if (!state.assignment._unassigned) state.assignment._unassigned = new Set();
}

// ============== 渲染 ==============
function render() {
  renderDomainFilter();
  renderBucketFilter();
  renderTree();
  renderBuckets();
  updateDirtyStatus();
  updateSelectionCount();
  updateTreeStats();
}

function updateTreeStats() {
  let totalEntities = 0, totalSelected = 0;
  for (const a of state.areas) {
    for (const d of a.devices) {
      totalEntities += d.entities.length;
      for (const e of d.entities) {
        if (findCatForEntity(e.entity_id) !== null) totalSelected++;
      }
    }
  }
  $('#tree-stats').textContent = `${totalSelected}/${totalEntities}`;
}

function findCatForEntity(eid) {
  for (const cat of state.categories) {
    if (state.assignment[cat.id]?.has(eid)) return cat.id;
  }
  if (state.assignment._unassigned?.has(eid)) return '_unassigned';
  return null;
}

function renderDomainFilter() {
  const domains = new Set();
  for (const a of state.areas) for (const d of a.devices) for (const e of d.entities) domains.add(e.domain);
  const sorted = [...domains].sort();
  const sel = $('#domain-filter');
  const prev = sel.value;
  sel.innerHTML = '<option value="">全部 domain</option>' + sorted.map(d => `<option value="${d}">${d}</option>`).join('');
  sel.value = prev;
}

function renderBucketFilter() {
  const sel = $('#bucket-filter');
  const prev = sel.value;
  sel.innerHTML = '<option value="">全部分类</option>' +
    '<option value="_unassigned">未分配</option>' +
    state.categories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
  sel.value = prev;
}

function renderTree() {
  const tree = $('#device-tree');
  tree.innerHTML = '';
  const term = state.treeSearchTerm.toLowerCase();
  for (const area of state.areas) {
    // 应用搜索过滤
    const matchedDevices = area.devices.filter(d => {
      if (!term) return true;
      if (d.name.toLowerCase().includes(term)) return true;
      return d.entities.some(e => e.entity_id.includes(term) || (e.friendly_name || '').toLowerCase().includes(term));
    });
    if (term && matchedDevices.length === 0) continue;

    const areaEl = document.createElement('div');
    areaEl.className = 'tree-area' + (state.collapsedAreas.has(area.area_id) ? ' collapsed' : '');

    const head = document.createElement('div');
    head.className = 'tree-area-head';
    head.innerHTML = `
      <span class="toggle">▼</span>
      <span>${escapeHtml(area.area_name)}</span>
      <span class="tree-area-count">${area.entity_count}</span>
    `;
    head.onclick = () => {
      if (state.collapsedAreas.has(area.area_id)) state.collapsedAreas.delete(area.area_id);
      else state.collapsedAreas.add(area.area_id);
      renderTree();
    };
    areaEl.appendChild(head);

    const devList = document.createElement('div');
    devList.className = 'tree-devices';
    for (const dev of matchedDevices) {
      const selectedCount = dev.entities.filter(e => findCatForEntity(e.entity_id) !== null).length;
      const allSelected = selectedCount === dev.entities.length;
      const devEl = document.createElement('div');
      devEl.className = 'tree-device' + (state.selectedDevice === dev.key ? ' active' : '');
      devEl.innerHTML = `
        <span class="tree-device-name" title="${escapeHtml(dev.name)}">${escapeHtml(dev.name)}</span>
        <span class="tree-device-count ${allSelected ? 'selected-count' : ''}">${selectedCount}/${dev.entities.length}</span>
      `;
      devEl.onclick = () => {
        state.selectedDevice = state.selectedDevice === dev.key ? null : dev.key;
        renderTree();
        renderBuckets();
      };
      devList.appendChild(devEl);
    }
    areaEl.appendChild(devList);
    tree.appendChild(areaEl);
  }
}

function entityMatchesFilters(e) {
  // domain 过滤
  if (state.domainFilter && e.domain !== state.domainFilter) return false;
  // 桶过滤
  if (state.bucketFilter) {
    const cat = findCatForEntity(e.entity_id);
    if (state.bucketFilter === '_unassigned') {
      if (cat !== '_unassigned' && cat !== null) return false;
    } else if (cat !== state.bucketFilter) return false;
  }
  // 搜索
  if (state.searchTerm) {
    const t = state.searchTerm.toLowerCase();
    if (!e.entity_id.toLowerCase().includes(t) &&
        !(e.friendly_name || '').toLowerCase().includes(t) &&
        !e.domain.toLowerCase().includes(t)) return false;
  }
  // 选中设备过滤
  if (state.selectedDevice) {
    if (state.selectedDevice.startsWith('heuristic:')) {
      // 启发式设备:按 device name 前缀匹配
      const prefix = state.selectedDevice.slice('heuristic:'.length).toLowerCase();
      const fn = (e.friendly_name || '').split(' ')[0].toLowerCase();
      if (!fn.startsWith(prefix.toLowerCase().split('_')[0])) return false;
    }
  }
  return true;
}

function renderBuckets() {
  const container = $('#buckets-container');
  container.innerHTML = '';
  // 准备所有 entity 的索引
  const allEntities = [];
  const entitiesById = new Map();
  for (const a of state.areas) for (const d of a.devices) for (const e of d.entities) {
    allEntities.push(e);
    entitiesById.set(e.entity_id, e);
  }

  // 渲染分类桶
  for (const cat of state.categories) {
    const bucketEl = renderBucket(cat, entitiesById);
    container.appendChild(bucketEl);
  }
  // 渲染未分配桶
  const unassignedCat = { id: '_unassigned', name: '未分配', icon: '❓', port: '—' };
  container.appendChild(renderBucket(unassignedCat, entitiesById));
}

function renderBucket(cat, entitiesById) {
  const el = document.createElement('div');
  el.className = 'bucket';
  el.dataset.catId = cat.id;

  const ids = [...(state.assignment[cat.id] || new Set())];
  const entities = ids.map(id => entitiesById.get(id)).filter(Boolean).filter(entityMatchesFilters);

  el.innerHTML = `
    <div class="bucket-head">
      <span class="bucket-icon">${escapeHtml(cat.icon || '📁')}</span>
      <span class="bucket-name">${escapeHtml(cat.name)}</span>
      <span class="bucket-port">:${cat.port || '—'}</span>
      <span class="bucket-count">${ids.length} 个实体</span>
      ${cat.id !== '_unassigned' ? '<button class="bucket-clear" data-action="clear-bucket">清空</button>' : ''}
    </div>
    <div class="bucket-body"></div>
  `;
  const body = el.querySelector('.bucket-body');
  if (entities.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'bucket-empty';
    empty.textContent = ids.length === 0 ? '拖拽实体到这里,或使用 🎯 自动归类' : '没有匹配的实体(已应用筛选)';
    body.appendChild(empty);
  } else {
    for (const e of entities) {
      body.appendChild(renderEntityCard(e, true));
    }
  }
  // 清空按钮
  const clearBtn = el.querySelector('[data-action="clear-bucket"]');
  if (clearBtn) {
    clearBtn.onclick = () => {
      for (const id of [...state.assignment[cat.id]]) {
        moveEntity(id, '_unassigned');
      }
      markDirty();
      render();
    };
  }
  return el;
}

function renderEntityCard(e, inBucket) {
  const card = document.createElement('div');
  card.className = 'entity';
  card.dataset.entityId = e.entity_id;
  card.innerHTML = `
    <div class="entity-checkbox"></div>
    <div class="entity-info">
      <div class="entity-name" title="${escapeHtml(e.friendly_name || e.entity_id)}">${escapeHtml(e.friendly_name || e.entity_id)}</div>
      <div class="entity-id">${escapeHtml(e.entity_id)}</div>
    </div>
    <div class="entity-meta">
      <span class="domain-badge">${e.domain}</span>
      <span class="state-badge ${stateClass(e.state)}">${escapeHtml(String(e.state ?? '—'))}</span>
    </div>
  `;
  // 点击切换
  card.onclick = () => {
    const cat = findCatForEntity(e.entity_id);
    if (cat === '_unassigned' || cat === null) {
      // 加入到第一个分类(暖通/厨房.../清洁),如果没有则用 _unassigned
      moveEntity(e.entity_id, state.categories[0]?.id || '_unassigned');
    } else {
      // 移除到 _unassigned
      moveEntity(e.entity_id, '_unassigned');
    }
    markDirty();
    render();
  };
  return card;
}

function moveEntity(eid, targetCatId) {
  // 从所有分类移除
  for (const cat of state.categories) state.assignment[cat.id]?.delete(eid);
  state.assignment._unassigned?.delete(eid);
  // 加入目标
  if (!state.assignment[targetCatId]) state.assignment[targetCatId] = new Set();
  state.assignment[targetCatId].add(eid);
}

function markDirty() {
  state.dirty = true;
}

function updateDirtyStatus() {
  const info = $('#dirty-info');
  if (state.dirty) {
    info.textContent = '● 有未保存的修改';
    info.parentElement.classList.add('dirty');
  } else {
    info.textContent = '✓ 无修改';
    info.parentElement.classList.remove('dirty');
  }
}

function updateSelectionCount() {
  let n = 0;
  for (const cat of state.categories) n += state.assignment[cat.id]?.size || 0;
  $('#selection-count').textContent = `已选 ${n} / ${state.areas.reduce((s, a) => s + a.entity_count, 0)}`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ============== 事件绑定 ==============
function bindUI() {
  // 搜索/过滤
  $('#entity-search').addEventListener('input', e => {
    state.searchTerm = e.target.value.trim();
    renderBuckets();
  });
  $('#domain-filter').addEventListener('change', e => {
    state.domainFilter = e.target.value;
    renderBuckets();
  });
  $('#bucket-filter').addEventListener('change', e => {
    state.bucketFilter = e.target.value;
    renderBuckets();
  });
  $('#tree-search').addEventListener('input', e => {
    state.treeSearchTerm = e.target.value.trim();
    renderTree();
  });
  // 顶部按钮
  $('#btn-reload-bridges').onclick = reloadBridges;
  $('#btn-backups').onclick = showBackups;
  $('#btn-categories').onclick = openCategoriesDrawer;
  // 底部按钮
  $('#btn-save').onclick = saveAll;
  $('#btn-preview').onclick = previewDiff;
  $('#btn-auto-assign').onclick = async () => {
    await autoAssign();
    state.dirty = true;
    render();
    toast('已按分类规则自动归类', 'success');
  };
  $('#btn-select-all-visible').onclick = () => {
    // 选中当前 bucket filter 下所有未分配
    if (state.bucketFilter) return;
    const all = [];
    for (const a of state.areas) for (const d of a.devices) for (const e of d.entities) {
      if (findCatForEntity(e.entity_id) === null) all.push(e.entity_id);
    }
    if (all.length === 0) {
      toast('没有可分配的实体', 'warning');
      return;
    }
    if (!confirm(`将 ${all.length} 个未分配实体归入「${state.categories[0]?.name || '默认'}」?`)) return;
    for (const id of all) moveEntity(id, state.categories[0]?.id || '_unassigned');
    state.dirty = true;
    render();
  };
  $('#btn-clear-selection').onclick = () => {
    if (!confirm('清空所有分类中的实体(移到未分配)?')) return;
    for (const cat of state.categories) {
      for (const id of [...(state.assignment[cat.id] || [])]) {
        moveEntity(id, '_unassigned');
      }
    }
    state.dirty = true;
    render();
  };
  // 抽屉/模态关闭
  document.querySelectorAll('[data-close-drawer]').forEach(el => {
    el.onclick = () => document.getElementById(el.dataset.closeDrawer).style.display = 'none';
  });
  document.querySelectorAll('[data-close-modal]').forEach(el => {
    el.onclick = () => document.getElementById(el.dataset.closeModal).style.display = 'none';
  });
  // 分类管理按钮
  $('#btn-add-category').onclick = () => {
    state.categories.push({
      id: 'cat_' + Date.now(),
      name: '新分类',
      port: 51801 + state.categories.length,
      icon: '📁',
      rules: [],
    });
    state.assignment[state.categories[state.categories.length - 1].id] = new Set();
    renderCategoriesList();
  };
  $('#btn-reset-defaults').onclick = () => {
    if (!confirm('重置为内置 6 分类(暖通/厨房/衣物/照明/安防/影音)?已有自定义分类将丢失')) return;
    fetchCategoriesFromServerDefaults();
  };
  $('#btn-save-categories').onclick = saveCategories;
  // 预览保存按钮
  $('#btn-save-from-preview').onclick = saveAll;
}

// ============== API 动作 ==============
async function reloadBridges() {
  if (state.dirty && !confirm('有未保存的修改,继续 reload 吗?')) return;
  try {
    const r = await api('POST', '/api/reload');
    toast(`已 reload ${r.count || 0} 个 bridge`, 'success');
  } catch (e) {
    toast('Reload 失败: ' + e.message, 'error');
  }
}

async function saveCategories() {
  try {
    const r = await api('POST', '/api/categories', { categories: state.categories });
    toast(`已保存 ${r.count} 个分类配置`, 'success');
    document.getElementById('categories-drawer').style.display = 'none';
  } catch (e) {
    toast('保存分类失败: ' + e.message, 'error');
  }
}

async function fetchCategoriesFromServerDefaults() {
  // 通过删除服务器文件来获取默认,这里简化:直接用内置默认
  const defaults = [
    { id: 'hvac', name: '暖通空调', port: 51801, icon: '❄️', rules: [{ type: 'domain', values: ['climate'] }] },
    { id: 'kitchen', name: '厨房家电', port: 51802, icon: '🍳', rules: [{ type: 'name_contains', values: ['冰箱', '洗碗机', '净水', '管线机', '电饭煲'] }] },
    { id: 'laundry', name: '衣物护理', port: 51803, icon: '👕', rules: [{ type: 'name_contains', values: ['洗衣机', '干衣机', '晾衣机'] }] },
    { id: 'lighting', name: '照明与窗帘', port: 51804, icon: '💡', rules: [{ type: 'domain', values: ['light', 'cover', 'switch'] }] },
    { id: 'security', name: '安防与传感器', port: 51805, icon: '🛡️', rules: [{ type: 'domain', values: ['binary_sensor', 'sensor'] }] },
    { id: 'media', name: '清洁与影音', port: 51806, icon: '🎬', rules: [{ type: 'domain', values: ['media_player', 'vacuum', 'remote'] }] },
  ];
  state.categories = defaults;
  renderCategoriesList();
}

async function saveAll() {
  const assignment = {};
  for (const [k, v] of Object.entries(state.assignment)) assignment[k] = [...v];
  try {
    const r = await api('POST', '/api/save_all', {
      categories: state.categories,
      assignment,
      name_overrides: {},  // TODO: 自定义命名
      reload_bridges: true,
    });
    state.dirty = false;
    updateDirtyStatus();
    const totalEntities = r.bridges.reduce((s, b) => s + b.count, 0);
    toast(`已保存: ${r.bridges.length} bridge, ${totalEntities} entity`, 'success');
    document.getElementById('preview-modal').style.display = 'none';
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  }
}

async function previewDiff() {
  // 对比当前与服务器实际配置的差异
  try {
    const cur = await api('GET', '/api/bridges');
    const curMap = new Map(cur.bridges.map(b => [b.port, new Set(b.entities.map(e => e.entity_id))]));

    const lines = [];
    for (const cat of state.categories) {
      const newSet = state.assignment[cat.id] || new Set();
      const oldSet = curMap.get(cat.port) || new Set();
      const added = [...newSet].filter(x => !oldSet.has(x));
      const removed = [...oldSet].filter(x => !newSet.has(x));
      if (added.length || removed.length) {
        lines.push(`<div class="preview-section"><h4>${escapeHtml(cat.name)} (:${cat.port})</h4>`);
        if (added.length) {
          lines.push(`<div class="preview-list">${added.map(x => `<div class="added">+ ${escapeHtml(x)}</div>`).join('')}</div>`);
        }
        if (removed.length) {
          lines.push(`<div class="preview-list">${removed.map(x => `<div class="removed">- ${escapeHtml(x)}</div>`).join('')}</div>`);
        }
        lines.push('</div>');
      }
    }
    if (lines.length === 0) {
      $('#preview-body').innerHTML = '<p class="hint">无变更</p>';
    } else {
      $('#preview-body').innerHTML = lines.join('');
    }
    document.getElementById('preview-modal').style.display = 'flex';
  } catch (e) {
    toast('预览失败: ' + e.message, 'error');
  }
}

async function showBackups() {
  try {
    const r = await api('GET', '/api/backups');
    if (r.backups.length === 0) {
      $('#backups-body').innerHTML = '<p class="hint">暂无备份</p>';
    } else {
      $('#backups-body').innerHTML = '<div class="preview-list">' + r.backups.map(b =>
        `<div>${escapeHtml(b.name)} <button class="btn-ghost" data-restore="${escapeHtml(b.path)}">恢复</button></div>`
      ).join('') + '</div>';
      $$('#backups-body [data-restore]').forEach(btn => {
        btn.onclick = async () => {
          if (!confirm('恢复此备份?当前配置会覆盖。')) return;
          try {
            await api('POST', '/api/restore', { backup_path: btn.dataset.restore });
            toast('已恢复,请刷新页面查看', 'success');
            document.getElementById('backups-modal').style.display = 'none';
          } catch (e) { toast('恢复失败: ' + e.message, 'error'); }
        };
      });
    }
    document.getElementById('backups-modal').style.display = 'flex';
  } catch (e) {
    toast('加载备份失败: ' + e.message, 'error');
  }
}

// ============== 分类管理抽屉 ==============
function openCategoriesDrawer() {
  renderCategoriesList();
  document.getElementById('categories-drawer').style.display = 'flex';
}

function renderCategoriesList() {
  const list = $('#categories-list');
  list.innerHTML = '';
  state.categories.forEach((cat, idx) => {
    const el = document.createElement('div');
    el.className = 'cat-item';
    el.draggable = true;
    el.dataset.idx = idx;
    el.innerHTML = `
      <div class="cat-item-head">
        <span class="drag-handle">≡</span>
        <input class="cat-icon-input" value="${escapeHtml(cat.icon || '📁')}" data-field="icon">
        <input class="cat-name-input" value="${escapeHtml(cat.name)}" data-field="name">
        <input class="cat-port-input" value="${cat.port}" data-field="port">
        <button class="btn-danger" data-action="del">删除</button>
      </div>
      <div class="cat-rules">
        ${(cat.rules || []).map((r, ri) => renderRule(r, ri)).join('')}
        <button class="btn-ghost" data-action="add-rule">+ 规则</button>
      </div>
    `;
    // 绑定
    el.querySelectorAll('input').forEach(inp => {
      inp.oninput = () => {
        const f = inp.dataset.field;
        if (f === 'port') cat[f] = parseInt(inp.value) || cat[f];
        else cat[f] = inp.value;
      };
    });
    el.querySelector('[data-action="del"]').onclick = () => {
      if (!confirm(`删除分类「${cat.name}」?该分类下的实体会移到未分配`)) return;
      // 移到未分配
      for (const id of [...(state.assignment[cat.id] || [])]) moveEntity(id, '_unassigned');
      delete state.assignment[cat.id];
      state.categories.splice(idx, 1);
      renderCategoriesList();
    };
    el.querySelector('[data-action="add-rule"]').onclick = () => {
      cat.rules = cat.rules || [];
      cat.rules.push({ type: 'domain', values: [] });
      renderCategoriesList();
    };
    el.querySelectorAll('.cat-rule').forEach((ruleEl, ri) => {
      const typeSel = ruleEl.querySelector('[data-rfield="type"]');
      const valsInp = ruleEl.querySelector('[data-rfield="values"]');
      typeSel.onchange = () => {
        cat.rules[ri].type = typeSel.value;
        renderCategoriesList();
      };
      valsInp.oninput = () => {
        cat.rules[ri].values = valsInp.value.split(',').map(s => s.trim()).filter(Boolean);
      };
      ruleEl.querySelector('[data-action="del-rule"]').onclick = () => {
        cat.rules.splice(ri, 1);
        renderCategoriesList();
      };
    });
    // 拖拽
    el.ondragstart = (e) => {
      el.classList.add('dragging');
      e.dataTransfer.setData('text/plain', idx);
    };
    el.ondragend = () => el.classList.remove('dragging');
    el.ondragover = (e) => { e.preventDefault(); };
    el.ondrop = (e) => {
      e.preventDefault();
      const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
      const toIdx = parseInt(el.dataset.idx);
      if (fromIdx === toIdx) return;
      const [moved] = state.categories.splice(fromIdx, 1);
      state.categories.splice(toIdx, 0, moved);
      renderCategoriesList();
    };
    list.appendChild(el);
  });
}

function renderRule(r, idx) {
  return `
    <div class="cat-rule">
      <select data-rfield="type">
        <option value="domain" ${r.type === 'domain' ? 'selected' : ''}>domain</option>
        <option value="name_contains" ${r.type === 'name_contains' ? 'selected' : ''}>名字包含</option>
        <option value="entity_contains" ${r.type === 'entity_contains' ? 'selected' : ''}>entity_id 包含</option>
        <option value="manual" ${r.type === 'manual' ? 'selected' : ''}>手动(暂不支持编辑)</option>
      </select>
      <input class="rule-values" data-rfield="values" value="${escapeHtml((r.values || []).join(','))}" placeholder="逗号分隔,如 climate,select">
      <button class="btn-danger" data-action="del-rule">×</button>
    </div>
  `;
}
