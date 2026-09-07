const $ = id => document.getElementById(id);
const fields = ['domain', 'type', 'policy'];
let ready = false;
function preview() {
  $('preview').textContent = `${$('type').value},${$('domain').value || 'example.org'},${$('policy').value}`;
}
function message(text, error = false) {
  $('message').textContent = text;
  $('message').className = error ? 'error' : '';
}
function busy(value) {
  document.querySelectorAll('button,input,select').forEach(el => { el.disabled = value; });
  if (!value && !ready) { $('add').disabled = true; $('reapply').disabled = true; }
}
function native(payload) {
  return chrome.runtime.sendNativeMessage('local.clash_site_rule', payload).then(result => {
    if (!result?.ok) throw new Error(result?.error || '本地程序没有返回结果');
    return result;
  });
}
function show(state) {
  ready = true;
  $('connection').textContent = `已连接 · ${state.profile} · ${state.mode}`;
  const previous = $('policy').value;
  $('policy').replaceChildren(...state.policies.map(name => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name === 'DIRECT' ? '直连 · DIRECT' : name === 'REJECT' ? '阻止 · REJECT' : name;
    return option;
  }));
  $('policy').value = state.policies.includes(previous) ? previous : 'DIRECT';
  $('rules').replaceChildren();
  for (const rule of state.rules) {
    const row = document.createElement('div'); row.className = 'rule';
    const body = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = rule.domain;
    const detail = document.createElement('small');
    detail.textContent = `${rule.type === 'DOMAIN' ? '仅该域名' : '含子域名'} → ${rule.policy}`;
    body.append(title, detail);
    const remove = document.createElement('button'); remove.className = 'text'; remove.textContent = '删除';
    remove.setAttribute('aria-label', `删除 ${rule.domain} 规则`);
    remove.onclick = () => run({ action: 'delete', domain: rule.domain, type: rule.type }, '规则已删除，配置已重载。');
    row.append(body, remove); $('rules').append(row);
  }
  if (!state.rules.length) $('rules').textContent = '尚未通过扩展添加规则';
  if (state.mode !== 'rule') message('当前不是规则模式；请在 Clash 中切换为规则模式。', true);
  preview();
}
async function run(payload, success) {
  busy(true); message('正在保存并重载 Clash…');
  try {
    const state = await native(payload); show(state);
    message(success + (state.mode !== 'rule' ? ' 当前不是规则模式，请先在 Clash 中切换。' : ''));
  } catch (error) { message(error.message, true); }
  finally { busy(false); }
}
fields.forEach(id => $(id).addEventListener('input', preview));
$('form').onsubmit = event => {
  event.preventDefault();
  run({ action: 'add', domain: $('domain').value, type: $('type').value, policy: $('policy').value }, '规则已保存并加载，刷新网页即可。');
};
$('reapply').onclick = () => run({ action: 'reapply' }, '保存的规则已重新应用到当前配置。');
async function init() {
  busy(true);
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = new URL(tab?.url || 'about:blank');
    if (['http:', 'https:'].includes(url.protocol)) $('domain').value = url.hostname;
    else message('当前页面不是普通网站，请手动输入域名。');
    show(await native({ action: 'status' }));
  } catch (error) {
    $('connection').textContent = '连接失败';
    message(`${error.message}。请确认 Clash 已启动，并已运行对应系统的安装程序。`, true);
  } finally { busy(false); preview(); }
}
init();
