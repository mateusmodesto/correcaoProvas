<?php
require_once __DIR__ . '/../banco/modelos.php';
require_once __DIR__ . '/../banco/provas.php';

header('Content-Type: application/json; charset=utf-8');

$method = $_SERVER['REQUEST_METHOD'];
$path   = $_GET['rota'] ?? '';

// Remove trailing slash
$path = rtrim($path, '/');

// ── GET /modelos-lista ────────────────────────────────────────────────────────
if ($method === 'GET' && $path === 'modelos-lista') {
    echo json_encode(listar_modelos_completo());
    exit;
}

// ── GET /provas ───────────────────────────────────────────────────────────────
if ($method === 'GET' && $path === 'provas') {
    echo json_encode(listar_provas());
    exit;
}

// ── GET /provas/{id} ──────────────────────────────────────────────────────────
if ($method === 'GET' && preg_match('#^/provas/(\d+)$#', $path, $m)) {
    $prova = buscar_prova((int)$m[1]);
    if ($prova === null) {
        http_response_code(404);
        echo json_encode(['detail' => 'Prova não encontrada']);
    } else {
        echo json_encode($prova);
    }
    exit;
}

// ── POST /provas ──────────────────────────────────────────────────────────────
if ($method === 'POST' && $path === '/provas') {
    $body = json_decode(file_get_contents('php://input'), true);
    $id = upsert_prova(null, $body['descricao'], $body['modelo_id'], $body['gabarito']);
    if ($id === null) {
        http_response_code(500);
        echo json_encode(['detail' => 'Erro ao criar prova']);
    } else {
        http_response_code(201);
        echo json_encode(['id' => $id]);
    }
    exit;
}

// ── PUT /provas/{id} ──────────────────────────────────────────────────────────
if ($method === 'PUT' && preg_match('#^/provas/(\d+)$#', $path, $m)) {
    $body = json_decode(file_get_contents('php://input'), true);
    $id = upsert_prova((int)$m[1], $body['descricao'], $body['modelo_id'], $body['gabarito']);
    if ($id === null) {
        http_response_code(500);
        echo json_encode(['detail' => 'Erro ao atualizar prova']);
    } else {
        echo json_encode(['id' => $id]);
    }
    exit;
}

// ── DELETE /provas/{id} ───────────────────────────────────────────────────────
if ($method === 'DELETE' && preg_match('#^/provas/(\d+)$#', $path, $m)) {
    $ok = deletar_prova((int)$m[1]);
    if (!$ok) {
        http_response_code(404);
        echo json_encode(['detail' => 'Prova não encontrada']);
    } else {
        echo json_encode(['ok' => true]);
    }
    exit;
}

// ── GET /grid?modelo_id=... ───────────────────────────────────────────────────
if ($method === 'GET' && $path === 'grid') {
    $modelo_id = $_GET['modelo_id'] ?? '';
    if ($modelo_id === '') {
        http_response_code(400);
        echo json_encode(['detail' => 'modelo_id obrigatório']);
        exit;
    }
    echo json_encode(buscar_grid_modelo($modelo_id));
    exit;
}

http_response_code(404);
echo json_encode(['detail' => 'Rota não encontrada']);
