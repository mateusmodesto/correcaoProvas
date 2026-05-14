<?php
require_once __DIR__ . '/../../conexao.php';

header('Content-Type: application/json; charset=utf-8');

// Lote: ?ras=123,456,789
if (isset($_GET['ras']) && $_GET['ras'] !== '') {
    $raw = trim($_GET['ras']);
    $ras = [];
    foreach (explode(',', $raw) as $v) {
        $v = (string)trim($v);
        if ($v !== '' && ctype_alnum($v)) { $ras[] = $v; }
    }
    $ras = array_values(array_unique($ras));
    if (!$ras) { echo json_encode([]); exit; }
    try {
        $db = Conexao::getConnection('tb_');
        $ph = implode(',', array_fill(0, count($ras), '?'));
        $st = $db->prepare(
            "SELECT ALUNO, TURMA
             FROM tb_MATRICULA
             WHERE ALUNO IN ($ph)
               AND SIT_MATRICULA = 'Matriculado'
               AND TURMA NOT LIKE 'REM-%'
               AND TURMA NOT LIKE '%COORD%'
               AND TURMA NOT LIKE 'EST-%'
               AND TURMA NOT LIKE 'DD-%'"
        );
        $st->execute(array_values($ras));
        $rows = $st->fetchAll(PDO::FETCH_ASSOC);
        // por aluno, prefere turma mais curta
        $map = [];
        foreach ($rows as $r) {
            $a = (string)$r['ALUNO'];
            $t = (string)$r['TURMA'];
            if (!isset($map[$a]) || strlen($t) < strlen($map[$a])) $map[$a] = $t;
        }
        echo json_encode($map);
    } catch (Exception $e) {
        error_log("turma_aluno(lote) falhou: " . $e->getMessage());
        echo json_encode([]);
    }
    exit;
}

// Individual: ?ra=123
$ra = isset($_GET['ra']) ? trim($_GET['ra']) : '';
if ($ra === '') {
    http_response_code(400);
    echo json_encode(['detail' => 'RA obrigatório']);
    exit;
}

try {
    $db = Conexao::getConnection('tb_');

    $st = $db->prepare(
        "SELECT DISTINCT TURMA
         FROM tb_MATRICULA
         WHERE ALUNO = ?
           AND SIT_MATRICULA = 'Matriculado'
           AND TURMA NOT LIKE 'REM-%'
           AND TURMA NOT LIKE '%COORD%'
           AND TURMA NOT LIKE 'EST-%'
           AND TURMA NOT LIKE 'DD-%'"
    );
    $st->execute([$ra]);
    $rows = $st->fetchAll(PDO::FETCH_COLUMN);

    if (!$rows) {
        echo json_encode(['turma' => null]);
    } else {
        usort($rows, function($a, $b) { return strlen($a) - strlen($b); });
        echo json_encode(['turma' => $rows[0]]);
    }
} catch (Exception $e) {
    error_log("turma_aluno('$ra') falhou: " . $e->getMessage());
    http_response_code(500);
    echo json_encode(['detail' => $e->getMessage()]);
}
