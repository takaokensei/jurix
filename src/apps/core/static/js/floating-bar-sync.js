/**
 * Keep the floating conversation input bar's visibility in sync with the welcome state.
 *
 * Previously an inline <script>; moved out so the page's Content-Security-Policy does not need
 * 'unsafe-inline' for script-src.
 */
(function () {
    var welcomeEl = document.getElementById('welcome-state');
    var floatingInput = document.getElementById('conversation-input-bar');

    function updateFloatingBar() {
        if (!welcomeEl || !floatingInput) return;
        var isWelcomeHidden =
            welcomeEl.style.display === 'none' || getComputedStyle(welcomeEl).display === 'none';
        floatingInput.style.display = isWelcomeHidden ? 'flex' : 'none';
    }

    if (welcomeEl) {
        var observer = new MutationObserver(updateFloatingBar);
        observer.observe(welcomeEl, { attributes: true, attributeFilter: ['style', 'class'] });
        updateFloatingBar();
    }
})();
