let cadModelos = [];
let editingId  = null;
let disciplinas = []; // [{ codigo, nome, nq, inicio, fim, valor }]

const provList     = document.getElementById('provas-list');
const cadForm      = document.getElementById('cad-form-section');
const formTitle    = document.getElementById('form-title');
const inpDesc        = document.getElementById('inp-descricao');
const inpDtAplicacao = document.getElementById('inp-dt-aplicacao');
const inpDtTermino   = document.getElementById('inp-dt-termino');
const inpModelo    = document.getElementById('inp-modelo');
const inpNivel     = document.getElementById('inp-nivel');
const gabSection   = document.getElementById('gabarito-section');
const gabTitle     = document.getElementById('gabarito-title');
const gabGrid      = document.getElementById('gabarito-grid');
const fieldNq      = document.getElementById('field-nq');
const btnGerar       = document.getElementById('btn-gerar');
const btnImportarGab  = document.getElementById('btn-importar-gab');
const importBackdrop  = document.getElementById('import-modal-backdrop');
const importList      = document.getElementById('import-list');
const btnImportCancel = document.getElementById('btn-import-cancel');
const nqHint         = document.getElementById('nq-hint');
const btnSalvar    = document.getElementById('btn-salvar');
const btnCancelar  = document.getElementById('btn-cancelar');
const btnNova      = document.getElementById('btn-nova-prova');
const discList     = document.getElementById('disc-list');
const inpDiscNome  = document.getElementById('inp-disc-nome');
const inpDiscCodigo = document.getElementById('inp-disc-codigo');
const inpDiscNq    = document.getElementById('inp-disc-nq');
const inpDiscValor = document.getElementById('inp-disc-valor');
const btnAddDisc   = document.getElementById('btn-add-disc');
const discSuggestions = document.getElementById('disc-suggestions');

// ── Autocomplete de disciplinas ───────────────────────────────────────────────
let acTimer = null;
let acSelectedCodigo = '';

function closeSuggestions() {
  discSuggestions.classList.remove('open');
  discSuggestions.innerHTML = '';
}

inpDiscNome.addEventListener('input', () => {
  acSelectedCodigo = '';
  inpDiscCodigo.value = '';
  clearTimeout(acTimer);
  const q = inpDiscNome.value.trim();
  if (q.length < 2) { closeSuggestions(); return; }
  const nivel = inpNivel.value;
  if (!nivel) { closeSuggestions(); return; }
  acTimer = setTimeout(async () => {
    try {
      const res = await fetch(`banco/disciplinas.php?faculdade=${encodeURIComponent(nivel)}&q=${encodeURIComponent(q)}`);
      const items = await res.json();
      discSuggestions.innerHTML = '';
      if (!items.length) {
        discSuggestions.innerHTML = '<div class="disc-suggestion-empty">Nenhuma disciplina encontrada</div>';
      } else {
        items.forEach(item => {
          const el = document.createElement('div');
          el.className = 'disc-suggestion-item';
          el.innerHTML = `<div class="disc-suggestion-nome">${item.nome}</div><div class="disc-suggestion-compl">${item.nome}</div>`;
          el.addEventListener('mousedown', e => {
            e.preventDefault();
            inpDiscNome.value   = item.nome;
            inpDiscCodigo.value = item.nome;
            acSelectedCodigo    = item.nome;
            closeSuggestions();
            inpDiscNq.focus();
          });
          discSuggestions.appendChild(el);
        });
      }
      discSuggestions.classList.add('open');
    } catch (_) { closeSuggestions(); }
  }, 300);
});

inpDiscNome.addEventListener('blur', () => setTimeout(closeSuggestions, 150));
inpDiscNome.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeSuggestions();
});

// Reconstrói lista de disciplinas a partir do gabarito_raw JSON
function reconstruirDiscs(gabRaw, nqFallback) {
  if (!gabRaw || gabRaw[0] !== '{') {
    return [{ nome: 'Questões', nq: nqFallback, inicio: 1, fim: nqFallback, valor: null }];
  }
  try {
    const dict    = JSON.parse(gabRaw);
    const formulas = dict['_formulas'] || {};
    const codigos  = dict['_codigos']  || {};
    const grupos  = [];
    let cur = null;
    const keys = Object.keys(dict).filter(k => !k.startsWith('_')).map(Number).sort((a, b) => a - b);
    keys.forEach(q => {
      const val  = dict[String(q)];
      const disc = (typeof val === 'object' && val !== null) ? (val.disc || '') : '';
      if (!cur || cur.nome !== disc) {
        if (cur) grupos.push(cur);
        const nome = disc || 'Questões';
        cur = { codigo: codigos[nome] ?? '', nome, nq: 1, inicio: q, fim: q, valor: formulas[nome] ?? null };
      } else {
        cur.nq++; cur.fim = q;
      }
    });
    if (cur) grupos.push(cur);
    return grupos;
  } catch (e) {
    return [{ nome: 'Questões', nq: nqFallback, inicio: 1, fim: nqFallback, valor: null }];
  }
}

function totalDiscQuestoes() {
  return disciplinas.reduce((s, d) => s + d.nq, 0);
}

function recalcRanges() {
  let cur = 1;
  disciplinas.forEach(d => { d.inicio = cur; d.fim = cur + d.nq - 1; cur += d.nq; });
}

function renderDiscList() {
  discList.innerHTML = '';
  disciplinas.forEach((d, i) => {
    const el = document.createElement('div');
    el.className = 'disc-item';
    el.dataset.i = i;
    const valorLabel = d.valor != null ? ` · nota máx: ${d.valor}` : '';
    el.innerHTML = `
      <div class="disc-item-view">
        <span class="disc-item-name">${d.nome}</span>
        <span class="disc-item-range">Q${d.inicio}–Q${d.fim} (${d.nq} questões${valorLabel})</span>
        <button class="disc-item-edit" data-i="${i}" title="Editar">✏️</button>
        <button class="disc-item-del"  data-i="${i}" title="Remover">×</button>
      </div>
      <div class="disc-item-form" style="display:none;gap:6px;align-items:center;flex-wrap:wrap;margin-top:6px;position:relative">
        <div style="position:relative;flex:1;min-width:100px">
          <input class="disc-edit-nome" type="text" value="${d.nome}" placeholder="Nome" style="width:100%;box-sizing:border-box" data-codigo="${d.codigo || ''}">
          <div class="disc-edit-suggestions disc-suggestions"></div>
        </div>
        <input class="disc-edit-nq"    type="number" value="${d.nq}"    placeholder="Qtd" min="1" style="width:64px">
        <input class="disc-edit-valor" type="number" value="${d.valor ?? ''}" placeholder="Nota máx" min="0" step="0.1" style="width:100px">
        <button class="disc-edit-ok  cad-btn cad-btn-primary"   data-i="${i}">✓</button>
        <button class="disc-edit-cancel cad-btn cad-btn-secondary" data-i="${i}">✕</button>
      </div>`;
    discList.appendChild(el);
  });
  const m = cadModelos.find(x => x.id === inpModelo.value);
  const total = totalDiscQuestoes();
  const max   = m ? m.n_questoes : '?';
  nqHint.textContent = total > 0
    ? `Total: ${total} questões de ${max} disponíveis no modelo`
    : `Adicione disciplinas. Máximo: ${max} questões`;
  nqHint.style.color = m && total > m.n_questoes ? '#f87171' : '#6b7280';
}

discList.addEventListener('click', e => {
  // Remover
  const delBtn = e.target.closest('.disc-item-del');
  if (delBtn) {
    const i = parseInt(delBtn.dataset.i, 10);
    disciplinas.splice(i, 1);
    recalcRanges();
    renderDiscList();
    gabSection.style.display = 'none';
    gabGrid.innerHTML = '';
    return;
  }

  // Abrir edição
  const editBtn = e.target.closest('.disc-item-edit');
  if (editBtn) {
    const item = editBtn.closest('.disc-item');
    item.querySelector('.disc-item-view').style.display = 'none';
    const form = item.querySelector('.disc-item-form');
    form.style.display = 'flex';
    const nomeInput = form.querySelector('.disc-edit-nome');
    const sugg      = form.querySelector('.disc-edit-suggestions');
    let acEditTimer  = null;
    nomeInput.addEventListener('input', () => {
      nomeInput.dataset.codigo = '';
      clearTimeout(acEditTimer);
      const q = nomeInput.value.trim();
      if (q.length < 2) { sugg.classList.remove('open'); sugg.innerHTML = ''; return; }
      const nivel = inpNivel.value;
      if (!nivel) { sugg.classList.remove('open'); return; }
      acEditTimer = setTimeout(async () => {
        try {
          const res   = await fetch(`banco/disciplinas.php?faculdade=${encodeURIComponent(nivel)}&q=${encodeURIComponent(q)}`);
          const items = await res.json();
          sugg.innerHTML = '';
          if (!items.length) {
            sugg.innerHTML = '<div class="disc-suggestion-empty">Nenhuma disciplina encontrada</div>';
          } else {
            items.forEach(it => {
              const el = document.createElement('div');
              el.className = 'disc-suggestion-item';
              el.innerHTML = `<div class="disc-suggestion-nome">${it.nome}</div>`;
              el.addEventListener('mousedown', ev => {
                ev.preventDefault();
                nomeInput.value          = it.nome;
                nomeInput.dataset.codigo = it.nome;
                sugg.classList.remove('open');
                sugg.innerHTML = '';
                form.querySelector('.disc-edit-nq').focus();
              });
              sugg.appendChild(el);
            });
          }
          sugg.classList.add('open');
        } catch (_) { sugg.classList.remove('open'); }
      }, 300);
    });
    nomeInput.addEventListener('blur',   () => setTimeout(() => { sugg.classList.remove('open'); sugg.innerHTML = ''; }, 150));
    nomeInput.addEventListener('keydown', ev => { if (ev.key === 'Escape') { sugg.classList.remove('open'); sugg.innerHTML = ''; } });
    nomeInput.focus();
    return;
  }

  // Cancelar edição
  const cancelBtn = e.target.closest('.disc-edit-cancel');
  if (cancelBtn) {
    const item = cancelBtn.closest('.disc-item');
    item.querySelector('.disc-item-form').style.display = 'none';
    item.querySelector('.disc-item-view').style.display = '';
    return;
  }

  // Confirmar edição
  const okBtn = e.target.closest('.disc-edit-ok');
  if (okBtn) {
    const i    = parseInt(okBtn.dataset.i, 10);
    const item = okBtn.closest('.disc-item');
    const nomeInput = item.querySelector('.disc-edit-nome');
    const nome   = nomeInput.value.trim();
    const codigo = nomeInput.dataset.codigo || disciplinas[i].codigo || '';
    const nq     = parseInt(item.querySelector('.disc-edit-nq').value, 10);
    const vRaw   = item.querySelector('.disc-edit-valor').value;
    const valor  = vRaw !== '' ? parseFloat(vRaw) : null;
    if (!nome) { showToast('Informe o nome da disciplina', 'error'); return; }
    if (!nq || nq < 1) { showToast('Informe a quantidade de questões', 'error'); return; }
    const m = cadModelos.find(x => x.id === inpModelo.value);
    const totalSemEsta = disciplinas.reduce((s, d, j) => j === i ? s : s + d.nq, 0);
    if (m && totalSemEsta + nq > m.n_questoes) {
      showToast(`Limite excedido: modelo suporta ${m.n_questoes} questões`, 'error'); return;
    }
    const nqMudou = nq !== disciplinas[i].nq;
    disciplinas[i] = { ...disciplinas[i], nome, codigo, nq, valor };
    recalcRanges();
    renderDiscList();
    if (nqMudou) {
      gabSection.style.display = 'none';
      gabGrid.innerHTML = '';
    } else {
      // atualiza só os cabeçalhos no gabarito sem destruir as respostas
      const headers = [...gabGrid.querySelectorAll('.gabarito-disc-header')];
      disciplinas.forEach((d, j) => {
        if (headers[j]) headers[j].textContent = `${d.nome} (Q${d.inicio}–Q${d.fim})`;
      });
    }
  }
});

btnAddDisc.addEventListener('click', () => {
  const m = cadModelos.find(x => x.id === inpModelo.value);
  if (!m) { showToast('Selecione um modelo primeiro', 'error'); return; }
  if (!inpNivel.value) { showToast('Selecione o nível de ensino', 'error'); return; }
  const nome   = inpDiscNome.value.trim();
  const codigo = inpDiscCodigo.value.trim();
  const nq     = parseInt(inpDiscNq.value, 10);
  const valor  = inpDiscValor.value !== '' ? parseFloat(inpDiscValor.value) : null;
  if (!nome)   { showToast('Busque e selecione uma disciplina', 'error'); return; }
  if (!codigo) { showToast('Selecione uma disciplina da lista de sugestões', 'error'); return; }
  if (!nq || nq < 1) { showToast('Informe a quantidade de questões', 'error'); return; }
  const total = totalDiscQuestoes() + nq;
  if (total > m.n_questoes) {
    showToast(`Limite excedido: modelo suporta ${m.n_questoes} questões (total ficaria ${total})`, 'error'); return;
  }
  const inicio = totalDiscQuestoes() + 1;
  disciplinas.push({ codigo, nome, nq, inicio, fim: inicio + nq - 1, valor });
  inpDiscNome.value   = '';
  inpDiscCodigo.value = '';
  acSelectedCodigo    = '';
  inpDiscNq.value     = '';
  inpDiscValor.value  = '';
  inpDiscNome.focus();
  renderDiscList();
  gabSection.style.display = 'none';
  gabGrid.innerHTML = '';
});

function buildOptions(nAlternativas, selected = 'anulada') {
  const letters = 'ABCDEFGHIJ'.slice(0, nAlternativas);
  let html = '';
  for (const l of letters)
    html += `<option value="${l}"${selected === l ? ' selected' : ''}>${l}</option>`;
  html += `<option value="anulada"${selected === 'anulada' ? ' selected' : ''}>Não existe</option>`;
  return html;
}

function renderGabarito(nQuestoes, nAlternativas, gabarito = [], discs = []) {
  gabGrid.innerHTML = '';
  let discIdx = 0;
  for (let i = 1; i <= nQuestoes; i++) {
    // cabeçalho da disciplina quando começa
    if (discs.length && discIdx < discs.length && discs[discIdx].inicio === i) {
      const hdr = document.createElement('div');
      hdr.className = 'gabarito-disc-header';
      hdr.textContent = `${discs[discIdx].nome} (Q${discs[discIdx].inicio}–Q${discs[discIdx].fim})`;
      gabGrid.appendChild(hdr);
      discIdx++;
    }
    const cur = gabarito[i - 1] || '';
    const item = document.createElement('div');
    item.className = 'questao-item';
    item.innerHTML = `<span class="questao-num">${i}</span>
      <select class="questao-select" data-q="${i}">${buildOptions(nAlternativas, cur)}</select>`;
    gabGrid.appendChild(item);
  }
  gabSection.style.display = 'block';
  gabTitle.textContent = `Gabarito (${nQuestoes} questões)`;
}

inpModelo.addEventListener('change', () => {
  const m = cadModelos.find(x => x.id === inpModelo.value);
  gabSection.style.display = 'none';
  gabGrid.innerHTML = '';
  disciplinas = [];
  renderDiscList();
  fieldNq.style.display = m ? 'block' : 'none';
});

btnGerar.addEventListener('click', () => {
  const m = cadModelos.find(x => x.id === inpModelo.value);
  if (!m) return;
  if (!disciplinas.length) {
    showToast('Adicione pelo menos uma disciplina', 'error'); return;
  }
  const total = totalDiscQuestoes();
  renderGabarito(total, m.n_alternativas, [], disciplinas);
});

function collectGabarito() {
  const selects = [...gabGrid.querySelectorAll('.questao-select')];
  const obj = {};
  const formulas = {};
  const codigos = {};
  disciplinas.forEach(d => {
    if (d.valor != null) formulas[d.nome] = d.valor;
    if (d.codigo)        codigos[d.nome]  = d.codigo;
  });
  if (Object.keys(formulas).length) obj['_formulas'] = formulas;
  if (Object.keys(codigos).length)  obj['_codigos']  = codigos;
  if (inpNivel.value) obj['_nivel'] = inpNivel.value;
  selects.forEach(s => {
    const q = parseInt(s.dataset.q, 10);
    const disc = disciplinas.find(d => q >= d.inicio && q <= d.fim);
    obj[String(q)] = { resp: s.value, disc: disc ? disc.nome : '' };
  });
  return obj;
}

// 'YYYY-MM-DD HH:MM:SS' → 'YYYY-MM-DDTHH:MM' para input datetime-local
function sqlDtToInputDt(sql) {
  return sql ? sql.slice(0, 16).replace(' ', 'T') : '';
}

// 'YYYY-MM-DD HH:MM:SS' → texto legível + badge de status
function fmtDtAplicacao(inicio, termino) {
  if (!inicio) return '';
  const dtI = new Date(inicio.replace(' ', 'T'));
  const dtF = termino ? new Date(termino.replace(' ', 'T')) : null;
  const now = new Date();
  const fmtHora = dt => dt.toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
  const label = dtF ? `${fmtHora(dtI)} – ${fmtHora(dtF)}` : fmtHora(dtI);
  if (dtF && now > dtF)                                    return `🔴 Encerrada (${label})`;
  if (now >= dtI && (dtF ? now <= dtF : true))             return `🟢 Em aplicação (${label})`;
  if (dtI > now)                                           return `🟡 Em breve (${label})`;
  return label;
}

async function initCadastro() {
  try {
    const res = await fetch('banco/modelos.php');
    cadModelos = await res.json();
    inpModelo.innerHTML = '<option value="">Selecione um modelo</option>' +
      cadModelos.map(m => `<option value="${m.id}">${m.descricao} (${m.n_questoes}q · ${m.n_alternativas} alt)</option>`).join('');
  } catch (e) {
    inpModelo.innerHTML = '<option value="">Erro ao carregar modelos</option>';
  }
  loadProvasCad();
}

async function loadProvasCad() {
  const provList = document.getElementById('provas-list');
  provList.innerHTML = '<div class="empty">Carregando...</div>';
  try {
    const res = await fetch('banco/provas.php');
    const text = await res.text();
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const provas = JSON.parse(text);
    provList.innerHTML = '';
    if (!provas.length) {
      provList.innerHTML = '<div class="empty">Nenhuma prova cadastrada ainda.</div>'; return;
    }
    provas.forEach(p => {
      const card = document.createElement('div');
      card.className = 'prova-card';
      const dtLabel = p.dt_aplicacao ? fmtDtAplicacao(p.dt_aplicacao, p.dt_termino) : '';
      card.innerHTML = `
        <div class="prova-card-info">
          <div class="prova-card-name">${p.descricao}</div>
          <div class="prova-card-meta">${p.modelo_descricao} · ${p.n_questoes} questões · ${p.n_alternativas} alt${dtLabel ? ' · ' + dtLabel : ''}</div>
        </div>
        <div class="prova-card-actions">
          <button class="btn-icon" onclick="editProva(${p.id})">✏️ Editar</button>
          <button class="btn-icon danger" onclick="deleteProva(${p.id}, '${p.descricao.replace(/'/g,"\\'")}')">🗑️</button>
        </div>`;
      provList.appendChild(card);
    });
  } catch (e) {
    provList.innerHTML = `<div class="empty">Erro ao carregar provas: ${e.message}</div>`;
  }
}

async function editProva(id) {
  try {
    const res = await fetch('banco/provas.php?id=' + id);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const p = await res.json();
    editingId = id;
    formTitle.textContent = 'Editar Prova';
    inpDesc.value = p.descricao;
    inpDtAplicacao.value = p.dt_aplicacao ? sqlDtToInputDt(p.dt_aplicacao) : '';
    inpDtTermino.value   = p.dt_termino   ? sqlDtToInputDt(p.dt_termino)   : '';
    inpModelo.value = p.modelo_id;
    try {
      const raw = JSON.parse(p.gabarito_raw || '{}');
      inpNivel.value = raw['_nivel'] || '';
    } catch (_) { inpNivel.value = ''; }
    const m = cadModelos.find(x => x.id === p.modelo_id);
    if (m) {
      const nq = p.gabarito.length || m.n_questoes;
      disciplinas = reconstruirDiscs(p.gabarito_raw, nq);
      renderDiscList();
      fieldNq.style.display = 'block';
      renderGabarito(nq, m.n_alternativas, p.gabarito, disciplinas);
    }
    cadForm.style.display = 'block';
    cadForm.scrollIntoView({ behavior: 'smooth' });
  } catch (e) { showToast('Erro ao carregar prova: ' + e.message, 'error'); }
}

async function deleteProva(id, nome) {
  if (!confirm(`Deletar "${nome}"?`)) return;
  try {
    const res = await fetch('banco/provas.php?id=' + id, { method: 'DELETE' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    showToast('Prova deletada', 'success');
    loadProvasCad();
  } catch (e) { showToast('Erro ao deletar: ' + e.message, 'error'); }
}

btnNova.addEventListener('click', () => {
  editingId = null;
  formTitle.textContent = 'Nova Prova';
  inpDesc.value = ''; inpDtAplicacao.value = ''; inpDtTermino.value = ''; inpModelo.value = ''; inpNivel.value = '';
  inpDiscNome.value = ''; inpDiscCodigo.value = ''; acSelectedCodigo = '';
  disciplinas = []; renderDiscList();
  fieldNq.style.display = 'none'; nqHint.textContent = '';
  gabSection.style.display = 'none'; gabGrid.innerHTML = '';
  cadForm.style.display = 'block';
  cadForm.scrollIntoView({ behavior: 'smooth' });
});

btnCancelar.addEventListener('click', () => {
  cadForm.style.display = 'none';
  editingId = null;
  disciplinas = [];
  inpDiscCodigo.value = ''; acSelectedCodigo = '';
});

btnSalvar.addEventListener('click', async () => {
  const descricao = inpDesc.value.trim();
  const modelo_id = inpModelo.value;
  if (!descricao) { showToast('Informe a descrição', 'error'); return; }
  if (!modelo_id) { showToast('Selecione um modelo', 'error'); return; }
  if (!gabGrid.querySelectorAll('.questao-select').length) {
    showToast('Gabarito não gerado', 'error'); return;
  }
  const gabObj  = collectGabarito();
  const gabarito = JSON.stringify(gabObj);
  const dt_aplicacao = inpDtAplicacao.value || null;
  const dt_termino   = inpDtTermino.value   || null;
  const payload  = { descricao, modelo_id, gabarito, dt_aplicacao, dt_termino };
  const url    = editingId ? 'banco/provas.php?id=' + editingId : 'banco/provas.php';
  const method = editingId ? 'PUT' : 'POST';
  btnSalvar.disabled = true;
  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.status);
    showToast(editingId ? 'Prova atualizada!' : 'Prova criada!', 'success');
    cadForm.style.display = 'none'; editingId = null;
    loadProvasCad();
  } catch (e) { showToast('Erro: ' + e.message, 'error'); }
  finally { btnSalvar.disabled = false; }
});

// ── Importar gabarito de outra prova ─────────────────────────────────────────
btnImportCancel.addEventListener('click', () => {
  importBackdrop.classList.remove('active');
});

importBackdrop.addEventListener('click', e => {
  if (e.target === importBackdrop) importBackdrop.classList.remove('active');
});

btnImportarGab.addEventListener('click', async () => {
  const m = cadModelos.find(x => x.id === inpModelo.value);
  if (!m) { showToast('Selecione um modelo primeiro', 'error'); return; }
  importList.innerHTML = '<div style="color:#6b7280;font-size:13px;text-align:center;padding:12px">Carregando...</div>';
  importBackdrop.classList.add('active');
  try {
    const res = await fetch('banco/provas.php');
    const provas = await res.json();
    const outras = provas.filter(p => p.id !== editingId);
    importList.innerHTML = '';
    if (!outras.length) {
      importList.innerHTML = '<div style="color:#6b7280;font-size:13px;text-align:center;padding:12px">Nenhuma outra prova disponível.</div>';
      return;
    }
    outras.forEach(p => {
      const modeloIgual = p.modelo_id === inpModelo.value;
      const el = document.createElement('div');
      el.className = 'import-item';
      el.innerHTML = `
        <div class="import-item-name">${p.descricao}</div>
        <div class="import-item-meta">${p.modelo_descricao} · ${p.n_questoes}q · ${p.n_alternativas} alt</div>
        ${!modeloIgual ? '<div class="import-item-warn">⚠ Modelo diferente — gabarito será adaptado ao modelo atual</div>' : ''}`;
      el.addEventListener('click', () => importarDe(p.id, m));
      importList.appendChild(el);
    });
  } catch (e) {
    importList.innerHTML = `<div style="color:#f87171;font-size:13px;text-align:center;padding:12px">Erro: ${e.message}</div>`;
  }
});

async function importarDe(provaId, modeloAtual) {
  try {
    const res = await fetch('banco/provas.php?id=' + provaId);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const p = await res.json();
    const nqOrigem = p.gabarito.length;
    const nqDestino = modeloAtual.n_questoes;

    // reconstruir disciplinas da origem
    let discsOrigem = reconstruirDiscs(p.gabarito_raw, nqOrigem);

    // ajustar quantidade de questões se modelo diferente
    if (p.modelo_id !== modeloAtual.id) {
      const fator = nqDestino / nqOrigem;
      if (fator !== 1) {
        let total = 0;
        discsOrigem = discsOrigem.map((d, i, arr) => {
          const isLast = i === arr.length - 1;
          const nq = isLast ? nqDestino - total : Math.round(d.nq * fator);
          total += nq;
          return { ...d, nq };
        });
      }
    }

    // aplicar disciplinas
    disciplinas = discsOrigem;
    recalcRanges();
    renderDiscList();

    // montar gabarito: copiar respostas até o limite do modelo atual
    const gabOrigem = p.gabarito; // array de letras
    const totalNovo = disciplinas.reduce((s, d) => s + d.nq, 0);
    const gabNovo = [];
    for (let i = 0; i < totalNovo; i++) {
      const resp = gabOrigem[i] || 'anulada';
      // validar que a alternativa existe no modelo atual
      const letrasValidas = 'ABCDEFGHIJ'.slice(0, modeloAtual.n_alternativas);
      gabNovo.push(letrasValidas.includes(resp) ? resp : 'anulada');
    }

    renderGabarito(totalNovo, modeloAtual.n_alternativas, gabNovo, disciplinas);
    importBackdrop.classList.remove('active');
    showToast('Gabarito importado! Revise antes de salvar.', 'success');
    gabSection.scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    showToast('Erro ao importar: ' + e.message, 'error');
  }
}
