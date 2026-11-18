/* Diseño con barra lateral: menú móvil, menú compacto, tema claro/oscuro, reloj,
   enlace activo y campana de notificaciones con actualización periódica (Fetch API). */
(function () {
  'use strict';
  var html = document.documentElement;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } }
  function leer(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ---------- Tema ---------- */
  var mq = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
  function aplicarTema(pref) {
    var oscuro = pref === 'oscuro' || (pref === 'sistema' && mq && mq.matches);
    html.setAttribute('data-bs-theme', oscuro ? 'dark' : 'light');
    document.querySelectorAll('[data-tema] i').forEach(function (i) {
      i.className = oscuro ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
    });
    document.querySelectorAll('input[name="pref-tema"]').forEach(function (r) { r.checked = r.value === pref; });
  }
  window.CitasTema = function (pref) { guardar('cm-tema', pref); aplicarTema(pref); };
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { aplicarTema(leer('cm-tema', 'sistema')); });

  /* ---------- Menú compacto ---------- */
  window.CitasCompacto = function (on) {
    html.classList.toggle('sidebar-compacto', on);
    guardar('cm-compacto', on ? '1' : '0');
    document.querySelectorAll('input[name="pref-compacto"]').forEach(function (c) { c.checked = on; });
    tooltipsMenu();
  };
  var tips = [];
  function tooltipsMenu() {
    tips.forEach(function (t) { t.dispose(); }); tips = [];
    if (!window.bootstrap || !html.classList.contains('sidebar-compacto')) return;
    document.querySelectorAll('.sidebar .nav-link[title]').forEach(function (el) {
      tips.push(new bootstrap.Tooltip(el, { placement: 'right', trigger: 'hover' }));
    });
  }

  /* ---------- Notificaciones ---------- */
  var badge, lista, ultimo = null;
  function pintarBadge(n) {
    if (!badge) return;
    badge.textContent = n > 99 ? '99+' : n;
    badge.classList.toggle('d-none', !n);
    document.querySelectorAll('.sidebar .nav-badge').forEach(function (b) {
      if (b.closest('a') && /notificaciones/.test(b.closest('a').getAttribute('href'))) {
        b.textContent = n; b.style.display = n ? '' : 'none';
      }
    });
  }
  function pintarLista(items) {
    if (!lista) return;
    if (!items.length) {
      lista.innerHTML = '<div class="notif-vacio"><i class="fa-regular fa-bell-slash"></i>No tiene notificaciones.</div>';
      return;
    }
    lista.innerHTML = items.map(function (n) {
      return '<form method="post" action="' + esc(n.abrir) + '"><input type="hidden" name="_csrf" value="' + esc(csrf) + '">' +
        '<button type="submit" class="notif-item ' + (n.leida ? '' : 'no-leida') + '">' +
        '<span class="notif-ic ' + esc(n.clase) + '"><i class="fa-solid ' + esc(n.icono) + '"></i></span>' +
        '<span class="notif-body"><strong>' + esc(n.titulo) + '</strong><span>' + esc(n.mensaje) + '</span><small>' +
        esc(n.fecha) + '</small></span></button></form>';
    }).join('');
  }
  function toast(n) {
    var zona = document.getElementById('toastZone');
    if (!zona || !window.bootstrap) return;
    var el = document.createElement('div');
    el.className = 'toast align-items-center border-0 shadow';
    el.setAttribute('role', 'status');
    el.innerHTML = '<div class="toast-header"><span class="notif-ic ' + esc(n.clase) + ' me-2" style="width:26px;height:26px">' +
      '<i class="fa-solid ' + esc(n.icono) + ' small"></i></span><strong class="me-auto">' + esc(n.titulo) +
      '</strong><button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Cerrar"></button></div>' +
      '<div class="toast-body">' + esc(n.mensaje) + '</div>';
    zona.appendChild(el);
    el.addEventListener('hidden.bs.toast', function () { el.remove(); });
    new bootstrap.Toast(el, { delay: 6000 }).show();
  }
  function consultar() {
    if (!lista || document.hidden) return;
    fetch(lista.dataset.resumen, { headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        var nuevas = d.items.filter(function (n) { return !n.leida && ultimo !== null && n.id > ultimo; });
        if (nuevas.length) { badge.classList.add('pulso'); setTimeout(function () { badge.classList.remove('pulso'); }, 2100); }
        nuevas.slice(0, 3).forEach(toast);
        if (d.items.length) ultimo = Math.max(ultimo || 0, d.items[0].id);
        else if (ultimo === null) ultimo = 0;
        pintarBadge(d.no_leidas);
        pintarLista(d.items);
      })
      .catch(function () { /* sin conexión: se reintenta en el siguiente ciclo */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    aplicarTema(leer('cm-tema', 'sistema'));
    document.querySelectorAll('input[name="pref-compacto"]').forEach(function (c) { c.checked = html.classList.contains('sidebar-compacto'); });
    tooltipsMenu();

    document.addEventListener('click', function (e) {
      var t = e.target.closest('[data-sidebar-toggle]');
      if (t) { document.body.classList.toggle('sidebar-abierto'); return; }
      if (e.target.closest('[data-compacto]')) { window.CitasCompacto(!html.classList.contains('sidebar-compacto')); return; }
      if (e.target.closest('[data-tema]')) {
        window.CitasTema(html.getAttribute('data-bs-theme') === 'dark' ? 'claro' : 'oscuro');
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') document.body.classList.remove('sidebar-abierto');
    });
    document.addEventListener('change', function (e) {
      if (e.target.name === 'pref-tema') window.CitasTema(e.target.value);
      if (e.target.name === 'pref-compacto') window.CitasCompacto(e.target.checked);
    });

    // Enlace activo: el más específico que coincide con la ruta (y la pestaña ?tab=)
    var mejor = null, largo = -1, actual = location.pathname + location.search;
    document.querySelectorAll('.sidebar .sb-nav .nav-link').forEach(function (a) {
      var href = a.getAttribute('href') || '', ruta = href.split('?')[0];
      var coincide = href === actual ? 1000 : (location.pathname === ruta || location.pathname.indexOf(ruta + '/') === 0) && href.indexOf('?') === -1 ? ruta.length : -1;
      if (coincide > largo) { largo = coincide; mejor = a; }
    });
    if (mejor) mejor.classList.add('active');

    // Reloj de la barra superior
    var reloj = document.querySelector('[data-reloj]');
    if (reloj) setInterval(function () {
      var d = new Date();
      reloj.textContent = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    }, 15000);

    // Campana
    badge = document.querySelector('[data-notif-count]');
    lista = document.querySelector('[data-notif-list]');
    var primera = lista && lista.querySelector('form');
    var m = primera && /\/notificaciones\/(\d+)\//.exec(primera.getAttribute('action'));
    ultimo = m ? parseInt(m[1], 10) : 0;
    if (lista) {
      setInterval(consultar, 45000);
      document.addEventListener('visibilitychange', function () { if (!document.hidden) consultar(); });
    }
    var todas = document.querySelector('[data-leer-todas]');
    if (todas) todas.addEventListener('click', function () {
      fetch(todas.dataset.url, { method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRF-Token': csrf, 'X-Requested-With': 'fetch' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function () {
          pintarBadge(0);
          lista.querySelectorAll('.no-leida').forEach(function (el) { el.classList.remove('no-leida'); });
        })
        .catch(function () { location.href = todas.dataset.url.replace('/leer-todas', ''); });
    });
  });
})();
