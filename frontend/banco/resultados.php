<?php


header('Content-Type: application/json; charset=utf-8');

$prova_id = isset($_GET['prova_id']) ? (int)$_GET['prova_id'] : null;
$aluno    = isset($_GET['aluno'])    ? trim($_GET['aluno'])    : null;

// ── GET ?prova_id=X&aluno=Y → resultado completo do aluno ────────────────────
if ($prova_id && $aluno) {
    try {
        $db = _db();
        $st = $db->prepare(
            "SELECT TOP 1 id, ALUNO, prova_id, data_processamento, acertos, erros, resultado
             FROM gabaritos_processados
             WHERE prova_id = ? AND ALUNO = ?
             ORDER BY data_processamento DESC"
        );
        $st->execute([$prova_id, $aluno]);
        $row = $st->fetch(PDO::FETCH_ASSOC);
        if (!$row) { http_response_code(404); echo json_encode(['detail' => 'Não encontrado']); exit; }
        $row['resultado'] = json_decode($row['resultado'], true);
        echo json_encode($row);
    } catch (Exception $e) {
        http_response_code(500); echo json_encode(['detail' => $e->getMessage()]);
    }
    exit;
}

// ── GET ?prova_id=X → lista alunos da prova ───────────────────────────────────
if ($prova_id) {
    try {
        $db = _db();
        $st = $db->prepare(
            "SELECT g.ALUNO, MAX(g.data_processamento) AS data_processamento,
                    MAX(g.acertos) AS acertos, MAX(g.erros) AS erros
             FROM gabaritos_processados g
             WHERE g.prova_id = ?
             GROUP BY g.ALUNO
             ORDER BY g.ALUNO"
        );
        $st->execute([$prova_id]);
        $rows = $st->fetchAll(PDO::FETCH_ASSOC);
        echo json_encode(array_map(function($r) {
            return [
                'aluno'               => (string) $r['ALUNO'],
                'data_processamento'  => (string) $r['data_processamento'],
                'acertos'             => (int)    $r['acertos'],
                'erros'               => (int)    $r['erros'],
            ];
        }, $rows));
    } catch (Exception $e) {
        http_response_code(500); echo json_encode(['detail' => $e->getMessage()]);
    }
    exit;
}

// ── GET → lista provas com contagem de alunos ────────────────────────────────
try {
    $db = _db();
    $st = $db->query(
        "SELECT p.id, p.descricao, p.gabarito,
                COUNT(DISTINCT g.ALUNO) AS total_alunos,
                MAX(g.data_processamento) AS ultima_correcao
         FROM cadastro_prova p
         LEFT JOIN gabaritos_processados g ON g.prova_id = p.id
         WHERE p.ativo = 1
         GROUP BY p.id, p.descricao, p.gabarito
         ORDER BY MAX(g.data_processamento) DESC, p.descricao"
    );
    $rows = $st->fetchAll(PDO::FETCH_ASSOC);
    echo json_encode(array_map(function($r) {
        $raw = (string)($r['gabarito'] ?? '');
        $formulas = [];
        if ($raw && $raw[0] === '{') {
            $dict = json_decode($raw, true);
            $formulas = is_array($dict['_formulas'] ?? null) ? $dict['_formulas'] : [];
        }
        return [
            'id'              => (int)    $r['id'],
            'descricao'       => (string) $r['descricao'],
            'total_alunos'    => (int)    $r['total_alunos'],
            'ultima_correcao' => $r['ultima_correcao'] ? (string)$r['ultima_correcao'] : null,
            'formulas_disc'   => $formulas,
        ];
    }, $rows));
} catch (Exception $e) {
    http_response_code(500); echo json_encode(['detail' => $e->getMessage()]);
}
