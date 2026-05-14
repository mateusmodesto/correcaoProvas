const PAGES = ['home', 'camera', 'cadastro', 'resultados'];

function navigate(page) {
  PAGES.forEach(id => {
    const el = document.getElementById(`page-${id}`);
    el.classList.toggle('active', id === page);
  });

  if (page === 'camera') {
    initCamera();
  } else {
    stopStream();
    if (page === 'cadastro')   initCadastro();
    if (page === 'resultados') initResultados();
  }
}
