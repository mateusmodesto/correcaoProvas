// Estado de navegação
let resProvaAtual = null; // { id, descricao, formulas_disc }

const resContainer  = document.getElementById('res-container');
const resBreadcrumb = document.getElementById('res-breadcrumb');

// ── Utilitários ───────────────────────────────────────────────────────────────
function fmtData(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function setBreadcrumb(parts) {
  resBreadcrumb.innerHTML = parts.map((p, i) =>
    i < parts.length - 1
      ? `<span class="res-bc-link" data-level="${i}">${p}</span>`
      : `<span class="res-bc-cur">${p}</span>`
  ).join(' <span class="res-bc-sep">›</span> ');
}

resBreadcrumb.addEventListener('click', e => {
  const link = e.target.closest('.res-bc-link');
  if (!link) return;
  const level = parseInt(link.dataset.level);
  if (level === 0) loadProvas();
  if (level === 1 && resProvaAtual) loadAlunos(resProvaAtual);
});

// ── Nível 1: lista de provas ──────────────────────────────────────────────────
async function loadProvas() {
  resProvaAtual = null;
  setBreadcrumb(['Resultados']);
  resContainer.innerHTML = '<div class="res-loading">Carregando...</div>';
  try {
    const res   = await fetch('banco/resultados.php');
    const provas = await res.json();
    if (!provas.length) {
      resContainer.innerHTML = '<div class="res-empty">Nenhuma prova com correções ainda.</div>';
      return;
    }
    const provasComCorrecao = provas.filter(p => p.total_alunos > 0);
    if (!provasComCorrecao.length) {
      resContainer.innerHTML = '<div class="res-empty">Nenhuma prova com correções ainda.</div>';
      return;
    }
    resContainer.innerHTML = '';
    provasComCorrecao.forEach(p => {
      const card = document.createElement('div');
      card.className = 'res-card';
      card.innerHTML = `
        <div class="res-card-main">
          <div class="res-card-name">${p.descricao}</div>
          <div class="res-card-meta">${p.ultima_correcao ? 'última: ' + fmtData(p.ultima_correcao) : ''}</div>
        </div>
        <div class="res-card-arrow">›</div>`;
      card.addEventListener('click', () => loadAlunos(p));
      resContainer.appendChild(card);
    });
  } catch (e) {
    resContainer.innerHTML = `<div class="res-empty">Erro: ${e.message}</div>`;
  }
}

// ── Nível 2: lista de alunos agrupados por turma ─────────────────────────────
async function loadAlunos(prova) {
  resProvaAtual = prova;
  setBreadcrumb(['Resultados', prova.descricao]);
  resContainer.innerHTML = '<div class="res-loading">Carregando...</div>';
  try {
    const res    = await fetch('banco/resultados.php?prova_id=' + prova.id);
    const alunos = await res.json();
    if (!alunos.length) {
      resContainer.innerHTML = '<div class="res-empty">Nenhuma correção registrada para esta prova.</div>';
      return;
    }

    // para cada RA, inclui versão com M (ex: 2201528 → também busca 2201528M)
    const rasSet = new Set();
    alunos.forEach(a => {
      rasSet.add(a.aluno);
      if (!/M$/i.test(a.aluno)) rasSet.add(a.aluno + 'M');
    });
    const ras = [...rasSet].join(',');

    // busca nomes e turmas em paralelo (best-effort)
    const nomesRaw  = {};
    const turmasRaw = {};
    await Promise.allSettled([
      fetch('banco/nomes_alunos.php?ras=' + encodeURIComponent(ras))
        .then(r => r.json()).then(j => Object.assign(nomesRaw, j)),
      fetch('banco/turma_aluno.php?ras=' + encodeURIComponent(ras))
        .then(r => r.json()).then(j => Object.assign(turmasRaw, j)),
    ]);

    // prefere versão com M: se 2201528M existe, usa para 2201528 também
    const nomes  = {};
    const turmas = {};
    alunos.forEach(a => {
      const raM = a.aluno.toUpperCase().endsWith('M') ? a.aluno : a.aluno + 'M';
      nomes[a.aluno]  = nomesRaw[raM]  || nomesRaw[a.aluno]  || '';
      turmas[a.aluno] = turmasRaw[raM] || turmasRaw[a.aluno] || '';
    });

    // agrupa por turma (sem turma → "Sem turma")
    const grupos = {};
    alunos.forEach(a => {
      const t = turmas[a.aluno] || 'Sem turma';
      if (!grupos[t]) grupos[t] = [];
      grupos[t].push(a);
    });

    resContainer.innerHTML = '';
    Object.keys(grupos).filter(t => t !== 'Sem turma').sort().forEach(turma => {
      const section = document.createElement('div');
      section.className = 'res-turma-section';

      const header = document.createElement('div');
      header.className = 'res-turma-header';
      header.innerHTML = `<span class="res-turma-nome">${turma}</span>
        <span class="res-turma-count">${grupos[turma].length} aluno${grupos[turma].length !== 1 ? 's' : ''}</span>
        <span class="res-turma-arrow">›</span>`;
      section.appendChild(header);

      const body = document.createElement('div');
      body.className = 'res-turma-body';

      // ordena por nome (fallback para RA se sem nome)
      grupos[turma]
        .slice()
        .sort((x, y) => {
          const nx = nomes[x.aluno] || x.aluno;
          const ny = nomes[y.aluno] || y.aluno;
          return nx.localeCompare(ny, 'pt-BR');
        })
        .forEach(a => {
        const total = a.acertos + a.erros;
        const pct   = total > 0 ? (a.acertos / total * 100).toFixed(0) : '—';
        const cor   = total > 0 && (a.acertos / total) >= 0.6 ? '#4ade80' : '#f87171';
        const nome  = nomes[a.aluno] || '';
        const card  = document.createElement('div');
        card.className = 'res-card';
        card.innerHTML = `
          <div class="res-card-main">
            <div class="res-card-name">${nome || a.aluno}${nome ? '<span class="res-card-ra"> · ' + a.aluno + '</span>' : ''}</div>
            <div class="res-card-meta">
              <span style="color:#4ade80">✓ ${a.acertos}</span> &nbsp;
              <span style="color:#f87171">✗ ${a.erros}</span> &nbsp;
              <span style="color:${cor};font-weight:700">${pct}${total > 0 ? '%' : ''}</span>
              · ${fmtData(a.data_processamento)}
            </div>
          </div>
          <div class="res-card-arrow">›</div>`;
        card.addEventListener('click', () => loadCorrecao(prova, a.aluno, nome));
        body.appendChild(card);
      });
      section.appendChild(body);

      header.addEventListener('click', () => {
        const open = section.classList.toggle('open');
        header.querySelector('.res-turma-arrow').style.transform = open ? 'rotate(90deg)' : '';
      });

      resContainer.appendChild(section);
    });
  } catch (e) {
    resContainer.innerHTML = `<div class="res-empty">Erro: ${e.message}</div>`;
  }
}

// ── Nível 3: correção do aluno ────────────────────────────────────────────────
async function loadCorrecao(prova, aluno, nomeAluno) {
  setBreadcrumb(['Resultados', prova.descricao, aluno + (nomeAluno ? ' — ' + nomeAluno : '')]);
  resContainer.innerHTML = '<div class="res-loading">Carregando...</div>';
  try {
    const res  = await fetch(`banco/resultados.php?prova_id=${prova.id}&aluno=${encodeURIComponent(aluno)}`);
    const data = await res.json();
    if (!res.ok) { resContainer.innerHTML = `<div class="res-empty">${data.detail}</div>`; return; }

    const comp     = data.resultado?.comparacao || {};
    const formulas = prova.formulas_disc || {};
    const ac       = comp.acertos_por_disciplina || {};
    const er       = comp.erros_por_disciplina   || {};
    const discs    = [...new Set([...Object.keys(ac), ...Object.keys(er)])];
    const temNota  = discs.some(d => formulas[d] != null);

    const totalPorDisc = {};
    Object.values(comp.detalhes || {}).forEach(det => {
      const disc = det.disciplina || '';
      totalPorDisc[disc] = (totalPorDisc[disc] || 0) + 1;
    });

    const pct    = comp.porcentagem_acerto != null ? Number(comp.porcentagem_acerto).toFixed(1) : '—';
    const corPct = comp.porcentagem_acerto >= 60 ? '#4ade80' : '#f87171';

    let html = `<div class="res-detalhe">`;
    html += `<div class="res-detalhe-header">
      <div><strong>RA:</strong> ${aluno}${nomeAluno ? ' &nbsp;|&nbsp; <strong>Nome:</strong> ' + nomeAluno : ''}</div>
      <div><strong>Data:</strong> ${fmtData(data.data_processamento)}</div>
      <div style="margin-top:8px">
        <span style="color:#9ca3af">— ${comp.total_em_branco ?? 0} em branco</span>
        ${(comp.total_anuladas ?? 0) > 0 ? `&nbsp;|&nbsp;<span style="color:#a78bfa">∅ ${comp.total_anuladas} anulada${comp.total_anuladas > 1 ? 's' : ''}</span>` : ''}
      </div>
    </div>`;

    if (discs.length) {
      html += `<table class="res-table">
        <thead><tr>
          <th style="text-align:left">Disciplina</th>
          <th style="color:#4ade80">✓</th>
          <th style="color:#f87171">✗</th>
          <th>%</th>
          ${temNota ? '<th style="color:#fbbf24">Nota</th>' : ''}
        </tr></thead><tbody>`;
      discs.forEach(d => {
        const a   = ac[d] || 0;
        const e   = er[d] || 0;
        const tot = totalPorDisc[d] || (a + e);
        const p   = tot > 0 ? (a / tot * 100).toFixed(0) : '—';
        const cor = tot > 0 && (a / tot) >= 0.6 ? '#4ade80' : '#f87171';
        let notaCell = '';
        if (temNota) {
          const valMax = formulas[d];
          notaCell = valMax != null && tot > 0
            ? `<td style="color:#fbbf24;font-weight:700">${(a / tot * valMax).toFixed(2)}</td>`
            : `<td style="color:#6b7280">—</td>`;
        }
        html += `<tr>
          <td style="text-align:left;color:#e5e7eb">${d}</td>
          <td style="color:#4ade80">${a}</td>
          <td style="color:#f87171">${e}</td>
          <td style="color:${cor};font-weight:700">${p}${tot > 0 ? '%' : ''}</td>
          ${notaCell}
        </tr>`;
      });
      html += `</tbody><tfoot><tr style="border-top:2px solid #4b5563">
        <td style="text-align:left;color:#d1d5db;font-weight:700">Total</td>
        <td style="color:#4ade80;font-weight:700">${comp.total_acertos ?? '—'}</td>
        <td style="color:#f87171;font-weight:700">${comp.total_erros ?? '—'}</td>
        <td style="color:${corPct};font-weight:700;font-size:15px">${pct}${pct !== '—' ? '%' : ''}</td>
        ${temNota ? '<td></td>' : ''}
      </tr></tfoot></table>`;
    } else {
      html += `<div class="res-empty">Sem dados de disciplina para esta correção.</div>`;
    }

    html += `</div>`;
    resContainer.innerHTML = html;
  } catch (e) {
    resContainer.innerHTML = `<div class="res-empty">Erro: ${e.message}</div>`;
  }
}

function initResultados() {
  loadProvas();
}
