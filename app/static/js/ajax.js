/* Cliente-servidor dinámico con Fetch API:
   1) Listas con búsqueda/filtros en vivo  (form[data-live][data-target])
   2) Disponibilidad de horarios por profesional y fecha (form.js-agenda-form)            */
(function () {
  'use strict';
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  function debounce(fn, ms) {
    var t;
    return function () { var a = arguments, s = this; clearTimeout(t); t = setTimeout(function () { fn.apply(s, a); }, ms); };
  }

  /* ---------- 1) Listas dinámicas ---------- */
  function initLive(form) {
    var target = document.querySelector(form.dataset.target);
    if (!target) return;
    var url = form.getAttribute('action') || location.pathname;
    var run = function () {
      var params = new URLSearchParams();
      new FormData(form).forEach(function (v, k) { if (k !== '_csrf' && v !== '') params.append(k, v); });
      var qs = params.toString();
      var p = new URLSearchParams(params); p.set('partial', '1');
      target.classList.add('loading');
      fetch(url + '?' + p.toString(), { headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) {
          target.innerHTML = html;
          history.replaceState(null, '', qs ? '?' + qs : location.pathname);
          target.dispatchEvent(new CustomEvent('partial:updated', { bubbles: true }));
        })
        .catch(function () {
          target.innerHTML = '<div class="empty-state"><i class="fa-solid fa-triangle-exclamation"></i>No se pudo actualizar la lista. Recargue la página.</div>';
        })
        .finally(function () { target.classList.remove('loading'); });
    };
    form.addEventListener('input', debounce(run, 300));
    form.addEventListener('change', run);
    form.addEventListener('submit', function (e) {
      if (e.submitter && e.submitter.hasAttribute('data-export')) return;   // exportar CSV: envío normal
      e.preventDefault(); run();
    });
    var limpiar = form.querySelector('[data-clear]');
    if (limpiar) limpiar.addEventListener('click', function () {
      form.querySelectorAll('input:not([type=hidden]),select').forEach(function (i) { i.value = ''; });
      run();
    });
  }

  /* ---------- 2) Disponibilidad de horarios ---------- */
  function initAgenda(form) {
    var el = function (n) { return form.elements[n]; };
    var horaSel = el('hora') || el('nueva_hora'), fechaIn = el('fecha') || el('nueva_fecha');
    var profIn = el('profesional_id'), pacIn = el('paciente_id');
    var msg = form.querySelector('.slot-msg');
    if (!horaSel || !fechaIn) return;
    var actual = horaSel.dataset.actual || '';
    var cargar = function () {
      var prof = profIn ? profIn.value : form.dataset.profesional;
      if (!prof || !fechaIn.value) {
        horaSel.innerHTML = '<option value="">-- Elija profesional y fecha --</option>';
        if (msg) msg.textContent = '';
        return;
      }
      var q = new URLSearchParams({ profesional_id: prof, fecha: fechaIn.value });
      if (pacIn && pacIn.value) q.set('paciente_id', pacIn.value);
      if (form.dataset.excluir) q.set('excluir_cita', form.dataset.excluir);
      horaSel.disabled = true;
      fetch('/api/disponibilidad?' + q.toString(), { credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          horaSel.innerHTML = '';
          if (!d.slots.length) horaSel.add(new Option('Sin horarios disponibles', ''));
          else {
            horaSel.add(new Option('-- Seleccione hora --', ''));
            d.slots.forEach(function (s) { horaSel.add(new Option(s, s, false, s === actual)); });
          }
          if (msg) { msg.textContent = d.mensaje; msg.className = 'slot-msg ' + (d.slots.length ? 'ok' : 'bad'); }
        })
        .catch(function () {
          if (msg) { msg.textContent = 'No se pudo consultar la disponibilidad.'; msg.className = 'slot-msg bad'; }
        })
        .finally(function () { horaSel.disabled = false; });
    };
    [profIn, fechaIn, pacIn].forEach(function (c) {
      if (c) c.addEventListener('change', function () { actual = ''; cargar(); });
    });
    form._cargarSlots = cargar;
    if (!form.closest('.modal')) cargar();
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-live]').forEach(initLive);
    document.querySelectorAll('form.js-agenda-form').forEach(initAgenda);
  });
  document.addEventListener('shown.bs.modal', function (e) {
    e.target.querySelectorAll('form.js-agenda-form').forEach(function (f) { if (f._cargarSlots) f._cargarSlots(); });
  });
})();
