(() => {
  'use strict';
  const compare = document.querySelector('.compare');
  const range = document.querySelector('.compare-range');
  if (compare && range) {
    const update = () => compare.style.setProperty('--reveal', `${range.value}%`);
    range.addEventListener('input', update, {passive:true});
    update();
  }

  if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const stepObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('active');
          stepObserver.unobserve(entry.target);
        }
      });
    }, {threshold:.14, rootMargin:'0px 0px -10%'});
    document.querySelectorAll('.step').forEach(step => stepObserver.observe(step));
  } else {
    document.querySelectorAll('.step').forEach(step => step.classList.add('active'));
  }

  const lightbox = document.getElementById('lightbox');
  const inner = document.getElementById('lightboxInner');
  const caption = document.getElementById('lightboxCaption');
  const gallery = document.querySelector('.gallery-grid');

  gallery?.addEventListener('click', e => {
    const img = e.target.closest('.gallery-item img');
    if (!img || !lightbox || !inner) return;
    inner.querySelector('img')?.remove();
    const clone = new Image();
    clone.src = img.currentSrc || img.src;
    clone.alt = img.alt || '';
    clone.decoding = 'async';
    inner.prepend(clone);
    if (caption) caption.textContent = img.alt || '';
    lightbox.classList.add('active');
  });

  const close = () => lightbox?.classList.remove('active');
  document.getElementById('lightboxClose')?.addEventListener('click', close);
  lightbox?.addEventListener('click', e => { if (e.target === lightbox) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
})();
