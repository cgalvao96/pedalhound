/* PedalHound – main.js */

(function () {
  'use strict';

  /* ── Nav active link ── */
  const path = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a, .mobile-nav-panel a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path || (path === '' && href === 'index.html')) {
      a.classList.add('active');
    }
  });

  /* ── Hamburger / mobile nav ── */
  const hamburger  = document.querySelector('.hamburger');
  const mobileNav  = document.querySelector('.mobile-nav');
  const mobileOverlay = mobileNav;

  if (hamburger && mobileNav) {
    hamburger.addEventListener('click', () => {
      const open = hamburger.classList.toggle('open');
      mobileNav.classList.toggle('open', open);
      document.body.style.overflow = open ? 'hidden' : '';
    });
    mobileOverlay.addEventListener('click', e => {
      if (e.target === mobileOverlay) closeMobile();
    });
    mobileNav.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMobile));
  }

  function closeMobile() {
    hamburger && hamburger.classList.remove('open');
    mobileNav && mobileNav.classList.remove('open');
    document.body.style.overflow = '';
  }

  /* ── Scroll-to-top ── */
  const scrollBtn = document.getElementById('scroll-top');
  if (scrollBtn) {
    window.addEventListener('scroll', () => {
      scrollBtn.classList.toggle('show', window.scrollY > 400);
    }, { passive: true });
    scrollBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  }

  /* ── Reviews filter + search ── */
  const filterBtns  = document.querySelectorAll('.filter-btn');
  const reviewCards = document.querySelectorAll('.review-card[data-category]');
  const searchInput = document.querySelector('.search-bar input');
  const noResults   = document.querySelector('.no-results');

  let activeFilter = 'all';
  let searchTerm   = '';

  function applyFilters() {
    let visible = 0;
    reviewCards.forEach(card => {
      const cat   = card.dataset.category;
      const title = card.querySelector('.review-card-title').textContent.toLowerCase();
      const matchCat  = activeFilter === 'all' || cat === activeFilter;
      const matchSearch = title.includes(searchTerm);
      const show = matchCat && matchSearch;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    if (noResults) noResults.classList.toggle('show', visible === 0);
  }

  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', () => {
      searchTerm = searchInput.value.toLowerCase().trim();
      applyFilters();
    });
  }

  /* ── Contact form ── */
  const contactForm = document.getElementById('contact-form');
  const formSuccess = document.querySelector('.form-success');
  if (contactForm) {
    contactForm.addEventListener('submit', e => {
      e.preventDefault();
      const btn = contactForm.querySelector('button[type="submit"]');
      btn.disabled = true;
      btn.textContent = 'Sending…';
      setTimeout(() => {
        contactForm.style.display = 'none';
        if (formSuccess) formSuccess.classList.add('show');
      }, 900);
    });
  }

  /* ── Newsletter form ── */
  const nlForm = document.querySelector('.newsletter-form');
  if (nlForm) {
    nlForm.addEventListener('submit', e => {
      e.preventDefault();
      const input = nlForm.querySelector('input');
      const btn   = nlForm.querySelector('button');
      if (!input.value.trim()) return;
      btn.disabled = true;
      btn.textContent = '✓ Subscribed!';
      input.value = '';
      setTimeout(() => { btn.disabled = false; btn.textContent = 'Subscribe'; }, 3000);
    });
  }

  /* ── Animate cards on scroll (Intersection Observer) ── */
  const animEls = document.querySelectorAll('.review-card, .cat-card, .value-card, .team-card');
  if ('IntersectionObserver' in window && animEls.length) {
    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

    animEls.forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      el.style.transition = 'opacity 0.45s ease, transform 0.45s ease, border-color 0.22s ease, box-shadow 0.22s ease';
      io.observe(el);
    });
  }

})();
