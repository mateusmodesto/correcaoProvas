<?php

// ── Busca modelo completo por id ──────────────────────────────────────────────
function buscar_modelo_gabarito(string $modelo_id): ?array {
    try {
        $db  = _db();
        $sql = "SELECT id, descricao, n_panels, n_alternativas, n_questoes,
                       grid_top_ratio, grid_bottom_ratio,
                       grid_left_ratio, grid_right_ratio,
                       fill_threshold_empty, fill_threshold_filled,
                       disable_auto_top, ativo,
                       ra_n_digits,
                       ra_fill_threshold_empty, ra_fill_threshold_filled,
                       ra_region_top, ra_region_bottom,
                       ra_region_left, ra_region_right
                FROM modelos_gabarito
                WHERE id = ?";
        $st = $db->prepare($sql);
        $st->execute([$modelo_id]);
        $row = $st->fetch(PDO::FETCH_ASSOC);
        if (!$row) return null;
        return [
            'id'                       => (string)  $row['id'],
            'descricao'                => (string)  $row['descricao'],
            'n_panels'                 => (int)     $row['n_panels'],
            'n_alternativas'           => (int)     $row['n_alternativas'],
            'n_questoes'               => (int)     $row['n_questoes'],
            'grid_top_ratio'           => (float)   $row['grid_top_ratio'],
            'grid_bottom_ratio'        => (float)   $row['grid_bottom_ratio'],
            'grid_left_ratio'          => (float)   $row['grid_left_ratio'],
            'grid_right_ratio'         => (float)   $row['grid_right_ratio'],
            'fill_threshold_empty'     => (float)   $row['fill_threshold_empty'],
            'fill_threshold_filled'    => (float)   $row['fill_threshold_filled'],
            'disable_auto_top'         => (bool)    $row['disable_auto_top'],
            'ativo'                    => (bool)    $row['ativo'],
            'ra_n_digits'              => $row['ra_n_digits']              !== null ? (int)   $row['ra_n_digits']              : null,
            'ra_fill_threshold_empty'  => $row['ra_fill_threshold_empty']  !== null ? (float) $row['ra_fill_threshold_empty']  : null,
            'ra_fill_threshold_filled' => $row['ra_fill_threshold_filled'] !== null ? (float) $row['ra_fill_threshold_filled'] : null,
            'ra_region_top'            => $row['ra_region_top']            !== null ? (float) $row['ra_region_top']            : null,
            'ra_region_bottom'         => $row['ra_region_bottom']         !== null ? (float) $row['ra_region_bottom']         : null,
            'ra_region_left'           => $row['ra_region_left']           !== null ? (float) $row['ra_region_left']           : null,
            'ra_region_right'          => $row['ra_region_right']          !== null ? (float) $row['ra_region_right']          : null,
        ];
    } catch (Exception $e) {
        error_log("buscar_modelo_gabarito('$modelo_id') falhou: " . $e->getMessage());
        return null;
    }
}

// ── Lista modelos ativos {id => descricao} ────────────────────────────────────
function listar_modelos(): array {
    try {
        $db = _db();
        $st = $db->query("SELECT id, descricao FROM modelos_gabarito WHERE ativo = 1");
        $result = [];
        foreach ($st->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $result[(string)$row['id']] = (string)$row['descricao'];
        }
        return $result;
    } catch (Exception $e) {
        error_log("listar_modelos falhou: " . $e->getMessage());
        return [];
    }
}

// ── Lista modelos ativos com campos para frontend ─────────────────────────────
function listar_modelos_completo(): array {
    try {
        $db  = _db();
        $sql = "SELECT id, descricao, n_panels, n_alternativas, n_questoes
                FROM modelos_gabarito
                WHERE ativo = 1
                ORDER BY descricao";
        $st = $db->query($sql);
        $rows = $st->fetchAll(PDO::FETCH_ASSOC);
        $result = [];
        foreach ($rows as $row) {
            $result[] = [
                'id'             => (string) $row['id'],
                'descricao'      => (string) $row['descricao'],
                'n_panels'       => (int)    $row['n_panels'],
                'n_alternativas' => (int)    $row['n_alternativas'],
                'n_questoes'     => (int)    $row['n_questoes'],
            ];
        }
        return $result;
    } catch (Exception $e) {
        error_log("listar_modelos_completo falhou: " . $e->getMessage());
        return [];
    }
}

// ── Insert ou update de modelo ────────────────────────────────────────────────
function upsert_modelo_gabarito(string $modelo_id, array $dados): bool {
    try {
        $db  = _db();
        $sql = "MERGE modelos_gabarito AS target
                USING (SELECT ? AS id) AS source ON target.id = source.id
                WHEN MATCHED THEN UPDATE SET
                    descricao                = ?,
                    n_panels                 = ?,
                    n_alternativas           = ?,
                    n_questoes               = ?,
                    grid_top_ratio           = ?,
                    grid_bottom_ratio        = ?,
                    grid_left_ratio          = ?,
                    grid_right_ratio         = ?,
                    fill_threshold_empty     = ?,
                    fill_threshold_filled    = ?,
                    disable_auto_top         = ?,
                    ativo                    = ?,
                    ra_n_digits              = ?,
                    ra_fill_threshold_empty  = ?,
                    ra_fill_threshold_filled = ?,
                    ra_region_top            = ?,
                    ra_region_bottom         = ?,
                    ra_region_left           = ?,
                    ra_region_right          = ?
                WHEN NOT MATCHED THEN INSERT (
                    id, descricao, n_panels, n_alternativas, n_questoes,
                    grid_top_ratio, grid_bottom_ratio, grid_left_ratio, grid_right_ratio,
                    fill_threshold_empty, fill_threshold_filled,
                    disable_auto_top, ativo,
                    ra_n_digits, ra_fill_threshold_empty, ra_fill_threshold_filled,
                    ra_region_top, ra_region_bottom, ra_region_left, ra_region_right
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

        $params = [
            // USING
            $modelo_id,
            // UPDATE
            $dados['descricao'],
            $dados['n_panels'],
            $dados['n_alternativas']           ?? 5,
            $dados['n_questoes']               ?? 0,
            $dados['grid_top_ratio'],
            $dados['grid_bottom_ratio'],
            $dados['grid_left_ratio'],
            $dados['grid_right_ratio'],
            $dados['fill_threshold_empty'],
            $dados['fill_threshold_filled'],
            $dados['disable_auto_top']         ?? false,
            $dados['ativo']                    ?? true,
            $dados['ra_n_digits']              ?? null,
            $dados['ra_fill_threshold_empty']  ?? null,
            $dados['ra_fill_threshold_filled'] ?? null,
            $dados['ra_region_top']            ?? null,
            $dados['ra_region_bottom']         ?? null,
            $dados['ra_region_left']           ?? null,
            $dados['ra_region_right']          ?? null,
            // INSERT
            $modelo_id,
            $dados['descricao'],
            $dados['n_panels'],
            $dados['n_alternativas']           ?? 5,
            $dados['n_questoes']               ?? 0,
            $dados['grid_top_ratio'],
            $dados['grid_bottom_ratio'],
            $dados['grid_left_ratio'],
            $dados['grid_right_ratio'],
            $dados['fill_threshold_empty'],
            $dados['fill_threshold_filled'],
            $dados['disable_auto_top']         ?? false,
            $dados['ativo']                    ?? true,
            $dados['ra_n_digits']              ?? null,
            $dados['ra_fill_threshold_empty']  ?? null,
            $dados['ra_fill_threshold_filled'] ?? null,
            $dados['ra_region_top']            ?? null,
            $dados['ra_region_bottom']         ?? null,
            $dados['ra_region_left']           ?? null,
            $dados['ra_region_right']          ?? null,
        ];

        $db->prepare($sql)->execute($params);
        return true;
    } catch (Exception $e) {
        error_log("upsert_modelo_gabarito('$modelo_id') falhou: " . $e->getMessage());
        return false;
    }
}

// ── Busca grade (modelo_grid) de um modelo ─────────────────────────────
function buscar_grid_modelo(string $modelo_id): array {
    try {
        $db  = _db();
        $sql = "SELECT tipo, indice, posicao_px, label
                FROM modelo_grid
                WHERE modelo_id = ?
                ORDER BY tipo, indice";
        $st = $db->prepare($sql);
        $st->execute([$modelo_id]);
        $rows = $st->fetchAll(PDO::FETCH_ASSOC);
        $horizontal = [];
        $vertical   = [];
        foreach ($rows as $row) {
            $item = [
                'indice'     => (int)   $row['indice'],
                'posicao_px' => (float) $row['posicao_px'],
                'label'      => (string)$row['label'],
            ];
            if ($row['tipo'] === 'H') {
                $horizontal[] = $item;
            } elseif ($row['tipo'] === 'V') {
                $vertical[] = $item;
            }
        }
        return ['horizontal' => $horizontal, 'vertical' => $vertical];
    } catch (Exception $e) {
        error_log("buscar_grid_modelo('$modelo_id') falhou: " . $e->getMessage());
        return ['horizontal' => [], 'vertical' => []];
    }
}

// ── Deleta modelo ─────────────────────────────────────────────────────────────
function deletar_modelo_gabarito(string $modelo_id): bool {
    try {
        $db = _db();
        $st = $db->prepare("DELETE FROM modelos_gabarito WHERE id = ?");
        $st->execute([$modelo_id]);
        return $st->rowCount() > 0;
    } catch (Exception $e) {
        error_log("deletar_modelo_gabarito('$modelo_id') falhou: " . $e->getMessage());
        return false;
    }
}

// ── Endpoint HTTP ─────────────────────────────────────────────────────────────
if (basename($_SERVER['SCRIPT_FILENAME']) === basename(__FILE__)) {
    header('Content-Type: application/json; charset=utf-8');
    $action = $_GET['action'] ?? 'lista';
    $id     = $_GET['id'] ?? null;

    if ($action === 'lista') {
        echo json_encode(listar_modelos_completo());
    } elseif ($action === 'buscar' && $id !== null) {
        $modelo = buscar_modelo_gabarito($id);
        if ($modelo === null) { http_response_code(404); echo json_encode(['detail' => 'Modelo não encontrado']); }
        else echo json_encode($modelo);
    } else {
        http_response_code(400);
        echo json_encode(['detail' => 'Requisição inválida']);
    }
    exit;
}
