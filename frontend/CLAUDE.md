# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Contexto

Sistema de leitura e correção de provas via foto para o Colégio Anchieta. Captura folhas de resposta pela câmera do celular, envia para um backend externo de visão computacional, e exibe os resultados corrigidos.

## Como rodar

Sem build. O sistema roda diretamente no Apache via Docker:

```
http://localhost/sistema_correcao_prova/
```

O `../../conexao.php` (fora deste diretório) gerencia a conexão com SQL Server. Não existe `composer.json`, `package.json` ou variáveis de ambiente neste projeto — configuração é toda no ambiente Docker.

Para testar endpoints PHP diretamente:
```
http://localhost/sistema_correcao_prova/banco/provas.php
http://localhost/sistema_correcao_prova/banco/provas.php?id=1
```

## Arquitetura

### Frontend (Vanilla JS, sem framework, sem build)

`index.php` é o único HTML — contém 4 páginas como `<div>` ocultas:
- `#page-home` → menu inicial
- `#page-camera` → captura de foto
- `#page-cadastro` → cadastro de provas e gabaritos
- `#page-resultados` → visualização de resultados

Scripts carregados em ordem (cada um se auto-inicializa via `navigate.js`):
| Arquivo | Responsabilidade |
|---|---|
| `js/toast.js` | `showToast(msg, type)` — notificações globais |
| `js/navigate.js` | `navigate('page')` — troca de página, chama init de cada módulo |
| `js/camera.js` | Stream WebRTC, overlay SVG, captura, upload para `/php/processar.php` |
| `js/cadastro.js` | Formulário de prova: disciplinas, gabarito, importar de outra prova |
| `js/resultados.js` | Navegação 3 níveis: provas → alunos por turma → detalhe de correção |

### Backend (PHP/PDO, sem framework)

```
banco/          → acesso direto ao banco, retornam JSON
php/api.php     → roteador REST para modelos e grid
php/processar.php → gateway: envia foto para IA externa (10.200.23.13:5041)
```

### Bancos de dados (SQL Server)

Dois bancos via `Conexao::getConnection()`:

**`anchieta`** — dados do sistema:
- `anchi_cadastro_prova` — provas (id, descricao, modelo_id, gabarito, dt_aplicacao, ativo)
- `anchi_modelos_gabarito` — modelos de folha de resposta
- `anchi_modelo_grid` — coordenadas do grid por modelo
- `anchi_gabaritos_processados` — resultados das correções

**`lyceum`** — dados da escola (somente leitura):
- `ly_disciplina`, `ly_aluno`, `ly_matricula` — disciplinas, alunos, turmas

### Formato do gabarito (coluna `gabarito` em `anchi_cadastro_prova`)

JSON com estrutura:
```json
{
  "_formulas": { "Matemática": 5.0 },
  "_codigos":  { "Matemática": "COD123" },
  "_nivel":    "EJND_ENS_MED",
  "1": { "resp": "A", "disc": "Matemática" },
  "2": { "resp": "B", "disc": "Matemática" }
}
```

`reconstruirDiscs(gabRaw, nqFallback)` em `cadastro.js` reconstrói a lista de disciplinas a partir desse JSON. `collectGabarito()` faz o caminho inverso.

### Lógica de destaque de provas na câmera

`_provaStatus(dtSql)` em `camera.js` classifica provas pelo `dt_aplicacao`:
- `'aplicando'` → entre 0 e `APLICACAO_DURACAO_MIN` (300min) após o horário
- `'em-breve'` → até 60min antes
- `'normal'` → demais

Provas `aplicando` sobem ao topo da lista com badge verde pulsante.

## Padrões do projeto

- **Soft delete:** `UPDATE ... SET ativo = 0` — nunca `DELETE` físico
- **RA de alunos:** pode precisar de sufixo `'M'` para busca no Lyceum (lógica em `processar.php`)
- **Modelos de gabarito:** determinam `n_questoes` e `n_alternativas` — o total de disciplinas no formulário deve respeitar `n_questoes` do modelo selecionado
- **Sem sessão/auth:** sistema aberto, sem login
- **Imagens:** resolução interna fixada em 1240×1754px (`camera.js` constantes `IMG_W`, `IMG_H`)
