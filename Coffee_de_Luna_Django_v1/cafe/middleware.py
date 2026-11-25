class PrivatePagesMiddleware:
    """Prevent authenticated screens from being reused after logout."""
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(('/app/', '/login/', '/admin/')):
            response['Cache-Control'] = 'no-store, private, max-age=0'
            response['Pragma'] = 'no-cache'
        return response
