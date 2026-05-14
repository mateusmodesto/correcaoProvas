<?php


// ── Parseia gabarito CSV ou JSON ──────────────────────────────────────────────
function _parse_gabarito(string $raw): array {
    $raw = trim($raw);
    if ($raw === '') return [];
    if ($raw[0] === '{') {
        $dict = json_decode($raw, true);
        $result = [];
        for ($i = 1; isset($dict[(string)$i]); $i++) {
            $val = $dict[(string)$i];
            $result[] = is_array($val) ? ($val['resp'] ?? '') : $val;
        }
        return $result;
    }
    return array_values(array_filter(array_map('trim', explode(',', $raw))));
}

// ── Extrai formulas_disc do JSON do gabarito ──────────────────────────────────
function _parse_formulas(string $raw): array {
    $raw = trim($raw);
    if ($raw === '' || $raw[0] !== '{') return [];
    $dict = json_decode($raw, true);
    return is_array($dict['_formulas'] ?? null) ? $dict['_formulas'] : [];
}

// ── Lista provas com modelo associado ─────────────────────────────────────────
function listar_provas(): array {
    try {
        $db  = _db();
        $sql = "SELECT p.id, p.descricao, p.modelo_id, p.gabarito, p.dt_aplicacao, p.dt_termino, m.descricao AS modelo_descricao,
                       m.n_questoes, m.n_alternativas
                FROM cadastro_prova p
                JOIN modelos_gabarito m ON m.id = p.modelo_id
                WHERE m.ativo = 1 AND p.ativo = 1
                ORDER BY p.descricao";
        $st = $db->query($sql);
        $rows = $st->fetchAll(PDO::FETCH_ASSOC);
        $result = [];
        foreach ($rows as $row) {
            $raw = (string)($row['gabarito'] ?? '');
            $result[] = [
                'id'               => (int)    $row['id'],
                'descricao'        => (string) $row['descricao'],
                'modelo_id'        => (string) $row['modelo_id'],
                'modelo_descricao' => (string) $row['modelo_descricao'],
                'n_questoes'       => (int)    $row['n_questoes'],
                'n_alternativas'   => (int)    $row['n_alternativas'],
                'dt_aplicacao'     => $row['dt_aplicacao'] ? (string)$row['dt_aplicacao'] : null,
                'dt_termino'       => $row['dt_termino']  ? (string)$row['dt_termino']  : null,
                'formulas_disc'    => _parse_formulas($raw),
            ];
        }
        return $result;
    } catch (Exception $e) {
        error_log("listar_provas falhou: " . $e->getMessage());
        return [];
    }
}

// ── Busca prova por id ────────────────────────────────────────────────────────
function buscar_prova(int $prova_id): ?array {
    try {
        $db = _db();
        $st = $db->prepare(
            "SELECT id, descricao, modelo_id, gabarito, dt_aplicacao, dt_termino FROM cadastro_prova WHERE id = ?"
        );
        $st->execute([$prova_id]);
        $row = $st->fetch(PDO::FETCH_ASSOC);
        if (!$row) return null;
        $raw = (string)($row['gabarito'] ?? '');
        return [
            'id'           => (int)    $row['id'],
            'descricao'    => (string) $row['descricao'],
            'modelo_id'    => (string) $row['modelo_id'],
            'gabarito'     => _parse_gabarito($raw),
            'gabarito_raw' => $raw,
            'dt_aplicacao' => $row['dt_aplicacao'] ? (string)$row['dt_aplicacao'] : null,
            'dt_termino'   => $row['dt_termino']   ? (string)$row['dt_termino']   : null,
            'formulas_disc'=> _parse_formulas($raw),
        ];
    } catch (Exception $e) {
        error_log("buscar_prova('$prova_id') falhou: " . $e->getMessage());
        return null;
    }
}

// ── Insert ou update de prova ─────────────────────────────────────────────────
// Retorna id da prova ou null em caso de erro.
function upsert_prova(?int $prova_id, string $descricao, string $modelo_id, string $gabarito_csv, ?string $dt_aplicacao, ?string $dt_termino = null): ?int {
    try {
        $db = _db();
        $normDt = function(?string $v): ?string {
            if ($v === null || $v === '') return null;
            $s = str_replace('T', ' ', $v);
            return strlen($s) === 16 ? $s . ':00' : $s;
        };
        $dt  = $normDt($dt_aplicacao);
        $dtf = $normDt($dt_termino);
        if ($prova_id !== null) {
            $st = $db->prepare(
                "UPDATE cadastro_prova SET descricao=?, modelo_id=?, gabarito=?, dt_aplicacao=?, dt_termino=? WHERE id=?"
            );
            $st->execute([$descricao, $modelo_id, $gabarito_csv, $dt, $dtf, $prova_id]);
            return $prova_id;
        } else {
            $st = $db->prepare(
                "INSERT INTO cadastro_prova (descricao, modelo_id, gabarito, dt_aplicacao, dt_termino) OUTPUT INSERTED.id VALUES (?, ?, ?, ?, ?)"
            );
            $st->execute([$descricao, $modelo_id, $gabarito_csv, $dt, $dtf]);
            $row = $st->fetch(PDO::FETCH_ASSOC);
            return (int)$row['id'];
        }
    } catch (Exception $e) {
        error_log("upsert_prova falhou: " . $e->getMessage());
        return null;
    }
}

// ── Deleta prova ──────────────────────────────────────────────────────────────
function deletar_prova(int $prova_id): bool {
    try {
        $db = _db();
        $db->prepare("UPDATE cadastro_prova SET ativo = 0 WHERE id = ?")->execute([$prova_id]);
        return true;
    } catch (Exception $e) {
        error_log("deletar_prova('$prova_id') falhou: " . $e->getMessage());
        return false;
    }
}

// ── Endpoint HTTP ─────────────────────────────────────────────────────────────
if (basename($_SERVER['SCRIPT_FILENAME']) === basename(__FILE__)) {
    header('Content-Type: application/json; charset=utf-8');
    $method = $_SERVER['REQUEST_METHOD'];
    $id     = isset($_GET['id']) ? (int)$_GET['id'] : null;

    if ($method === 'GET' && $id === null) {
        echo json_encode(listar_provas());
    } elseif ($method === 'GET' && $id !== null) {
        $prova = buscar_prova($id);
        if ($prova === null) { http_response_code(404); echo json_encode(['detail' => 'Prova não encontrada']); }
        else echo json_encode($prova);
    } elseif ($method === 'POST') {
        $body = json_decode(file_get_contents('php://input'), true);
        $newId = upsert_prova(null, $body['descricao'], $body['modelo_id'], $body['gabarito'], $body['dt_aplicacao'] ?? null, $body['dt_termino'] ?? null);
        if ($newId === null) { http_response_code(500); echo json_encode(['detail' => 'Erro ao criar prova']); }
        else { http_response_code(201); echo json_encode(['id' => $newId]); }
    } elseif ($method === 'PUT' && $id !== null) {
        $body = json_decode(file_get_contents('php://input'), true);
        $newId = upsert_prova($id, $body['descricao'], $body['modelo_id'], $body['gabarito'], $body['dt_aplicacao'] ?? null, $body['dt_termino'] ?? null);
        if ($newId === null) { http_response_code(500); echo json_encode(['detail' => 'Erro ao atualizar prova']); }
        else echo json_encode(['id' => $newId]);
    } elseif ($method === 'DELETE' && $id !== null) {
        $ok = deletar_prova($id);
        if (!$ok) { http_response_code(500); echo json_encode(['detail' => 'Erro ao deletar prova']); }
        else echo json_encode(['ok' => true]);
    } else {
        http_response_code(400);
        echo json_encode(['detail' => 'Requisição inválida']);
    }
    exit;
}
