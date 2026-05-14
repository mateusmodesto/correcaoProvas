<?php

header('Content-Type: application/json; charset=utf-8');

$raw = isset($_GET['ras']) ? trim($_GET['ras']) : '';
try{
    if ($raw === '') { echo json_encode([]); exit; }

    $ras = [];
    foreach (explode(',', $raw) as $v) {
        $v = (string)trim($v);
        if ($v !== '' && ctype_alnum($v)) { $ras[] = $v; }
    }
    $ras = array_values(array_unique($ras));
    if (!$ras) { echo json_encode([]); exit; }
} catch (Exception $e) {
    error_log('nomes_alunos.php parse ras erro: ' . $e->getMessage());
    echo json_encode(['_erro' => 'Erro ao processar RAs']);
    exit;
}
try {
    $placeholders = implode(',', array_fill(0, count($ras), '?'));
    $st = $db->prepare(
        "SELECT ALUNO, NOME_COMPL FROM TB_ALUNO WHERE ALUNO IN ($placeholders)"
    );
    $st->execute($ras);
    $rows = $st->fetchAll(PDO::FETCH_ASSOC);
    $result = [];
    foreach ($rows as $r) {
        $result[(string)$r['ALUNO']] = (string)$r['NOME_COMPL'];
    }
    echo json_encode($result);
} catch (Exception $e) {
    error_log('nomes_alunos.php erro: ' . $e->getMessage());
    echo json_encode(['_erro' => $e->getMessage()]);
}
