<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Leitura de Prova</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="css/style.css">
</head>
<body>

<!-- ═══════════════════════════════ HOME ══════════════════════════════════ -->
<div id="page-home" class="active">
  <div class="home-title">Leitura de Prova</div>
  <div class="home-subtitle">Escola Padre Anchieta</div>

  <button class="home-card" onclick="navigate('camera')">
    <div class="home-card-icon">📷</div>
    <div class="home-card-name">Fotografar Gabarito</div>
    <div class="home-card-desc">Selecione a prova e capture a folha de respostas</div>
  </button>

  <button class="home-card" onclick="navigate('cadastro')">
    <div class="home-card-icon">📋</div>
    <div class="home-card-name">Cadastrar Prova</div>
    <div class="home-card-desc">Crie ou edite provas e gabaritos</div>
  </button>

  <button class="home-card" onclick="navigate('resultados')">
    <div class="home-card-icon">📊</div>
    <div class="home-card-name">Resultados</div>
    <div class="home-card-desc">Veja correções por prova e por aluno</div>
  </button>
</div>

<!-- ══════════════════════════════ CÂMERA ════════════════════════════════ -->
<div id="page-camera">

  <div id="selection-screen">
    <div class="sel-header">
      <button id="btn-sel-home" onclick="navigate('home')">← Início</button>
      <div id="selection-title">Selecione a prova</div>
      <div style="width:74px;flex-shrink:0"></div>
    </div>
    <div id="selection-subtitle">Qual prova será fotografada?</div>
    <div id="models-list" style="width:100%;max-width:400px;display:flex;flex-direction:column;gap:12px;">
      <div style="color:#6b7280;font-size:13px;font-family:sans-serif;text-align:center;padding:16px">Carregando...</div>
    </div>
  </div>

  <div id="viewport">
    <video id="cam-video" autoplay playsinline muted></video>
    <canvas id="cam-canvas"></canvas>

    <svg id="overlay" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <mask id="sheet-mask">
          <rect id="mask-bg" x="0" y="0" fill="white"/>
          <rect id="mask-sheet" rx="4" fill="black"/>
        </mask>
      </defs>
      <rect id="shadow" x="0" y="0" fill="rgba(0,0,0,0.55)" mask="url(#sheet-mask)"/>
      <rect id="border-sheet" rx="4" fill="none" stroke="rgba(255,255,255,0.7)" stroke-width="3"/>
      <rect id="border-answers" rx="2" fill="none" stroke="#f59e0b" stroke-width="3"/>
      <polyline id="corner-tl" fill="none" stroke="#f59e0b" stroke-width="5" stroke-linecap="round"/>
      <polyline id="corner-tr" fill="none" stroke="#f59e0b" stroke-width="5" stroke-linecap="round"/>
      <polyline id="corner-bl" fill="none" stroke="#f59e0b" stroke-width="5" stroke-linecap="round"/>
      <polyline id="corner-br" fill="none" stroke="#f59e0b" stroke-width="5" stroke-linecap="round"/>
      <g id="col-lines"></g>
      <g id="grid-lines"></g>
      <circle id="grid-center-dot" r="5" fill="none" stroke="#facc15" stroke-width="2" opacity="0" />
      <rect id="border-title" rx="2" fill="rgba(245,158,11,0.12)" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4,3"/>
      <text id="label-respostas" fill="#f59e0b" font-size="11" font-family="sans-serif" font-weight="bold" text-anchor="middle" opacity="0.9"></text>
    </svg>

    <button id="btn-cam-back">← Trocar prova</button>
    <div id="hint"><span>Aproxime o celular até a folha preencher o guia branco</span></div>
    <button id="btn-capture" title="Fotografar"></button>
    <button id="btn-flip" title="Virar câmera">🔄</button>
    <button id="btn-flash" title="Flash">⚡</button>
    <div id="flash-overlay"></div>
  </div>

  <div id="preview-screen">
    <img id="preview-img" alt="Foto capturada">
    <div id="preview-actions">
      <button class="btn btn-secondary" id="btn-retake">↩ Refazer</button>
      <button class="btn btn-primary"   id="btn-send">✓ Enviar</button>
      <button class="btn btn-secondary" id="btn-nova-digitalizacao" style="display:none">📷 Nova digitalização</button>
      <button class="btn btn-secondary" id="btn-voltar-home"        style="display:none">⌂ Início</button>
    </div>
    <div id="status"></div>
  </div>

  <div id="ra-modal-backdrop">
    <div id="ra-modal">
      <h2>RA não detectado</h2>
      <p>O RA do aluno não foi lido automaticamente.<br>Digite o RA para continuar.</p>
      <input id="ra-input" type="number" inputmode="numeric" pattern="[0-9]*" placeholder="0000000" maxlength="10">
      <div id="ra-modal-actions">
        <button class="btn btn-secondary" id="btn-ra-cancel">Cancelar</button>
        <button class="btn btn-primary"   id="btn-ra-confirm">Confirmar</button>
      </div>
    </div>
  </div>

</div>

<!-- ═══════════════════════════ CADASTRO ═════════════════════════════════ -->
<div id="page-cadastro">
  <div class="cad-container">

    <div class="cad-header">
      <button class="back-btn" onclick="navigate('home')">← Início</button>
      <h1>Cadastro de Provas</h1>
      <div style="width:62px;flex-shrink:0"></div>
    </div>

    <div id="provas-list"></div>

    <button id="btn-nova-prova">+ Nova Prova</button>

    <div id="cad-form-section" style="display:none">
      <h2 id="form-title">Nova Prova</h2>

      <div class="field">
        <label for="inp-descricao">Descrição</label>
        <input type="text" id="inp-descricao" placeholder="Ex: Prova Bimestral — 7º Ano A">
      </div>

      <div class="field">
        <label for="inp-dt-aplicacao">Data e hora de início <span style="color:#6b7280;font-weight:400;font-size:12px">(opcional)</span></label>
        <input type="datetime-local" id="inp-dt-aplicacao">
      </div>

      <div class="field">
        <label for="inp-dt-termino">Data e hora de término <span style="color:#6b7280;font-weight:400;font-size:12px">(opcional)</span></label>
        <input type="datetime-local" id="inp-dt-termino">
      </div>

      <div class="field">
        <label for="inp-modelo">Modelo de gabarito</label>
        <select id="inp-modelo">
          <option value="">Carregando modelos...</option>
        </select>
      </div>

      <div class="field">
        <label for="inp-nivel">Nível de ensino</label>
        <select id="inp-nivel">
          <option value="">Selecione o nível</option>
          <option value="EJND_ENS_MED">Ensino Médio</option>
          <option value="EJND_ENS_FUND">Ensino Fundamental</option>
          <option value="EJND_GRAD">Graduação</option>
          <option value="EJND_POS_GRAD">Pós-Graduação</option>
          <option value="FCAJ_ENS_MED">Ensino Médio (FCAJ)</option>
          <option value="FCAJ_ENS_FUND">Ensino Fundamental (FCAJ)</option>
          <option value="FCAJ_GRAD">Graduação (FCAJ)</option>
          <option value="FVZA_ENS_MED">Ensino Médio (FVZA)</option>
          <option value="FVZA_ENS_FUND">Ensino Fundamental (FVZA)</option>
          <option value="FVZA_GRAD">Graduação (FVZA)</option>
          <option value="EAD_GRAD">Graduação EAD</option>
          <option value="EAD_POS_GRAD">Pós-Graduação EAD</option>
        </select>
      </div>

      <div class="field" id="field-nq" style="display:none">
        <label>Disciplinas</label>
        <div id="disc-list"></div>
        <div style="display:flex;gap:8px;align-items:flex-start;margin-top:8px;flex-wrap:wrap">
          <div class="disc-autocomplete-wrap" style="flex:1;min-width:180px;position:relative">
            <input type="text" id="inp-disc-nome" placeholder="Digite para buscar disciplina..." autocomplete="off">
            <div id="disc-suggestions" class="disc-suggestions"></div>
          </div>
          <input type="number" id="inp-disc-nq"    placeholder="Qtd" min="1" style="width:72px">
          <input type="number" id="inp-disc-valor" placeholder="Nota máx" min="0" step="0.1" style="width:100px">
          <button class="cad-btn cad-btn-secondary" id="btn-add-disc" type="button">+ Adicionar</button>
        </div>
        <input type="hidden" id="inp-disc-codigo">
        <div id="nq-hint" style="font-size:12px;color:#6b7280;margin-top:6px"></div>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="cad-btn cad-btn-secondary" id="btn-gerar"   type="button" style="flex:1">Gerar gabarito</button>
          <button class="cad-btn cad-btn-secondary" id="btn-importar-gab" type="button" style="flex:1">↓ Importar de outra prova</button>
        </div>
      </div>

      <div id="gabarito-section" style="display:none">
        <h3 id="gabarito-title">Gabarito</h3>
        <div id="gabarito-grid"></div>
      </div>

      <div class="form-actions">
        <button class="cad-btn cad-btn-primary"   id="btn-salvar">Salvar prova</button>
        <button class="cad-btn cad-btn-secondary" id="btn-cancelar">Cancelar</button>
      </div>
    </div>

  </div>
</div>

<!-- ══════════════════════════ RESULTADOS ════════════════════════════════ -->
<div id="page-resultados">
  <div class="cad-container">
    <div class="cad-header">
      <button class="back-btn" onclick="navigate('home')">← Início</button>
      <h1>Resultados</h1>
      <div style="width:62px;flex-shrink:0"></div>
    </div>
    <nav id="res-breadcrumb" class="res-breadcrumb"></nav>
    <div id="res-container"></div>
  </div>
</div>

<!-- ─── Modal importar gabarito ──────────────────────────────────────────── -->
<div id="import-modal-backdrop">
  <div id="import-modal">
    <h2>Importar gabarito</h2>
    <p>Selecione a prova cujo gabarito deseja copiar.</p>
    <div id="import-list"></div>
    <div id="import-modal-actions">
      <button class="cad-btn cad-btn-secondary" id="btn-import-cancel">Cancelar</button>
    </div>
  </div>
</div>

<!-- ─── Toast global ─────────────────────────────────────────────────────── -->
<div id="toast"></div>

<!-- ─── Tutorial câmera (global, fora das páginas) ────────────────────────── -->
<!--
<div id="guide-modal-backdrop">
  <div id="guide-modal">
    <div id="guide-title">Como posicionar a folha</div>
    <ul id="guide-list">
      <li><span class="guide-swatch" style="border:2px dashed rgba(255,255,255,0.6)"></span><span>Linhas brancas pontilhadas separam os <strong>painéis</strong> de questões</span></li>
      <li><span class="guide-swatch" style="background:rgba(147,210,255,0.9)"></span><span>Linhas <strong>azuis horizontais</strong> — alinhe com as linhas de questões</span></li>
      <li><span class="guide-swatch" style="background:rgba(134,239,172,0.9)"></span><span>Linhas <strong>verdes verticais</strong> — alinhe com as colunas de alternativas</span></li>
      <li><span class="guide-swatch" style="border:2px dashed #f59e0b"></span><span>Retângulo <strong>laranja pontilhado</strong> deve cobrir o título <em>Respostas</em></span></li>
      <li><span class="guide-swatch" style="border:2px solid rgba(255,255,255,0.7)"></span><span>A <strong>folha inteira</strong> deve ficar dentro do quadro branco</span></li>
    </ul>
    <button id="btn-guide-ok" class="btn btn-primary">Entendido</button>
  </div>
</div>
-->

<script src="js/toast.js"></script>
<script src="js/navigate.js"></script>
<script src="js/camera.js"></script>
<script src="js/cadastro.js"></script>
<script src="js/resultados.js"></script>
</body>
</html>
