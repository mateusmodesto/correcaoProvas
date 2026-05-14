<?php
header('Content-Type: application/json; charset=utf-8');

$faculdade = $_GET['faculdade'] ?? '';
$q         = trim($_GET['q'] ?? '');

if (!$faculdade || strlen($q) < 2) {
    echo json_encode([]);
    exit;
}


if (!in_array($faculdade, $allowed, true)) {
    echo json_encode([]);
    exit;
}

try {
    $db  = Conexao::getConnection('lyceum');
    $st  = $db->prepare(
        "SELECT DISTINCT NOME
         FROM tb_disciplina
         WHERE ATIVA = 'S'
           AND FACULDADE = ?
           AND (NOME LIKE ?)"
    );
    $like = '%' . $q . '%';
    $st->execute([$faculdade, $like, $like]);
    $rows = $st->fetchAll(PDO::FETCH_ASSOC);
    $result = [];
    foreach ($rows as $r) {
        $result[] = [
            'nome'       => (string) $r['NOME']
        ];
    }
    echo json_encode($result);
} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()]);
}
