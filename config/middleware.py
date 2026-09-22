"""Security middleware used by the Django application."""

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "manifest-src 'self'; "
    "worker-src 'self' blob:"
)


class ContentSecurityPolicyMiddleware:
    """Apply the application CSP as an HTTP header to HTML responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.headers.get('Content-Type', '')
        if content_type.lower().startswith('text/html') and not request.path.startswith('/admin/'):
            response['Content-Security-Policy'] = CONTENT_SECURITY_POLICY
        return response
