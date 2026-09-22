/**
 * Populate window.JURIX_CONFIG from the data-* attributes on <body>.
 *
 * Previously an inline <script>; moved out so the page's Content-Security-Policy does not need
 * 'unsafe-inline' for script-src. Values come from Django template tags rendered as HTML
 * attributes (auto-escaped the same as everywhere else in the template).
 */
(function () {
    var body = document.body;
    window.JURIX_CONFIG = {
        chatbotUrl: body.dataset.chatbotUrl || '',
        normaListUrl: body.dataset.normaListUrl || '',
        logoIconUrl: body.dataset.logoIconUrl || '',
        userName: body.dataset.userName || '',
    };
})();
