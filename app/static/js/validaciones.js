/* Validaciones del lado del cliente (eventos input/blur/submit) con estilos de Bootstrap. */
(function () {
  'use strict';

  var hoy = function () {
    var d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  };

  var REGLAS = {
    nombre:    function (v) { return v.trim().length >= 3 || 'Escriba al menos 3 caracteres.'; },
    documento: function (v) { return /^\d{5,15}$/.test(v) || 'El documento debe tener entre 5 y 15 dígitos.'; },
    telefono:  function (v) { return v === '' || /^\d{7,15}$/.test(v) || 'El teléfono debe tener entre 7 y 15 dígitos.'; },
    correo:    function (v) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) || 'Ingrese un correo válido.'; },
    password:  function (v) { return v === '' || v.length >= 6 || 'La contraseña debe tener mínimo 6 caracteres.'; },
    fecha:     function (v) { return v === '' || v >= hoy() || 'La fecha no puede ser anterior a hoy.'; },
    texto5:    function (v) { return v.trim().length >= 5 || 'Escriba al menos 5 caracteres.'; }
  };

  function feedbackDe(input) {
    var cont = input.closest('.input-icon') || input;
    var fb = cont.parentElement.querySelector(':scope > .invalid-feedback');
    if (!fb) {
      fb = document.createElement('div'); fb.className = 'invalid-feedback';
      cont.insertAdjacentElement('afterend', fb);
    }
    return fb;
  }

  function validar(input) {
    var msg = '';
    var regla = REGLAS[input.dataset.rule];
    if (regla && !input.disabled) {
      var r = regla(input.value);
      if (r !== true) msg = r;
    }
    if (!msg && input.dataset.match) {
      var otro = document.querySelector(input.dataset.match);
      if (otro && otro.value !== input.value) msg = 'Las contraseñas no coinciden.';
    }
    input.setCustomValidity(msg);
    feedbackDe(input).textContent = msg || input.validationMessage;
    return input.checkValidity();
  }

  function marcar(c) {
    var ok = validar(c);
    c.classList.toggle('is-invalid', !ok);
    c.classList.toggle('is-valid', ok && c.value !== '');
    return ok;
  }

  function medidor(input) {
    var barra = document.querySelector(input.dataset.strength);
    if (!barra) return;
    var v = input.value, s = 0;
    if (v.length >= 6) s++;
    if (v.length >= 10) s++;
    if (/[A-Z]/.test(v) && /[a-z]/.test(v)) s++;
    if (/\d/.test(v)) s++;
    if (/[^A-Za-z0-9]/.test(v)) s++;
    var n = v ? Math.max(1, s) : 0;
    var span = barra.querySelector('span');
    span.style.width = (n * 20) + '%';
    span.style.background = ['#e2e8f0', '#ef4444', '#f59e0b', '#eab308', '#22c55e', '#16a34a'][n];
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('input[data-min-today]').forEach(function (i) { i.min = hoy(); });

    document.querySelectorAll('form.needs-validation').forEach(function (form) {
      form.setAttribute('novalidate', '');
      var campos = form.querySelectorAll('input:not([type=hidden]),select,textarea');
      campos.forEach(function (c) {
        c.addEventListener('blur', function () { c.dataset.touched = '1'; marcar(c); });
        ['input', 'change'].forEach(function (ev) {
          c.addEventListener(ev, function () {
            if (c.dataset.touched) marcar(c);
            if (c.dataset.strength) medidor(c);
            if (c.id) {
              var dep = form.querySelector('[data-match="#' + c.id + '"]');
              if (dep && dep.dataset.touched) marcar(dep);
            }
          });
        });
      });
      form.addEventListener('submit', function (e) {
        var ok = true;
        campos.forEach(function (c) {
          if (c.disabled) return;
          c.dataset.touched = '1';
          if (!marcar(c)) ok = false;
        });
        if (!ok) {
          e.preventDefault(); e.stopImmediatePropagation();
          var primero = form.querySelector('.is-invalid'); if (primero) primero.focus();
        }
      });
    });
  });
})();
