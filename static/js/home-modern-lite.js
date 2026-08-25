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

  const revealTargets = document.querySelectorAll(
    '.section-title, .gallery-item, .materials article, .timeline-item, .number, .laptop-stage, .compare, .project-card'
  );

  if (!reducedMotion && 'IntersectionObserver' in window) {
    revealTargets.forEach(el => el.classList.add('fs-reveal'));
    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('fs-visible');
        revealObserver.unobserve(entry.target);
      });
    }, { threshold:0.08, rootMargin:'0px 0px -7% 0px' });
    revealTargets.forEach(el => revealObserver.observe(el));
  } else {
    revealTargets.forEach(el => el.classList.add('fs-visible'));
  }

  if (reducedMotion) return;

  const laptopSection = document.querySelector('.laptop-section');
  const laptopScreen = document.querySelector('.laptop-screen');
  const heroScene = document.querySelector('#scene3D .iso-tilt');
  const showroomScene = document.querySelector('#showroom3D .iso-tilt');
  const projectImages = document.querySelectorAll('.project-media');

  let ticking = false;
  const clamp = (n, min, max) => Math.min(max, Math.max(min, n));

  const updateScrollEffects = () => {
    const vh = window.innerHeight || 900;

    if (laptopSection && laptopScreen) {
      const rect = laptopSection.getBoundingClientRect();
      const start = vh * 0.92;
      const end = -rect.height * 0.15;
      const progress = clamp((start - rect.top) / (start - end), 0, 1);
      const rotate = -96 + (progress * 84);
      const lift = progress * 12;
      const shadow = .28 + (progress * .24);
      laptopScreen.style.setProperty('--screen-rotate', `${rotate.toFixed(2)}deg`);
      laptopScreen.style.setProperty('--screen-lift', `${lift.toFixed(2)}px`);
      laptopScreen.style.setProperty('--screen-shadow-alpha', shadow.toFixed(3));
    }

    if (heroScene) {
      const rect = heroScene.getBoundingClientRect();
      const progress = clamp((vh - rect.top) / (vh + rect.height), 0, 1);
      heroScene.style.setProperty('--scroll-y', `${((progress - .5) * -18).toFixed(2)}px`);
      heroScene.style.setProperty('--scroll-rotate', `${((progress - .5) * 5).toFixed(2)}deg`);
    }

    if (showroomScene) {
      const rect = showroomScene.getBoundingClientRect();
      const progress = clamp((vh - rect.top) / (vh + rect.height), 0, 1);
      showroomScene.style.setProperty('--scroll-y', `${((progress - .5) * -12).toFixed(2)}px`);
      showroomScene.style.setProperty('--scroll-rotate', `${((progress - .5) * -4).toFixed(2)}deg`);
    }

    projectImages.forEach((card, index) => {
      const rect = card.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > vh) return;
      const progress = clamp((vh - rect.top) / (vh + rect.height), 0, 1);
      const offset = ((progress - .5) * (index % 2 === 0 ? -10 : 10));
      card.style.setProperty('--float-y', `${offset.toFixed(2)}px`);
    });

    ticking = false;
  };

  const requestTick = () => {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(updateScrollEffects);
    }
  };

  updateScrollEffects();
  window.addEventListener('scroll', requestTick, { passive:true });
  window.addEventListener('resize', requestTick, { passive:true });
})();
