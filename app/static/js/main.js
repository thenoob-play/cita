/* Interacciones generales: alertas, confirmaciones, selects filtrables, credenciales de prueba. */
(function () {
  'use strict';

  // Confirmación antes de enviar formularios marcados con data-confirm
  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  document.addEventListener('DOMContentLoaded', function () {
    // Cerrar automáticamente las alertas de éxito
    document.querySelectorAll('.alert-success').forEach(function (a) {
      setTimeout(function () {
        if (window.bootstrap && document.body.contains(a)) bootstrap.Alert.getOrCreateInstance(a).close();
      }, 7000);
    });

    // Tooltips (p. ej. motivo de un botón de estado deshabilitado en la agenda)
    if (window.bootstrap) {
      document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
        bootstrap.Tooltip.getOrCreateInstance(el);
      });
    }

    // Filtro de opciones de un <select>:  <input data-filter-select="#idSelect">
    document.querySelectorAll('[data-filter-select]').forEach(function (inp) {
      var sel = document.querySelector(inp.dataset.filterSelect);
      if (!sel) return;
      var opts = Array.from(sel.options).map(function (o) { return { v: o.value, t: o.text }; });
      inp.addEventListener('input', function () {
        var q = inp.value.toLowerCase(), cur = sel.value;
        sel.innerHTML = '';
        opts.forEach(function (o) {
          if (o.v === '' || o.t.toLowerCase().indexOf(q) !== -1 || o.v === cur) {
            sel.add(new Option(o.t, o.v, false, o.v === cur));
          }
        });
        sel.dispatchEvent(new Event('change'));
      });
    });

    // Rellenar credenciales de prueba en el login al hacer clic
    document.querySelectorAll('[data-cred]').forEach(function (b) {
      b.addEventListener('click', function () {
        var p = b.dataset.cred.split('|');
        var c = document.getElementById('correo'), pw = document.getElementById('password');
        if (c && pw) { c.value = p[0]; pw.value = p[1]; pw.focus(); }
      });
    });

    // Mostrar/ocultar contraseña
    document.querySelectorAll('[data-toggle-pw]').forEach(function (b) {
      b.addEventListener('click', function () {
        var i = document.querySelector(b.dataset.togglePw);
        if (!i) return;
        i.type = i.type === 'password' ? 'text' : 'password';
        b.querySelector('i').className = i.type === 'password' ? 'fa-solid fa-eye' : 'fa-solid fa-eye-slash';
      });
    });

    // Mostrar/ocultar campos según el rol elegido: data-show-if-rol="profesional"
    var rolSel = document.getElementById('rol');
    if (rolSel) {
      var upd = function () {
        document.querySelectorAll('[data-show-if-rol]').forEach(function (el) {
          var show = el.dataset.showIfRol === rolSel.value;
          el.classList.toggle('d-none', !show);
          el.querySelectorAll('select,input').forEach(function (i) { i.required = show; i.disabled = !show; });
        });
      };
      rolSel.addEventListener('change', upd); upd();
    }
  });
})();
