// Contenido para app/static/js/script.js
document.addEventListener('DOMContentLoaded', function() {
    const yearSpan = document.getElementById('currentYear');
    if (yearSpan) {
        yearSpan.textContent = new Date().getFullYear();
    }
    // Puedes añadir más scripts generales del sitio aquí en el futuro
});