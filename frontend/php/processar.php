<?php
header('Content-Type: application/json; charset=utf-8');
require_once __DIR__ . '/../../conexao.php';

$url = 'http://localhost:5041/api/v1/processar-prova';

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HEADER, true);
curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);

$post = $_POST;
foreach ($_FILES as $key => $f) {
    if (is_array($f['tmp_name'])) {
        foreach ($f['tmp_name'] as $i => $tmp) {
            $post[$key . "[$i]"] = new CURLFile($tmp, $f['type'][$i], $f['name'][$i]);
        }
    } else {
        $post[$key] = new CURLFile($f['tmp_name'], $f['type'], $f['name']);
    }
}
curl_setopt($ch, CURLOPT_POSTFIELDS, $post);

$raw     = curl_exec($ch);
$curlErr = curl_error($ch);
$hdrSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$hdrRaw  = substr($raw, 0, $hdrSize);
$body    = substr($raw, $hdrSize);
curl_close($ch);

if ($curlErr) {
    http_response_code(502);
    echo json_encode(['detail' => 'cURL: ' . $curlErr]);
    exit;
}

foreach (explode("\r\n", $hdrRaw) as $h) {
    if (preg_match('/^(Content-Type|HTTP\/)/i', $h)) header($h);
}

if ($body === false) {
    echo json_encode(['detail' => 'Backend indisponível']);
    exit;
}

// Normaliza RA: se foi salvo sem M mas existe com M no Lyceum, atualiza no banco
$data = json_decode($body, true);
if (is_array($data) && isset($data['dados_aluno']['ra'])) {
    $ra = (string)$data['dados_aluno']['ra'];
    if ($ra !== '' && !preg_match('/M$/i', $ra)) {
        $raComM = $ra . 'M';
        try {
            $lyceum = Conexao::getConnection('lyceum');
            $st = $lyceum->prepare(
                "SELECT COUNT(*) FROM TB_ALUNO WHERE ALUNO = ?"
            );
            $st->execute([$raComM]);
            if ((int)$st->fetchColumn() > 0) {
                // RA com M existe no Lyceum — atualiza registros sem M no banco
                $up = $anchieta->prepare(
                    "UPDATE gabaritos_processados
                     SET ALUNO = ?
                     WHERE ALUNO = ?"
                );
                $up->execute([$raComM, $ra]);
                // atualiza o JSON retornado para refletir o RA correto
                $data['dados_aluno']['ra'] = $raComM;
                $body = json_encode($data);
            }
        } catch (Exception $e) {
            error_log('processar.php normaliza RA erro: ' . $e->getMessage());
        }
    }
}

echo $body;
