(() => {
  'use strict';

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Se a imagem original externa não responder, usa a foto do produto do próprio ERP.
  document.querySelectorAll('img.template-visual').forEach(img => {
    img.addEventListener('error', () => {
      const fallback = img.dataset.fallbackSrc;
      if (fallback && img.src !== fallback) {
        img.classList.add('is-fallback');
        img.removeAttribute('data-fallback-src');
        img.src = fallback;
        return;
      }
      if (!img.dataset.localFallbackApplied) {
        img.dataset.localFallbackApplied = '1';
        img.src = '/static/store/image-fallback.svg';
      }
    }, { once:false });
  });

  // Reveal leve e executado uma única vez por elemento.
  const revealTargets = document.querySelectorAll(
    '.section-title, .gallery-item, .materials article, .timeline-item, .number, .laptop-stage, .compare'
  );

  if (!reducedMotion && 'IntersectionObserver' in window) {
    revealTargets.forEach(el => el.classList.add('fs-reveal'));
    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('fs-visible');
        revealObserver.unobserve(entry.target);
      });
    }, { threshold:0.09, rootMargin:'0px 0px -7% 0px' });
    revealTargets.forEach(el => revealObserver.observe(el));
  } else {
    revealTargets.forEach(el => el.classList.add('fs-visible'));
  }

  // Tilt sutil apenas em mouse/trackpad. Não roda em celular e usa requestAnimationFrame.
  const scene = document.querySelector('#scene3D');
  const tilt = scene?.querySelector('.iso-tilt');
  const finePointer = window.matchMedia('(hover:hover) and (pointer:fine)').matches;
  if (scene && tilt && finePointer && !reducedMotion) {
    let raf = 0;
    const renderTilt = (x, y) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        tilt.style.setProperty('--tilt-x', `${x.toFixed(2)}deg`);
        tilt.style.setProperty('--tilt-y', `${y.toFixed(2)}deg`);
      });
    };
    scene.addEventListener('pointermove', event => {
      const r = scene.getBoundingClientRect();
      const px = (event.clientX - r.left) / r.width - .5;
      const py = (event.clientY - r.top) / r.height - .5;
      renderTilt(px * 3.2, py * -2.4);
    }, { passive:true });
    scene.addEventListener('pointerleave', () => renderTilt(0, 0), { passive:true });
  }
})();
