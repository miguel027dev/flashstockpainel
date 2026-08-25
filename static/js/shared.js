(() => {
  'use strict';
  const navToggle = document.getElementById('navToggle');
  const drawer = document.getElementById('navDrawer');
  const storeBtn = document.querySelector('.store-menu-btn');
  const storeNav = document.querySelector('.store-nav');

  const setBodyLock = locked => document.body.classList.toggle('no-scroll', !!locked);
  function closeAll(){
    drawer?.classList.remove('open');
    navToggle?.classList.remove('active');
    navToggle?.setAttribute('aria-expanded','false');
    storeNav?.classList.remove('open');
    storeBtn?.setAttribute('aria-expanded','false');
    setBodyLock(false);
  }

  navToggle?.addEventListener('click', () => {
    const open = !drawer?.classList.contains('open');
    drawer?.classList.toggle('open', open);
    navToggle.classList.toggle('active', open);
    navToggle.setAttribute('aria-expanded', String(open));
    setBodyLock(open);
  });

  storeBtn?.addEventListener('click', () => {
    const open = !storeNav?.classList.contains('open');
    storeNav?.classList.toggle('open', open);
    storeBtn.setAttribute('aria-expanded', String(open));
  });

  document.addEventListener('keydown', e => { if(e.key === 'Escape') closeAll(); });
  document.querySelectorAll('.nav-drawer a,.store-nav a').forEach(a => a.addEventListener('click', closeAll));

  document.querySelectorAll('a[href^="#"]').forEach(a => a.addEventListener('click', e => {
    const href = a.getAttribute('href');
    if (!href || href === '#') return;
    const target = document.querySelector(href);
    if (!target) return;
    e.preventDefault();
    closeAll();
    target.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'});
  }));

  if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      }
    }, {threshold:.06, rootMargin:'0px 0px -24px'});
    document.querySelectorAll('section .container,.produto-card,.value-card').forEach(el => {
      el.classList.add('reveal');
      observer.observe(el);
    });
  }
})();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    const register = () => navigator.serviceWorker.register('/static/sw.js').catch(() => {});
    if ('requestIdleCallback' in window) requestIdleCallback(register, {timeout:1500});
    else setTimeout(register, 250);
  }, {once:true});
}
