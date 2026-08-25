(() => {
  'use strict';

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (n, min, max) => Math.min(max, Math.max(min, n));

  // Fallback das imagens externas para o catálogo do próprio ERP.
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
    '.section-title, .gallery-item, .materials article, .timeline-item, .number, .laptop-stage, .compare, .project-card, .project-footer-cta, .project-heading-note'
  );

  if (!reducedMotion && 'IntersectionObserver' in window) {
    revealTargets.forEach(el => el.classList.add('fs-reveal'));
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('fs-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold:0.08, rootMargin:'0px 0px -7% 0px' });
    revealTargets.forEach(el => observer.observe(el));
  } else {
    revealTargets.forEach(el => el.classList.add('fs-visible'));
  }

  if (reducedMotion) return;

  const laptopSection = document.querySelector('.laptop-section');
  const laptopScreen = document.querySelector('.laptop-screen');
  const laptopBase = document.querySelector('.laptop-base');
  const laptopStage = document.querySelector('.laptop-stage');
  const heroScene = document.querySelector('#scene3D .iso-tilt');
  const showroomScene = document.querySelector('#showroom3D .iso-tilt');
  const projectImages = [...document.querySelectorAll('.project-media img')];

  let ticking = false;

  const updateScrollEffects = () => {
    const vh = window.innerHeight || 900;

    // Notebook: abre ao entrar na viewport e volta exatamente ao rolar para cima.
    if (laptopSection && laptopScreen) {
      const rect = laptopSection.getBoundingClientRect();
      const start = vh * 0.96;
      const finish = vh * 0.18;
      const progress = clamp((start - rect.top) / Math.max(1, start - finish), 0, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const rotate = -96 + (eased * 88); // fecha em -96°, abre até -8°
      const lift = eased * 14;
      const shadow = .22 + (eased * .32);
      const brightness = .70 + (eased * .30);

      laptopScreen.style.setProperty('--screen-rotate', `${rotate.toFixed(2)}deg`);
      laptopScreen.style.setProperty('--screen-lift', `${lift.toFixed(2)}px`);
      laptopScreen.style.setProperty('--screen-shadow-alpha', shadow.toFixed(3));
      laptopScreen.style.setProperty('--screen-brightness', brightness.toFixed(3));
      laptopBase?.style.setProperty('--base-rotate', `${(eased * 1.8).toFixed(2)}deg`);
      laptopStage?.style.setProperty('--laptop-stage-y', `${((1 - eased) * 18).toFixed(2)}px`);
    }

    // Movimento sutil por scroll; sem qualquer efeito baseado no ponteiro/mouse.
    if (heroScene) {
      const rect = heroScene.getBoundingClientRect();
      const p = clamp((vh - rect.top) / (vh + rect.height), 0, 1);
      heroScene.style.setProperty('--scroll-y', `${((p - .5) * -16).toFixed(2)}px`);
      heroScene.style.setProperty('--scroll-rotate', `${((p - .5) * 3.2).toFixed(2)}deg`);
    }

    if (showroomScene) {
      const rect = showroomScene.getBoundingClientRect();
      const p = clamp((vh - rect.top) / (vh + rect.height), 0, 1);
      showroomScene.style.setProperty('--scroll-y', `${((p - .5) * -10).toFixed(2)}px`);
      showroomScene.style.setProperty('--scroll-rotate', `${((p - .5) * -2.4).toFixed(2)}deg`);
    }

    projectImages.forEach((img, index) => {
      const media = img.closest('.project-media');
      if (!media) return;
      const rect = media.getBoundingClientRect();
      if (rect.bottom < -40 || rect.top > vh + 40) return;
      const p = clamp((vh - rect.top) / (vh + rect.height), 0, 1);
      const direction = index % 2 === 0 ? -1 : 1;
      const offset = (p - .5) * 12 * direction;
      media.style.setProperty('--image-y', `${offset.toFixed(2)}px`);
    });

    ticking = false;
  };

  const requestTick = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(updateScrollEffects);
  };

  updateScrollEffects();
  window.addEventListener('scroll', requestTick, { passive:true });
  window.addEventListener('resize', requestTick, { passive:true });
})();
