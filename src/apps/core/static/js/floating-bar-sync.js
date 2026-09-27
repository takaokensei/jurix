/**
 * Keep the floating conversation input bar's visibility in sync with the welcome state.
 *
 * Previously an inline <script>; moved out so the page's Content-Security-Policy does not need
 * 'unsafe-inline' for script-src.
 */
(function () {
    function updateFloatingBar() {
        var welcomeEl = document.getElementById('welcome-state');
        var floatingInput = document.getElementById('conversation-input-bar');
        if (!welcomeEl || !floatingInput) return;
        var isWelcomeHidden = welcomeEl.classList.contains('is-hidden') || getComputedStyle(welcomeEl).display === 'none';
        // Anonymous history can restore messages through a separate path. In
        // that case the session loader may not own the welcome node, so derive
        // the visible mode from the actual message state as a final invariant.
        var hasMessages = document.querySelectorAll('#messages-wrapper .message').length > 0;
        if (hasMessages && !isWelcomeHidden) {
            welcomeEl.classList.add('is-hidden');
            isWelcomeHidden = true;
        }
        // The initial-state class is intentionally display:none. Remove it
        // once a conversation is active; toggling only `is-hidden` leaves the
        // composer permanently invisible after restoring a session.
        floatingInput.classList.toggle('jurix-floating-input-initial', !isWelcomeHidden);
        floatingInput.classList.toggle('is-hidden', !isWelcomeHidden);
        // Keep the computed state deterministic even if an older cached CSS
        // bundle still contains the original display:none rule.
        floatingInput.style.setProperty('display', isWelcomeHidden ? 'flex' : 'none', 'important');
    }

    function init() {
        var welcomeEl = document.getElementById('welcome-state');
        if (welcomeEl) {
            var observer = new MutationObserver(updateFloatingBar);
            observer.observe(welcomeEl, { attributes: true, attributeFilter: ['class'] });
            var messagesWrapper = document.getElementById('messages-wrapper');
            if (messagesWrapper) observer.observe(messagesWrapper, { childList: true });
        }
        updateFloatingBar();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

