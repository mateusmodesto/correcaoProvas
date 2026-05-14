const SHEET = {
  answers: { left: 24/1240, top: 684/1754, right: 1227/1240, bottom: 1736/1754 }
};
const SHEET_MARGIN = 0.01;
const COL_LINES = [376, 638, 894].map(x => x / 1240);

const IMG_W = 1240, IMG_H = 1754;

let stream = null;
let facingMode = 'environment';
let flashOn = false;
let capturedBlob = null;
let selectedProvaId = null;
let selectedNQuestoes = null;
let selectedNAlternativas = null;
let gridData = null; // { horizontal: [...], vertical: [...] }
let selectedModeloId = null;
let selectedFormulas = {}; // { "Disciplina": valor_maximo }

const camVideo      = document.getElementById('cam-video');
const camCanvas     = document.getElementById('cam-canvas');
const btnCapture    = document.getElementById('btn-capture');
const btnFlip       = document.getElementById('btn-flip');
const btnFlash      = document.getElementById('btn-flash');
const btnCamBack    = document.getElementById('btn-cam-back');
const btnRetake     = document.getElementById('btn-retake');
const btnSend       = document.getElementById('btn-send');
const previewScr    = document.getElementById('preview-screen');
const previewImg    = document.getElementById('preview-img');
const statusEl      = document.getElementById('status');
const selectionScr  = document.getElementById('selection-screen');
const modelsList    = document.getElementById('models-list');


function stopStream() {
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  flashOn = false;
  btnFlash.classList.remove('active');
}

let torchSupported = false;

async function setTorch(on) {
  if (!stream) return;
  const track = stream.getVideoTracks()[0];
  if (!track) return;
  try {
    await track.applyConstraints({ advanced: [{ torch: on }] });
    torchSupported = true;
    flashOn = on;
    btnFlash.classList.toggle('active', on);
  } catch (_) {
    torchSupported = false;
    flashOn = on;
    btnFlash.classList.toggle('active', on);
  }
}

function screenFlash() {
  const el = document.getElementById('flash-overlay');
  el.style.display = 'block';
  el.style.opacity = '1';
  setTimeout(() => {
    el.style.transition = 'opacity 0.4s';
    el.style.opacity = '0';
    setTimeout(() => { el.style.display = 'none'; el.style.transition = ''; }, 400);
  }, 60);
}

btnFlash.addEventListener('click', () => setTorch(!flashOn));

function initCamera() {
  previewScr.classList.remove('active');
  capturedBlob = null;
  selectedProvaId = null;
  selectedFormulas = {};
  selectionScr.classList.remove('hidden');
  loadProvasList();
}

const APLICACAO_DURACAO_MIN = 300; // fallback quando dt_termino não informado

function _provaStatus(dtInicio, dtTermino) {
  if (!dtInicio) return 'normal';
  const inicio = new Date(dtInicio.replace(' ', 'T'));
  const now    = new Date();
  const fim    = dtTermino ? new Date(dtTermino.replace(' ', 'T'))
                           : new Date(inicio.getTime() + APLICACAO_DURACAO_MIN * 60000);
  if (now > fim) return dtTermino ? 'encerrado' : 'normal';
  if (now >= inicio) return 'aplicando';
  return 'em-breve';
}

function _provaStatusLabel(dtInicio, dtTermino) {
  if (!dtInicio) return '';
  const inicio  = new Date(dtInicio.replace(' ', 'T'));
  const fim     = dtTermino ? new Date(dtTermino.replace(' ', 'T')) : null;
  const now     = new Date();
  const fmtHora = dt => dt.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const fmtData = dt => dt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  const fimLabel = fim ? ` – ${fmtHora(fim)}` : '';
  const efFim    = fim ?? new Date(inicio.getTime() + APLICACAO_DURACAO_MIN * 60000);
  const diffMin  = (inicio - now) / 60000;
  if (now > efFim && fim)            return `Encerrada — ${fmtData(inicio)} ${fmtHora(inicio)}${fimLabel}`;
  if (now >= inicio && now <= efFim) return `Em aplicação — ${fmtHora(inicio)}${fimLabel}`;
  if (diffMin > 0)  return `Começa em ${fmtData(inicio)} às ${fmtHora(inicio)}${fimLabel}`;
  return `${fmtData(inicio)} às ${fmtHora(inicio)}${fimLabel}`;
}

async function loadProvasList() {
  modelsList.innerHTML = '<div style="color:#6b7280;font-size:13px;font-family:sans-serif;text-align:center;padding:16px">Carregando...</div>';
  try {
    const res = await fetch('banco/provas.php');
    const provas = await res.json();
    modelsList.innerHTML = '';
    if (!provas.length) {
      modelsList.innerHTML = '<div style="color:#f87171;font-size:13px;font-family:sans-serif;text-align:center;padding:16px">Nenhuma prova cadastrada.</div>';
      return;
    }

    // ordenar: aplicando → em-breve → normal → encerrado (alfabético dentro de cada grupo)
    const ordem = { 'aplicando': 0, 'em-breve': 1, 'normal': 2, 'encerrado': 3 };
    provas.sort((a, b) => {
      const sa = ordem[_provaStatus(a.dt_aplicacao, a.dt_termino)];
      const sb = ordem[_provaStatus(b.dt_aplicacao, b.dt_termino)];
      return sa !== sb ? sa - sb : a.descricao.localeCompare(b.descricao, 'pt-BR');
    });

    let separatorAdded  = false;
    let encSeparatorAdded = false;
    provas.forEach(p => {
      const status = _provaStatus(p.dt_aplicacao, p.dt_termino);

      // separador visual entre provas ativas e as demais
      if (status === 'normal' && !separatorAdded && provas.some(x => ['aplicando','em-breve'].includes(_provaStatus(x.dt_aplicacao, x.dt_termino)))) {
        separatorAdded = true;
        const sep = document.createElement('div');
        sep.style.cssText = 'border-top:1px solid #374151;margin:4px 0;';
        modelsList.appendChild(sep);
      }
      // separador antes das encerradas
      if (status === 'encerrado' && !encSeparatorAdded) {
        encSeparatorAdded = true;
        const sep = document.createElement('div');
        sep.style.cssText = 'border-top:1px solid #374151;margin:4px 0;';
        modelsList.appendChild(sep);
      }

      const btn = document.createElement('button');
      btn.className = 'model-card' + (status !== 'normal' ? ' model-card--' + status : '');
      const statusLabel = _provaStatusLabel(p.dt_aplicacao, p.dt_termino);
      const badge = status === 'aplicando'
        ? '<span class="model-card-badge model-card-badge--aplicando">● EM APLICAÇÃO</span>'
        : status === 'em-breve'
          ? '<span class="model-card-badge model-card-badge--em-breve">⏱ EM BREVE</span>'
          : status === 'encerrado'
            ? '<span class="model-card-badge model-card-badge--encerrado">✓ ENCERRADA</span>'
            : '';
      btn.innerHTML = `
        <div class="model-card-name">${p.descricao} ${badge}</div>
        <div class="model-card-desc">${p.n_questoes} questões · ${p.n_alternativas} alternativas · ${p.modelo_descricao}</div>
        ${statusLabel ? `<div class="model-card-status model-card-status--${status}">${statusLabel}</div>` : ''}`;
      btn.addEventListener('click', () => {
        selectedProvaId       = p.id;
        selectedNQuestoes     = String(p.n_questoes || 100);
        selectedNAlternativas = String(p.n_alternativas || 5);
        selectedModeloId      = p.modelo_id || null;
        selectedFormulas      = p.formulas_disc || {};
        gridData              = null;
        selectionScr.classList.add('hidden');
        startCam();
        if (selectedModeloId) carregarGrid(selectedModeloId);
      });
      modelsList.appendChild(btn);
    });
  } catch (e) {
    modelsList.innerHTML = `<div style="color:#f87171;font-size:13px;font-family:sans-serif;text-align:center;padding:16px">Erro: ${e.message}</div>`;
  }
}

async function carregarGrid(modeloId) {
  try {
    const res  = await fetch(`php/api.php?rota=grid&modelo_id=${encodeURIComponent(modeloId)}`);
    const data = await res.json();
    if (data.horizontal && data.vertical) {
      gridData = data;
      const vw = window.innerWidth, vh = window.innerHeight;
      const sheetW = vw * (1 - SHEET_MARGIN * 2);
      const sheetH = sheetW * 1.414;
      const sheetX = vw * SHEET_MARGIN;
      const sheetY = Math.max(8, (vh - sheetH) / 2 - 20);
      drawGrid(sheetX, sheetY, sheetW, sheetH);
    }
  } catch (e) {
    // grade não essencial — ignora silenciosamente
  }
}

async function startCam() {
  stopStream();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false
    });
  } catch (_) {
    // fallback sem torch (alguns devices rejeitam advanced no getUserMedia)
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false
      });
    } catch (e) {
      alert('Não foi possível acessar a câmera: ' + e.message);
      return;
    }
  }
  camVideo.srcObject = stream;
  camVideo.onloadedmetadata = positionGuides;
  btnFlash.style.display = '';
}

function positionGuides() {
  const vw = window.innerWidth, vh = window.innerHeight;
  const sheetW = vw * (1 - SHEET_MARGIN * 2);
  const sheetH = sheetW * 1.414;
  const sheetX = vw * SHEET_MARGIN;
  const sheetY = Math.max(8, (vh - sheetH) / 2 - 20);
  const ansX = sheetX + sheetW * SHEET.answers.left;
  const ansY = sheetY + sheetH * SHEET.answers.top;
  const ansW = sheetW * (SHEET.answers.right - SHEET.answers.left);
  const ansH = sheetH * (SHEET.answers.bottom - SHEET.answers.top);
  const C = 18;
  const svg = document.getElementById('overlay');
  svg.setAttribute('width', vw); svg.setAttribute('height', vh);
  const setR = (id, x, y, w, h) => {
    const el = document.getElementById(id);
    el.setAttribute('x', x); el.setAttribute('y', y);
    el.setAttribute('width', w); el.setAttribute('height', h);
  };
  document.getElementById('mask-bg').setAttribute('width', vw);
  document.getElementById('mask-bg').setAttribute('height', vh);
  setR('mask-sheet', sheetX, sheetY, sheetW, sheetH);
  setR('shadow', 0, 0, vw, vh);
  setR('border-sheet', sheetX, sheetY, sheetW, sheetH);
  setR('border-answers', ansX, ansY, ansW, ansH);
  const titleH = ansH * 0.03;
  const titleY = ansY - titleH - 2;
  setR('border-title', ansX, titleY, ansW, titleH);
  const lbl = document.getElementById('label-respostas');
  lbl.setAttribute('x', ansX + ansW / 2);
  lbl.setAttribute('y', titleY + titleH / 2);
  lbl.setAttribute('dominant-baseline', 'middle');
  lbl.textContent = 'RESPOSTAS';
  document.getElementById('corner-tl').setAttribute('points', `${ansX+C},${ansY} ${ansX},${ansY} ${ansX},${ansY+C}`);
  document.getElementById('corner-tr').setAttribute('points', `${ansX+ansW-C},${ansY} ${ansX+ansW},${ansY} ${ansX+ansW},${ansY+C}`);
  document.getElementById('corner-bl').setAttribute('points', `${ansX},${ansY+ansH-C} ${ansX},${ansY+ansH} ${ansX+C},${ansY+ansH}`);
  document.getElementById('corner-br').setAttribute('points', `${ansX+ansW-C},${ansY+ansH} ${ansX+ansW},${ansY+ansH} ${ansX+ansW},${ansY+ansH-C}`);
  const colGroup = document.getElementById('col-lines');
  colGroup.innerHTML = '';
  COL_LINES.forEach(ratio => {
    const x = sheetX + sheetW * ratio;
    if (x < ansX - 2 || x > ansX + ansW + 2) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x); line.setAttribute('y1', ansY);
    line.setAttribute('x2', x); line.setAttribute('y2', ansY + ansH);
    line.setAttribute('stroke', 'rgba(255,255,255,0.35)');
    line.setAttribute('stroke-width', '1');
    line.setAttribute('stroke-dasharray', '4,4');
    colGroup.appendChild(line);
  });

}

function drawGrid(sheetX, sheetY, sheetW, sheetH) {
  const g = document.getElementById('grid-lines');
  g.innerHTML = '';
  const dot = document.getElementById('grid-center-dot');
  dot.setAttribute('opacity', '0');

  if (!gridData) return;

  const scaleX = sheetW / IMG_W;
  const scaleY = sheetH / IMG_H;

  const SVG_NS = 'http://www.w3.org/2000/svg';

  // Linha horizontal (H) — última apenas (Q100)
  const lastH = gridData.horizontal[gridData.horizontal.length - 1];
  if (lastH) {
    const y = sheetY + lastH.posicao_px * scaleY;
    const line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('x1', sheetX);
    line.setAttribute('y1', y);
    line.setAttribute('x2', sheetX + sheetW);
    line.setAttribute('y2', y);
    line.setAttribute('stroke', 'rgba(147,210,255,0.7)');
    line.setAttribute('stroke-width', '2');
    g.appendChild(line);
  }

  // Linhas verticais (V) — verde claro, ignora label='idx'
  const vLines = gridData.vertical.filter(v => v.label !== 'idx');
  vLines.forEach(v => {
    const x = sheetX + v.posicao_px * scaleX;
    const line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('x1', x);
    line.setAttribute('y1', sheetY);
    line.setAttribute('x2', x);
    line.setAttribute('y2', sheetY + sheetH);
    line.setAttribute('stroke', 'rgba(134,239,172,0.7)');
    line.setAttribute('stroke-width', '2');
    g.appendChild(line);
  });

}

btnFlip.addEventListener('click', () => {
  facingMode = facingMode === 'environment' ? 'user' : 'environment';
  startCam();
});

btnCamBack.addEventListener('click', () => {
  stopStream();
  selectedProvaId  = null;
  capturedBlob     = null;
  gridData         = null;
  selectedModeloId = null;
  const g = document.getElementById('grid-lines');
  if (g) g.innerHTML = '';
  const dot = document.getElementById('grid-center-dot');
  if (dot) dot.setAttribute('opacity', '0');
  previewScr.classList.remove('active');
  selectionScr.classList.remove('hidden');
});

btnCapture.addEventListener('click', () => {
  if (flashOn && !torchSupported) screenFlash();
  const vidW = camVideo.videoWidth, vidH = camVideo.videoHeight;
  if (!vidW || !vidH) { alert('Câmera não pronta. Tente novamente.'); return; }
  const rendW = camVideo.clientWidth  || window.innerWidth;
  const rendH = camVideo.clientHeight || window.innerHeight;
  const scaleX = vidW / rendW, scaleY = vidH / rendH;
  const scale  = Math.max(scaleX, scaleY);
  const cropOffX = (vidW - rendW * scale) / 2;
  const cropOffY = (vidH - rendH * scale) / 2;
  const vw = window.innerWidth, vh = window.innerHeight;
  const sheetW = vw * (1 - SHEET_MARGIN * 2);
  const sheetH = sheetW * 1.414;
  const sheetX = vw * SHEET_MARGIN;
  const sheetY = Math.max(8, (vh - sheetH) / 2 - 20);
  const cropX = Math.max(0, Math.round(sheetX * scale + cropOffX));
  const cropY = Math.max(0, Math.round(sheetY * scale + cropOffY));
  const cropW = Math.min(Math.round(sheetW * scale), vidW - cropX);
  const cropH = Math.min(Math.round(sheetH * scale), vidH - cropY);
  if (cropW <= 0 || cropH <= 0) {
    camCanvas.width = vidW; camCanvas.height = vidH;
    camCanvas.getContext('2d').drawImage(camVideo, 0, 0, vidW, vidH);
  } else {
    camCanvas.width = cropW; camCanvas.height = cropH;
    camCanvas.getContext('2d').drawImage(camVideo, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);
  }
  camCanvas.toBlob(blob => {
    capturedBlob = blob;
    previewImg.src = URL.createObjectURL(blob);
    previewScr.classList.add('active');
    statusEl.textContent = '';
    const old = document.getElementById('annotated-img');
    if (old) old.remove();
  }, 'image/jpeg', 0.92);
});

function showPreviewButtons(mode) {
  const retake = document.getElementById('btn-retake');
  const send   = document.getElementById('btn-send');
  const nova   = document.getElementById('btn-nova-digitalizacao');
  const home   = document.getElementById('btn-voltar-home');
  const isResult = mode === 'result';
  retake.style.display = isResult ? 'none' : '';
  send.style.display   = isResult ? 'none' : '';
  nova.style.display   = isResult ? '' : 'none';
  home.style.display   = isResult ? '' : 'none';
}

btnRetake.addEventListener('click', () => {
  previewScr.classList.remove('active');
  capturedBlob = null;
  showPreviewButtons('capture');
  const old = document.getElementById('annotated-img');
  if (old) old.remove();
});

document.getElementById('btn-nova-digitalizacao').addEventListener('click', () => {
  previewScr.classList.remove('active');
  capturedBlob = null;
  statusEl.textContent = '';
  showPreviewButtons('capture');
  const old = document.getElementById('annotated-img');
  if (old) old.remove();
});

document.getElementById('btn-voltar-home').addEventListener('click', () => {
  showPreviewButtons('capture');
  const old = document.getElementById('annotated-img');
  if (old) old.remove();
  navigate('home');
});

// ── Modal RA ──────────────────────────────────────────────────────────────────
const raModalBackdrop = document.getElementById('ra-modal-backdrop');
const raInput         = document.getElementById('ra-input');
const btnRaConfirm    = document.getElementById('btn-ra-confirm');
const btnRaCancel     = document.getElementById('btn-ra-cancel');
let pendingRaResolve  = null;

function pedirRA() {
  return new Promise(resolve => {
    pendingRaResolve = resolve;
    raInput.value = '';
    raModalBackdrop.classList.add('active');
    raInput.focus();
  });
}
btnRaConfirm.addEventListener('click', () => {
  const val = raInput.value.trim();
  if (!val) { raInput.focus(); return; }
  raModalBackdrop.classList.remove('active');
  if (pendingRaResolve) { pendingRaResolve(val); pendingRaResolve = null; }
});
btnRaCancel.addEventListener('click', () => {
  raModalBackdrop.classList.remove('active');
  if (pendingRaResolve) { pendingRaResolve(null); pendingRaResolve = null; }
});
raInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') btnRaConfirm.click();
  if (e.key === 'Escape') btnRaCancel.click();
});

// ── Envio ─────────────────────────────────────────────────────────────────────
async function enviarGabarito(raManual = null) {
  if (!capturedBlob) return;
  statusEl.textContent = 'Enviando...';
  btnSend.disabled = true;

  const form = new FormData();
  form.append('arquivo', capturedBlob, 'gabarito.jpg');
  if (selectedProvaId !== null) {
    form.append('prova_id', String(selectedProvaId));
  } else {
    form.append('n_questoes', selectedNQuestoes || '100');
    form.append('n_alternativas', selectedNAlternativas || '5');
  }
  if (raManual) form.append('ra_manual', raManual);

  try {
    const res  = await fetch('php/processar.php', { method: 'POST', body: form });
    const text = await res.text();
    if (!text) throw new Error('Resposta vazia do servidor (HTTP ' + res.status + ')');
    let data;
    try { data = JSON.parse(text); }
    catch (e) { throw new Error('Resposta inválida: ' + text.slice(0, 120)); }
    if (res.ok) {
      const aluno = data.dados_aluno;
      const ra    = aluno?.ra;
      const nome  = aluno?.nome ?? '';
      const comp  = data.comparacao;

      if (!ra && !raManual) {
        btnSend.disabled = false;
        statusEl.textContent = '';
        const raDigitado = await pedirRA();
        if (raDigitado) { await enviarGabarito(raDigitado); }
        else { statusEl.textContent = 'Envio cancelado — RA não informado.'; statusEl.style.color = '#9ca3af'; }
        return;
      }

      const raEfetivo = ra || raManual;
      const raComM    = raEfetivo && !/M$/i.test(raEfetivo) ? raEfetivo + 'M' : raEfetivo;
      let turma = null;
      let nomeEfetivo = nome;
      if (raEfetivo) {
        try {
          const ras = raComM && raComM !== raEfetivo ? `${raEfetivo},${raComM}` : raEfetivo;
          const tr = await fetch('banco/turma_aluno.php?ras=' + encodeURIComponent(ras));
          const tj = await tr.json();
          turma = tj[raComM] || tj[raEfetivo] || null;
        } catch (_) {}
        if (!nomeEfetivo) {
          try {
            const ras = raComM && raComM !== raEfetivo ? `${raEfetivo},${raComM}` : raEfetivo;
            const nr = await fetch('banco/nomes_alunos.php?ras=' + encodeURIComponent(ras));
            const nj = await nr.json();
            nomeEfetivo = nj[raComM] || nj[raEfetivo] || '';
          } catch (_) {}
        }
      }

      let html = `<strong>RA:</strong> ${raEfetivo ?? '—'}`;
      if (nomeEfetivo) html += ` &nbsp;|&nbsp; <strong>Nome:</strong> ${nomeEfetivo}`;
      if (turma) html += ` &nbsp;|&nbsp; <strong>Turma:</strong> ${turma}`;
      html += `<br><strong>Questões lidas:</strong> ${data.total_respondidas} / ${data.total_questoes}`;

      if (comp) {
        const pct = comp.porcentagem_acerto.toFixed(1);
        html += `<br>
          <span style="color:#9ca3af">— ${comp.total_em_branco} em branco</span>
          ${comp.total_anuladas > 0 ? `&nbsp;|&nbsp;<span style="color:#a78bfa">∅ ${comp.total_anuladas} anulada${comp.total_anuladas > 1?'s':''}</span>` : ''}`;

        const ac = comp.acertos_por_disciplina || {};
        const er = comp.erros_por_disciplina   || {};
        const discs = [...new Set([...Object.keys(ac), ...Object.keys(er)])];
        const temNota = discs.some(d => selectedFormulas[d] != null);

        // conta total de questões por disciplina a partir dos detalhes
        const totalPorDisc = {};
        Object.values(comp.detalhes || {}).forEach(det => {
          const disc = det.disciplina || '';
          totalPorDisc[disc] = (totalPorDisc[disc] || 0) + 1;
        });

        if (discs.length) {
          const corTotal = pct >= 60 ? '#4ade80' : '#f87171';
          html += `<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">
            <thead><tr>
              <th style="text-align:left;color:#9ca3af;padding:4px 6px;border-bottom:1px solid #374151">Disciplina</th>
              <th style="color:#4ade80;padding:4px 6px;border-bottom:1px solid #374151">✓</th>
              <th style="color:#f87171;padding:4px 6px;border-bottom:1px solid #374151">✗</th>
              <th style="color:#9ca3af;padding:4px 6px;border-bottom:1px solid #374151">%</th>
              ${temNota ? '<th style="color:#fbbf24;padding:4px 6px;border-bottom:1px solid #374151">Nota</th>' : ''}
            </tr></thead><tbody>`;
          discs.forEach(d => {
            const a    = ac[d] || 0;
            const e    = er[d] || 0;
            const tot  = totalPorDisc[d] || (a + e);
            const p    = tot > 0 ? (a / tot * 100).toFixed(0) : '—';
            const cor  = tot > 0 && (a / tot) >= 0.6 ? '#4ade80' : '#f87171';
            let notaCell = '';
            if (temNota) {
              const valMax = selectedFormulas[d];
              if (valMax != null && tot > 0) {
                const nota = (a / tot * valMax).toFixed(2);
                notaCell = `<td style="padding:4px 6px;color:#fbbf24;text-align:center;font-weight:700">${nota}</td>`;
              } else {
                notaCell = `<td style="padding:4px 6px;color:#6b7280;text-align:center">—</td>`;
              }
            }
            html += `<tr>
              <td style="text-align:left;padding:4px 6px;color:#e5e7eb">${d}</td>
              <td style="padding:4px 6px;color:#4ade80;text-align:center">${a}</td>
              <td style="padding:4px 6px;color:#f87171;text-align:center">${e}</td>
              <td style="padding:4px 6px;color:${cor};text-align:center;font-weight:700">${p}${tot>0?'%':''}</td>
              ${notaCell}
            </tr>`;
          });
          html += `</tbody><tfoot><tr style="border-top:2px solid #4b5563">
            <td style="text-align:left;padding:6px 6px;color:#d1d5db;font-weight:700">Total</td>
            <td style="padding:6px 6px;color:#4ade80;text-align:center;font-weight:700">${comp.total_acertos}</td>
            <td style="padding:6px 6px;color:#f87171;text-align:center;font-weight:700">${comp.total_erros}</td>
            <td style="padding:6px 6px;color:${corTotal};text-align:center;font-weight:700;font-size:15px">${pct}%</td>
            ${temNota ? '<td></td>' : ''}
          </tr></tfoot></table>`;
        }
      } else {
        html += `<br><span style="color:#9ca3af">Gabarito não enviado — sem comparação</span>`;
      }

      statusEl.innerHTML = html;
      statusEl.style.color = '#fff';
      showPreviewButtons('result');

      if (data.imagem_anotada) {
        let imgEl = document.getElementById('annotated-img');
        if (!imgEl) {
          imgEl = document.createElement('img');
          imgEl.id = 'annotated-img';
          imgEl.style.cssText = 'width:100%;max-width:480px;border-radius:8px;margin-top:12px;display:block';
          statusEl.parentNode.insertBefore(imgEl, statusEl.nextSibling);
        }
        imgEl.src = 'data:image/jpeg;base64,' + data.imagem_anotada;
      }
    } else {
      statusEl.textContent = 'Erro: ' + (data.detail || res.status);
      statusEl.style.color = '#f87171';
    }
  } catch (e) {
    statusEl.textContent = 'Falha de rede: ' + e.message;
    statusEl.style.color = '#f87171';
  }
  btnSend.disabled = false;
}


btnSend.addEventListener('click', () => enviarGabarito());
window.addEventListener('resize', positionGuides);
