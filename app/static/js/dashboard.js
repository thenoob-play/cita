/* Gráficos del reporte (Chart.js). Se redibujan cuando la tabla se actualiza por AJAX. */
(function () {
  'use strict';
  var charts = {};
  var COLORES = { Pendiente: '#f59e0b', Atendida: '#22c55e', Cancelada: '#ef4444', Inasistida: '#94a3b8' };

  function dibujar() {
    var data = document.getElementById('chart-data');
    if (!data || !window.Chart) return;
    var d = JSON.parse(data.textContent);
    var c1 = document.getElementById('chartEstados'), c2 = document.getElementById('chartProfesionales');
    Object.keys(charts).forEach(function (k) { charts[k].destroy(); delete charts[k]; });
    if (c1) charts.e = new Chart(c1, {
      type: 'doughnut',
      data: { labels: d.estados.labels, datasets: [{ data: d.estados.values,
        backgroundColor: d.estados.labels.map(function (l) { return COLORES[l]; }), borderWidth: 0 }] },
      options: { maintainAspectRatio: false, cutout: '62%', plugins: { legend: { position: 'bottom' } } }
    });
    if (c2) charts.p = new Chart(c2, {
      type: 'bar',
      data: { labels: d.profesionales.labels, datasets: [{ label: 'Citas', data: d.profesionales.values,
        backgroundColor: '#2563eb', borderRadius: 8 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
                 scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
    });
  }
  document.addEventListener('DOMContentLoaded', dibujar);
  document.addEventListener('partial:updated', dibujar);

  // Mostrar/ocultar campos de rango personalizado
  document.addEventListener('change', function (e) {
    if (e.target.name === 'periodo') {
      document.querySelectorAll('.rango-fechas').forEach(function (el) {
        el.classList.toggle('d-none', e.target.value !== 'rango');
      });
    }
  });
})();
