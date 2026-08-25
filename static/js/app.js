document.addEventListener('DOMContentLoaded', () => {
  const token = document.body.dataset.csrf || '';
  document.querySelectorAll('form').forEach(f => {
    if ((f.method || 'get').toLowerCase() === 'post' && !f.querySelector('input[name="csrf_token"]')) {
      const i = document.createElement('input');
      i.type = 'hidden';
      i.name = 'csrf_token';
      i.value = token;
      f.prepend(i);
    }
  });

  const side = document.querySelector('.sidebar');
  const overlay = document.querySelector('.mobile-overlay');
  const openMenu = () => {
    side?.classList.add('open');
    overlay?.classList.add('open');
    document.body.style.overflow = 'hidden';
  };
  const closeMenu = () => {
    side?.classList.remove('open');
    overlay?.classList.remove('open');
    document.body.style.overflow = '';
  };
  document.querySelector('.menu-btn')?.addEventListener('click', openMenu);
  document.querySelector('.mobile-menu-open')?.addEventListener('click', openMenu);
  document.querySelector('.sidebar-close')?.addEventListener('click', closeMenu);
  overlay?.addEventListener('click', closeMenu);
  document.querySelectorAll('.nav-item').forEach(el => el.addEventListener('click', () => {
    if (window.innerWidth <= 860) closeMenu();
  }));

  const modal = document.getElementById('searchModal');
  const searchInput = document.getElementById('globalSearch');
  const results = document.getElementById('searchResults');
  const closeSearchBtn = document.querySelector('.search-close');

  function openSearch() {
    if (!modal) return;
    modal.classList.add('open');
    setTimeout(() => searchInput?.focus(), 30);
  }
  function closeSearch() {
    modal?.classList.remove('open');
  }

  document.querySelector('.search-trigger')?.addEventListener('click', openSearch);
  document.querySelector('.mobile-search-open')?.addEventListener('click', openSearch);
  closeSearchBtn?.addEventListener('click', closeSearch);
  modal?.addEventListener('click', e => { if (e.target === modal) closeSearch(); });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openSearch();
    }
    if (e.key === 'Escape') {
      closeSearch();
      closeMenu();
    }
  });

  let timer;
  searchInput?.addEventListener('input', () => {
    clearTimeout(timer);
    const q = searchInput.value.trim();
    if (q.length < 2) {
      results.innerHTML = '<div class="empty">Digite pelo menos 2 caracteres.</div>';
      return;
    }
    timer = setTimeout(async () => {
      try {
        const r = await fetch('/api/search?q=' + encodeURIComponent(q));
        const data = await r.json();
        results.innerHTML = data.length
          ? data.map(x => `
            <a class="search-result" href="${x.url}">
              <span><b>${x.title}</b><br><small>${x.subtitle || ''}</small></span>
              <small>${x.type}</small>
            </a>`).join('')
          : '<div class="empty">Nada encontrado.</div>';
      } catch (err) {
        results.innerHTML = '<div class="empty">Erro ao pesquisar.</div>';
      }
    }, 180);
  });

  // Em telas pequenas, transforma tabelas administrativas em cards legíveis.
  document.querySelectorAll('.table-wrap table').forEach(table => {
    const labels = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
    if (!labels.length) return;
    table.querySelectorAll('tbody tr').forEach(row => {
      Array.from(row.children).forEach((cell, index) => {
        if (cell.tagName !== 'TD' || cell.hasAttribute('colspan')) return;
        if (!cell.dataset.label) cell.dataset.label = labels[index] || '';
      });
    });
  });

  // Ajuda a indicar a seção ativa no dock sem criar links públicos para o admin.
  const dock = document.querySelector('.mobile-admin-dock');
  if (dock) {
    const active = dock.querySelector('[href="/dashboard"]');
    if (active && location.pathname !== '/dashboard') active.classList.remove('active');
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js').catch(() => {}));
  }
});

function addOrderItem() {
  const tpl = document.getElementById('orderItemTemplate');
  const list = document.getElementById('orderItems');
  if (tpl && list) list.insertAdjacentHTML('beforeend', tpl.innerHTML);
}

function removeRow(btn) {
  btn.closest('.item-row')?.remove();
}
